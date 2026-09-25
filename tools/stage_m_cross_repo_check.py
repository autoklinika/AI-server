"""Optional local compatibility check; never collected by CI.

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:/tmp python -m pytest \
  -p stage_m_asyncio_poll tools/stage_m_cross_repo_check.py
Uses actual CRT public APIs and writes only to pytest's temporary directory.
"""
import json
import sys
from pathlib import Path


def test_actual_crt_exporter(tmp_path):
    sys.path.insert(0, '/home/harrypotter/agent-worktrees/stage-m-crt')
    from app.project import CrtProject
    from app.models import CanFrame, CaptureSession
    from app.session_stream import SessionStreamWriter
    from app.domain import AnalysisInput, ArtifactSource
    from app.extensions import ArtifactWriter, CancellationToken
    from app.project_domain_store import ProjectDomainStore
    from app.platform_export import PlatformExporter, content_hash
    from ai_bridge.domains.crt.schemas import Manifest, AIContext
    from ai_bridge.domains.crt.release import create_stage_m_app
    from ai_bridge.settings import Settings
    from ai_bridge.storage.base import Base
    from ai_bridge.providers.contracts import LLMResponse, LLMExecution
    from fastapi.testclient import TestClient

    project = CrtProject.create(tmp_path / 'project', name='Stage M compatibility')
    original = project.root / 'sessions/imported/source/input.csv'
    original.write_text('original evidence')
    path = project.live_sessions_dir / 'capture.crt.jsonl'
    writer = SessionStreamWriter(CaptureSession(name='capture', source='test',
        metadata={'receive_mode': 'silent', 'original_file': project.relative_path(original)}), path)
    writer.open()
    writer.append(CanFrame(0, 30, 123, b'\x01'))
    writer.append(CanFrame(1, 20, 123, b'\x02'))
    writer.close()
    record = project.register_session(path, name='capture', source='test', status='ready')
    project.finalize_session(path, frame_count=2, marker_count=0, duration_s=0.0)
    store = ProjectDomainStore(project)
    run = store.create_analysis_run(provider_id='crt.test', provider_version='1',
        algorithm_version='2', inputs=(AnalysisInput('session', record.id),))
    artifact = ArtifactWriter(project=project, store=store, analysis_run_id=run.id,
        provider_id=run.provider_id, provider_version='1', algorithm_version='2',
        cancellation=CancellationToken()).write_json(filename='stats.json',
        artifact_type='statistics', schema_version=2,
        sources=(ArtifactSource(record.id, 'session', {}),), payload={'count': 2})
    exporter = PlatformExporter(project.root)
    manifest = exporter.manifest(record.id, artifact_ids=(artifact.id,))
    context = exporter.context(record.id, question='Explain count', artifact_ids=(artifact.id,))
    assert Manifest.model_validate(manifest).model_dump(mode='json') == json.loads(json.dumps(manifest))
    assert Manifest.model_validate(manifest).manifest_hash == content_hash(manifest)
    assert AIContext.model_validate(context).model_dump(mode='json') == json.loads(json.dumps(context))

    class Provider:
        def generate(self, request):
            assert request.tools == []
            return LLMResponse(request_id=request.request_id, content='{"statement":"Advisory only"}',
                execution=LLMExecution(provider='fixture', model='fixture'))

    app = create_stage_m_app(Settings(database_url='sqlite+pysqlite:///' + str(tmp_path / 'ai.db')), provider=Provider())
    with TestClient(app) as client:
        Base.metadata.create_all(app.state.database.engine)
        response = client.post('/api/v1/crt/manifests', json=manifest)
        assert response.status_code == 200, response.text
        row = response.json()
        assert row['manifest_hash'] == content_hash(manifest)
        assert row['manifest'] == json.loads(json.dumps(manifest))
        assert client.post('/api/v1/crt/manifests', json=manifest).json()['id'] == row['id']
        url = '/api/v1/crt/sessions/' + row['id']
        result = client.post(url + '/signal-hypothesis', json=context)
        assert result.status_code == 201, result.text
        assert result.json()['payload']['context'] == json.loads(json.dumps(context))
        other = client.post('/api/v1/crt/manifests', json=exporter.manifest(record.id)).json()
        assert other['projection_revision'] == 2 and other['id'] != row['id']
        assert client.get(url).json()['manifest'] == json.loads(json.dumps(manifest))
        empty_context = exporter.context(record.id, question='No selected evidence')
        assert client.post('/api/v1/crt/sessions/' + other['id'] + '/signal-hypothesis', json=empty_context).status_code == 201
    # Opt-in regeneration is local only; normal check never modifies the fixture.
    if '--write-fixture' in sys.argv:
        Path('tests/fixtures/crt_platform_v1.json').write_text(json.dumps(
            {'manifest': manifest, 'context': context}, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        test_actual_crt_exporter(Path(directory))
    print('PASS: actual CRT manifest/context models, API, idempotency, revisions, selected and empty evidence')
