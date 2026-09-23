from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from sqlalchemy import func, select

from ai_bridge.api.app import create_app
from ai_bridge.settings import Settings
from ai_bridge.domains.wvc.policy import WVCAnalysisPolicy
from ai_bridge.domains.wvc.analysis.service_v12_2 import VentilationAnalysisServiceV122
from ai_bridge.domains.wvc.profiles.schemas import VentilationTelemetryBatch
from ai_bridge.domains.wvc.storage.models import Base, TelemetrySampleRecord, VentilationAnalysisRunRecord
from ai_bridge.domains.wvc.storage.repository import VentilationTelemetryRepository
from ai_bridge.domains.wvc.storage.analysis_repository import VentilationAnalysisRepository
from ai_bridge.storage.database import Database
from test_api import batch, sample
from test_analysis_service_v12_2 import EnvironmentalLLM


def setup(tmp_path):
    db = Database('sqlite:///' + str(tmp_path / 'history.sqlite'))
    Base.metadata.create_all(db.engine)
    repository = VentilationAnalysisRepository(db)
    llm = EnvironmentalLLM()
    calls = []
    original = llm.generate
    def generate(request):
        calls.append(request)
        time.sleep(.02)
        return original(request)
    llm.generate = generate
    service = VentilationAnalysisServiceV122(repository=repository, llm=llm, model='test', think=False, temperature=0, min_samples=1)
    return db, WVCAnalysisPolicy(repository, service), calls


def ingest(db, *, suffix='fresh', captured='2026-08-08T11:29:55+00:00'):
    payload = batch(batch_id=suffix, samples=[sample(suffix, 1)])
    payload['samples'][0]['captured_at'] = captured
    return VentilationTelemetryRepository(db).ingest(VentilationTelemetryBatch.model_validate(payload))


def test_disconnect_reconnect_ingest_analysis_and_retry_preserve_history(tmp_path):
    db, policy, calls = setup(tmp_path)
    end = datetime(2026, 8, 8, 11, 30, tzinfo=timezone.utc)
    args = dict(source_id='workshop-ventilation-cm5-01', window_start=end-timedelta(minutes=15), window_end=end)
    try:
        # Old telemetry is retained but cannot make this window fresh.
        ingest(db, suffix='historical', captured='2026-08-07T11:29:55+00:00')
        skipped = policy.run_window(**args)
        assert skipped.as_dict()['status'] == 'skipped'
        assert skipped.reason == 'no_fresh_data' and not calls
        assert skipped.as_dict()['control_actions_supported'] is False
        with db.session() as session:
            assert session.scalar(select(func.count()).select_from(VentilationAnalysisRunRecord)) == 0
        assert ingest(db).stored == 1
        assert ingest(db).duplicates == 1
        completed = policy.run_window(**args)
        reused = policy.run_window(**args)
        assert completed.status == 'completed' and reused.status == 'reused'
        assert completed.analysis.analysis_id == reused.analysis.analysis_id and len(calls) == 1
        with db.session() as session:
            assert session.scalar(select(func.count()).select_from(TelemetrySampleRecord)) == 2
            assert session.scalar(select(func.count()).select_from(VentilationAnalysisRunRecord)) == 1
    finally:
        db.dispose()


def test_overlapping_runs_generate_only_once(tmp_path):
    db, policy, calls = setup(tmp_path)
    ingest(db)
    end = datetime(2026, 8, 8, 11, 30, tzinfo=timezone.utc)
    def run():
        return policy.run_window(source_id='workshop-ventilation-cm5-01', window_start=end-timedelta(minutes=15), window_end=end)
    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        assert sorted(r.status for r in results) == ['completed', 'reused']
        assert len(calls) == 1
    finally:
        db.dispose()


def test_platform_can_compose_without_wvc_and_has_no_sensor_policy():
    app = create_app(Settings(database_url='sqlite://'), domains=())
    assert '/api/v1/ventilation/telemetry/batches' not in app.openapi()['paths']
    root = Path(__file__).parents[1] / 'src/ai_bridge'
    for directory in ('core', 'gateway', 'api', 'storage'):
        for path in (root / directory).glob('*.py'):
            text = path.read_text().lower()
            assert 'sen55' not in text and 'supply_voltage' not in text and 'extract_voltage' not in text, path


def test_old_imports_are_exact_domain_aliases():
    from ai_bridge.analysis.service_v12_2 import VentilationAnalysisServiceV122 as legacy
    from ai_bridge.storage.models import TelemetrySampleRecord as legacy_record
    assert legacy is VentilationAnalysisServiceV122
    assert legacy_record is TelemetrySampleRecord


