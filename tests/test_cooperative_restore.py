"""CPU only: never execute a host command."""
import importlib.util
from pathlib import Path
from unittest import TestCase, mock
import subprocess

spec = importlib.util.spec_from_file_location('restore', Path(__file__).parents[1] / 'tools/restore_cooperative_v1.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class RestoreTests(TestCase):
    def setUp(self):
        self.stack = __import__('contextlib').ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(r.os, 'geteuid', return_value=1000))
        self.stack.enter_context(mock.patch.object(r.time, 'sleep'))

    def test_allowlisted_order_and_readiness(self):
        with mock.patch.object(r, 'baseline') as base, mock.patch.object(r, 'idle'), \
             mock.patch.object(r, 'run') as run, mock.patch.object(r, 'ready') as ready, \
             mock.patch.object(r.sys.stdin, 'isatty', return_value=True), \
             mock.patch.object(r.sys.stdout, 'isatty', return_value=True):
            r.restore(True)
            self.assertEqual(run.call_args_list, [mock.call('sudo', '-k'), mock.call('sudo', '-v')] +
                             [mock.call('sudo', '-n', 'systemctl', 'start', u) for u in r.START])
            self.assertEqual(ready.call_args_list, [mock.call(11434, '/api/version'),
                             mock.call(11435, '/health', True), mock.call(11435, '/health', True)])
            self.assertEqual(base.call_count, 6)

    def test_preflight_failure_never_sudo(self):
        with mock.patch.object(r, 'baseline', side_effect=RuntimeError('DIRTY')), mock.patch.object(r, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'DIRTY'):
                r.restore(True)
            run.assert_not_called()

    def test_readiness_failure_stops_sequence(self):
        with mock.patch.object(r, 'baseline'), mock.patch.object(r, 'idle'), \
             mock.patch.object(r, 'run') as run, mock.patch.object(r, 'ready', side_effect=RuntimeError('timeout')), \
             mock.patch.object(r.sys.stdin, 'isatty', return_value=True), \
             mock.patch.object(r.sys.stdout, 'isatty', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                r.restore(True)
            self.assertEqual(run.call_args_list[-1], mock.call('sudo', '-n', 'systemctl', 'start', 'ollama.service'))
            self.assertEqual(run.call_count, 3)

    def test_check_only_never_sudo(self):
        with mock.patch.object(r, 'baseline'), mock.patch.object(r, 'idle', side_effect=RuntimeError('visibility')), mock.patch.object(r, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'visibility'):
                r.restore()
            run.assert_not_called()

    def test_release_guard(self):
        with mock.patch.object(r.Path, 'resolve', return_value=Path('/wrong')):
            with self.assertRaisesRegex(RuntimeError, 'release mismatch'):
                r.baseline()

    def test_config_guard(self):
        with mock.patch.object(r.Path, 'resolve', return_value=Path(r.RELEASE)), \
             mock.patch.object(r, 'files', return_value={}), \
             mock.patch.object(r.Path, 'read_text', return_value='{"expected":"hash"}'):
            with self.assertRaisesRegex(RuntimeError, 'configuration/source drift'):
                r.baseline()

    def test_gpu_ambiguous_fuser_blocks(self):
        with mock.patch.object(r.Path, 'read_text', side_effect=['0x1002', '0x150e']), \
             mock.patch.object(r.os, 'listdir', return_value=[]), \
             mock.patch.object(r.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'Permission denied')):
            with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
                r.idle(True)

    def test_kfd_owner_blocks(self):
        with mock.patch.object(r.Path, 'read_text', side_effect=['0x1002', '0x150e']), \
             mock.patch.object(r.os, 'listdir', return_value=['123']):
            with self.assertRaisesRegex(RuntimeError, 'KFD owners'):
                r.idle(True)

    def test_readiness_bounded(self):
        with mock.patch.object(r.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = OSError('offline')
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                r.ready(11435, '/health', True)
            self.assertEqual(opener.return_value.open.call_count, 20)

    def test_metadata_preflight_does_not_need_sudo(self):
        with mock.patch.object(r.Path, 'read_text', side_effect=['0x1002','0x150e']), \
             mock.patch.object(r.os, 'listdir', return_value=[]), \
             mock.patch.object(r.subprocess, 'run') as runner:
            self.assertEqual(r.idle(False), 'READ_ONLY_KFD_CHECK_FULL_FUSER_NOT_VERIFIED')
            runner.assert_not_called()

    def test_root_forbidden(self):
        with mock.patch.object(r.os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'ordinary operator'):
                r.restore(True)

    def test_baseline_rejects_service_and_marker(self):
        with mock.patch.object(r.Path, 'resolve', return_value=Path(r.RELEASE)), \
             mock.patch.object(r, 'files', return_value={}), \
             mock.patch.object(r.Path, 'read_text', return_value='{}'), \
             mock.patch.object(r, 'run', return_value='multi-user.target'), \
             mock.patch.object(r, 'prop', side_effect=['loaded', 'no', 'active']):
            with self.assertRaisesRegex(RuntimeError, 'unexpected service state'):
                r.baseline()

    def test_blocked_report_persists(self):
        import tempfile
        import json
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(r.Path, 'cwd', return_value=Path(folder)), \
             mock.patch.object(r.sys, 'argv', ['restore']), \
             mock.patch.object(r, 'restore', side_effect=RuntimeError('DIRTY')), \
             mock.patch('builtins.print'):
            self.assertEqual(r.main(), 2)
            report = json.loads(next(Path(folder).glob('*.json')).read_text())
            self.assertEqual(report['status'], 'BLOCKED')
            self.assertEqual(report['reason'], 'DIRTY')
            self.assertIn('stop ai-gateway.service', report['rollback'])
