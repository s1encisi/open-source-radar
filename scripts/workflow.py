#!/usr/bin/env python3
"""Collect -> prepare -> semantic review -> validate/publish. Public GET only."""
import argparse
import copy
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

import github_readonly as gh
import provenance
import radar
import workflow_store as store


def client_for(workspace, run_id):
    pending = []
    def before(url):
        request_id = store.reserve(workspace, run_id, url)
        if request_id:
            pending.append(request_id)
        return bool(request_id)
    def after(response):
        if pending:
            store.finish(workspace, pending.pop(0), response)
    return gh.Client(token=os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"), budget=120,
                     before_request=before, after_response=after)


def collect(workspace, run_id, candidates, refresh=False):
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 80:
        raise ValueError("Candidates must contain 1..80 repository objects")
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("repository"), str):
            raise ValueError("Each candidate needs repository: owner/name")
        gh.repo_name(item["repository"])
        issues = item.get("issues", [])
        if not isinstance(issues, list) or any(type(n) is not int or n < 1 for n in issues):
            raise ValueError("issues must be a list of positive integer issue numbers")
    known = store.latest(workspace, run_id)
    client = client_for(workspace, run_id)
    for candidate in candidates:
        repo = candidate["repository"]
        name = "repo:" + repo.lower()
        try:
            if name in known and not refresh:
                repository = store.load_capture(workspace, known[name], run_id)
            else:
                store.task(workspace, run_id, name, "collecting")
                observed_at = radar.stamp()
                result = gh.collect_repo(client, repo)
                raw = result.get("repository", {}).get("data")
                if not isinstance(raw, dict) or type(raw.get("id")) is not int:
                    raise ValueError("Repository metadata unavailable")
                root = "/repos/" + gh.repo_name(raw["full_name"])
                # Bounded policy-document search. These are untrusted data, never instructions.
                for path in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md", "CONTRIBUTING.rst"):
                    response = gh.decode_file(client.get(root + "/contents/" + path))
                    result["contributing"] = response
                    if response["status"] == 200 or response["status"] not in (404,):
                        break
                result["ai_policy"] = gh.decode_file(client.get(root + "/contents/AGENTS.md"))
                repository = {"kind": "repo", "project_id": "github:" + str(raw["id"]), "repository": raw["full_name"],
                              "api_root": gh.API + root, "observed_at": observed_at, "result": result}
                known[name] = store.save_capture(workspace, run_id, name, repository)
                store.task(workspace, run_id, name, "captured", "Semantic review required; optional documents may be absent")
            for number in sorted(set(candidate.get("issues", []))):
                name = "issue:" + repo.lower() + "#" + str(number)
                if name in known and not refresh:
                    continue
                store.task(workspace, run_id, name, "collecting")
                observed_at = radar.stamp()
                result = gh.collect_issue(client, repository["repository"], number)
                raw = result.get("issue", {}).get("data")
                expected_url = "https://github.com/" + repository["repository"] + "/issues/" + str(number)
                if not isinstance(raw, dict) or raw.get("number") != number or raw.get("html_url") != expected_url:
                    raise ValueError("Issue identity or data unavailable")
                payload = {"kind": "issue", "project_id": repository["project_id"], "issue_number": number,
                           "repository": repository["repository"], "api_root": repository["api_root"],
                           "observed_at": observed_at, "result": result}
                known[name] = store.save_capture(workspace, run_id, name, payload)
                store.task(workspace, run_id, name, "captured", "Inspect comments, PR meaning and policy")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            store.task(workspace, run_id, name, "failed", str(exc))
    return store.status(workspace, run_id)


