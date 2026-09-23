import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest

from ai_bridge.gateway.app import create_gateway_app
from ai_bridge.providers.contracts import LLMResponse
from ai_bridge.settings import Settings


@asynccontextmanager
async def client(handler=None, provider=None, peer="127.0.0.1", **settings):
    def default(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "private-model"}]})
        return httpx.Response(200, json={"done": True, "message": {"content": "ok"},
                                         "prompt_eval_count": 4, "eval_count": 1})
    app = create_gateway_app(Settings(ollama_model="private-model", **settings),
                             upstream_transport=httpx.MockTransport(handler or default),
                             platform_provider=provider)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=(peer, 123)),
                                     base_url="http://platform") as http:
            yield http, app


def payload(**extra):
    return {"messages": [{"role": "user", "content": "private-prompt"}], **extra}


def test_v1_contract_and_provider_wire_boundary():
    async def run():
        seen = []
        def upstream(request):
            seen.append(json.loads(request.content))
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"done": True, "message": {"content": "answer"},
                                             "backend_private": "secret"})
        async with client(upstream) as (http, app):
            r = await http.post('/api/v1/ai', json=payload(context={"request_id": "req_test", "domain": "wvc"}))
            assert r.status_code == 200, r.text
            data = r.json()
            assert data['schema_version'] == 1
            assert data['request_id'] == r.headers['x-request-id'] == 'req_test'
            assert data['execution']['model'] == 'reasoning-main'
            assert 'private-model' not in r.text and 'backend_private' not in r.text
            assert seen[0]['model'] == 'private-model'
            assert 'context' not in seen[0]
            job = (await http.get('/api/v1/jobs/' + data['job_id'])).json()['job']
            assert job['state'] == 'completed'
            assert job['request_id'] == data['request_id']
            assert job['domain'] == 'wvc'
            assert job['assigned_provider'] == 'ollama-local'
            assert 'private-prompt' not in (await http.get('/api/v1/jobs')).text
            assert (await app.state.scheduler.snapshot())['active_count'] == 0
            assert (await http.get('/api/v1/models')).json()['models'][0]['logical_id'] == 'reasoning-main'
            assert (await http.get('/api/v1/systems')).status_code == 200
    asyncio.run(run())


@pytest.mark.parametrize('body', [payload(model='raw-model'), payload(stream=True), payload(priority_class='bad'),
    payload(context={"actor_id": {"secret": "private"}}), payload(provider='ollama'),
    payload(capability='structured-generation'), payload(schema_version=2)])
def test_invalid_requests_never_reach_provider(body):
    async def run():
        def upstream(request):
            pytest.fail('invalid input reached provider')
        async with client(upstream) as (http, _):
            r = await http.post('/api/v1/ai', json=body)
            assert r.status_code == 400
            assert r.json()['error']['code'] == 'invalid_request'
            assert 'private' not in r.text and 'raw-model' not in r.text
            assert r.json()['error']['request_id'] == r.headers['x-request-id']
    asyncio.run(run())


