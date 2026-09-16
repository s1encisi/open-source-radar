#!/usr/bin/env python3
"""Exercise two synthetic observations with no network or third-party packages."""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import radar
from test_radar import fixture


def observation(workspace, number, observed_at):
    run = radar.start(workspace)
    data = fixture()
    template = radar.load(Path(run["draft"]))
    for key in ("run_id", "report_date", "generated_at", "report_timezone", "utc_offset"):
        data[key] = template[key]
    mapping = {e["id"]: run["run_id"] + "-" + e["id"] for e in data["evidence"]}
    for evidence in data["evidence"]:
        evidence["id"] = mapping[evidence["id"]]
        evidence["observed_at"] = observed_at
    for coverage in data["coverage"]:
        coverage["evidence_ids"] = [mapping[i] for i in coverage["evidence_ids"]]
    project = data["projects"][0]
    project["checked_at"] = observed_at
    project["stars"] = 10 if number == 1 else 14
    project["evidence_ids"] = [mapping[i] for i in project["evidence_ids"]]
    for claim in project["claims"]:
        claim["evidence_ids"] = [mapping[i] for i in claim["evidence_ids"]]
    issue = project["opportunities"][0]
    issue["checked_at"] = observed_at
    issue["evidence_ids"] = [mapping[i] for i in issue["evidence_ids"]]
    if number == 2:
        issue["assignees"] = ["synthetic-contributor"]
        issue["claim_status"] = "claimed"
    path = Path(run["draft"])
    radar.atomic_text(path, radar.dumps(data))
    result = radar.publish(workspace, path, allow_fixture=True)
    status, _ = radar.opportunity_gate(project, issue, {e["id"]: e for e in data["evidence"]})
    return data, path, result, status


def run_demo(workspace):
    radar.initialize(workspace)
    at = radar.now()
    first = observation(workspace, 1, (at - timedelta(hours=2)).isoformat())
    second = observation(workspace, 2, (at - timedelta(minutes=2)).isoformat())
    radar.publish(workspace, second[1], allow_fixture=True)
    report = Path(second[2]["report"])
    expected = report.read_bytes()
    report.rename(report.with_suffix(".before-recovery.md"))
    radar.export_run(workspace, second[0]["run_id"])
    recovered = report.read_bytes() == expected
    with radar.connect(workspace) as con:
        projects = con.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        observations = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        runs = con.execute("SELECT COUNT(*) FROM runs WHERE phase='published'").fetchone()[0]
    delta = radar.star_change(first[0]["projects"][0], second[0]["projects"][0])
    if (projects, observations, runs) != (1, 2, 2) or not recovered or delta["delta"] != 4:
        raise RuntimeError("Demo invariants failed")
    if (first[3], second[3]) != ("candidate_for_review", "in_progress"):
        raise RuntimeError("Opportunity transition failed")
    summary = {"synthetic": True, "network_requests": 0, "projects": projects,
               "observations": observations, "published_runs": runs, "star_delta": delta["delta"],
               "opportunity_states": [first[3], second[3]], "idempotent_publish": True,
               "report_recovery": recovered, "reports": [
                   str(Path(item[2]["report"]).relative_to(workspace)) for item in (first, second)]}
    radar.atomic_text(workspace / "summary.json", radar.dumps(summary) + "\n")
    print("Synthetic offline demo — no network requests")
    print(f"Projects: {projects} | Observations: {observations}")
    print(f"Stars: 10 -> 14 | Delta: +{delta['delta']}")
    print(f"Opportunity: {first[3]} -> {second[3]}")
    print("Idempotent publish: PASS | Report recovery: PASS")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Keep output in a new or empty directory")
    args = parser.parse_args()
    if args.output:
        output = args.output.resolve()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            parser.error("Output must be a new or empty directory; existing data was not changed")
        run_demo(output)
        print("Output:", output)
    else:
        with tempfile.TemporaryDirectory(prefix="radar-demo-") as directory:
            run_demo(Path(directory) / "workspace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