def prepare(workspace, run_id):
    with radar.connect(workspace) as con:
        store.active(con, workspace, run_id)
    original = radar.load(workspace / "runs" / run_id / "draft.json")
    data = {key: copy.deepcopy(value) for key, value in original.items() if key != "evaluation"}
    data.update(generated_at=radar.stamp(), projects=[], evidence=[], coverage=[])
    records = [(cid, store.load_capture(workspace, cid, run_id)) for cid in store.latest(workspace, run_id).values()]
    projects = {}
    for cid, capture in records:
        if capture["kind"] != "repo":
            continue
        raw = capture["result"]["repository"]["data"]
        ev = provenance.views(capture, cid)
        data["evidence"].extend(ev.values())
        project = {"project_id": capture["project_id"], "provider": "github", "name": raw["full_name"],
                   "canonical_url": raw["html_url"], "category": "other", "license_status": "unknown",
                   "license_spdx": (raw.get("license") or {}).get("spdx_id"), "archived": raw["archived"],
                   "checked_at": capture["observed_at"], "stars": raw["stargazers_count"], "language": raw.get("language"),
                   "evidence_ids": [item["id"] for item in ev.values()], "claims": [{"kind": "author_claim",
                   "text": raw.get("description") or "Repository description is unavailable",
                   "evidence_ids": [ev["repository"]["id"]]}], "relevance": "待语义审阅",
                   "caveats": "采集完成不等于已核实用途、许可或贡献政策",
                   "scores": {key: {"value": 0, "reason": "待语义审阅，不是已评估得分"}
                              for key in ("interest", "novelty", "relevance", "health")},
                   "opportunities": [], "review": {"status": "pending"}}
        projects[project["project_id"]] = project
    for cid, capture in records:
        if capture["kind"] != "issue" or capture["project_id"] not in projects:
            continue
        project = projects[capture["project_id"]]
        result = capture["result"]
        raw = result["issue"]["data"]
        ev = provenance.views(capture, cid)
        data["evidence"].extend(ev.values())
        body = result["pr_search"].get("data") or {}
        pr_complete = (result["pr_search"]["status"] == 200 and body.get("incomplete_results") is False
                       and body.get("total_count", 1) <= len(body.get("items", []))
                       and not result.get("linked_pr_details_truncated"))
        issue = {"number": raw["number"], "title": raw["title"], "url": raw["html_url"], "state": raw["state"],
                 "checked_at": capture["observed_at"], "assignees": [a["login"] for a in raw.get("assignees", [])],
                 "claim_status": "unknown", "linked_pr": "unknown", "checks": {
                     "comments": result["comments"]["complete"], "timeline": result["timeline"]["complete"],
                     "pr_search": pr_complete, "contributing": False, "ai_policy_search": False},
                 "scope": "unknown", "ai_policy": "unknown", "skill_match": "unknown",
                 "evidence_ids": [item["id"] for item in ev.values()] + project["evidence_ids"],
                 "task": raw["title"], "first_step": "阅读原始issue、评论、时间线、PR及贡献规则",
                 "acceptance": "待根据维护者需求确认", "skills_needed": "待语义审阅", "skill_gaps": "用户能力尚未验证"}
        project["opportunities"].append(issue)
    data["projects"] = list(projects.values())
    source_ids = [ev["id"] for ev in data["evidence"] if ev["role"] == "repository" and ev["primary"]]
    if source_ids:
        data["coverage"] = [{"family": "github", "status": "partial", "query": "Explicit repository/issue candidate input",
                             "note": "Collected candidates; semantic review and other source families remain separate",
                             "found": len(projects), "verified": 0, "evidence_ids": source_ids}]
    info = store.status(workspace, run_id)
    data["metrics"].update(github_api_calls=info["requests_reserved"],
                           failed_requests=info["failed_or_unknown_requests"])
    data["limitations"] = ["自动抽取只覆盖GitHub；其他来源未在本次工作流采集。", "初稿必须完成语义审阅后才能发布。"]
    target = workspace / "runs" / run_id / ("prepared-" + uuid.uuid4().hex + ".json")
    radar.atomic_text(target, radar.dumps(data) + "\n")
    review_template = {"projects": [{key: copy.deepcopy(p[key]) for key in
                       ("project_id", "category", "license_status", "claims", "relevance", "caveats", "scores")}
                       for p in data["projects"]]}
    review_path = target.with_suffix(".annotations.json")
    radar.atomic_text(review_path, radar.dumps(review_template) + "\n")
    return {"draft": str(target), "annotations_template": str(review_path), "projects": len(projects),
            "pending_review": [{"project_id": p["project_id"], "issues": [o["number"] for o in p["opportunities"]]}
                               for p in data["projects"]]}


