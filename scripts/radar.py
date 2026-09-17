#!/usr/bin/env python3
"""Open Source Radar: local state, evidence checks and reproducible reports.
Python 3.10+, standard library only. No network, shell, or external writes.
Facts still require human/agent source review; validation is not a truth oracle.
"""
from __future__ import annotations
from collections.abc import Iterator
from contextlib import closing, contextmanager
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from draft_validation import structure_errors
import runtime_policy

VERSION = "1.1.0"
RULES_VERSION = "2026-09-17.2"
SCHEMA_VERSION = 1
CATEGORIES = {"ai_agents", "science_environment", "developer_tools", "web_ui",
              "games_creative", "data_infrastructure", "systems_security", "other"}
LICENSES = {"open_source_verified", "source_available", "open_weights", "unknown"}
EVIDENCE_ROLES = {"repository", "readme", "license", "release", "issue", "comments",
                  "timeline", "pull_requests", "contributing", "ai_policy", "benchmark", "discovery", "code"}
CLAIM_TYPES = {"fact", "author_claim", "inference", "recommendation"}
COVERAGE_STATES = {"success", "partial", "blocked", "failed", "not_attempted"}
ROOT = Path(__file__).resolve().parents[1]


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat(timespec="seconds")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)


def load(path: Path):
    # utf-8-sig also accepts JSON written by Windows PowerShell.
    return json.loads(path.read_text(encoding="utf-8-sig"),
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Non-finite JSON: " + v)))


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".radar-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def parsed_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must include timezone offset")
    return dt.astimezone(timezone.utc)


def fresh(value, hours=24, at=None) -> bool:
    try:
        delta = ((at or now()) - parsed_time(value)).total_seconds()
        return -300 <= delta <= hours * 3600
    except (ValueError, TypeError):
        return False


def valid_url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and bool(u.hostname) and not u.username
                and not u.password and u.port in (None, 443)
                and not re.search(r"[\x00-\x20<>]", value)
                and not re.search(r"(?:access_token|api_key|token)=", u.query, re.I))
    except (ValueError, TypeError):
        return False


def md(value) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    for char in ("\\", "`", "*", "_", "[", "]", "<", ">", "|", "#"):
        text = text.replace(char, "\\" + char)
    return text


@contextmanager
def connect(workspace: Path) -> Iterator[sqlite3.Connection]:
    """Commit/rollback a unit of work and always close its underlying handle."""
    path = workspace / "state" / "radar.sqlite3"
    if not path.exists():
        raise ValueError("Workspace not initialized. Run init first.")
    con = sqlite3.connect(path, timeout=15)
    try:
        con.execute("PRAGMA foreign_keys=ON")
        con.row_factory = sqlite3.Row
        version = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if not version or version[0] != str(SCHEMA_VERSION):
            raise ValueError("Unsupported state schema; back up and migrate explicitly")
        with con:
            yield con
    finally:
        con.close()


def locked_policy(workspace: Path, con: sqlite3.Connection):
    for name in ("mission.md", "profile.json", "config.json"):
        row = con.execute("SELECT value FROM meta WHERE key=?", ("hash:" + name,)).fetchone()
        if not row or row[0] != digest((workspace / name).read_bytes()):
            raise ValueError("Policy drift detected in " + name + "; stop and obtain explicit user approval.")


