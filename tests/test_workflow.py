"""Synthetic captures exercise the whole deterministic workflow without network."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import test_radar
import provenance
import runtime_policy
import workflow
import workflow_store as store

radar = test_radar.radar


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspace"
        source = Path(self.tmp.name) / "source"
        shutil.copytree(radar.ROOT / "templates", source / "templates")
        config = radar.load(source / "templates/config.json")
        config["budgets"]["github_requests_max"] = 3
        config["budgets"]["initial_context_chars_target"] = 2048
        config["verification"]["dynamic_ttl_hours"] = 6
        radar.atomic_text(source / "templates/config.json", radar.dumps(config))
        with patch.object(radar, "ROOT", source):
            radar.initialize(self.root)
        self.run_id = radar.start(self.root)["run_id"]

    def capture(self, comments_complete=True):
        at = radar.stamp()
        repo = "fixture-only/not-a-real-project"
        api = "https://api.github.com/repos/" + repo
        def response(path, data):
            return {"url": api + path, "status": 200, "data": data, "observed_at": at}
        raw = {"id": 999000000, "full_name": repo, "private": False, "html_url": "https://github.com/" + repo,
               "archived": False, "stargazers_count": 10, "language": "Python", "description": "SYNTHETIC description",
               "license": {"spdx_id": "MIT"}}
        result = {"repository": response("", raw), "readme": response("/readme", {"content": "SYNTHETIC"}),
                  "license": response("/license", {"content": "SYNTHETIC license"}),
                  "contributing": response("/contents/CONTRIBUTING.md", {"content": "SYNTHETIC rules"}),
                  "ai_policy": response("/contents/AGENTS.md", {"content": "SYNTHETIC policy"})}
        base = {"repository": repo, "project_id": "github:999000000", "api_root": api, "observed_at": at}
        self.repo_capture = store.save_capture(self.root, self.run_id, "repo:" + repo,
                                                {**base, "kind": "repo", "result": result})
        issue = {"number": 1, "html_url": raw["html_url"] + "/issues/1", "title": "SYNTHETIC issue",
                 "state": "open", "assignees": []}
        result = {"issue": response("/issues/1", issue),
                  "comments": {"items": [], "pages": 1, "complete": comments_complete},
                  "timeline": {"items": [], "pages": 1, "complete": True},
                  "pr_search": {"url": "https://api.github.com/search/issues?q=synthetic", "status": 200,
                                "data": {"total_count": 0, "incomplete_results": False, "items": []}},
                  "linked_pr_details": [], "linked_pr_details_truncated": False}
        store.save_capture(self.root, self.run_id, "issue:" + repo + "#1",
                           {**base, "kind": "issue", "issue_number": 1, "result": result})
        return Path(workflow.prepare(self.root, self.run_id)["draft"])

    def annotations(self, draft):
        p = radar.load(draft)["projects"][0]
        return {"projects": [{"project_id": p["project_id"], "category": "developer_tools",
                 "license_status": "open_source_verified", "claims": p["claims"],
                 "relevance": "SYNTHETIC relevance", "caveats": "SYNTHETIC; no real project",
                 "scores": {k: {"value": 3, "reason": "SYNTHETIC assessment"}
                            for k in ("interest", "novelty", "relevance", "health")},
                 "opportunities": [{"number": 1, "claim_status": "none_observed", "linked_pr": "none_observed",
                   "scope": "clear", "ai_policy": "not_found_after_search",
                   "task": "SYNTHETIC task", "acceptance": "SYNTHETIC acceptance",
                   "policy_checks": {"contributing": True, "ai_policy_search": True}}]}]}

    def reviewed(self, comments_complete=True):
        draft = self.capture(comments_complete)
        return Path(workflow.review(self.root, draft, self.annotations(draft))["draft"])

    def test_full_capture_prepare_review_publish(self):
        path = self.reviewed()
        result = radar.publish(self.root, path)
        self.assertEqual(result["contribution_candidates"], 1)
        audit = radar.load(Path(result["report"]).parent / "audit.json")
        self.assertEqual(audit["evaluation"]["effective_policy"]["dynamic_ttl_hours"], 6)

    def test_pending_review_blocks_publication(self):
        with self.assertRaisesRegex(ValueError, "review is pending"):
            radar.publish(self.root, self.capture())

    def test_binding_rejects_url_subject_and_source_slice_changes(self):
        data = radar.load(self.reviewed())
        for field, value in (("url", "https://github.com/other/repo"),
                             ("subject", {"project_id": "github:123"}), ("excerpt", "invented")):
            with self.subTest(field=field):
                changed = copy.deepcopy(data)
                ev = next(e for e in changed["evidence"] if e["role"] == "repository")
                ev[field] = value
                ev["sha256"] = radar.digest(ev["excerpt"].encode("utf-8"))
                self.assertTrue(provenance.verify(self.root, changed))

    def test_foreign_project_cannot_reuse_valid_repository_evidence(self):
        data = radar.load(self.reviewed())
        data["projects"][0]["project_id"] = "github:123"
        self.assertTrue(provenance.verify(self.root, data))

    def test_machine_fields_cannot_be_hand_edited(self):
        data = radar.load(self.reviewed())
        data["projects"][0]["stars"] = 100000
        self.assertTrue(any("machine field" in e for e in provenance.verify(self.root, data)))

    def test_raw_capture_tampering_is_rejected(self):
        data = radar.load(self.reviewed())
        with radar.connect(self.root) as con:
            row = con.execute("SELECT path FROM captures WHERE capture_id=?", (self.repo_capture,)).fetchone()
        with (self.root / row[0]).open("a", encoding="utf-8") as stream:
            stream.write(" ")
        self.assertTrue(any("modified" in e for e in provenance.verify(self.root, data)))

    def test_partial_comments_cannot_be_promoted_by_hand(self):
        data = radar.load(self.reviewed(comments_complete=False))
        data["projects"][0]["opportunities"][0]["checks"]["comments"] = True
        self.assertTrue(any("cannot be marked complete" in e for e in provenance.verify(self.root, data)))

    def test_review_cannot_overwrite_machine_fields(self):
        draft = self.capture()
        review = self.annotations(draft)
        review["projects"][0]["stars"] = 100
        with self.assertRaisesRegex(ValueError, "machine fields"):
            workflow.review(self.root, draft, review)

    def test_other_run_cannot_reuse_capture(self):
        data = radar.load(self.reviewed())
        data["run_id"] = radar.start(self.root)["run_id"]
        self.assertTrue(provenance.verify(self.root, data))

    def test_budget_is_atomic_across_connections(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            reservations = list(pool.map(lambda _: store.reserve(self.root, self.run_id, "https://api.github.com/test"), range(10)))
        self.assertEqual(sum(value is not None for value in reservations), 3)
        self.assertEqual(store.status(self.root, self.run_id)["requests_remaining"], 0)

    def test_failure_and_unknown_attempts_still_consume_budget(self):
        request_id = store.reserve(self.root, self.run_id, "https://api.github.com/test")
        store.finish(self.root, request_id, {"status": 500, "latency_ms": 50})
        info = store.status(self.root, self.run_id)
        self.assertEqual(info["requests_reserved"], 1)
        self.assertEqual(info["failed_or_unknown_requests"], 1)

    def test_clock_policy_is_read_from_the_run_snapshot(self):
        data = test_radar.fixture()
        data["projects"][0]["checked_at"] = (radar.now() - timedelta(hours=8)).isoformat()
        data["run_id"] = self.run_id
        errors, _ = radar.validate(data, allow_fixture=True, workspace=self.root)
        self.assertTrue(any("TTL" in e for e in errors))

    def test_context_honors_configured_character_limit(self):
        for _ in range(10):
            radar.feedback(self.root, None, "watch", "x" * 500, "explicit " + "y" * 500)
        self.assertLessEqual(len(radar.dumps(radar.context(self.root))), 2048)

    def test_invalid_config_is_rejected_before_start(self):
        raw = radar.load(self.root / "config.json")
        raw["budgets"]["github_requests_max"] = -1
        radar.atomic_text(self.root / "config.json", radar.dumps(raw))
        with self.assertRaises(ValueError):
            runtime_policy.resolve(self.root)

    def test_setup_is_idempotent(self):
        self.assertEqual(store.setup(self.root)["status"], "already_ready")

    def test_collect_skips_previously_captured_tasks(self):
        self.capture()
        with patch.object(workflow.gh, "collect_repo", side_effect=AssertionError("Must not recollect")):
            result = workflow.collect(self.root, self.run_id, [{"repository": "fixture-only/not-a-real-project", "issues": [1]}])
        self.assertEqual(result["requests_reserved"], 0)

    def test_github_provider_cannot_be_changed_to_skip_binding(self):
        data = radar.load(self.reviewed())
        data["projects"][0]["provider"] = "other"
        self.assertTrue(provenance.verify(self.root, data))

    def test_detected_license_cannot_be_rewritten_as_another_license(self):
        data = radar.load(self.reviewed())
        data["projects"][0]["license_spdx"] = "GPL-3.0-only"
        self.assertTrue(provenance.verify(self.root, data))

    def test_open_pr_annotation_needs_a_captured_matching_pr(self):
        data = radar.load(self.reviewed())
        issue = data["projects"][0]["opportunities"][0]
        issue.update(linked_pr="open", related_pr_numbers=[999])
        self.assertTrue(any("related_pr_numbers" in e for e in provenance.verify(self.root, data)))

    def test_review_output_stays_inside_workspace(self):
        draft = self.capture()
        external = Path(self.tmp.name) / "external-input.json"
        shutil.copy2(draft, external)
        result = workflow.review(self.root, external, self.annotations(draft))
        self.assertTrue(Path(result["draft"]).is_relative_to(self.root / "runs"))