def test_error_auth_and_health_contracts():
    async def run():
        async with client(peer='192.0.2.5') as (http, _):
            assert (await http.get('/api/v1/health', headers={'x-forwarded-for':'127.0.0.1'})).status_code == 403
        token = 'test-service-token-only'
        async with client(platform_api_token=token) as (http, _):
            assert (await http.get('/api/v1/health')).status_code == 401
            r = await http.get('/api/v1/health', headers={'authorization': 'Bearer ' + token})
            assert r.json()['readiness'] is True
            assert 'private-model' not in r.text and token not in r.text
        async with client() as (http, _):
            for path in ('/api/v1/missing', '/api/v1/jobs/missing'):
                r = await http.get(path)
                assert r.status_code == 404
                assert r.json()['error']['code'] == 'not_found'
            assert (await http.get('/api/v2/health')).status_code == 404
            r = await http.post('/api/v1/ai', content='{"secret":', headers={'content-type':'application/json'})
            assert r.status_code == 400 and 'secret' not in r.text
            r = await http.post('/api/v1/ai', json=payload(context={'request_id':'body'}), headers={'x-request-id':'header'})
            assert r.status_code == 400
            r = await http.post('/api/v1/ai', json=payload(capability='video-generation'))
            assert r.status_code == 503 and r.json()['error']['code'] == 'capability_unavailable'
        def broken(request):
            return httpx.Response(500, text='secret upstream URL and prompt')
        async with client(broken) as (http, app):
            r = await http.post('/api/v1/ai', json=payload())
            assert r.status_code == 503 and 'secret' not in r.text
            assert (await app.state.scheduler.snapshot())['recent_jobs'][-1]['state'] == 'failed'
            r = await http.get('/api/v1/health')
            assert r.json()['readiness'] is False and 'secret' not in r.text
    asyncio.run(run())


def test_shared_admission_timeout_queue_full_and_cancellation():
    async def run():
        calls = []
        started, release = asyncio.Event(), asyncio.Event()
        async def upstream(request):
            calls.append(request.url.path)
            started.set()
            await release.wait()
            return httpx.Response(200, json={"done": True, "message": {"content":"ok"}})
        async with client(upstream, gateway_max_queue_size=1) as (http, app):
            # A legacy caller owns the only slot: v1 must wait in the same queue.
            legacy = asyncio.create_task(http.post('/api/chat', json={'model':'legacy'}))
            await started.wait()
            waiting = asyncio.create_task(http.post('/api/v1/ai', json=payload(timeout_seconds=2.0)))
            for _ in range(1000):
                if (await app.state.scheduler.snapshot())['queued_count'] == 1:
                    break
                await asyncio.sleep(.001)
            else:
                pytest.fail('v1 request never entered the shared queue')
            full = await http.post('/api/v1/ai', json=payload())
            assert full.status_code == 429
            expired = await waiting
            assert expired.status_code == 504
            assert calls == ['/api/chat']
            release.set()
            await legacy
            release.clear()
            started.clear()
            running = asyncio.create_task(http.post('/api/v1/ai', json=payload()))
            await started.wait()
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
            snap = await app.state.scheduler.snapshot()
            assert snap['active_count'] == snap['queued_count'] == 0
            assert snap['recent_jobs'][-1]['state'] == 'cancelled'
    asyncio.run(run())


def test_provider_can_be_replaced_without_client_changes():
    class Alternate:
        # Logical registry binding remains stable while the executor changes.
        provider_id = 'ollama-local'
        node_id = Settings().node_id
        async def generate(self, request):
            return LLMResponse(request_id=request.request_id, content='alternate executor')
        async def ready(self):
            return True
    async def run():
        async with client(provider=Alternate()) as (http, _):
            r = await http.post('/api/v1/ai', json=payload())
            assert r.json()['content'] == 'alternate executor'
            assert r.json()['execution']['model'] == 'reasoning-main'
    asyncio.run(run())


def test_auth_and_legacy_control_headers_do_not_cross_v1_boundary():
    async def run():
        seen = []
        token = 'service-token-for-test-only'
        async def upstream(request):
            seen.append(dict(request.headers))
            return httpx.Response(200, json={'done':True, 'message':{'content':'ok'}})
        async with client(upstream, platform_api_token=token) as (http, app):
            r = await http.post('/api/v1/ai', json=payload(priority_class='normal'), headers={
                'authorization':'Bearer '+token, 'x-ai-priority':'-1000',
                'x-ai-resource-lease':'not-a-real-lease', 'x-ai-source':'private-chat-id'})
            assert r.status_code == 200
            job = (await app.state.scheduler.snapshot())['recent_jobs'][-1]
            assert job['priority_class'] == 'normal'
            assert all(name not in seen[0] for name in
                       ('authorization', 'x-ai-priority', 'x-ai-resource-lease', 'x-ai-source'))
    asyncio.run(run())


