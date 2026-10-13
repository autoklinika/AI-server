"""CPU-only denial tests. No real bus, HTTP, GPU, credentials or installed units.

These are NOT positive lifecycle/containment tests: no trusted collector exists.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

observer = load('boundary_observer', 'deploy/vision-rm-security/vision_gpu_observer.py')
evidence = load('boundary_evidence', 'src/ai_bridge/gateway/vision_residency_evidence.py')
runner = load('boundary_runner', 'deploy/vision-rm-security/vision_rm_runner.py')
with patch.dict(sys.modules, {'httpx': types.ModuleType('httpx'),
        'boundary': types.ModuleType('boundary'),
        'boundary.vision_residency_evidence': evidence}):
    residency = load('boundary.residency', 'src/ai_bridge/gateway/residency.py')

SCOPE = '/user.slice/user-994.slice/user@994.service/app.slice/vision-bench-012345abcdef.scope'
REGISTER = dict(version=1, op='register_scope', runner_pid=40, runner_birth=50,
                pid=60, birth=70, scope_suffix='012345abcdef')
QUERY = dict(version=1, op='query_terminal', handle='a'*32, epoch=observer.TERMINAL_EPOCH)

class ProtocolDenial(unittest.TestCase):
    def setUp(self):
        self.gpu = patch.object(observer, 'snapshot_gpu_clients', side_effect=AssertionError('GPU touched'))
        self.gpu.start()
        self.addCleanup(self.gpu.stop)

    def request(self, request, uid=993):
        raw = request if isinstance(request, bytes) else json.dumps(request).encode()
        return json.loads(observer.dispatch(raw, peer_uid=uid, trusted_uids=frozenset({993,994})))

    def test_controller_cannot_register_without_containment(self):
        self.assertEqual(self.request(REGISTER)['reason'], 'containment_unavailable')
        self.assertNotIn('handle', self.request(REGISTER))

    def test_wrong_peer_uid(self):
        for uid in (0, 994, 995):
            for req in (REGISTER, QUERY):
                self.assertEqual(self.request(req, uid)['status'], 'denied')

    def test_wrong_runner_pid_and_birth_never_get_a_watch(self):
        for field in ('runner_pid', 'runner_birth', 'pid', 'birth'):
            for value in (True, -1, 0, '60', 2**64, 99):
                reply = self.request({**REGISTER, field:value})
                self.assertIn(reply['status'], ('unknown','invalid_request'))
                self.assertNotIn('handle', reply)

    def test_malicious_scope(self):
        for value in ('../system.slice', 'A'*12, 'a'*13, 'a'*12+'\n', '', 12):
            self.assertEqual(self.request({**REGISTER,'scope_suffix':value})['status'], 'invalid_request')

    def test_forged_events_and_signatures_are_not_evidence(self):
        for field in ('signature','source_event','terminal','gpu_fds','manager_epoch','invocation_id'):
            self.assertEqual(self.request({**REGISTER,field:True})['status'], 'invalid_request')
        for op in ('UnitRemoved','JobRemoved','PropertiesChanged','StartTransientUnit','run'):
            self.assertEqual(self.request({**REGISTER,'op':op})['status'], 'invalid_request')

    def test_duplicate_extra_boolean_and_oversized_messages(self):
        for raw in (b'{"op":"snapshot","version":1,"version":1}',
                    b'{"op":"snapshot","version":true}', b' '*513,
                    json.dumps({**QUERY, 'extra':1}).encode(), b'[]', b'{}'):
            self.assertEqual(self.request(raw)['status'], 'invalid_request')

    def test_early_gc_and_reused_unit_cannot_create_history(self):
        # Repeated same-name registrations cannot allocate a handle or infer GC.
        for _ in range(3):
            self.assertEqual(self.request(REGISTER)['status'], 'unknown')
            self.assertEqual(self.request(QUERY)['reason'], 'unregistered')

    def test_observer_restart_and_epoch_mismatch(self):
        with patch.object(observer, 'TERMINAL_EPOCH', 'b'*32):
            self.assertEqual(self.request(QUERY)['reason'], 'epoch_mismatch')

    def test_manager_restart_or_disabled_bus_has_no_positive_fallback(self):
        # No D-Bus backend exists; neither event nor disconnected snapshot is accepted.
        with patch.object(observer, 'inspect_worker_executable', side_effect=OSError):
            self.assertEqual(self.request(REGISTER)['status'], 'unknown')
            self.assertEqual(self.request(QUERY)['status'], 'unknown')

    def test_unknown_gpu_fds_remain_unknown(self):
        with patch.object(observer, 'snapshot_gpu_clients', return_value=None):
            self.assertEqual(self.request(dict(version=1,op='snapshot'))['status'], 'evidence_unavailable')

    def test_existing_snapshot_contract_survives_strict_parser(self):
        with patch.object(observer, 'snapshot_gpu_clients', return_value=((60,70),)):
            reply = self.request(dict(version=1,op='snapshot'))
        self.assertEqual(reply, dict(schema_version=1,status='ok',gpu_clients=[dict(pid=60,birth=70)]))

    def test_existing_inspect_contract_remains_controller_only(self):
        with patch.object(observer, 'inspect_worker_executable', return_value=None) as inspect:
            raw = json.dumps(dict(version=1,op='inspect_worker',pid=60,birth=70)).encode()
            reply = json.loads(observer.dispatch(raw,peer_uid=994,
                trusted_uids=frozenset({993,994}),controller_uid=993,worker_uid=994))
            self.assertEqual(reply['status'],'denied')
            inspect.assert_not_called()
            reply = json.loads(observer.dispatch(raw,peer_uid=993,
                trusted_uids=frozenset({993,994}),controller_uid=993,worker_uid=994))
            self.assertEqual(reply['status'],'evidence_unavailable')
            inspect.assert_called_once_with(60,70,worker_uid=994)

    def test_registration_flood_allocates_no_history(self):
        for i in range(100):
            self.assertNotIn('handle', self.request({**REGISTER,'pid':i+2}))

class SubtreeDenial(unittest.TestCase):
    def test_nested_child_cgroup_is_in_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / SCOPE.lstrip('/')
            (target/'child'/'grandchild').mkdir(parents=True)
            (target/'cgroup.procs').write_text('')
            (target/'child'/'cgroup.procs').write_text('')
            (target/'child'/'grandchild'/'cgroup.procs').write_text('9001\n')
            def mapped(path):
                return root if str(path) == '/sys/fs/cgroup' else Path(path)
            with patch.object(evidence,'Path',side_effect=mapped):
                self.assertEqual(evidence.scoped_processes(SCOPE), {9001})
                self.assertEqual(evidence.scope_members_or_terminal(SCOPE), {9001})

    def test_escaped_child_and_empty_snapshot_cannot_release(self):
        # Absence from subtree says nothing about a sleeper outside it.
        with patch.object(evidence,'scoped_processes',return_value=set()):
            self.assertIsNone(evidence.scope_members_or_terminal(SCOPE))

    def test_missing_subtree_is_unknown(self):
        with patch.object(evidence,'scoped_processes',return_value=None):
            self.assertIsNone(evidence.scope_members_or_terminal(SCOPE))

    def test_race_empty_then_new_member_never_yields_terminal(self):
        with patch.object(evidence,'scoped_processes',side_effect=[set(), {9001}]):
            self.assertIsNone(evidence.scope_members_or_terminal(SCOPE))
            self.assertEqual(evidence.scope_members_or_terminal(SCOPE), {9001})

    def test_missing_nested_procs_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / SCOPE.lstrip('/')
            (target/'child').mkdir(parents=True)
            (target/'cgroup.procs').write_text('')
            with patch.object(evidence,'Path',side_effect=lambda p: root if str(p)=='/sys/fs/cgroup' else Path(p)):
                self.assertIsNone(evidence.scoped_processes(SCOPE))

class ReleaseIntegration(unittest.TestCase):
    def test_empty_or_missing_or_nested_keeps_marker_and_blocks_before_gpu(self):
        for members in (set(), None, {9001}):
            with self.subTest(members=members), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory)/'blocked'
                marker.write_text('blocked')
                gpu = Mock(side_effect=AssertionError('GPU touched'))
                rm = residency.GPUResidency(Mock(), Mock(), marker,
                    vision_process_probe=lambda p: None, vision_memory_probe=gpu)
                rm.state='vision'
                rm._vision_worker=(60,70)
                rm._vision_scope_path=SCOPE
                rm._vision_baseline_bytes=0
                with patch.object(evidence,'scoped_processes',return_value=members):
                    with self.assertRaises(residency.ResidencyError):
                        asyncio.run(rm.leave_vision())
                self.assertTrue(marker.exists())
                self.assertEqual(rm.state,'blocked')
                self.assertEqual(rm._vision_worker,(60,70))
                gpu.assert_not_called()

    def test_admission_denied_before_any_provider_or_gpu_io(self):
        with tempfile.TemporaryDirectory() as directory:
            io = Mock(side_effect=AssertionError('unexpected I/O'))
            rm = residency.GPUResidency(io, io, Path(directory)/'marker',
                vision_process_probe=io, vision_memory_probe=io)
            with self.assertRaisesRegex(residency.ResidencyError, 'containment unavailable'):
                asyncio.run(rm.enter_vision(60, SCOPE))
            io.assert_not_called()
            self.assertEqual(rm.state,'llm')

    def test_runner_rejects_wrong_broker_before_sending(self):
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.getsockopt.return_value = struct.pack('3i',40,994,994)
        with patch.object(runner.socket,'socket',return_value=connection):
            with self.assertRaises(RuntimeError):
                runner.request({'op':'finish','session':'synthetic'})
        connection.sendall.assert_not_called()

if __name__ == '__main__':
    unittest.main()
