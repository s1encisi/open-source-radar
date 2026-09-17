"""Snapshot compatibility and CLI integration; synthetic data only."""
import contextlib
from datetime import timedelta
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_radar

radar, gh = test_radar.radar, test_radar.gh


class SnapshotCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_radar.StateTests()
        self.helper.setUp()
        self.addCleanup(self.helper.tearDown)
        self.root = self.helper.root

    def test_publication_samples_the_clock_once(self):
        _, path = self.helper.prepared()
        at = radar.now()
        with patch.object(radar, "now", side_effect=[at, at + timedelta(days=2)]) as clock:
            result = radar.publish(self.root, path, allow_fixture=True)
        self.assertEqual(clock.call_count, 1)
        self.assertEqual(result["contribution_candidates"], 1)

    def test_render_reads_snapshot_without_running_rules(self):
        data, path = self.helper.prepared()
        result = radar.publish(self.root, path, allow_fixture=True)
        report = Path(result["report"])
        audit = radar.load(report.parent / "audit.json")
        with patch.object(radar, "opportunity_decision", side_effect=AssertionError("Do not reevaluate")):
            self.assertEqual(radar.render(radar.load(path), audit, {}), report.read_text(encoding="utf-8"))

    def test_legacy_publication_exports_without_migration(self):
        _, path = self.helper.prepared()
        radar.publish(self.root, path, allow_fixture=True)
        with radar.connect(self.root) as con:
            row = con.execute("SELECT payload,manifest FROM runs").fetchone()
            legacy_manifest = json.loads(row["manifest"])
            legacy_manifest.pop("evaluation")
            legacy_manifest["version"] = "1.0.0"
            legacy_report = "# 历史报告\n\n保留原始判断。\n"
            legacy_payload = row["payload"]
            con.execute("UPDATE runs SET manifest=?, report=?", (radar.dumps(legacy_manifest), legacy_report))
        with patch.object(radar, "now", return_value=radar.now() + timedelta(days=2)):
            result = radar.publish(self.root, path, allow_fixture=True)
        directory = Path(result["report"]).parent
        self.assertEqual((directory / "daily.md").read_text(encoding="utf-8"), legacy_report)
        self.assertEqual((directory / "data.json").read_text(encoding="utf-8"), legacy_payload + "\n")
        self.assertNotIn("evaluation", radar.load(directory / "audit.json"))

    def test_cli_malformed_input_returns_json_error_without_traceback(self):
        data, path = self.helper.prepared()
        data["projects"][0]["canonical_url"] = None
        radar.atomic_text(path, radar.dumps(data))
        command = [sys.executable, "-B", str(radar.ROOT / "scripts" / "radar.py"),
                   "--workspace", str(self.root), "validate", str(path)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_context_emits_utf8_for_non_gbk_feedback(self):
        radar.feedback(self.root, None, "interested", "new projects", "关注新项目 🧪")
        command = [sys.executable, "-B", str(radar.ROOT / "scripts" / "radar.py"),
                   "--workspace", str(self.root), "context"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("🧪", json.loads(result.stdout)["explicit_user_feedback"][0]["user_quote"])


class CollectorIntegrationTests(unittest.TestCase):
    def test_remote_content_is_not_interpreted_as_collector_flags(self):
        result = {"repository": {"status": 200, "data": {"partial": True, "complete": False}},
                  "comments": {"complete": True, "items": [{"partial": True}]}}
        summary = gh.collection_completeness(result, [{"status": 200}])
        self.assertFalse(summary["partial"])
        self.assertEqual(summary["incomplete_reasons"], [])

    def test_search_cli_propagates_the_actual_pagination_flag(self):
        class FakeClient(gh.Client):
            def get(self, path):
                self.requests += 1
                response = {"status": 200, "data": {"total_count": 2, "items": [{"id": 1}],
                                                      "incomplete_results": False}}
                self.responses.append(response)
                return response
        with tempfile.TemporaryDirectory(prefix="radar-search-test-") as directory:
            output = Path(directory) / "result.json"
            stream = io.StringIO()
            with patch.object(gh, "Client", FakeClient), patch.object(sys, "argv", [
                    "github_readonly.py", "--output", str(output), "search", "synthetic"]):
                with contextlib.redirect_stdout(stream):
                    code = gh.main()
            self.assertEqual(code, 1)
            self.assertTrue(json.loads(stream.getvalue())["partial"])
            saved = radar.load(output)
            self.assertTrue(saved["result"]["partial"])
            self.assertTrue(saved["partial"])