def test_running_deadline_cancels_executor_before_releasing_slot():
    async def run():
        cancelled = False
        async def upstream(request):
            nonlocal cancelled
            try:
                await asyncio.Event().wait()
            finally:
                cancelled = True
        async with client(upstream) as (http, app):
            r = await http.post('/api/v1/ai', json=payload(timeout_seconds=.03))
            assert r.status_code == 504 and cancelled
            snap = await app.state.scheduler.snapshot()
            assert snap['active_count'] == snap['queued_count'] == 0
            assert snap['recent_jobs'][-1]['state'] == 'expired'
    asyncio.run(run())


def test_observability_snapshot_is_bounded_metadata_only():
    async def run():
        token = 'observability-test-service-token'
        async with client(platform_api_token=token) as (http, app):
            headers = {'authorization': 'Bearer ' + token}
            ok = await http.post('/api/v1/ai', json=payload(
                context={'request_id': 'req_observe', 'domain': 'wvc'}), headers=headers)
            assert ok.status_code == 200
            bad = await http.post('/api/v1/ai', json=payload(
                capability='video-generation'), headers=headers)
            assert bad.status_code == 503
            r = await http.get('/api/v1/observability', headers=headers)
            assert r.status_code == 200
            data = r.json()
            assert data['schema_version'] == 1 and data['status'] == 'ok'
            assert data['resource_manager']['active'] == 0
            assert data['resource_manager']['queued'] == 0
            assert data['resource_leases']['active'] == 0
            assert data['gpu_residency']['recovery_required'] is False
            assert data['execution'] == {
                'provider': 'ollama-local', 'node': app.state.platform_provider.node_id,
                'logical_model': 'reasoning-main'}
            assert data['jobs']['states']['completed'] >= 1
            assert data['jobs']['providers']['ollama-local'] >= 1
            assert data['jobs']['queue_wait']['count'] >= 1
            assert data['jobs']['execution']['count'] >= 1
            assert data['requests']['errors']['capability_unavailable'] == 1
            assert data['retention']['persistent'] is False
            assert data['retention']['terminal_limit'] == 128
            assert data['process']['rss_bytes'] > 0
            serialized = r.text
            assert 'private-prompt' not in serialized
            assert 'private-model' not in serialized
            assert token not in serialized
            health = (await http.get('/api/v1/health', headers=headers)).json()
            assert health['components']['resource_leases']['active'] == 0
            assert health['components']['gpu_residency']['recovery_required'] is False
    asyncio.run(run())


def test_observability_counts_invalid_boundary_requests_without_echoing_input():
    async def run():
        async with client() as (http, _):
            bad_id = 'bad request id with spaces'
            r = await http.get('/api/v1/health', headers={'x-request-id': bad_id})
            assert r.status_code == 400 and bad_id not in r.text
            obs = (await http.get('/api/v1/observability')).json()
            assert obs['requests']['errors']['invalid_request'] == 1
            assert obs['requests']['status_classes']['4xx'] >= 1
    asyncio.run(run())


def test_structured_platform_log_never_contains_dynamic_path_or_query(caplog):
    import logging
    async def run():
        caplog.set_level(logging.INFO, logger='ai_bridge.platform.api')
        async with client() as (http, _):
            dynamic = 'private-chat-id'
            secret_query = 'private-query-token'
            r = await http.get(f'/api/v1/jobs/{dynamic}?token={secret_query}')
            assert r.status_code == 404
            logs = '\n'.join(record.getMessage() for record in caplog.records
                             if record.name == 'ai_bridge.platform.api')
            assert 'PLATFORM_REQUEST' in logs
            assert dynamic not in logs and secret_query not in logs
            assert '/jobs/{job_id}' in logs
            assert 'not_found' in logs
    asyncio.run(run())
