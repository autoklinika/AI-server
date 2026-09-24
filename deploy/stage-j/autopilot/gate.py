#!/usr/bin/env python3
"""Stage J production gate: Knowledge Service with verified Stage I rollback."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback
from urllib.error import HTTPError
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    'stage_i_e_primitives', ROOT / 'deploy/stage-e/autopilot/gate.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)

BASE = Path('/opt/ai-platform/releases/stage-i-30626dcc60f8')
BASE_SHA = '30626dcc60f86c80bacb3c602b87f2d345b22221'
STATE = Path('/var/lib/ai-platform/stage-j')
CHECKS = ('platform_api', 'observability', 'knowledge_search', 'knowledge_ask',
          'knowledge_document', 'wvc', 'hermes_connected', 'hermes_inference',
          'messaging_boundary', 'matched_clients', 'media_preflight', 'health')

_original_verify = e.verify_release
e.D6 = BASE
e.D6_SHA = BASE_SHA
e.STATE = STATE


def require(condition):
    return e.require(condition)


def verify_release(path, _stage=None):
    stamp = dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())
    stage = stamp['stage'].lower()
    require(stage in ('i', 'j'))
    return _original_verify(path, stage)


e.verify_release = verify_release


def observability_snapshot(cfg):
    token = Path(cfg['api_token_file']).read_text().strip() if cfg['api_token_file'] else None
    value = e.fetch(e.GATEWAY + '/api/v1/observability', token=token)
    require(value['schema_version'] == 1 and value['status'] in ('ok', 'blocked'))
    rm = value['resource_manager']
    require(type(rm['active']) is int and type(rm['queued']) is int)
    require(type(value['resource_leases']['active']) is int)
    require(value['execution']['provider'] == 'ollama-local')
    require(value['execution']['logical_model'] == 'reasoning-main')
    require(value['execution']['node'])
    require(value['retention']['persistent'] is False)
    require(value['retention']['terminal_limit'] == 128)
    require(type(value['process']['rss_bytes']) is int and value['process']['rss_bytes'] > 0)
    require(value['gpu_residency']['state'] in ('llm', 'media', 'blocked'))
    # Explicit allowlist check: the observability contract must never contain payloads.
    serialized = json.dumps(value, sort_keys=True).lower()
    for forbidden in ('private-prompt', 'authorization', 'chat_id', 'bot_token', 'message.content'):
        require(forbidden not in serialized)
    return {
        'status': value['status'],
        'jobs_observed': value['jobs']['observed'],
        'requests_total': value['requests']['total'],
        'provider': value['execution']['provider'],
        'node': value['execution']['node'],
        'gpu_state': value['gpu_residency']['state'],
    }


def knowledge_absent(cfg):
    token = Path(cfg['api_token_file']).read_text().strip() if cfg['api_token_file'] else None
    payload = {
        'schema_version': 1,
        'query': '0 281 007 439',
        'mode': 'exact',
        'context': {'domain': 'ecu-repair'},
        'limit': 1,
    }
    try:
        e.fetch(e.GATEWAY + '/api/v1/knowledge/search', payload=payload, token=token)
    except HTTPError as error:
        require(error.code == 404)
        return
    raise RuntimeError('Stage I unexpectedly exposes Stage J Knowledge API')


def knowledge_smoke(cfg):
    token = Path(cfg['api_token_file']).read_text().strip() if cfg['api_token_file'] else None
    search = e.fetch(e.GATEWAY + '/api/v1/knowledge/search', payload={
        'schema_version': 1,
        'query': '0 281 007 439',
        'mode': 'exact',
        'context': {'domain': 'ecu-repair'},
        'limit': 3,
    }, token=token)
    require(search['schema_version'] == 1)
    require(search['backend'] == 'knowledge-primary')
    require(search['results'])
    candidates = [item for item in search['results'] if '0 281 007 439' in item['text']]
    require(bool(candidates))
    first = candidates[0]
    document_id = first['metadata']['document_id']

    document = e.fetch(
        e.GATEWAY + '/api/v1/knowledge/documents/' + document_id,
        token=token,
    )
    require(document['document']['document_id'] == document_id)
    require(document['chunks'])

    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = e.Request(
        e.GATEWAY + '/api/v1/knowledge/documents/' + document_id + '/content',
        headers=headers,
    )
    with e.urlopen(request, timeout=20) as response:
        require(response.status == 200)
        require(len(response.read(1024)) > 0)

    ask = e.fetch(e.GATEWAY + '/api/v1/knowledge/ask', payload={
        'schema_version': 1,
        'query': 'Co bylo przyczyna SPN 107 FMI 3 w CASE-0001?',
        'mode': 'hybrid',
        'context': {'domain': 'ecu-repair'},
        'limit': 8,
        'timeout_seconds': 300,
    }, token=token)
    require(ask['schema_version'] == 1)
    require(type(ask['answer']) is str and bool(ask['answer'].strip()))
    require(ask['insufficient_context'] is False)
    require(bool(ask['citations']))
    require(all(item.get('document_id') and item.get('chunk_id')
                for item in ask['citations']))
    serialized = json.dumps(ask, sort_keys=True).lower()
    for forbidden in ('ollama-local', 'qdrant', 'private-model', 'storage_uri'):
        require(forbidden not in serialized)
    return {
        'search_results': len(search['results']),
        'document_id': document_id,
        'rag_citations': len(ask['citations']),
        'rag_model': ask['execution']['model'],
    }


def ensure_gateway_knowledge_env():
    bridge_env = Path('/etc/ai-bridge/ai-bridge.env')
    gateway_env = Path('/etc/ai-gateway/ai-gateway.env')
    bridge_lines = bridge_env.read_text().splitlines()
    db_lines = [line for line in bridge_lines if line.startswith('AI_BRIDGE_DATABASE_URL=')]
    require(len(db_lines) == 1)
    db_line = db_lines[0]

    original = gateway_env.read_text()
    gateway_lines = original.splitlines()
    existing = [line for line in gateway_lines if line.startswith('AI_BRIDGE_DATABASE_URL=')]
    if existing:
        require(existing == [db_line])
        return

    info = gateway_env.stat()
    updated = original
    if updated and not updated.endswith('\n'):
        updated += '\n'
    updated += db_line + '\n'
    temp = gateway_env.with_name(gateway_env.name + '.stage-j.tmp')
    temp.write_text(updated)
    os.chmod(temp, info.st_mode & 0o777)
    os.chown(temp, info.st_uid, info.st_gid)
    os.replace(temp, gateway_env)


def smoke(phase, target, candidate, cfg, baseline, state):
    e.runtime(target, cfg, baseline)
    before = [e.identity(unit) for unit in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')]
    challenge = uuid4().hex
    e.write_once(state / (phase + '-started.json'), {
        'challenge': challenge, 'release_id': target.name})

    # Freeze the scheduled WVC producer only for the bounded smoke window; ingress
    # itself stays live. Restore the exact baseline timer state in finally.
    timer_active = baseline['analysis_timer_active'] == 'active'
    if timer_active:
        e.run(['systemctl', 'stop', 'ai-bridge-analysis.timer'])
    try:
        e.api_smoke(cfg)
        obs = observability_snapshot(cfg)
        if target == candidate:
            knowledge = knowledge_smoke(cfg)
        else:
            knowledge_absent(cfg)
            knowledge = {'status': 'absent_on_stage_i'}
        e.preflight_step('smoke_wvc', e.wvc_smoke)
        e.preflight_step('smoke_hermes_connected', e.hermes_state)
        e.preflight_step('smoke_hermes_inference', e.hermes_oneshot_smoke)
        e.preflight_step('smoke_messaging_boundary', e.messaging_boundary_smoke)
        require(e.clients() == baseline['clients'])
        e.media_preflight()
        e.runtime(target, cfg, baseline)
        require(before == [e.identity(unit) for unit in
                           ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')])
    finally:
        if timer_active:
            e.run(['systemctl', 'start', 'ai-bridge-analysis.timer'])

    e.write_once(state / (phase + '.json'), {
        'schema_version': 1, 'release_id': target.name, 'challenge': challenge,
        'checks': {key: True for key in CHECKS},
        'observability': obs, 'knowledge': knowledge,
        'time': int(time.time()), 'services': before})


def rollback_to_i(state, candidate, cfg, baseline):
    installed = state / 'installed.json'
    if not installed.exists():
        # A failed build has not changed production. Prove Stage I is still healthy
        # and record a no-op rollback without stopping/restarting any service.
        require(e.CURRENT.resolve(strict=True) == BASE)
        e.runtime(BASE, cfg, baseline)
        require(e.user_systemctl([
            'show', 'hermes-gateway.service', '-p', 'ActiveState', '--value']) == 'active')
        require(e.run(['systemctl', 'show', 'ai-bridge-analysis.timer',
                       '-p', 'ActiveState', '--value']) == 'active')
        if not (state / 'rollback.json').exists():
            e.write_once(state / 'rollback.json', {
                'release_id': BASE.name, 'no_mutation': True})
        return
    e.switch(BASE, candidate, cfg, baseline)
    if not (state / 'rollback.json').exists():
        e.write_once(state / 'rollback.json', {
            'release_id': BASE.name, 'no_mutation': False})


def main(step):
    cfg = e.config()
    sha = e.git_run(['rev-parse', 'HEAD'])
    candidate = Path('/opt/ai-platform/releases') / ('stage-j-' + sha[:12])
    state = STATE / sha

    if step == '00_preflight':
        e.preflight(cfg)
        return

    require(os.geteuid() == 0)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        if step == '10_build_install':
            e.preflight(cfg)
            require(not state.exists() and not candidate.exists())
            require(not e.git_run(['status', '--porcelain']))
            state.mkdir(mode=0o700)
            baseline = {
                'rollback': BASE.name, 'rollback_sha': BASE_SHA,
                'candidate': candidate.name, 'source_sha': sha,
                'clients': e.clients(), 'comfy': e.identity('comfyui.service'),
                'hermes_active': e.user_systemctl([
                    'show', 'hermes-gateway.service', '-p', 'ActiveState', '--value']),
                'analysis_timer_active': e.run([
                    'systemctl', 'show', 'ai-bridge-analysis.timer',
                    '-p', 'ActiveState', '--value']),
                'rollback_checksums': e.digest(BASE / 'metadata/SHA256SUMS'),
            }
            require(baseline['hermes_active'] == 'active')
            require(baseline['analysis_timer_active'] == 'active')
            e.write_once(state / 'baseline.json', baseline)
            e.run(['bash', ROOT / 'deploy/stage-j/build_release.sh', candidate, candidate.name],
                  timeout=1800, cwd=ROOT,
                  env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            require(verify_release(candidate)['source_git_sha'] == sha)
            e.runtime(BASE, cfg, baseline)
            e.write_once(state / 'installed.json', {
                'candidate': candidate.name, 'source_sha': sha,
                'checksums': e.digest(candidate / 'metadata/SHA256SUMS')})
            return

        baseline = e.read(state / 'baseline.json')
        require(baseline['source_sha'] == sha and baseline['rollback_sha'] == BASE_SHA)
        require(baseline['candidate'] == candidate.name and baseline['rollback'] == BASE.name)
        require(e.digest(BASE / 'metadata/SHA256SUMS') == baseline['rollback_checksums'])

        if step == '40_rollback':
            rollback_to_i(state, candidate, cfg, baseline)
            return

        if step == '50_rollback_smoke':
            require((state / 'rollback.json').is_file())
            phase = 'rollback-smoke'
            if (state / (phase + '-started.json')).exists():
                phase = 'recovery-smoke-' + uuid4().hex
            smoke(phase, BASE, candidate, cfg, baseline, state)
            return

        installed = e.read(state / 'installed.json')
        require(installed['source_sha'] == sha)
        require(e.digest(candidate / 'metadata/SHA256SUMS') == installed['checksums'])

        if step in ('20_cutover', '60_reactivate'):
            ensure_gateway_knowledge_env()
            if step == '60_reactivate':
                require((state / 'rollback-smoke.json').is_file())
            else:
                require(not (state / 'rollback.json').exists())
            require(not (state / (step + '.json')).exists())
            e.switch(candidate, BASE, cfg, baseline)
            e.write_once(state / (step + '.json'), {'release_id': candidate.name})
            return

        if step in ('30_smoke', '70_reactivate_smoke'):
            phase, prior = {
                '30_smoke': ('candidate-smoke', '20_cutover'),
                '70_reactivate_smoke': ('final-smoke', '60_reactivate'),
            }[step]
            require((state / (prior + '.json')).is_file())
            smoke(phase, candidate, candidate, cfg, baseline, state)
            return

        if step == '90_finalize':
            require(verify_release(candidate)['source_git_sha'] == sha)
            e.runtime(candidate, cfg, baseline)
            evidence = [e.read(state / (phase + '.json')) for phase in
                        ('candidate-smoke', 'rollback-smoke', 'final-smoke')]
            require([item['release_id'] for item in evidence]
                    == [candidate.name, BASE.name, candidate.name])
            require(len({item['challenge'] for item in evidence}) == 3)
            require(all(set(item['checks']) == set(CHECKS)
                        and all(item['checks'].values()) for item in evidence))
            require(all(item['observability']['status'] in ('ok', 'blocked')
                        for item in evidence))
            require(evidence[0]['knowledge']['rag_citations'] >= 1)
            require(evidence[1]['knowledge']['status'] == 'absent_on_stage_i')
            require(evidence[2]['knowledge']['rag_citations'] >= 1)
            require(evidence[0]['time'] <= evidence[1]['time'] <= evidence[2]['time'])
            require(e.user_systemctl([
                'show', 'hermes-gateway.service', '-p', 'ActiveState', '--value']) == 'active')
            require(e.run(['systemctl', 'show', 'ai-bridge-analysis.timer',
                           '-p', 'ActiveState', '--value']) == 'active')
            e.write_once(state / 'complete.json', {
                'source_sha': sha, 'candidate': candidate.name, 'rollback': BASE.name,
                'observability_contract': 1, 'knowledge_service_contract': 1,
                'rollback_cycle': 'PASS',
                'checks': list(CHECKS), 'hermes_active': 'active',
                'analysis_timer_active': 'active', 'time': int(time.time())})
            return

        raise ValueError('unknown step')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except BaseException as error:
        frames = [frame for frame in traceback.extract_tb(error.__traceback__)
                  if str(ROOT / 'deploy') in frame.filename]
        location = '/'.join(f'{Path(frame.filename).name}:{frame.name}:{frame.lineno}'
                            for frame in frames)
        print(f'GATE_FAIL={type(error).__name__} location={location}', file=sys.stderr)
        raise SystemExit(1)
    print('PASS: Stage J ' + sys.argv[1])
