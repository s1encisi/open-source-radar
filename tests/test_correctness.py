"""Regression cases for publication boundaries. Synthetic data; no network."""
import contextlib
import copy
from datetime import timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_radar

radar = test_radar.radar
gh = test_radar.gh


class InputBoundaryTests(unittest.TestCase):
    def test_malformed_fields_return_paths_instead_of_exceptions(self):
        cases = [
            (("projects", 0, "canonical_url"), None),
            (("projects", 0, "canonical_url"), []),
            (("projects", 0, "scores"), []),
            (("projects", 0, "scores", "interest"), None),
            (("projects", 0, "evidence_ids"), [{}]),
            (("projects", 0, "claims", 0, "kind"), []),
            (("projects", 0, "category"), {}),
            (("projects", 0, "opportunities", 0, "number"), []),
            (("projects", 0, "opportunities", 0, "checks"), None),
            (("projects", 0, "opportunities", 0, "checks", "comments"), "true"),
            (("projects", 0, "opportunities", 0, "assignees"), "someone"),
            (("projects", 0, "opportunities", 0, "state"), []),
            (("evidence", 0, "role"), []),
            (("evidence", 0, "url"), {}),
            (("coverage", 0, "evidence_ids"), None),
            (("coverage", 0, "status"), {}),
            (("limitations",), [None]),
            (("run_id",), []),
        ]
        for keys, value in cases:
            with self.subTest(path=keys):
                data = test_radar.fixture()
                target = data
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                errors, _ = radar.validate(data, allow_fixture=True)
                expected = "$" + "".join(f"[{k}]" if isinstance(k, int) else "." + k for k in keys)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_unknown_fields_do_not_bypass_nested_validation(self):
        data = test_radar.fixture()
        data["projects"][0]["scores"]["extra"] = {"value": 1}
        errors, _ = radar.validate(data, allow_fixture=True)
        self.assertTrue(errors)

    def test_valid_url_handles_non_strings(self):
        for value in (None, [], {}, 1, True):
            with self.subTest(value=value):
                self.assertFalse(radar.valid_url(value))

    def test_stale_negative_states_need_reverification(self):
        for field, value in (("state", "closed"), ("assignees", ["someone"]),
                             ("claim_status", "claimed"), ("linked_pr", "open"), ("linked_pr", "merged")):
            with self.subTest(field=field, value=value):
                data = test_radar.fixture()
                issue = data["projects"][0]["opportunities"][0]
                issue[field] = value
                issue["checked_at"] = (radar.now() - timedelta(hours=25)).isoformat()
                self.assertEqual(test_radar.gate(data), "needs_verification")

    def test_stale_evidence_cannot_support_negative_state(self):
        for field, value, role in (("state", "closed", "issue"),
                                   ("claim_status", "claimed", "comments"),
                                   ("linked_pr", "merged", "pull_requests")):
            with self.subTest(field=field):
                data = test_radar.fixture()
                data["projects"][0]["opportunities"][0][field] = value
                next(e for e in data["evidence"] if e["role"] == role)["observed_at"] = (
                    radar.now() - timedelta(hours=25)).isoformat()
                self.assertEqual(test_radar.gate(data), "needs_verification")

    def test_stale_archive_is_not_current_exclusion(self):
        data = test_radar.fixture()
        data["projects"][0].update(archived=True, checked_at=(radar.now() - timedelta(hours=25)).isoformat())
        self.assertEqual(test_radar.gate(data), "needs_verification")

    def test_current_closed_issue_does_not_require_complete_pr_search(self):
        data = test_radar.fixture()
        issue = data["projects"][0]["opportunities"][0]
        issue["state"] = "closed"
        issue["checks"]["pr_search"] = False
        self.assertEqual(test_radar.gate(data), "excluded")


class PublicationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_radar.StateTests()
        self.helper.setUp()
        self.addCleanup(self.helper.tearDown)
        self.root = self.helper.root

    def test_ttl_boundary_has_one_persisted_decision(self):
        data, path = self.helper.prepared()
        at = radar.now()
        generated = at - timedelta(hours=1)
        data["generated_at"] = generated.isoformat()
        project = data["projects"][0]
        project["checked_at"] = (generated - timedelta(minutes=2)).isoformat()
        issue = project["opportunities"][0]
        issue["checked_at"] = (at - timedelta(hours=24, minutes=30)).isoformat()
        for evidence in data["evidence"]:
            evidence["observed_at"] = (issue["checked_at"] if evidence["role"] in
                {"issue", "comments", "timeline", "pull_requests"} else project["checked_at"])
        radar.atomic_text(path, radar.dumps(data))
        with patch.object(radar, "now", return_value=at):
            result = radar.publish(self.root, path, allow_fixture=True)
        directory = Path(result["report"]).parent
        audit = radar.load(directory / "audit.json")
        exported = radar.load(directory / "data.json")
        self.assertEqual(result["contribution_candidates"], 0)
        self.assertEqual(audit["evaluation"]["evaluated_at"], at.isoformat())
        decision = audit["evaluation"]["decisions"][0]
        self.assertEqual(decision["status"], "needs_verification")
        self.assertTrue(decision["reason_codes"])
        self.assertEqual(exported["evaluation"], audit["evaluation"])
        report = (directory / "daily.md").read_text(encoding="utf-8")
        self.assertIn("#1｜待核验", report)
        self.assertNotIn("#1｜待你复核的贡献候选", report)
        with patch.object(radar, "now", return_value=at + timedelta(days=7)):
            radar.export_run(self.root, data["run_id"])
        self.assertEqual((directory / "daily.md").read_text(encoding="utf-8"), report)

    def test_repeat_after_expiry_preserves_original_publication(self):
        data, path = self.helper.prepared()
        first = radar.publish(self.root, path, allow_fixture=True)
        with radar.connect(self.root) as con:
            before = tuple(con.execute("SELECT updated_at,payload,manifest,report FROM runs").fetchone())
        with patch.object(radar, "now", return_value=radar.now() + timedelta(hours=25)):
            repeated = radar.publish(self.root, path, allow_fixture=True)
        self.assertEqual(repeated["status"], "already_published")
        self.assertEqual(repeated["report"], first["report"])
        with radar.connect(self.root) as con:
            self.assertEqual(tuple(con.execute("SELECT updated_at,payload,manifest,report FROM runs").fetchone()), before)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)

    def test_expired_first_publication_is_rejected(self):
        _, path = self.helper.prepared()
        with patch.object(radar, "now", return_value=radar.now() + timedelta(hours=25)):
            with self.assertRaisesRegex(ValueError, "Validation failed"):
                radar.publish(self.root, path, allow_fixture=True)
        with radar.connect(self.root) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)

    def test_repeat_with_changed_content_is_rejected_after_expiry(self):
        data, path = self.helper.prepared()
        radar.publish(self.root, path, allow_fixture=True)
        data["limitations"].append("changed")
        radar.atomic_text(path, radar.dumps(data))
        with patch.object(radar, "now", return_value=radar.now() + timedelta(hours=25)):
            with self.assertRaisesRegex(ValueError, "Immutable published run"):
                radar.publish(self.root, path, allow_fixture=True)

    def test_repeat_cannot_bypass_fixture_or_policy_guard(self):
        _, path = self.helper.prepared()
        radar.publish(self.root, path, allow_fixture=True)
        with self.assertRaises(ValueError):
            radar.publish(self.root, path)
        radar.atomic_text(self.root / "mission.md", "changed policy")
        with self.assertRaisesRegex(ValueError, "Policy drift"):
            radar.publish(self.root, path, allow_fixture=True)

    def test_malformed_draft_does_not_write_state(self):
        data, path = self.helper.prepared()
        data["projects"][0]["canonical_url"] = None
        radar.atomic_text(path, radar.dumps(data))
        with self.assertRaisesRegex(ValueError, r"projects\[0\].canonical_url"):
            radar.publish(self.root, path, allow_fixture=True)
        with radar.connect(self.root) as con:
            for table in ("evidence", "projects", "observations"):
                self.assertEqual(con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0)


class CollectorCompletenessTests(unittest.TestCase):
    def run_collector(self, result, responses=None):
        with tempfile.TemporaryDirectory(prefix="radar-collector-test-") as directory:
            output = Path(directory) / "captured.json"
            client = gh.Client()
            client.responses = responses or [{"status": 200}]
            client.requests = len(client.responses)
            stream = io.StringIO()
            with patch.object(gh, "Client", return_value=client), patch.object(gh, "search", return_value=result), \
                 patch.object(sys, "argv", ["github_readonly.py", "--output", str(output), "search", "synthetic"]), \
                 contextlib.redirect_stdout(stream):
                code = gh.main()
            return code, json.loads(stream.getvalue()), radar.load(output)

    def test_all_200_partial_results_are_not_complete(self):
        cases = [
            {"partial": True},
            {"comments": {"complete": False, "reason": "page_cap"}},
            {"linked_pr_details_truncated": True},
            {"readme": {"decoded_text_truncated": True}},
            {"pr_search": {"status": 200, "data": {"total_count": 2, "items": [{}], "incomplete_results": False}}},
            {"pr_search": {"status": 200, "data": {"total_count": 0, "items": [], "incomplete_results": True}}},
        ]
        for result in cases:
            with self.subTest(result=result):
                code, printed, saved = self.run_collector(result)
                self.assertEqual(code, 1)
                self.assertTrue(printed["partial"])
                self.assertTrue(saved["partial"])
                self.assertTrue(saved["transport_complete"])
                self.assertTrue(saved["incomplete_reasons"])
                self.assertEqual(printed["incomplete_reasons"], saved["incomplete_reasons"])

    def test_complete_empty_search_is_success(self):
        code, printed, saved = self.run_collector({"partial": False, "response": {"status": 200,
            "data": {"total_count": 0, "items": [], "incomplete_results": False}}})
        self.assertEqual(code, 0)
        self.assertFalse(printed["partial"])
        self.assertEqual(saved["incomplete_reasons"], [])

    def test_http_failure_records_transport_and_completeness(self):
        code, printed, saved = self.run_collector({"complete": False}, [{"status": 429}])
        self.assertEqual(code, 1)
        self.assertFalse(saved["transport_complete"])
        self.assertTrue(saved["partial"])
        self.assertEqual(printed["non_200"], 1)


if __name__ == "__main__":
    unittest.main()
