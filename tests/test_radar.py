"""Offline tests. ALL repositories and issue content in this file are synthetic."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import radar
import github_readonly as gh
import evidence as evidence_helper


def fixture():
    t = (radar.now() - timedelta(minutes=2)).isoformat()
    roles = ['repository', 'readme', 'license', 'issue', 'comments', 'timeline', 'pull_requests', 'contributing', 'ai_policy']
    ev = []
    for role in roles:
        excerpt = 'SYNTHETIC TEST FIXTURE ONLY: ' + role
        ev.append({'id': 'test-' + role, 'url': 'https://github.com/fixture-only/not-a-real-project',
                   'observed_at': t, 'role': role, 'primary': True, 'excerpt': excerpt,
                   'sha256': radar.digest(excerpt.encode())})
    ids = [e['id'] for e in ev]
    p = {'synthetic': True, 'project_id': 'github:999000000', 'provider': 'github',
         'name': 'SYNTHETIC PROJECT', 'canonical_url': 'https://github.com/fixture-only/not-a-real-project',
         'category': 'developer_tools', 'license_status': 'open_source_verified', 'license_spdx': 'MIT',
         'archived': False, 'checked_at': t, 'stars': 10, 'language': 'Python', 'evidence_ids': ids,
         'claims': [{'kind': 'fact', 'text': 'SYNTHETIC fact', 'evidence_ids': ['test-readme']}],
         'relevance': 'SYNTHETIC assessment', 'caveats': 'No real project exists in this fixture',
         'scores': {k: {'value': 3, 'reason': 'SYNTHETIC scoring'} for k in ['interest','novelty','relevance','health']},
         'opportunities': [{'number': 1, 'title': 'SYNTHETIC ISSUE',
             'url': 'https://github.com/fixture-only/not-a-real-project/issues/1', 'state': 'open', 'checked_at': t,
             'assignees': [], 'claim_status': 'none_observed', 'linked_pr': 'none_observed',
             'checks': {k: True for k in ['comments','timeline','pr_search','contributing','ai_policy_search']},
             'scope': 'clear', 'ai_policy': 'not_found_after_search', 'skill_match': 'unknown',
             'evidence_ids': ids, 'task': 'SYNTHETIC task', 'first_step': 'Read source only',
             'acceptance': 'SYNTHETIC acceptance', 'skills_needed': 'Unknown', 'skill_gaps': 'Unverified'}]}
    return {'schema_version':1, 'run_id':'synthetic-test', 'report_date':radar.now().date().isoformat(),
            'generated_at':radar.stamp(), 'report_timezone':'UTC', 'utc_offset':'+0000',
            'coverage':[{'family':'github','status':'success','query':'synthetic query','note':'test only',
                         'found':1,'verified':1,'evidence_ids':['test-repository']}],
            'evidence':ev,'projects':[p],'metrics':{'search_calls':None},'limitations':['SYNTHETIC TEST ONLY']}


def gate(data):
    p = data['projects'][0]
    return radar.opportunity_gate(p, p['opportunities'][0], {e['id']:e for e in data['evidence']})[0]


class ValidationTests(unittest.TestCase):
    def setUp(self): self.data = fixture()
    def errors(self): return radar.validate(self.data, allow_fixture=True)[0]
    def test_valid_fixture_structure(self): self.assertEqual(self.errors(), [])
    def test_fixture_cannot_publish_as_real(self): self.assertTrue(radar.validate(self.data)[0])
    def test_closed_issue_excluded(self):
        self.data['projects'][0]['opportunities'][0]['state']='closed'; self.assertEqual(gate(self.data),'excluded')
    def test_archived_excluded(self):
        self.data['projects'][0]['archived']=True; self.assertEqual(gate(self.data),'excluded')
    def test_assigned_not_available(self):
        self.data['projects'][0]['opportunities'][0]['assignees']=['someone']; self.assertEqual(gate(self.data),'in_progress')
    def test_comment_claim_not_available(self):
        self.data['projects'][0]['opportunities'][0]['claim_status']='claimed'; self.assertEqual(gate(self.data),'in_progress')
    def test_open_pr_not_available(self):
        self.data['projects'][0]['opportunities'][0]['linked_pr']='open'; self.assertEqual(gate(self.data),'in_progress')
    def test_merged_pr_excluded(self):
        self.data['projects'][0]['opportunities'][0]['linked_pr']='merged'; self.assertEqual(gate(self.data),'excluded')
    def test_missing_pr_scan_degraded(self):
        self.data['projects'][0]['opportunities'][0]['checks']['pr_search']=False; self.assertEqual(gate(self.data),'needs_verification')
    def test_unknown_assignee_not_empty(self):
        self.data['projects'][0]['opportunities'][0]['assignees']=None; self.assertEqual(gate(self.data),'needs_verification')
    def test_expired_issue_degraded(self):
        self.data['projects'][0]['opportunities'][0]['checked_at']=(radar.now()-timedelta(hours=25)).isoformat()
        self.assertEqual(gate(self.data),'needs_verification')
    def test_old_evidence_with_new_timestamp_degraded(self):
        self.data['evidence'][3]['observed_at']=(radar.now()-timedelta(hours=25)).isoformat()
        self.assertEqual(gate(self.data),'needs_verification')
    def test_current_unclaimed_issue_is_conditional_candidate(self): self.assertEqual(gate(self.data),'candidate_for_review')
    def test_unknown_license_degraded(self):
        self.data['projects'][0]['license_status']='unknown'; self.assertEqual(gate(self.data),'needs_verification')
    def test_missing_license_evidence(self):
        self.data['projects'][0]['evidence_ids'].remove('test-license'); self.assertTrue(self.errors())
    def test_unsupported_factual_claim(self):
        self.data['projects'][0]['claims'][0]['evidence_ids']=[]; self.assertTrue(self.errors())
    def test_nonprimary_claim_is_not_fact(self):
        self.data['evidence'][1]['primary']=False; self.assertTrue(self.errors())
    def test_hash_tampering(self):
        self.data['evidence'][0]['excerpt']+=' altered'; self.assertTrue(self.errors())
    def test_duplicates(self):
        self.data['projects'].append(copy.deepcopy(self.data['projects'][0])); self.assertTrue(self.errors())
    def test_future_timestamp(self):
        self.data['generated_at']=(radar.now()+timedelta(days=1)).isoformat(); self.assertTrue(self.errors())
    def test_naive_timestamp(self):
        self.data['generated_at']='2026-09-15T08:00:00'; self.assertTrue(self.errors())
    def test_wrong_repo_issue_url(self):
        self.data['projects'][0]['opportunities'][0]['url']='https://github.com/other/repo/issues/1'; self.assertTrue(self.errors())
    def test_non_numeric_github_identity(self):
        self.data['projects'][0]['project_id']='github:owner/repo'; self.assertTrue(self.errors())
    def test_skill_verified_requires_evidence(self):
        self.data['projects'][0]['opportunities'][0]['skill_match']='verified'; self.assertTrue(self.errors())
    def test_nan_score(self):
        self.data['projects'][0]['scores']['health']['value']=float('nan'); self.assertTrue(self.errors())
    def test_missing_stars_are_not_zero(self):
        self.data['projects'][0]['stars']=None; self.assertEqual(self.errors(),[])
    def test_metric_unknown_is_null(self): self.assertEqual(self.errors(),[])
    def test_negative_metric_rejected(self):
        self.data['metrics']['search_calls']=-1; self.assertTrue(self.errors())
    def test_coverage_cannot_overclaim_count(self):
        self.data['coverage'][0]['verified']=2; self.assertTrue(self.errors())
    def test_missing_coverage_degrades_not_fabricates(self):
        self.data['coverage']=[]; self.assertTrue(radar.validate(self.data,allow_fixture=True)[1])
    def test_empty_report_allowed_with_warning(self):
        self.data['projects']=[]; errors,warnings=radar.validate(self.data); self.assertFalse(errors); self.assertTrue(warnings)
    def test_secret_url_rejected(self): self.assertFalse(radar.valid_url('https://example.org/?token=secret'))
    def test_javascript_url_rejected(self): self.assertFalse(radar.valid_url('javascript:alert(1)'))
    def test_negative_delta_preserved(self):
        a={'stars':10,'checked_at':(radar.now()-timedelta(hours=48)).isoformat()}
        b={'stars':8,'checked_at':radar.stamp()}
        d=radar.star_change(a,b); self.assertEqual(d['delta'],-2); self.assertAlmostEqual(d['hours'],48,places=1)
    def test_missing_baseline_no_fake_growth(self): self.assertIsNone(radar.star_change(None,{'stars':5}))


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'workspace'; radar.initialize(self.root)
    def tearDown(self): self.tmp.cleanup()
    def prepared(self):
        run=radar.start(self.root); d=fixture(); template=radar.load(Path(run['draft']))
        for k in ['run_id','report_date','generated_at','report_timezone','utc_offset']: d[k]=template[k]
        # Every observation has a fresh immutable evidence identity.
        mapping={e['id']:run['run_id']+'-'+e['id'] for e in d['evidence']}
        for e in d['evidence']: e['id']=mapping[e['id']]
        for c in d['coverage']: c['evidence_ids']=[mapping[i] for i in c['evidence_ids']]
        for p in d['projects']:
            p['evidence_ids']=[mapping[i] for i in p['evidence_ids']]
            for c in p['claims']: c['evidence_ids']=[mapping[i] for i in c['evidence_ids']]
            for o in p['opportunities']: o['evidence_ids']=[mapping[i] for i in o['evidence_ids']]
        path=Path(run['draft']); radar.atomic_text(path,radar.dumps(d)); return d,path
    def test_reinitialize_idempotent(self): self.assertEqual(radar.initialize(self.root)['status'],'already_initialized')
    def test_refuse_unrecognized_nonempty_root(self):
        other=Path(self.tmp.name)/'other'; other.mkdir(); (other/'unique.txt').write_text('do not overwrite')
        with self.assertRaises(ValueError): radar.initialize(other)
    def test_publish_export_and_fixture_watermark(self):
        d,path=self.prepared(); result=radar.publish(self.root,path,allow_fixture=True)
        self.assertIn('合成测试数据',Path(result['report']).read_text(encoding='utf-8'))
    def test_duplicate_publish_does_not_duplicate_observations(self):
        d,path=self.prepared(); radar.publish(self.root,path,allow_fixture=True); radar.publish(self.root,path,allow_fixture=True)
        with radar.connect(self.root) as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM observations').fetchone()[0],1)
    def test_published_runs_are_immutable(self):
        d,path=self.prepared(); radar.publish(self.root,path,allow_fixture=True)
        d['limitations'].append('changed'); radar.atomic_text(path,radar.dumps(d))
        with self.assertRaises(ValueError): radar.publish(self.root,path,allow_fixture=True)
    def test_export_recovers_deleted_report(self):
        d,path=self.prepared(); result=radar.publish(self.root,path,allow_fixture=True)
        target=Path(result['report']); expected=target.read_text(encoding='utf-8'); target.unlink()
        radar.export_run(self.root,d['run_id']); self.assertEqual(target.read_text(encoding='utf-8'),expected)
    def test_policy_drift_blocks_start(self):
        (self.root/'mission.md').write_text('silently changed')
        with self.assertRaises(ValueError): radar.start(self.root)
    def test_missing_user_quote_rejected(self):
        with self.assertRaises(ValueError): radar.feedback(self.root,None,'watch','inferred','')
    def test_feedback_does_not_change_profile(self):
        old=(self.root/'profile.json').read_bytes(); radar.feedback(self.root,None,'watch','explicit','请关注这个项目')
        self.assertEqual(old,(self.root/'profile.json').read_bytes())
    def test_checkpoint_is_durable(self):
        run=radar.start(self.root); p=radar.checkpoint(self.root,run['run_id'],'verify','Resume these IDs')
        self.assertTrue(Path(p['checkpoint']).exists())
    def test_omission_does_not_close_tracked_issue(self):
        d,path=self.prepared(); radar.publish(self.root,path,allow_fixture=True)
        d2,path2=self.prepared(); d2['projects'][0]['opportunities']=[]; radar.atomic_text(path2,radar.dumps(d2))
        radar.publish(self.root,path2,allow_fixture=True)
        with radar.connect(self.root) as con:
            p=json.loads(con.execute('SELECT current_payload FROM projects').fetchone()[0]); self.assertEqual(p['opportunities'][0]['state'],'open')
    def test_new_run_same_repo_does_not_duplicate_registry(self):
        for _ in range(2):
            d,path=self.prepared(); radar.publish(self.root,path,allow_fixture=True)
        with radar.connect(self.root) as con: self.assertEqual(con.execute('SELECT COUNT(*) FROM projects').fetchone()[0],1)
    def test_stale_snapshot_cannot_rollback_registry(self):
        d,path=self.prepared(); radar.publish(self.root,path,allow_fixture=True)
        d2,path2=self.prepared(); d2['projects'][0]['checked_at']=(radar.now()-timedelta(hours=1)).isoformat(); radar.atomic_text(path2,radar.dumps(d2))
        with self.assertRaises(ValueError): radar.publish(self.root,path2,allow_fixture=True)
    def test_connection_closed_after_success(self):
        with radar.connect(self.root) as con:
            con.execute("SELECT 1")
        with self.assertRaises(radar.sqlite3.ProgrammingError):
            con.execute("SELECT 1")
    def test_connection_closed_and_rolled_back_after_error(self):
        with self.assertRaisesRegex(RuntimeError, "intentional"):
            with radar.connect(self.root) as con:
                con.execute("INSERT INTO meta VALUES('rollback_test','temporary')")
                raise RuntimeError("intentional")
        with self.assertRaises(radar.sqlite3.ProgrammingError):
            con.execute("SELECT 1")
        with radar.connect(self.root) as recovered:
            self.assertIsNone(recovered.execute("SELECT value FROM meta WHERE key='rollback_test'").fetchone())
    def test_context_is_bounded_with_large_escaped_feedback(self):
        for _ in range(10):
            radar.feedback(self.root, None, 'watch', '\x01' * 500, 'explicit ' + '\x02' * 500)
        self.assertLessEqual(len(radar.dumps(radar.context(self.root))), 14000)
    def test_context_is_bounded(self):
        d,path=self.prepared(); radar.publish(self.root,path,allow_fixture=True)
        self.assertLessEqual(len(radar.dumps(radar.context(self.root))),14000)


class CollectorTests(unittest.TestCase):
    def test_no_cross_host_redirect(self):
        with self.assertRaises(ValueError): gh.checked_api_url('https://attacker.example/api')
    def test_no_http(self):
        with self.assertRaises(ValueError): gh.checked_api_url('http://api.github.com/repos/a/b')
    def test_no_url_userinfo(self):
        with self.assertRaises(ValueError): gh.checked_api_url('https://secret@api.github.com/repos/a/b')
    def test_invalid_repo(self):
        with self.assertRaises(ValueError): gh.repo_name('a/../../etc')
    def test_budget_defers_without_network(self):
        c=gh.Client(budget=0); self.assertEqual(c.get('/repos/a/b')['status'],'deferred'); self.assertEqual(c.requests,0)
    def test_partial_pagination_detected(self):
        c=gh.Client(); c.get=lambda path:{'status':200,'data':[{'id':1}], 'link':'<https://api.github.com/example?page=2>; rel="next"'}
        self.assertFalse(c.pages('/example',max_pages=1)['complete'])
    def test_json_pointer_exact(self): self.assertEqual(evidence_helper.pointer({'a':[{'b':1}]},'/a/0/b'),1)
    def test_markdown_external_html_escaped(self): self.assertIn('\\<',radar.md('<script>'))


if __name__=='__main__': unittest.main(verbosity=2)
