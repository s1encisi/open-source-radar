"""Structural checks before any rule evaluation. No coercion or I/O."""


def structure_errors(data):
    errors = []

    def fields(value, path, spec):
        if not isinstance(value, dict):
            errors.append(path + ": expected object")
            return False
        for key, types in spec.items():
            allowed = types if isinstance(types, tuple) else (types,)
            if key not in value:
                errors.append(path + "." + key + ": missing required field")
            elif type(value[key]) not in allowed:
                expected = "/".join("null" if t is type(None) else t.__name__ for t in allowed)
                errors.append(path + "." + key + ": expected " + expected)
        return True

    def strings(value, path):
        if not isinstance(value, list):
            return  # Container errors are reported by fields().
        for index, item in enumerate(value):
            if not isinstance(item, str):
                errors.append(f"{path}[{index}]: expected str")

    def items(value):
        return enumerate(value) if isinstance(value, list) else []

    root_spec = {key: str for key in ("run_id", "report_date", "generated_at", "report_timezone", "utc_offset")}
    root_spec.update({key: list for key in ("coverage", "evidence", "projects", "limitations")})
    root_spec["metrics"] = dict
    if not fields(data, "$", root_spec):
        return errors
    if "schema_version" in data and (type(data["schema_version"]) is not int or data["schema_version"] != 1):
        errors.append("$.schema_version: expected supported draft schema 1")
    strings(data.get("limitations"), "$.limitations")
    for index, evidence in items(data.get("evidence")):
        path = f"$.evidence[{index}]"
        spec = {key: str for key in ("id", "url", "observed_at", "role", "excerpt", "sha256")}
        spec["primary"] = bool
        fields(evidence, path, spec)
    for index, coverage in items(data.get("coverage")):
        path = f"$.coverage[{index}]"
        spec = {key: str for key in ("family", "status", "query", "note")}
        spec.update(found=int, verified=int)
        if fields(coverage, path, spec) and "evidence_ids" in coverage:
            fields(coverage, path, {"evidence_ids": list})
            strings(coverage["evidence_ids"], path + ".evidence_ids")
    for index, project in items(data.get("projects")):
        path = f"$.projects[{index}]"
        spec = {key: str for key in ("project_id", "provider", "name", "canonical_url", "category",
                                    "license_status", "checked_at", "relevance", "caveats")}
        spec.update(license_spdx=(str, type(None)), language=(str, type(None)),
                    archived=(bool, type(None)), stars=(int, type(None)), evidence_ids=list,
                    claims=list, scores=dict, opportunities=list)
        if not fields(project, path, spec):
            continue
        if "synthetic" in project:
            fields(project, path, {"synthetic": bool})
        strings(project.get("evidence_ids"), path + ".evidence_ids")
        for ci, claim in items(project.get("claims")):
            cp = f"{path}.claims[{ci}]"
            if fields(claim, cp, {"kind": str, "text": str}) and "evidence_ids" in claim:
                fields(claim, cp, {"evidence_ids": list})
                strings(claim["evidence_ids"], cp + ".evidence_ids")
        scores = project.get("scores")
        if isinstance(scores, dict):
            dimensions = ("interest", "novelty", "relevance", "health")
            for key in dimensions:
                if key not in scores:
                    errors.append(path + ".scores." + key + ": missing required field")
            for key, score in scores.items():
                if key not in dimensions:
                    errors.append(path + ".scores." + str(key) + ": unknown scoring dimension")
                fields(score, path + ".scores." + str(key), {"value": (int, float), "reason": str})
        for oi, issue in items(project.get("opportunities")):
            op = f"{path}.opportunities[{oi}]"
            spec = {key: str for key in ("title", "url", "state", "checked_at", "claim_status", "linked_pr",
                                        "scope", "ai_policy", "skill_match", "task", "first_step", "acceptance",
                                        "skills_needed", "skill_gaps")}
            spec.update(number=int, assignees=(list, type(None)), checks=dict, evidence_ids=list)
            if not fields(issue, op, spec):
                continue
            if "related_pr_numbers" in issue:
                numbers = issue["related_pr_numbers"]
                if not isinstance(numbers, list) or any(type(n) is not int or n < 1 for n in numbers):
                    errors.append(op + ".related_pr_numbers: expected positive integer list")
            strings(issue.get("evidence_ids"), op + ".evidence_ids")
            strings(issue.get("assignees"), op + ".assignees")
            checks = issue.get("checks")
            if isinstance(checks, dict):
                for key, value in checks.items():
                    if type(value) is not bool:
                        errors.append(op + ".checks." + str(key) + ": expected bool")
    return errors