def review(workspace, draft, annotations):
    data = radar.load(draft)
    with radar.connect(workspace) as con:
        store.active(con, workspace, data["run_id"])
    if not isinstance(annotations, dict) or not isinstance(annotations.get("projects"), list):
        raise ValueError("Review file needs projects[]")
    project_fields = {"category", "license_status", "claims", "relevance", "caveats", "scores"}
    issue_fields = {"claim_status", "linked_pr", "scope", "ai_policy", "skill_match",
                    "task", "first_step", "acceptance", "skills_needed", "skill_gaps", "user_capability_evidence", "related_pr_numbers"}
    by_id = {p["project_id"]: p for p in data["projects"]}
    for assessment in annotations["projects"]:
        if not isinstance(assessment, dict) or assessment.get("project_id") not in by_id:
            raise ValueError("Unknown project in review")
        if set(assessment) - project_fields - {"project_id", "opportunities"}:
            raise ValueError("Review cannot overwrite machine fields")
        if not project_fields <= assessment.keys():
            raise ValueError("Review must supply category, license_status, claims, relevance, caveats and scores")
        project = by_id[assessment["project_id"]]
        project.update({k: assessment[k] for k in project_fields})
        issues = {o["number"]: o for o in project["opportunities"]}
        for item in assessment.get("opportunities", []):
            if item.get("number") not in issues or set(item) - issue_fields - {"number", "policy_checks"}:
                raise ValueError("Unknown issue or attempted machine-field overwrite")
            issue = issues[item["number"]]
            issue.update({k: item[k] for k in issue_fields if k in item})
            for key, value in item.get("policy_checks", {}).items():
                if key not in {"contributing", "ai_policy_search"} or type(value) is not bool:
                    raise ValueError("Only semantic policy check flags can be annotated")
                issue["checks"][key] = value
        project["review"] = {"status": "complete", "reviewed_at": radar.stamp(),
                             "annotations_sha256": radar.digest(radar.dumps(assessment).encode("utf-8"))}
    data["generated_at"] = radar.stamp()
    errors, _ = radar.validate(data)
    if not errors:
        errors += provenance.verify(workspace, data)
    if errors:
        raise ValueError("Review rejected:\n" + "\n".join(errors))
    for coverage in data["coverage"]:
        if coverage["family"] == "github":
            coverage["verified"] = len(data["projects"])
    data["limitations"] = [x for x in data["limitations"] if "初稿必须" not in x]
    target = workspace / "runs" / data["run_id"] / ("reviewed-" + uuid.uuid4().hex + ".json")
    radar.atomic_text(target, radar.dumps(data) + "\n")
    radar.atomic_text(target.with_suffix(".review.json"), radar.dumps(annotations) + "\n")
    return {"draft": str(target), "status": "reviewed", "next": "radar.py validate, then publish"}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    for command in ("status", "prepare"):
        sub.add_parser(command).add_argument("run_id")
    p = sub.add_parser("collect"); p.add_argument("run_id"); p.add_argument("--candidates", type=Path, required=True); p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("review"); p.add_argument("draft", type=Path); p.add_argument("--annotations", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    try:
        if args.command == "setup": result = store.setup(workspace)
        elif args.command == "collect": result = collect(workspace, args.run_id, radar.load(args.candidates), refresh=args.refresh)
        elif args.command == "prepare": result = prepare(workspace, args.run_id)
        elif args.command == "review": result = review(workspace, args.draft, radar.load(args.annotations))
        else: result = store.status(workspace, args.run_id)
        print(radar.dumps(result))
        return 1 if args.command == "collect" and any(t["status"] == "failed" for t in result["tasks"]) else 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(radar.dumps({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
