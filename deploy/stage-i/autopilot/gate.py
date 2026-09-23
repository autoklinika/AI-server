#!/usr/bin/env python3
"""Stage I production gate: metadata-only observability with verified H rollback."""
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

BASE = Path('/opt/ai-platform/releases/stage-h-b9362bdae1c3')
BASE_SHA = 'b9362bdae1c30b53606d992fcecb575d7de71f4b'
STATE = Path('/var/lib/ai-platform/stage-i')
CHECKS = ('platform_api', 'observability', 'wvc', 'hermes_connected',
          'hermes_inference', 'messaging_boundary', 'matched_clients',
          'media_preflight', 'health')

_original_verify = e.verify_release
e.D6 = BASE
e.D6_SHA = BASE_SHA
e.STATE = STATE


def require(condition):
    return e.require(condition)


def verify_release(path, _stage=None):
    stamp = dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())
    stage = stamp['stage'].lower()
    require(stage in ('h', 'i'))
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


def observability_absent(cfg):
    token = Path(cfg['api_token_file']).read_text().strip() if cfg['api_token_file'] else None
    try:
        e.fetch(e.GATEWAY + '/api/v1/observability', token=token)
    except HTTPError as error:
        require(error.code == 404)
        return
    raise RuntimeError('Stage H unexpectedly exposes Stage I observability endpoint')


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
        if target == candidate:
            obs = observability_snapshot(cfg)
        else:
            observability_absent(cfg)
            obs = {'status': 'absent_on_stage_h'}
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
        'observability': obs, 'time': int(time.time()), 'services': before})


def rollback_to_h(state, candidate, cfg, baseline):
    installed = state / 'installed.json'
    if not installed.exists():
        # A failed build has not changed production. Prove H is still healthy
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
    candidate = Path('/opt/ai-platform/releases') / ('stage-i-' + sha[:12])
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
            e.run(['bash', ROOT / 'deploy/stage-i/build_release.sh', candidate, candidate.name],
                  timeout=1800, cwd=ROOT,
                  env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            require(verify_release(candidate)['source_git_sha'] == sha)
            for source in e.CLIENTS.values():
                for service in ('ai-bridge', 'ai-gateway'):
                    require((candidate / 'services' / service / source).read_bytes()
                            == (BASE / 'services/ai-bridge' / source).read_bytes())
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
            rollback_to_h(state, candidate, cfg, baseline)
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
            require(evidence[0]['observability']['status'] in ('ok', 'blocked'))
            require(evidence[1]['observability']['status'] == 'absent_on_stage_h')
            require(evidence[2]['observability']['status'] in ('ok', 'blocked'))
            require(evidence[0]['time'] <= evidence[1]['time'] <= evidence[2]['time'])
            require(e.user_systemctl([
                'show', 'hermes-gateway.service', '-p', 'ActiveState', '--value']) == 'active')
            require(e.run(['systemctl', 'show', 'ai-bridge-analysis.timer',
                           '-p', 'ActiveState', '--value']) == 'active')
            e.write_once(state / 'complete.json', {
                'source_sha': sha, 'candidate': candidate.name, 'rollback': BASE.name,
                'observability_contract': 1, 'rollback_cycle': 'PASS',
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
    print('PASS: Stage I ' + sys.argv[1])
