"""CPU mocks only: never contact systemd, broker sockets, HTTP or GPU."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

# Load only stdlib modules; do not import the application dependency graph.
ROOT=Path(__file__).resolve().parents[1]
def load(name, relative):
    spec=importlib.util.spec_from_file_location(name,ROOT/relative)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod

with patch.dict(sys.modules):
    for name in ('ai_bridge','ai_bridge.benchmarks','ai_bridge.gateway'):
        sys.modules[name]=types.ModuleType(name)
    load('ai_bridge.benchmarks.vision_rm_executor','src/ai_bridge/benchmarks/vision_rm_executor.py')
    load('ai_bridge.gateway.vision_residency_evidence','src/ai_bridge/gateway/vision_residency_evidence.py')
    broker_mod=load('diagnostic_broker','src/ai_bridge/benchmarks/vision_rm_broker.py')

spec = importlib.util.spec_from_file_location(
    'runner_diagnostics', Path(__file__).resolve().parents[1] /
    'deploy/vision-rm-security/vision_rm_runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CleanupDiagnostics(unittest.TestCase):
    def setUp(self):
        self.api=Mock(return_value={'released': True})
        self.broker=broker_mod.ControlBroker(gateway='http://127.0.0.1:1',vision_uid=994,
            runner_path=Path('/unused'),runner_sha256='unused',api_call=self.api,
            peer_validator=lambda p,u: p==40)
        self.broker.session=broker_mod.Session('session',40,50,'lease','use','token')
        self.birth=patch.object(broker_mod,'worker_birth_ticks',return_value=50)
        self.birth.start()
        self.addCleanup(self.birth.stop)

    def finish(self, **kw):
        return self.broker.request({'op':'finish','session':'session'},
                                   peer_pid=kw.get('pid',40),peer_uid=kw.get('uid',994))

    def test_stage_and_no_remote_content(self):
        for stage in ('use_cleanup','lease_release'):
            for code in (401,403,404,409,500):
                with self.subTest(stage=stage,code=code):
                    err=HTTPError('http://private/lease',code,'SECRET',{},None)
                    self.api.side_effect=[err] if stage=='use_cleanup' else [{'released':True},err]
                    result=self.finish()
                    err.close()
                    self.assertEqual(result['stage'],stage)
                    self.assertEqual(result['http_status'],code)
                    self.assertNotIn('SECRET',json.dumps(result))
                    self.assertNotIn('private',json.dumps(result))
                    self.assertIsNotNone(self.broker.session)

    def test_lease_failure_after_use_cleanup_retains_session_for_retry(self):
        self.api.side_effect=[{'released':True},{'released':False}]
        self.assertEqual(self.finish(),{'status':'cleanup_failed','stage':'lease_release',
                                       'reason':'release_unverified'})
        self.assertIsNotNone(self.broker.session)
        self.api.side_effect=[{'released':True},{'released':True}]
        self.assertEqual(self.finish(),{'status':'released'})

    def test_transport_malformed_and_non_boolean_release(self):
        for response in (TimeoutError('SECRET'),URLError('SECRET'),ValueError('SECRET'),
                         {'released':False},{'released':1},[],{'released':True,'private':'SECRET'}):
            with self.subTest(response=type(response).__name__):
                self.api.reset_mock()
                self.api.side_effect=[response]
                result=self.finish()
                self.assertEqual(result['stage'],'use_cleanup')
                self.assertNotIn('SECRET',json.dumps(result))
                self.assertEqual(self.api.call_count,1)
                self.assertIsNotNone(self.broker.session)

    def test_wrong_uid_peer_session_and_pid_reuse(self):
        for kwargs in ({'uid':993},{'pid':41}):
            self.assertEqual(self.finish(**kwargs),{'status':'denied'})
        with patch.object(broker_mod,'worker_birth_ticks',return_value=51):
            self.assertEqual(self.finish(),{'status':'denied'})
        self.assertEqual(self.broker.request({'op':'finish','session':'forged'},
                            peer_pid=40,peer_uid=994),{'status':'denied'})
        self.api.assert_not_called()

    def test_unknown_begin_never_claims_deferred_release(self):
        self.broker.session.use_id=None
        with patch.object(broker_mod,'worker_cgroup_path',return_value='/trusted'), \
             patch.object(Path,'stat',return_value=Mock(st_uid=994)):
            for response in (TimeoutError('SECRET'),{'use_id':'use','worker_token':'bad'}):
                self.broker.session.admission_uncertain=False
                self.api.side_effect=[response]
                try:
                    self.broker.request({'op':'begin','session':'session','worker_pid':60,
                                         'scope_path':'/trusted'},peer_pid=40,peer_uid=994)
                except TimeoutError:
                    pass
                self.api.reset_mock()
                self.assertEqual(self.finish()['reason'],'admission_outcome_unknown')
                self.api.assert_not_called()

    def test_forged_scope_and_arbitrary_remote_action_denied(self):
        self.broker.session.use_id=None
        with patch.object(broker_mod,'worker_cgroup_path',return_value='/trusted'):
            result=self.broker.request({'op':'begin','session':'session','worker_pid':60,
                                       'scope_path':'/forged'},peer_pid=40,peer_uid=994)
        self.assertEqual(result['status'],'worker_scope_denied')
        for op in ('POST','restart_ollama','release','token','http://remote'):
            self.assertEqual(self.broker.request({'op':op,'session':'session'},
                                peer_pid=40,peer_uid=994),{'status':'denied'})
        self.api.assert_not_called()

    def test_success_clears_only_after_both_deletes(self):
        self.assertEqual(self.finish(),{'status':'released'})
        self.assertEqual(self.api.call_count,2)
        self.assertIsNone(self.broker.session)

    def test_lost_create_reply_blocks_retry_without_unknown_lease_release(self):
        self.broker.session=None
        self.api.side_effect=TimeoutError('synthetic')
        with self.assertRaises(TimeoutError):
            self.broker.request({'op':'create'},peer_pid=40,peer_uid=994)
        self.api.reset_mock()
        self.assertEqual(self.broker.request({'op':'create'},peer_pid=40,peer_uid=994),
                         {'status':'busy'})
        self.assertEqual(self.finish(),{'status':'denied'})
        self.api.assert_not_called()

    def test_malformed_create_reply_blocks_retry(self):
        for reply in ({}, {'lease_id':'lease','state':True},
                      {'lease_id':False,'state':'active'}, []):
            self.broker.session=None
            self.broker.reservation_uncertain=False
            self.api.return_value=reply
            self.assertEqual(self.broker.request({'op':'create'},peer_pid=40,peer_uid=994),
                             {'status':'reservation_unverified'})
            self.api.reset_mock()
            self.assertEqual(self.broker.request({'op':'create'},peer_pid=40,peer_uid=994),
                             {'status':'busy'})
            self.api.assert_not_called()

    def test_stop_timeout_does_not_skip_finish_or_mask_primary(self):
        primary=RuntimeError('PRIVATE PATH AND SECRET')
        output=io.StringIO()
        with patch.object(runner.subprocess,'run',side_effect=subprocess.TimeoutExpired('PRIVATE',8)), \
             patch.object(runner,'request',return_value={'status':'denied'}) as request, \
             contextlib.redirect_stderr(output):
            with self.assertRaises(RuntimeError) as caught:
                try:
                    raise primary
                finally:
                    runner.finalize(Mock(),unit='mock',env={},session='session',
                                    primary=primary,primary_stage='worker_execution')
        self.assertIs(caught.exception,primary)
        request.assert_called_once()
        diagnostic=json.loads(output.getvalue())
        self.assertEqual(len(diagnostic['cleanup']),2)
        self.assertNotIn('PRIVATE',output.getvalue())
        self.assertNotIn('SECRET',output.getvalue())

    def test_untrusted_reply_and_ipc_exception_are_redacted(self):
        for reply in ({'status':'SECRET','stage':'/private','reason':'token'},
                      {'status':'cleanup_failed','stage':'use_cleanup','reason':[]},
                      ValueError('SECRET')):
            with patch.object(runner,'request',side_effect=[reply]):
                issues=runner.cleanup(None,unit='unused',env={},session='session')
                self.assertTrue(issues)
                self.assertNotIn('SECRET',json.dumps(issues))
                self.assertNotIn('/private',json.dumps(issues))

    def test_cleanup_failure_without_primary_fails(self):
        with patch.object(runner,'request',return_value={'status':'cleanup_failed',
                'stage':'lease_release','reason':'release_unverified'}), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(RuntimeError):
            runner.finalize(None,unit='unused',env={},session='session',
                            primary=None,primary_stage='worker_execution')


if __name__=='__main__':
    unittest.main()
