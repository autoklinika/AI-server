import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'tools/mes_stability/mes_stability.py'
if not MODULE.exists():
    MODULE = Path(__file__).with_name('mes_stability.py')
spec = importlib.util.spec_from_file_location('mes_stability', MODULE)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class ClassificationTests(unittest.TestCase):
    def test_wait_stops_before_ring_full(self):
        self.assertEqual(m.classify('amdgpu: MES failed to respond to msg=MISC (WAIT_REG_MEM)'), ['mes_wait'])
    def test_full(self):
        self.assertEqual(m.classify('amdgpu: MES ring buffer is full'), ['mes_full'])
    def test_other_mes(self):
        self.assertEqual(m.classify('MES failed to respond to msg=REMOVE_QUEUE'), ['mes_other'])
    def test_gpuvm(self):
        self.assertEqual(m.classify('GCVM_L2_PROTECTION_FAULT_STATUS: 0x3'), ['gpuvm'])
    def test_kfd(self):
        self.assertEqual(m.classify('kfd: failed to restore queues'), ['kfd'])
    def test_svm_is_warning_not_kfd_fault(self):
        self.assertEqual(m.classify('workqueue: svm_range_restore_work [amdgpu] hogged CPU'), ['svm_warning'])
    def test_normal_boot_is_not_error(self):
        for text in ['kfd kfd: added device 1002:150e', 'iommu: Default domain type: Translated',
                     'iommu: DMA domain TLB invalidation policy: lazy mode',
                     'MES: vmid_mask_mmhub 0x0000ff00', 'NMI watchdog: Enabled',
                     'AMD-Vi: [Firmware Bug]: No ACPI device matched UID']:
            self.assertEqual(m.classify(text), [])
    def test_actual_iommu_oom_watchdog(self):
        for text, category in [('AMD-Vi: IO_PAGE_FAULT', 'iommu_sva'),
                               ('Memory cgroup out of memory: Killed process', 'oom'),
                               ('watchdog: BUG: soft lockup', 'watchdog')]:
            self.assertIn(category, m.classify(text))
    def test_old_counts_not_new(self):
        old = [{'MESSAGE': 'MES ring buffer is full'}]
        new = [{'MESSAGE': 'kfd: added device'}]
        self.assertEqual(m.count_records(old), {'mes_full': 1})
        self.assertEqual(m.count_records(new), {})


