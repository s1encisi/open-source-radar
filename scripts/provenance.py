"""Bind critical GitHub evidence to registered captures and exact source slices."""
import radar
import workflow_store as store

PROJECT_ROLES = {"repository", "readme", "license", "contributing", "ai_policy"}
ISSUE_ROLES = {"issue", "comments", "timeline", "pull_requests"}


def views(capture, capture_id):
    result = capture["result"]
    subject = {"project_id": capture["project_id"]}
    if capture["kind"] == "repo":
        mapping = {key: key for key in PROJECT_ROLES}
    else:
        subject["issue_number"] = capture["issue_number"]
        mapping = {"issue": "issue", "comments": "comments", "timeline": "timeline", "pull_requests": "pr_search"}
    output = {}
    for role, key in sorted(mapping.items()):
        if key not in result:
            continue
        value = result[key]
        pointer = "/result/" + key
        if role in {"readme", "license", "contributing", "ai_policy"} and isinstance(value.get("decoded_text_untrusted"), str):
            value = value["decoded_text_untrusted"]
            pointer += "/decoded_text_untrusted"
        projection = None
        if role == "pull_requests":
            search = result["pr_search"]
            body = search.get("data") or {}
            value = {"search": {"status": search.get("status"), "url": search.get("url"),
                                "total_count": body.get("total_count"), "incomplete_results": body.get("incomplete_results"),
                                "items": [{k: item.get(k) for k in ("number", "title", "state", "html_url")} for item in body.get("items", [])]},
                     "linked_prs": [{"status": item.get("status"), "url": item.get("url"),
                                     "data": {k: (item.get("data") or {}).get(k) for k in ("number", "title", "state", "merged", "body")}}
                                    for item in result.get("linked_pr_details", [])]}
            projection = "pr_evidence_v1"
        text = value if isinstance(value, str) else radar.dumps(value)
        excerpt = text[:12000]
        original = result[key]
        url = original.get("url") or capture["api_root"] + "/issues/" + str(capture.get("issue_number")) + "/" + key
        primary = original.get("status") == 200 if "status" in original else original.get("pages", 0) > 0
        output[role] = {"id": "ev-" + capture_id + "-" + role, "url": url,
                        "observed_at": capture["observed_at"], "role": role, "primary": primary,
                        "excerpt": excerpt, "sha256": radar.digest(excerpt.encode("utf-8")),
                        "subject": dict(subject), "source": {"capture_id": capture_id,
                        "pointer": pointer, "length": len(excerpt)}, "excerpt_truncated": len(text) > 12000}
        if projection:
            output[role]["source"]["projection"] = projection
            output[role]["source"]["pointer"] = "/result"
    return output


def verify(workspace, data):
    """Check provenance before publication; this does not certify semantic truth."""
    errors, verified, loaded = [], {}, {}
    for evidence in data["evidence"]:
        source = evidence.get("source")
        if source is None:
            continue
        try:
            if not isinstance(source, dict) or not isinstance(source.get("capture_id"), str):
                raise ValueError("source must contain a string capture_id")
            cid = source["capture_id"]
            if cid not in loaded:
                loaded[cid] = store.load_capture(workspace, cid, data["run_id"])
            expected = views(loaded[cid], cid).get(evidence["role"])
            if not expected or any(evidence.get(key) != expected[key] for key in
                ("url", "observed_at", "role", "primary", "excerpt", "sha256", "subject", "source")):
                raise ValueError("Evidence differs from its captured source or subject")
            verified[evidence["id"]] = (evidence, loaded[cid])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            errors.append(evidence["id"] + ": " + str(exc))

    def bound(ids, role, subject):
        return [pair for eid, pair in verified.items() if eid in ids and pair[0]["role"] == role
                and pair[0]["primary"] and pair[0]["subject"] == subject]

    for project in data["projects"]:
        if project["provider"] != "github":
            if project["project_id"].startswith("github:") or project["canonical_url"].startswith("https://github.com/"):
                errors.append(project["project_id"] + ": GitHub identity cannot use another provider")
            continue
        pid = project["project_id"]
        subject = {"project_id": pid}
        repositories = bound(project["evidence_ids"], "repository", subject)
        if not repositories:
            errors.append(pid + ": bound repository capture required; collect and prepare this run")
            continue
        capture = repositories[0][1]
        raw = capture["result"]["repository"]["data"]
        expected = {"name": raw["full_name"], "canonical_url": raw["html_url"], "archived": raw["archived"],
                    "stars": raw["stargazers_count"], "language": raw.get("language"), "checked_at": capture["observed_at"],
                    "license_spdx": (raw.get("license") or {}).get("spdx_id")}
        for key, value in expected.items():
            if project[key] != value:
                errors.append(pid + ": machine field differs from capture: " + key)
        review = project.get("review")
        if not isinstance(review, dict) or review.get("status") != "complete":
            errors.append(pid + ": semantic review is pending")
        if project["license_status"] == "open_source_verified" and not bound(project["evidence_ids"], "license", subject):
            errors.append(pid + ": license evidence must be bound to this repository")
        for issue in project["opportunities"]:
            issue_subject = {**subject, "issue_number": issue["number"]}
            matches = bound(issue["evidence_ids"], "issue", issue_subject)
            label = pid + "#" + str(issue["number"])
            if not matches:
                errors.append(label + ": bound issue capture required")
                continue
            capture = matches[0][1]
            raw = capture["result"]["issue"]["data"]
            expected = {"number": raw["number"], "title": raw["title"], "url": raw["html_url"],
                        "state": raw["state"], "assignees": [a["login"] for a in raw.get("assignees", [])],
                        "checked_at": capture["observed_at"]}
            for key, value in expected.items():
                if issue[key] != value:
                    errors.append(label + ": machine field differs from capture: " + key)
            if issue["linked_pr"] in {"open", "merged"}:
                numbers = issue.get("related_pr_numbers", [])
                details = [(item.get("data") or {}) for item in capture["result"].get("linked_pr_details", []) if item.get("status") == 200]
                supported = any(p.get("number") in numbers and
                                (p.get("state") == "open" if issue["linked_pr"] == "open" else p.get("merged") is True)
                                for p in details)
                if not supported:
                    errors.append(label + ": linked PR decision needs captured related_pr_numbers with matching state")
            for role, flag in (("comments", "comments"), ("timeline", "timeline"), ("pull_requests", "pr_search")):
                if issue["checks"].get(flag):
                    evidence = bound(issue["evidence_ids"], role, issue_subject)
                    part = capture["result"][flag]
                    if role == "pull_requests":
                        body = part.get("data") or {}
                        complete = part.get("status") == 200 and body.get("incomplete_results") is False and body.get("total_count", 1) <= len(body.get("items", [])) and not capture["result"].get("linked_pr_details_truncated")
                    else:
                        complete = part.get("complete") is True
                    same_capture = any(ev["source"]["capture_id"] == matches[0][0]["source"]["capture_id"] for ev, _ in evidence)
                    if not evidence or not complete or not same_capture:
                        errors.append(label + ": incomplete or unbound check cannot be marked complete: " + flag)
            if issue["checks"].get("contributing") and not bound(issue["evidence_ids"], "contributing", subject):
                errors.append(label + ": contributing check needs bound process documentation")
            for eid in issue["evidence_ids"]:
                if eid in verified:
                    ev = verified[eid][0]
                    wanted = issue_subject if ev["role"] in ISSUE_ROLES else subject
                    if ev["role"] in ISSUE_ROLES | PROJECT_ROLES and ev["subject"] != wanted:
                        errors.append(label + ": evidence subject mismatch: " + eid)
    return errors