def initialize(workspace: Path):
    if (workspace / "state" / "radar.sqlite3").exists():
        with connect(workspace) as con:
            locked_policy(workspace, con)
        return {"status": "already_initialized", "workspace": str(workspace)}
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Refusing to initialize a nonempty unrecognized workspace.")
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ("state", "runs", "reports", "evidence"):
        (workspace / name).mkdir(exist_ok=True)
    for target, source in (("mission.md", "mission.md"), ("profile.json", "profile.json"),
                           ("config.json", "config.json")):
        atomic_text(workspace / target, (ROOT / "templates" / source).read_text(encoding="utf-8"))
    with closing(sqlite3.connect(workspace / "state" / "radar.sqlite3", timeout=15)) as con, con:
        con.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE runs(run_id TEXT PRIMARY KEY, report_date TEXT NOT NULL,
          started_at TEXT NOT NULL, updated_at TEXT NOT NULL, phase TEXT NOT NULL,
          payload TEXT, manifest TEXT, report TEXT, fixture INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE evidence(evidence_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE projects(project_id TEXT PRIMARY KEY, first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL, current_payload TEXT NOT NULL);
        CREATE TABLE observations(run_id TEXT NOT NULL REFERENCES runs(run_id),
          project_id TEXT NOT NULL REFERENCES projects(project_id), observed_at TEXT NOT NULL,
          payload TEXT NOT NULL, PRIMARY KEY(run_id,project_id));
        CREATE INDEX obs_project_time ON observations(project_id,observed_at);
        CREATE TABLE changes(run_id TEXT NOT NULL REFERENCES runs(run_id),
          project_id TEXT NOT NULL, field TEXT NOT NULL, before_json TEXT, after_json TEXT);
        CREATE TABLE feedback(feedback_id INTEGER PRIMARY KEY, created_at TEXT NOT NULL,
          project_id TEXT, event TEXT NOT NULL, note TEXT NOT NULL, user_quote TEXT NOT NULL);
        """)
        con.execute("INSERT INTO meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        for name in ("mission.md", "profile.json", "config.json"):
            con.execute("INSERT INTO meta VALUES(?,?)", ("hash:" + name, digest((workspace / name).read_bytes())))
        import workflow_store
        workflow_store.install(con)
    return {"status": "initialized", "workspace": str(workspace)}


def start(workspace: Path):
    local = datetime.now().astimezone()
    # Unique run IDs support same-day revisions; reports never overwrite previous runs.
    run_id = local.strftime("%Y%m%dT%H%M%S%f") + "-" + os.urandom(3).hex()
    with connect(workspace) as con:
        locked_policy(workspace, con)
        con.execute("INSERT INTO runs(run_id,report_date,started_at,updated_at,phase) VALUES(?,?,?,?,?)",
                    (run_id, local.date().isoformat(), stamp(), stamp(), "discover"))
        con.execute("INSERT INTO meta VALUES(?,?)", ("policy:" + run_id, dumps(runtime_policy.resolve(workspace))))
    directory = workspace / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    draft = load(ROOT / "templates" / "draft.json")
    draft.update(run_id=run_id, report_date=local.date().isoformat(), generated_at=stamp(),
                 report_timezone=str(local.tzinfo), utc_offset=local.strftime("%z"))
    atomic_text(directory / "draft.json", dumps(draft) + "\n")
    return {"run_id": run_id, "draft": str(directory / "draft.json")}


def evidence_reference(evidence, ids, roles=None, primary=False, hours=None, at=None) -> bool:
    if not isinstance(ids, list) or not ids:
        return False
    selected = [evidence.get(i) for i in ids if isinstance(i, str)]
    return any(e is not None and (not primary or e.get("primary") is True)
               and (roles is None or e.get("role") in roles)
               and (hours is None or fresh(e.get("observed_at"), hours, at)) for e in selected)


def opportunity_decision(project, opportunity, evidence, at=None, ttl_hours=24):
    """Evaluate observed state using one clock and only the evidence it needs."""
    at = at or now()
    reasons = []
    def result(status, entries):
        return {"status": status, "reason_codes": [code for code, _ in entries],
                "reasons": [text for _, text in entries]}

    if not fresh(project.get("checked_at"), ttl_hours, at):
        reasons.append(("repository_stale", f"仓库核验不在最近{ttl_hours:g}小时"))
    if not evidence_reference(evidence, project.get("evidence_ids"), {"repository"}, True, ttl_hours, at):
        reasons.append(("repository_evidence_stale", "缺少新鲜的仓库原始证据"))
    if reasons:
        return result("needs_verification", reasons)
    if project.get("archived") is True:
        return result("excluded", [("repository_archived", "本次新鲜证据显示仓库已归档")])
    if not fresh(opportunity.get("checked_at"), ttl_hours, at):
        reasons.append(("issue_stale", "issue上次观测已过期或时间非法；当前状态待重新核验"))
    if not evidence_reference(evidence, opportunity.get("evidence_ids"), {"issue"}, True, ttl_hours, at):
        reasons.append(("issue_evidence_stale", "缺少新鲜的issue原始证据"))
    if reasons:
        return result("needs_verification", reasons)
    if opportunity.get("state") == "closed":
        return result("excluded", [("issue_closed", "本次新鲜证据显示issue已关闭")])
    if opportunity.get("linked_pr") in {"open", "merged"}:
        if not evidence_reference(evidence, opportunity.get("evidence_ids"), {"pull_requests"}, True, ttl_hours, at):
            return result("needs_verification", [("pr_evidence_stale", "关联PR证据缺失或过期；当前状态待重新核验")])
        if opportunity["linked_pr"] == "merged":
            return result("excluded", [("pr_merged", "已有合并 PR，需先查证问题是否仍存在")])
        return result("in_progress", [("pr_open", "本次新鲜证据显示有进行中的 PR")])
    if opportunity.get("assignees"):
        return result("in_progress", [("issue_assigned", "本次新鲜证据显示已有受理人")])
    if opportunity.get("claim_status") == "claimed":
        if not evidence_reference(evidence, opportunity.get("evidence_ids"), {"comments"}, True, ttl_hours, at):
            return result("needs_verification", [("claim_evidence_stale", "认领评论证据缺失或过期；当前状态待重新核验")])
        return result("in_progress", [("issue_claimed", "本次新鲜评论证据显示已有认领")])
    if project.get("license_status") != "open_source_verified":
        reasons.append(("license_unverified", "尚未核实为开源软件许可"))
    if opportunity.get("state") != "open" or project.get("archived") is not False:
        reasons.append(("state_unknown", "issue/仓库当前状态不完整"))
    if opportunity.get("assignees") != [] or opportunity.get("claim_status") != "none_observed":
        reasons.append(("ownership_unknown", "未完成认领情况检查"))
    if opportunity.get("linked_pr") != "none_observed":
        reasons.append(("pr_unknown", "关联PR检查不完整"))
    if not all(opportunity.get("checks", {}).get(k) is True for k in
               ("comments", "timeline", "pr_search", "contributing", "ai_policy_search")):
        reasons.append(("checks_incomplete", "贡献规则、评论、时间线或PR检查尚未完成"))
    if not all(evidence_reference(evidence, opportunity.get("evidence_ids"), roles, True, ttl_hours, at)
               for roles in ({"issue"}, {"comments"}, {"timeline"}, {"pull_requests"})):
        reasons.append(("dynamic_evidence_incomplete", "缺少新鲜的issue/评论/时间线/PR原始证据"))
    if not evidence_reference(evidence, opportunity.get("evidence_ids"), {"contributing"}, True):
        reasons.append(("contributing_missing", "贡献流程没有证据"))
    if opportunity.get("scope") != "clear":
        reasons.append(("scope_unknown", "任务边界或验收条件不明确"))
    if opportunity.get("ai_policy") not in {"allowed", "conditional", "not_found_after_search", "disallowed"}:
        reasons.append(("ai_policy_unknown", "AI贡献政策尚未检查"))
    if opportunity.get("skill_match") not in {"verified", "potential", "unknown"}:
        reasons.append(("skill_match_unknown", "技能匹配状态不明"))
    # Unknown ability remains explicitly conditional even when the issue is available.
    return result("needs_verification", reasons) if reasons else result("candidate_for_review", [
        ("candidate_conditional", "仅在本次已检查范围内未发现占用；行动前重新核验"),
        ("ability_not_certified", "技能匹配不是能力认证，也不保证维护者接收"),
        ("follow_ai_policy", "项目禁止AI生成贡献，禁止自动写代码" if opportunity.get("ai_policy") == "disallowed"
         else "须遵循项目AI政策；未知政策不等于允许")])


def opportunity_gate(project, opportunity, evidence, at=None, ttl_hours=24) -> tuple[str, list[str]]:
    decision = opportunity_decision(project, opportunity, evidence, at, ttl_hours)
    return decision["status"], decision["reasons"]


def evaluate(data: dict, *, allow_fixture=False, at=None, ttl_hours=24):
    """Validate and compute one decision per opportunity at a fixed instant."""
    errors, warnings, decisions = structure_errors(data), [], []
    at = at or now()
    if errors:
        return errors, warnings, decisions
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(data["run_id"])):
        errors.append("Invalid run_id")
    try:
        datetime.strptime(data["report_date"], "%Y-%m-%d")
    except (ValueError, TypeError):
        errors.append("Invalid report_date")
    if not fresh(data["generated_at"], ttl_hours, at):
        errors.append("generated_at must be timezone-aware, current and not in the future")
    for key in ("coverage", "evidence", "projects", "limitations"):
        if not isinstance(data[key], list):
            errors.append(key + " must be a list")
    if errors:
        return errors, warnings, decisions
    if len(data["projects"]) > 100:
        errors.append("At most 100 deeply assessed project records per run; split batches")
    evidence = {}
    for e in data["evidence"]:
        if not isinstance(e, dict):
            errors.append("Evidence item must be an object")
            continue
        eid = e.get("id")
        if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", eid) or eid in evidence:
            errors.append("Missing, invalid, or duplicate evidence ID")
            continue
        evidence[eid] = e
        if not valid_url(e.get("url")):
            errors.append(eid + ": invalid HTTPS URL or URL includes credentials")
        if e.get("role") not in EVIDENCE_ROLES or type(e.get("primary")) is not bool:
            errors.append(eid + ": invalid evidence role/primary")
        try:
            if parsed_time(e.get("observed_at")) > at + timedelta(minutes=5):
                errors.append(eid + ": future evidence")
        except (ValueError, TypeError):
            errors.append(eid + ": timestamp needs timezone")
        excerpt = e.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 12000:
            errors.append(eid + ": need a bounded captured excerpt; not an invented summary")
        elif digest(excerpt.encode("utf-8")) != e.get("sha256"):
            errors.append(eid + ": captured excerpt hash mismatch")
    ids, urls, issue_ids = set(), set(), set()
    required = {"project_id", "provider", "name", "canonical_url", "category", "license_status",
                "license_spdx", "archived", "checked_at", "stars", "language", "evidence_ids",
                "claims", "relevance", "caveats", "scores", "opportunities"}
    for p in data["projects"]:
        if not isinstance(p, dict):
            errors.append("Project must be an object")
            continue
        pid = str(p.get("project_id", ""))
        missing = sorted(required - set(p))
        if missing:
            errors.append(pid + ": missing " + ", ".join(missing))
            continue
        if p.get("synthetic") is True and not allow_fixture:
            errors.append(pid + ": synthetic fixture cannot be published as a real project")
        if pid in ids or p["canonical_url"].rstrip("/").lower() in urls:
            errors.append(pid + ": duplicate project identity or canonical URL")
        ids.add(pid)
        urls.add(p["canonical_url"].rstrip("/").lower())
        if not pid or not valid_url(p["canonical_url"]):
            errors.append(pid + ": invalid project identity/URL")
        if p["provider"] == "github":
            if not re.fullmatch(r"github:\d+", pid):
                errors.append(pid + ": use immutable GitHub numeric repository ID")
            if not valid_url(p["canonical_url"]) or urlsplit(p["canonical_url"]).hostname != "github.com":
                errors.append(pid + ": GitHub provider URL mismatch")
        if p["category"] not in CATEGORIES or p["license_status"] not in LICENSES:
            errors.append(pid + ": invalid category/license class")
        if p["archived"] is not None and type(p["archived"]) is not bool:
            errors.append(pid + ": archived must be boolean/null")
        if p["stars"] is not None and (type(p["stars"]) is not int or p["stars"] < 0):
            errors.append(pid + ": stars must be nonnegative integer/null")
        if not fresh(p["checked_at"], ttl_hours, at):
            errors.append(pid + ": selected project is outside the configured TTL")
        refs = p["evidence_ids"]
        if not isinstance(refs, list) or any(i not in evidence for i in refs):
            errors.append(pid + ": unknown/malformed evidence references")
        if not evidence_reference(evidence, refs, {"repository"}, True, ttl_hours, at):
            errors.append(pid + ": primary repository evidence missing/stale")
        if p["license_status"] == "open_source_verified":
            if not p["license_spdx"] or not evidence_reference(evidence, refs, {"license"}, True):
                errors.append(pid + ": verified open-source license requires SPDX and license evidence")
        if not isinstance(p["claims"], list) or not p["claims"]:
            errors.append(pid + ": need factual and attributed claims")
        else:
            for claim in p["claims"]:
                if not isinstance(claim, dict) or claim.get("kind") not in CLAIM_TYPES or not claim.get("text"):
                    errors.append(pid + ": malformed claim")
                    continue
                cids = claim.get("evidence_ids", [])
                if not isinstance(cids, list) or any(i not in evidence for i in cids):
                    errors.append(pid + ": invalid claim evidence ID")
                elif claim["kind"] != "recommendation" and not evidence_reference(
                        evidence, cids, primary=claim["kind"] in {"fact", "author_claim"}):
                    errors.append(pid + ": unsupported claim: " + claim["kind"])
        for dimension in ("interest", "novelty", "relevance", "health"):
            item = p.get("scores", {}).get(dimension, {})
            score = item.get("value") if isinstance(item, dict) else None
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 5 or not item.get("reason"):
                errors.append(pid + ": invalid score/reason: " + dimension)
        if not isinstance(p["opportunities"], list):
            errors.append(pid + ": opportunities must be a list")
            continue
        for o in p["opportunities"]:
            if not isinstance(o, dict):
                errors.append(pid + ": opportunity must be an object")
                continue
            for key in ("number", "title", "url", "state", "checked_at", "assignees", "claim_status",
                        "linked_pr", "checks", "scope", "ai_policy", "skill_match", "evidence_ids",
                        "task", "first_step", "acceptance", "skills_needed", "skill_gaps"):
                if key not in o:
                    errors.append(pid + ": opportunity missing " + key)
            oid = (pid, o.get("number"))
            if oid in issue_ids:
                errors.append(pid + ": duplicate issue")
            issue_ids.add(oid)
            if type(o.get("number")) is not int or o.get("number", 0) < 1 or not valid_url(o.get("url")):
                errors.append(pid + ": invalid issue number/URL")
            if p["provider"] == "github" and o.get("url") != p["canonical_url"].rstrip("/") + "/issues/" + str(o.get("number")):
                errors.append(pid + ": issue URL must belong to this repository and number")
            if o.get("state") not in {"open", "closed", "unknown"}:
                errors.append(pid + ": invalid issue state")
            refs = o.get("evidence_ids", [])
            if not isinstance(refs, list) or any(i not in evidence for i in refs):
                errors.append(pid + ": issue references unknown evidence")
            if o.get("skill_match") == "verified" and not o.get("user_capability_evidence"):
                errors.append(pid + ": verified skill match requires explicit user evidence")
            decision = opportunity_decision(p, o, evidence, at, ttl_hours)
            decision.update(project_id=pid, number=o["number"],
                            evidence_ids=list(dict.fromkeys(p["evidence_ids"] + refs)))
            decisions.append(decision)
            if decision["status"] == "needs_verification":
                warnings.append(pid + "#" + str(o["number"]) + ": " + "; ".join(decision["reasons"]))
    for c in data["coverage"]:
        if not isinstance(c, dict) or c.get("status") not in COVERAGE_STATES or not c.get("family"):
            errors.append("Invalid coverage item")
            continue
        if not c.get("query") or not c.get("note"):
            errors.append("Coverage needs actual query/entry and note")
        for key in ("found", "verified"):
            if type(c.get(key)) is not int or c[key] < 0:
                errors.append("Coverage counts must be nonnegative integers")
        if type(c.get("found")) is int and type(c.get("verified")) is int and c["verified"] > c["found"]:
            errors.append("verified count cannot exceed discovered count")
        if c["status"] in {"success", "partial"} and not c.get("evidence_ids"):
            errors.append("Successful coverage needs captured evidence")
        if any(i not in evidence for i in c.get("evidence_ids", [])):
            errors.append("Coverage references unknown evidence")
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("metrics must be an object")
    else:
        for key, value in metrics.items():
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                errors.append("Metrics are measured nonnegative numbers or null: " + key)
    if not data["projects"]:
        warnings.append("No newly verified project; publish degraded report, never fill from memory")
    families = {c.get("family") for c in data["coverage"] if isinstance(c, dict) and c.get("status") in {"success", "partial"}}
    if len(families) < 5:
        warnings.append("Fewer than five successfully accessed discovery-source families")
    if len({p.get("category") for p in data["projects"] if isinstance(p, dict)}) < 5:
        warnings.append("Fewer than five project categories verified")
    return errors, warnings, decisions


def validate(data: dict, *, allow_fixture=False, at=None, ttl_hours=24, workspace=None):
    if workspace is not None:
        with connect(workspace) as con:
            locked_policy(workspace, con)
            run_id = data.get("run_id", "") if isinstance(data, dict) else ""
            policy = runtime_policy.for_run(workspace, con, run_id) if isinstance(run_id, str) else runtime_policy.resolve(workspace)
            ttl_hours = policy["dynamic_ttl_hours"]
    errors, warnings, _ = evaluate(data, allow_fixture=allow_fixture, at=at, ttl_hours=ttl_hours)
    if not errors and workspace is not None and not allow_fixture:
        import provenance
        errors.extend(provenance.verify(workspace, data))
    return errors, warnings


def priority(p):
    s = p["scores"]
    return round(sum(s[k]["value"] * w for k, w in
                     (("interest", 20), ("novelty", 20), ("relevance", 35), ("health", 25))) / 5, 1)


def star_change(previous, current):
    if not previous or previous.get("stars") is None or current.get("stars") is None:
        return None
    hours = (parsed_time(current["checked_at"]) - parsed_time(previous["checked_at"])).total_seconds() / 3600
    if hours <= 0:
        return None
    return {"delta": current["stars"] - previous["stars"], "hours": round(hours, 2),
            "from": previous["checked_at"], "to": current["checked_at"]}


def render(data, manifest, deltas):
    evidence = {e["id"]: e for e in data["evidence"]}
    evaluation = manifest["evaluation"]
    decisions = {(item["project_id"], item["number"]): item for item in evaluation["decisions"]}
    refnumbers = {eid: i + 1 for i, eid in enumerate(evidence)}
    def refs(ids):
        return " ".join("[E" + str(refnumbers[i]) + "](" + evidence[i]["url"] + ")" for i in ids if i in evidence)
    status_cn = {"candidate_for_review": "待你复核的贡献候选", "needs_verification": "待核验，不能当作可认领",
                 "in_progress": "有人推进，暂不重复认领", "excluded": "已排除"}
    lines = ["# 开源项目雷达｜" + data["report_date"], "",
             "运行编号：`" + data["run_id"] + "`；生成时间：" + md(data["generated_at"]),
             "统一判定时间：" + md(evaluation["evaluated_at"]) + "；规则版本：" + md(evaluation["rules_version"]),
             "报告时区：" + md(data["report_timezone"]) + "（偏移 " + md(data["utc_offset"]) + "）", "",
             "**本报告是只读调研：未安装、运行、fork、评论、认领、提交代码或创建 PR。**", ""]
    if manifest["fixture"]:
        lines += ["**合成测试数据；不是实际项目日报，不可据此行动。**", ""]
    lines += ["## 今日结论", "",
              f"已核验项目 {manifest['projects']} 个，其中已核实开源许可 {manifest['open_source']} 个；贡献线索 {manifest['issues']} 条，进入待你复核候选 {manifest['actionable']} 条。",
              "优先级分数是本工作流的启发式排序，不是质量认证、创新证明或 PR 接收概率。", "",
              "## 值得关注的项目", ""]
    labels = {"fact": "已核验事实", "author_claim": "作者自述", "inference": "分析判断", "recommendation": "建议"}
    for i, p in enumerate(sorted(data["projects"], key=priority, reverse=True), 1):
        lines += [f"### {i}. {md(p['name'])}｜{priority(p):g}/100", "",
                  f"[官方仓库]({p['canonical_url']}) · {md(p['category'])} · {md(p['language'] or '未核实语言')} · 许可：{md(p['license_status'])} / {md(p['license_spdx'] or '未核实')}",
                  f"Star：{p['stars'] if p['stars'] is not None else '未核实'}；核验时间：{md(p['checked_at'])}。 " + refs(p["evidence_ids"]), ""]
        d = deltas.get(p["project_id"])
        if d:
            lines.append(f"本地两次观测间 Star 变化 {d['delta']:+d}，间隔 {d['hours']:g} 小时（{md(d['from'])} → {md(d['to'])}）；不是平台提供的‘今日新增’。")
        else:
            lines.append("Star 增量：缺少可比较的历史观测，不估算日增。")
        for claim in p["claims"]:
            lines.append("**" + labels[claim["kind"]] + "：**" + md(claim["text"]) + " " + refs(claim.get("evidence_ids", [])))
        lines += ["", "**与你的关系：**" + md(p["relevance"]), "**限制与成本：**" + md(p["caveats"]), "",
                  "排序依据：" + "；".join(k + " " + str(v["value"]) + "/5：" + md(v["reason"]) for k, v in p["scores"].items()), ""]
    lines += ["## 贡献机会核验", ""]
    for p in data["projects"]:
        for o in p["opportunities"]:
            decision = decisions[(p["project_id"], o["number"])]
            gate, reasons = decision["status"], decision["reasons"]
            lines += ["### " + md(p["name"]) + " #" + str(o["number"]) + "｜" + status_cn[gate], "",
                      "[" + md(o["title"]) + "](" + o["url"] + ") " + refs(o["evidence_ids"]),
                      "上次观测：" + md(o["checked_at"]) + "；当时issue状态：" + md(o["state"]) +
                      "；AI 政策：" + md(o["ai_policy"]) + "；技能匹配：" + md(o["skill_match"]),
                      "判定：" + md("；".join(reasons)),
                      "任务：" + md(o["task"]), "第一步（只读）：" + md(o["first_step"]),
                      "完成/验收标准：" + md(o["acceptance"]),
                      "所需技能：" + md(o["skills_needed"]), "尚缺证据或需准备：" + md(o["skill_gaps"]), ""]
    if not manifest["issues"]:
        lines += ["本次没有完成核验的具体 issue；不把一般改进想法写成维护者已提出的需求。", ""]
    lines += ["## 增量与更正", ""]
    for change in manifest["changes"]:
        lines.append(md(change["project_id"]) + " · " + md(change["field"]) + "：" + md(change["before"]) + " → " + md(change["after"]))
    if not manifest["changes"]:
        lines.append("首次观测或没有已核实的字段变化；不等于项目没有变化。")
    lines += ["", "## 检索覆盖与缺口", ""]
    for c in data["coverage"]:
        lines.append("**" + md(c["family"]) + " / " + md(c["status"]) + "**：" + md(c["query"]) +
                     f"；发现 {c['found']}、核验 {c['verified']}。" + md(c["note"]) + " " + refs(c.get("evidence_ids", [])))
    lines += ["", "## 限制与质量检查", ""]
    lines += [md(w) for w in manifest["warnings"] + data["limitations"]]
    lines += ["", "## 运行指标", "", "```json", dumps(data["metrics"]), "```", "",
              "null 表示无法从当前运行环境测量，不等于零。候选去重后的检索母体未知，不声称全网召回率。", "", "## 原始证据索引", ""]
    for eid, e in evidence.items():
        lines.append(f"E{refnumbers[eid]} · [{md(e['role'])}]({e['url']}) · {md(e['observed_at'])} · sha256 `{e['sha256']}`")
    return "\n\n".join(lines).rstrip() + "\n"


def export_run(workspace: Path, run_id: str):
    with connect(workspace) as con:
        row = con.execute("SELECT report,payload,manifest FROM runs WHERE run_id=? AND phase='published'", (run_id,)).fetchone()
        if not row:
            raise ValueError("Published run not found")
        latest = con.execute("SELECT run_id FROM runs WHERE phase='published' ORDER BY updated_at DESC,run_id DESC LIMIT 1").fetchone()[0]
    out = workspace / "reports" / run_id
    out.mkdir(parents=True, exist_ok=True)
    atomic_text(out / "daily.md", row[0])
    manifest = json.loads(row[2])
    # Add a read-only decision projection; preserve legacy exports byte-for-byte.
    if "evaluation" in manifest:
        exported = json.loads(row[1])
        exported["evaluation"] = manifest["evaluation"]
        atomic_text(out / "data.json", dumps(exported) + "\n")
    else:
        atomic_text(out / "data.json", row[1] + "\n")
    atomic_text(out / "audit.json", row[2] + "\n")
    # The database is authoritative. latest.json is only a regenerable convenience pointer.
    if latest == run_id:
        atomic_text(workspace / "reports" / "latest.json", dumps({"run_id": run_id, "report": str(out / "daily.md")}) + "\n")
    return str(out / "daily.md")


def publish(workspace: Path, draft: Path, *, allow_fixture=False):
    data = load(draft)
    if not isinstance(data, dict) or not isinstance(data.get("run_id"), str):
        raise ValueError("Validation failed:\n$.run_id: expected string in a draft object")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", data["run_id"]):
        raise ValueError("Validation failed:\n$.run_id: invalid run identity")
    serialized = dumps(data)
    with connect(workspace) as con:
        locked_policy(workspace, con)
        con.execute("BEGIN IMMEDIATE")
        r = con.execute("SELECT * FROM runs WHERE run_id=?", (data["run_id"],)).fetchone()
        if not r:
            raise ValueError("Unknown run; use start first")
        if r["phase"] == "published":
            if r["payload"] != serialized:
                raise ValueError("Immutable published run; start a new revision instead")
            if r["fixture"] and not allow_fixture:
                raise ValueError("Synthetic fixture cannot be published as a real project")
            return {"status": "already_published", "report": export_run(workspace, data["run_id"])}
        evaluated_at = now()
        policy = runtime_policy.for_run(workspace, con, data["run_id"])
        errors, warnings, decisions = evaluate(data, allow_fixture=allow_fixture, at=evaluated_at,
                                                ttl_hours=policy["dynamic_ttl_hours"])
        if not errors and not allow_fixture:
            import provenance
            errors.extend(provenance.verify(workspace, data))
        if errors:
            raise ValueError("Validation failed:\n" + "\n".join(errors))
        if r["report_date"] != data["report_date"]:
            raise ValueError("report_date differs from start record")
        for e in data["evidence"]:
            old = con.execute("SELECT sha256,payload FROM evidence WHERE evidence_id=?", (e["id"],)).fetchone()
            if old and old["payload"] != dumps(e):
                raise ValueError("Evidence IDs are immutable; use a new ID for new observation: " + e["id"])
            con.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?)", (e["id"], e["sha256"], dumps(e)))
        changes, deltas = [], {}
        for p in data["projects"]:
            old = con.execute("SELECT current_payload FROM projects WHERE project_id=?", (p["project_id"],)).fetchone()
            previous = json.loads(old[0]) if old else None
            if previous and parsed_time(p["checked_at"]) < parsed_time(previous["checked_at"]):
                raise ValueError("Refusing stale snapshot rollback: " + p["project_id"])
            deltas[p["project_id"]] = star_change(previous, p)
            compared = ("name", "canonical_url", "archived", "license_status", "license_spdx")
            if previous:
                for field in compared:
                    if previous.get(field) != p.get(field):
                        change = {"project_id": p["project_id"], "field": field, "before": previous.get(field), "after": p.get(field)}
                        changes.append(change)
                        con.execute("INSERT INTO changes VALUES(?,?,?,?,?)", (data["run_id"], p["project_id"], field,
                                    dumps(previous.get(field)), dumps(p.get(field))))
            # Omitted issues are not closed issues. Preserve their last observation.
            old_issues = {o["number"]: o for o in (previous or {}).get("opportunities", [])}
            tracked = dict(old_issues)
            for o in p["opportunities"]:
                old_issue = old_issues.get(o["number"])
                if old_issue and parsed_time(o["checked_at"]) < parsed_time(old_issue["checked_at"]):
                    raise ValueError("Refusing stale issue rollback")
                tracked[o["number"]] = o
                if old_issue:
                    for field in ("state", "assignees", "claim_status", "linked_pr", "ai_policy"):
                        if old_issue.get(field) != o.get(field):
                            change = {"project_id": p["project_id"], "field": "issue#" + str(o["number"]) + "." + field,
                                      "before": old_issue.get(field), "after": o.get(field)}
                            changes.append(change)
                            con.execute("INSERT INTO changes VALUES(?,?,?,?,?)", (data["run_id"], p["project_id"], change["field"],
                                        dumps(change["before"]), dumps(change["after"])))
            stored = dict(p)
            stored["opportunities"] = list(tracked.values())
            con.execute("INSERT INTO projects VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET last_seen=excluded.last_seen,current_payload=excluded.current_payload",
                        (p["project_id"], data["generated_at"], data["generated_at"], dumps(stored)))
            con.execute("INSERT INTO observations VALUES(?,?,?,?)", (data["run_id"], p["project_id"], p["checked_at"], dumps(p)))
        issue_count = sum(len(p["opportunities"]) for p in data["projects"])
        candidate_count = sum(item["status"] == "candidate_for_review" for item in decisions)
        manifest = {"version": VERSION, "projects": len(data["projects"]),
                    "evaluation": {"evaluated_at": evaluated_at.isoformat(), "rules_version": RULES_VERSION,
                                   "effective_policy": policy, "decisions": decisions},
                    "open_source": sum(p["license_status"] == "open_source_verified" for p in data["projects"]),
                    "issues": issue_count, "actionable": candidate_count, "changes": changes, "warnings": warnings,
                    "fixture": any(p.get("synthetic") is True for p in data["projects"]),
                    "verification_boundary": "structural and provenance checks, not semantic truth certification"}
        report = render(data, manifest, deltas)
        con.execute("UPDATE runs SET updated_at=?,phase='published',payload=?,manifest=?,report=?,fixture=? WHERE run_id=?",
                    (evaluated_at.isoformat(), serialized, dumps(manifest), report, int(manifest["fixture"]), data["run_id"]))
    # If interrupted here, export reconstructs all files from the committed database.
    report_path = export_run(workspace, data["run_id"])
    return {"status": "published", "report": report_path, "warnings": warnings,
            "projects": manifest["projects"], "contribution_candidates": candidate_count}


def context(workspace: Path, limit=20):
    with connect(workspace) as con:
        locked_policy(workspace, con)
        policy = runtime_policy.resolve(workspace)
        context_limit = policy["context_chars_max"]
        runs = [dict(r) for r in con.execute("SELECT run_id,report_date,phase,updated_at FROM runs ORDER BY updated_at DESC LIMIT 3")]
        records = con.execute("SELECT project_id,last_seen,current_payload FROM projects ORDER BY last_seen DESC LIMIT ?", (min(limit, 50),)).fetchall()
        projects = []
        for row in records:
            p = json.loads(row["current_payload"])
            projects.append({"id": row["project_id"], "name": p["name"], "last_seen": row["last_seen"],
                             "checked_at": p["checked_at"], "stale_now": not fresh(p["checked_at"], policy["dynamic_ttl_hours"]),
                             "category": p["category"], "url": p["canonical_url"],
                             "tracked_issues": [{"number": o["number"], "state_last_observed": o["state"],
                                                 "checked_at": o["checked_at"], "stale_now": not fresh(o["checked_at"], policy["dynamic_ttl_hours"])}
                                                for o in p.get("opportunities", [])[-5:]]})
        feedback = [dict(r) for r in con.execute("SELECT * FROM feedback ORDER BY feedback_id DESC LIMIT 10")]
        for item in feedback:
            item["note"] = item["note"][:500]
            item["user_quote"] = item["user_quote"][:500]
    result = {"warning": "Historical observations are not current facts. Recheck before recommending.",
              "recent_runs": runs, "recent_projects": projects, "explicit_user_feedback": feedback,
              "read_policy_from": [str(workspace / n) for n in ("mission.md", "profile.json", "config.json")]}
    # Decrease the batch if the serialized handoff would grow too large.
    while len(dumps(result)) > context_limit and result["recent_projects"]:
        result["recent_projects"].pop()
    while len(dumps(result)) > context_limit and result["explicit_user_feedback"]:
        result["explicit_user_feedback"].pop()
    while len(dumps(result)) > context_limit and result["recent_runs"]:
        result["recent_runs"].pop()
    if len(dumps(result)) > context_limit:
        raise ValueError("Context metadata exceeds configured limit")
    return result


def query(workspace: Path, project_id: str):
    with connect(workspace) as con:
        rows = con.execute("SELECT run_id,observed_at,payload FROM observations WHERE project_id=? ORDER BY observed_at DESC LIMIT 3", (project_id,)).fetchall()
    return [{"run_id": r["run_id"], "observed_at": r["observed_at"], "record": json.loads(r["payload"])} for r in rows]


def checkpoint(workspace: Path, run_id: str, phase: str, note: str):
    with connect(workspace) as con:
        locked_policy(workspace, con)
        row = con.execute("SELECT phase FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row or row[0] == "published":
            raise ValueError("Missing or immutable run")
        con.execute("UPDATE runs SET phase=?,updated_at=? WHERE run_id=?", (phase, stamp(), run_id))
    directory = workspace / "runs" / run_id
    # Append-only timestamped handoff, not a replacement for evidence.
    target = directory / ("checkpoint-" + now().strftime("%H%M%S%f") + ".json")
    atomic_text(target, dumps({"run_id": run_id, "phase": phase, "at": stamp(), "note": note[:6000]}) + "\n")
    return {"checkpoint": str(target)}


def feedback(workspace, project_id, event, note, quote):
    if not quote.strip():
        raise ValueError("Need the user's actual explicit instruction; silence is not preference")
    with connect(workspace) as con:
        locked_policy(workspace, con)
        con.execute("INSERT INTO feedback(created_at,project_id,event,note,user_quote) VALUES(?,?,?,?,?)",
                    (stamp(), project_id, event, note, quote))
    return {"status": "recorded", "profile_changed": False}


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("start")
    c = sub.add_parser("context"); c.add_argument("--limit", type=int, default=20)
    q = sub.add_parser("query"); q.add_argument("project_id")
    for action in ("validate", "publish"):
        p = sub.add_parser(action); p.add_argument("draft", type=Path)
    p = sub.add_parser("export"); p.add_argument("run_id")
    p = sub.add_parser("checkpoint"); p.add_argument("run_id")
    p.add_argument("--phase", choices=["discover", "verify", "assess", "audit", "degraded"], required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("feedback"); p.add_argument("--project-id")
    p.add_argument("--event", choices=["watch", "dismiss", "interested", "claimed_by_user", "submitted", "merged", "correction"], required=True)
    p.add_argument("--note", required=True); p.add_argument("--user-quote", required=True)
    args = parser.parse_args()
    workspace = args.workspace.expanduser().resolve()
    try:
        if args.command == "init": result = initialize(workspace)
        elif args.command == "start": result = start(workspace)
        elif args.command == "context": result = context(workspace, args.limit)
        elif args.command == "query": result = query(workspace, args.project_id)
        elif args.command == "validate":
            errors, warnings = validate(load(args.draft), workspace=workspace)
            result = {"valid": not errors, "errors": errors, "warnings": warnings}
            print(dumps(result)); return 1 if errors else 0
        elif args.command == "publish": result = publish(workspace, args.draft)
        elif args.command == "export": result = {"report": export_run(workspace, args.run_id)}
        elif args.command == "checkpoint": result = checkpoint(workspace, args.run_id, args.phase, args.note)
        else: result = feedback(workspace, args.project_id, args.event, args.note, args.user_quote)
        print(dumps(result))
        return 0
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as exc:
        print(dumps({"error": str(exc), "command": args.command}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