class SafetyTests(unittest.TestCase):
    def sample(self):
        return {'mem_info_vram_used': 100, 'gpu_busy_percent': 0,
                'mem_available_bytes': 20*m.GIB, 'mem_info_vram_total': 96*m.GIB,
                'temperatures_c': {}, 'mem_info_gtt_used': 0}
    def test_tainted_boot_blocked(self):
        self.assertIn('BOOT_TAINTED', m.preflight_reason({'mes_wait': 1}, self.sample()))
    def test_occupied_blocked(self):
        s = self.sample(); s['mem_info_vram_used'] = 24*m.GIB
        self.assertIn('GPU_OCCUPIED', m.preflight_reason({}, s))
    def test_low_ram_blocked(self):
        s = self.sample(); s['mem_available_bytes'] = 7*m.GIB
        self.assertEqual('HOST_MEMORY_LOW', m.preflight_reason({}, s))
    def test_gpu_discovery_ignores_connector_devices(self):
        paths = [Path('/sys/class/drm/card0-HDMI-A-1/device'), Path('/sys/class/drm/card0/device')]
        with patch.object(Path, 'glob', return_value=paths), patch.object(Path, 'read_text', return_value='0x1002') as read:
            self.assertEqual(m.gpu_path(), paths[1])
            self.assertEqual(read.call_count, 1)
    def test_wait_for_asynchronous_gpu_release(self):
        with patch.object(m,'telemetry',side_effect=[{'mem_info_vram_used':56*m.GIB},{'mem_info_vram_used':100}]), patch.object(m.time,'sleep') as sleep:
            self.assertEqual(m.wait_release(Path('/gpu'),100,None)['mem_info_vram_used'],100)
            sleep.assert_called_once()
    def test_clean_preflight(self):
        self.assertIsNone(m.preflight_reason({}, self.sample()))
    def test_matrix_single_factors(self):
        self.assertEqual(m.VARIANTS['A'], {})
        self.assertEqual(m.VARIANTS['D'], m.VARIANTS['B'] | m.VARIANTS['C'])
    def test_empty_journal_fails_closed(self):
        with patch.object(m, 'command', return_value=SimpleNamespace(stdout='')):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                m.kernel_records()
    def test_command_timeout_propagates(self):
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired('docker', 3)):
            with self.assertRaises(subprocess.TimeoutExpired):
                m.command(['docker'])
    def test_follower_death_fails_closed(self):
        j = object.__new__(m.Journal)
        j.proc = SimpleNamespace(poll=lambda: 1)
        with self.assertRaisesRegex(RuntimeError, 'monitoring lost'):
            j.poll()
    def scenario(self, monitor_error=None, occupied=False):
        calls = []
        sample = self.sample()
        if occupied:
            sample['mem_info_vram_used'] = 24*m.GIB
        class FakeJournal:
            first_error = None
            counts = {}
            n = 0
            def __init__(self, *a): pass
            def poll(self):
                self.n += 1
                if self.n == 3 and monitor_error:
                    if isinstance(monitor_error, Exception):
                        raise monitor_error
                    self.first_error = {'MESSAGE': monitor_error}
                    self.counts = {'mes_wait': 1}
                    return self.first_error
            def close(self): pass
        killed = False
        def cmd(argv, **kwargs):
            nonlocal killed
            calls.append(argv)
            if argv[:3] == ['docker', 'image', 'inspect']:
                value = [{'Id': 'sha256:test', 'Config': {'Env': []}}]
            elif argv[:2] == ['docker', 'kill']:
                killed = True; value = {}
            elif argv[:2] == ['docker', 'inspect']:
                value = {'Running': not killed, 'ExitCode': 137 if killed else 0, 'OOMKilled': False}
            else:
                value = {}
            return SimpleNamespace(stdout=json.dumps(value), returncode=0)
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(output=str(Path(tmp)/'result'), variant='A', seconds=1,
                                   resident_gib=2, seed=1, image='image', profile='synthetic')
            with patch.object(m, 'git_state', return_value={'sha':'test','dirty':False}), \
                 patch.object(m, 'boot_id', return_value='boot'), \
                 patch.object(m, 'gpu_path', return_value=Path('/fake')), \
                 patch.object(m, 'telemetry', return_value=sample), \
                 patch.object(m, 'kernel_records', side_effect=[[{'__CURSOR':'old','MESSAGE':'clean'}], []]), \
                 patch.object(m, 'Journal', FakeJournal), \
                 patch.object(m, 'docker_args', return_value=['docker','create','--name','test']), \
                 patch.object(m, 'command', side_effect=cmd), \
                 patch.object(m.subprocess, 'Popen') as popen, patch('builtins.print'):
                popen.return_value.wait.return_value = 0
                m.run(args)
            result = json.loads((Path(args.output)/'result.json').read_text())
        return calls, result
    def test_first_mes_kills_only_owned_container(self):
        calls, result = self.scenario('MES failed to respond to msg=MISC (WAIT_REG_MEM)')
        kills = [c for c in calls if c[:2] == ['docker', 'kill']]
        self.assertEqual(len(kills), 1)
        self.assertTrue(kills[0][2].startswith('p5-mes-'))
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['container_stopped'])
        self.assertEqual(result['gate'], 'NOT_PASSED')
    def test_monitor_failure_kills_workload(self):
        calls, result = self.scenario(RuntimeError('monitoring lost'))
        self.assertTrue(any(c[:2] == ['docker','kill'] for c in calls))
        self.assertEqual(result['status'], 'FAIL')
    def test_preflight_block_never_creates_container(self):
        calls, result = self.scenario(occupied=True)
        self.assertFalse(any(c[:2] == ['docker','create'] for c in calls))
        self.assertEqual(result['status'], 'BLOCKED')
    def test_workload_has_no_dataset_or_checkpoint_interface(self):
        source = MODULE.with_name('workload.py').read_text()
        self.assertNotIn('save_pretrained', source)
        self.assertNotIn('adapter_dir', source)
        self.assertNotIn('electronics_v3_quality', source)
        self.assertNotIn('load_rows', source)