def _process_analysis(filename, calls_path, outcomes):
    db = Database('sqlite:///' + filename)
    repository = VentilationAnalysisRepository(db)
    llm = EnvironmentalLLM()
    original = llm.generate
    def generate(request):
        with open(calls_path, 'a') as stream:
            stream.write('generation\n')
        time.sleep(.1)
        return original(request)
    llm.generate = generate
    service = VentilationAnalysisServiceV122(repository=repository, llm=llm, model='test', think=False, temperature=0, min_samples=1)
    end = datetime(2026, 8, 8, 11, 30, tzinfo=timezone.utc)
    try:
        result = WVCAnalysisPolicy(repository, service).run_window(source_id='workshop-ventilation-cm5-01',
            window_start=end-timedelta(minutes=15), window_end=end)
        outcomes.put(result.status)
    finally:
        db.dispose()


def test_separate_scheduled_processes_do_not_duplicate_generation(tmp_path):
    import multiprocessing
    db, _, _ = setup(tmp_path)
    ingest(db)
    db.dispose()
    context = multiprocessing.get_context('spawn')
    outcomes = context.Queue()
    calls = tmp_path / 'calls'
    workers = [context.Process(target=_process_analysis, args=(str(tmp_path/'history.sqlite'), str(calls), outcomes)) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        for worker in workers:
            worker.join(15)
            assert worker.exitcode == 0
        assert sorted(outcomes.get(timeout=2) for _ in workers) == ['completed', 'reused']
        assert calls.read_text().splitlines() == ['generation']
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.kill()
            worker.join()
        outcomes.close()


def test_failed_analysis_does_not_consume_fresh_window(tmp_path):
    import pytest
    db, policy, calls = setup(tmp_path)
    ingest(db)
    original = policy.service.llm.generate
    def failure(request):
        raise RuntimeError('provider unavailable')
    policy.service.llm.generate = failure
    end = datetime(2026, 8, 8, 11, 30, tzinfo=timezone.utc)
    args = dict(source_id='workshop-ventilation-cm5-01', window_start=end-timedelta(minutes=15), window_end=end)
    try:
        with pytest.raises(RuntimeError):
            policy.run_window(**args)
        policy.service.llm.generate = original
        assert policy.run_window(**args).status == 'completed'
        assert len(calls) == 1
    finally:
        db.dispose()


def test_history_probe_allows_append_but_rejects_historical_mutation(tmp_path):
    import importlib.util
    import pytest
    path = Path(__file__).parents[1] / 'deploy/stage-g/domain_probe.py'
    spec = importlib.util.spec_from_file_location('domain_probe', path)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    db, _, _ = setup(tmp_path)
    try:
        ingest(db, suffix='first')
        baseline = probe.inventory(db)
        ingest(db, suffix='second')
        assert probe.inventory(db, baseline['tables'])['history'] == 'PRESERVED'
        with db.session() as session:
            record = session.scalar(select(TelemetrySampleRecord).order_by(TelemetrySampleRecord.id))
            record.sequence = 9000
        with pytest.raises(AssertionError):
            probe.inventory(db, baseline['tables'])
    finally:
        db.dispose()


def test_g_rollback_verifies_only_target_and_can_quiesce_failed_gateway(tmp_path, monkeypatch):
    import importlib.util
    path = Path(__file__).parents[1] / 'deploy/stage-g/autopilot/gate.py'
    spec = importlib.util.spec_from_file_location('g_rollback_test', path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    baseline_release = tmp_path / 'verified-f'
    baseline_release.mkdir()
    current = tmp_path / 'current'
    current.symlink_to(tmp_path / 'missing-failed-candidate')
    actions = []
    monkeypatch.setattr(gate, 'BASE', baseline_release)
    monkeypatch.setattr(gate.e, 'CURRENT', current)
    monkeypatch.setattr(gate, 'verify', lambda target: actions.append(('verify', target)))
    monkeypatch.setattr(gate.e, 'quiesce', lambda baseline, **kw: actions.append(('quiesce', kw)))
    for name in ('require_hermes_stopped', 'comfy_idle'):
        monkeypatch.setattr(gate.e, name, lambda: None)
    for name in ('require_no_media_workers', 'require_kernel_clear'):
        monkeypatch.setattr(gate.f, name, lambda: None)
    monkeypatch.setattr(gate.f, 'recover_gpu_quiesced', lambda state: actions.append(('recover', True)))
    monkeypatch.setattr(gate, 'run', lambda *a, **kw: None)
    monkeypatch.setattr(gate.e, 'runtime', lambda *a: None)
    monkeypatch.setattr(gate.e, 'config', lambda: {})
    monkeypatch.setattr(gate.e, 'identity', lambda unit: ['unchanged-provider'])
    monkeypatch.setattr(gate, 'history', lambda *a: None)
    monkeypatch.setattr(gate.e, 'resume_ingress', lambda b: actions.append(('resume', True)))
    gate.switch(baseline_release, tmp_path, {'ollama': ['unchanged-provider'], 'history': {}})
    assert current.resolve() == baseline_release
    assert actions == [('verify', baseline_release), ('quiesce', {'allow_gateway_unavailable': True}), ('recover', True), ('resume', True)]