gspec = importlib.util.spec_from_file_location('mes_gate', MODULE.with_name('gate.py'))
gate = importlib.util.module_from_spec(gspec); gspec.loader.exec_module(gate)

class GateTests(unittest.TestCase):
    def evidence(self):
        return [dict(variant='B', image_id='image', git={'sha':'same','dirty':False}, kernel='7',
                     profile='qwen', container_name=str(i), started_at_unix=i*4000,
                     ended_at_unix=i*4000+3700, status='PASS_RUN_ONLY', workload_exit_code=0,
                     container_stopped=True, error_counts={}, measured_workload_s=3601,
                     host_regression_free=True, peak_vram_bytes=56*m.GIB) for i in range(3)]
    def test_acceptance(self):
        self.assertEqual(gate.evaluate(self.evidence())['gate'], 'PASS')
    def test_short_or_microstress_never_passes(self):
        for field,value in [('profile','synthetic'),('measured_workload_s',60),('host_regression_free',False),('error_counts',{'mes_wait':1})]:
            rows=self.evidence();rows[0][field]=value
            self.assertNotEqual(gate.evaluate(rows)['gate'], 'PASS')
    def test_duplicate_and_incomplete_rejected(self):
        rows=self.evidence()
        self.assertNotEqual(gate.evaluate(rows[:2])['gate'], 'PASS')
        self.assertNotEqual(gate.evaluate([rows[0]]*3)['gate'], 'PASS')

sys.modules['mes_stability'] = m
mspec = importlib.util.spec_from_file_location('mes_matrix', MODULE.with_name('matrix.py'))
matrix = importlib.util.module_from_spec(mspec); mspec.loader.exec_module(matrix)

class MatrixTests(unittest.TestCase):
    def test_two_consecutive_idle_samples_after_unload(self):
        samples=[{'mem_info_vram_used':24*m.GIB,'gpu_busy_percent':0},
                 {'mem_info_vram_used':100,'gpu_busy_percent':13},
                 {'mem_info_vram_used':100,'gpu_busy_percent':0},
                 {'mem_info_vram_used':100,'gpu_busy_percent':0}]
        with patch.object(matrix,'telemetry',side_effect=samples), patch.object(matrix,'gpu_path'), patch.object(matrix.time,'sleep'), patch.object(matrix,'api') as api:
            matrix.wait_idle_gpu(lambda: api('heartbeat'))
            self.assertEqual(api.call_count,4)
    def test_idle_timeout_stops_matrix(self):
        with patch.object(matrix,'telemetry',return_value={'mem_info_vram_used':24*m.GIB,'gpu_busy_percent':0}), patch.object(matrix,'gpu_path'), patch.object(matrix.time,'monotonic',side_effect=[0,40]):
            with self.assertRaisesRegex(RuntimeError,'idle timeout'):
                matrix.wait_idle_gpu(lambda:None)
    def test_active_platform_never_reserves_or_unloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys,'argv',['matrix.py','--output',str(Path(tmp)/'out')]), patch.object(matrix,'api',return_value={'active_count':1,'queued_count':0,'admission_blocked':False}) as api:
                with self.assertRaisesRegex(RuntimeError,'not idle'):
                    matrix.main()
                self.assertEqual(api.call_count,1)

if __name__ == '__main__':
    unittest.main()
