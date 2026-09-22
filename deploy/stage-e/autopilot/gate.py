#!/usr/bin/env python3
"""Supervisor-only production executor. Output is always content-free.

Immutable baseline per source SHA; no client/config changes or deletion. External
user-path tests use a pinned, root-owned site harness (see README). A failed or
missing real integration harness blocks preflight, never becomes a fake PASS.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
import pwd
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time
from uuid import uuid4
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
D6 = Path('/opt/ai-platform/releases/stage-d-resource-manager-v2-20260922-r2')
D6_SHA = '82d55f629f763c9352ad7c9e678e22eadb623639'
CURRENT = Path('/opt/ai-platform/current')
STATE = Path('/var/lib/ai-platform/stage-e')
GATEWAY = 'http://127.0.0.1:11435'
CLIENTS = {
    '/usr/local/bin/hermes-foto-dispatch': 'tools/local_image/hermes_foto_dispatch_global.py',
    '/usr/local/libexec/ai-server/hermes_resource_queue.py': 'tools/hermes_resource_queue.py',
    '/usr/local/libexec/ai-server/hermes_foto_prompt_compiler.py': 'tools/local_image/hermes_foto_prompt_compiler.py',
    '/usr/local/libexec/ai-server/hermes_video_dispatch.py': 'tools/local_video/hermes_video_dispatch_global.py',
    '/usr/local/libexec/ai-server/qwen_prompt_compiler.py': 'tools/local_video/qwen_prompt_compiler.py',
}
CHECKS = ('messaging_connectivity', 'hermes_inference', 'matched_clients_unchanged',
          'media_preflight', 'real_media')


def require(condition):
    if not condition:
        raise RuntimeError('gate condition failed')


def run(args, timeout=60, **kwargs):
    # Never forward subprocess diagnostics, model output, environment or journal.
    return subprocess.run([str(x) for x in args], check=True, capture_output=True,
                          text=True, timeout=timeout, **kwargs).stdout.strip()


def worktree_account():
    info = ROOT.stat()
    require(info.st_uid != 0)
    account = pwd.getpwuid(info.st_uid)
    return account.pw_name, info.st_uid, account.pw_dir


def git_run(args, timeout=60):
    name, _uid, home = worktree_account()
    return run([
        'runuser', '-u', name, '--', 'env',
        f'HOME={home}',
        'PATH=/usr/local/bin:/usr/bin:/bin',
        'git', '-C', ROOT, *args,
    ], timeout=timeout)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_release(path, stage):
    # Helper imports are local, never installed runtime modules.
    sys.path.insert(0, str(ROOT / 'deploy/stage-d'))
    validator = load_module('gate_metadata_' + stage, ROOT / f'deploy/stage-{stage}/validate_release_metadata.py')
    validator.validate(path)
    from validate_rollback_readiness import verify_checksums
    verify_checksums(path)
    return dict(line.split('=', 1) for line in (path / 'RELEASE').read_text().splitlines())


def private_file(path, executable=False):
    require(path.is_absolute() and not any(p.is_symlink() for p in (path, *path.parents)))
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022)
    if executable:
        require(info.st_mode & 0o111)


def config():
    return {'api_token_file': None}


def bridge_health_url():
    # Preserve the Stage B/D network policy: AI Bridge is LAN-only and may not
    # listen on loopback. Resolve the effective bind exactly from systemd.
    raw = run(['systemctl', 'show', 'ai-bridge.service', '-p', 'Environment', '--value'])
    bind_host = ''
    for token in shlex.split(raw):
        if token.startswith('AI_BRIDGE_HOST='):
            bind_host = token.split('=', 1)[1]
    if bind_host in ('', '0.0.0.0', '::', '[::]'):
        bind_host = '127.0.0.1'
    require(re.fullmatch(r'(?:127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})', bind_host) is not None)
    return f'http://{bind_host}:8080/health'


def fetch(url, payload=None, token=None, with_headers=False):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    with urlopen(request, timeout=610 if payload else 10) as response:
        body = json.load(response)
        return (body, response.headers) if with_headers else body


def identity(unit):
    data = dict(line.split('=', 1) for line in run(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'InvocationID']).splitlines())
    require(data['ActiveState'] == 'active' and int(data['MainPID']) > 0 and data['InvocationID'])
    return [data['MainPID'], data['InvocationID']]


def clients():
    result = {}
    for name, source in CLIENTS.items():
        path = Path(name)
        private_file(path)
        require(path.read_bytes() == (D6 / 'services/ai-bridge' / source).read_bytes())
        info = path.stat()
        result[name] = [digest(path), stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid]
    return result


def comfy_idle():
    queue = fetch('http://127.0.0.1:8188/queue')
    require(queue['queue_running'] == [] and queue['queue_pending'] == [])


def idle():
    data = fetch(GATEWAY + '/status')
    require((data['active_count'], data['queued_count'], data['resource_leases']['lease_count']) == (0, 0, 0))
    comfy_idle()


def runtime(release, cfg, baseline=None, require_idle=True):
    require(CURRENT.resolve(strict=True) == release)
    for service in ('ai-gateway', 'ai-bridge'):
        pid, _ = identity(service + '.service')
        require(Path('/proc/' + pid + '/cwd').resolve(strict=True) == release / 'services' / service)
        require(run(['systemctl', 'show', service + '.service', '-p', 'WorkingDirectory', '--value']) == '/opt/ai-platform/current/services/' + service)
    require(fetch(GATEWAY + '/health')['status'] == 'ok')
    require(fetch(bridge_health_url())['status'] == 'ok')
    if require_idle:
        idle()
    actual = clients()
    if baseline:
        require(actual == baseline['clients'])
        require(identity('comfyui.service') == baseline['comfy'])


def hermes_account():
    info = Path('/srv/ai-data/hermes').stat()
    require(info.st_uid != 0)
    account = pwd.getpwuid(info.st_uid)
    return account.pw_name, info.st_uid, account.pw_dir


def user_systemctl(args):
    name, uid, home = hermes_account()
    return run([
        'runuser', '-u', name, '--', 'env',
        f'HOME={home}',
        f'XDG_RUNTIME_DIR=/run/user/{uid}',
        'systemctl', '--user', *args,
    ])


def hermes_state():
    path = Path('/srv/ai-data/hermes/gateway_state.json')
    require(path.is_file())
    value = json.loads(path.read_text())
    require(value.get('gateway_state') == 'running')
    platforms = value.get('platforms') or {}
    require((platforms.get('telegram') or {}).get('state') == 'connected')
    require((platforms.get('api_server') or {}).get('state') == 'connected')
    require((platforms.get('discord') or {}).get('state') == 'connected')


def quiesce(baseline, allow_gateway_unavailable=False):
    # Stop actual ingress instead of relying on a point-in-time idle observation.
    if baseline['analysis_timer_active'] == 'active':
        run(['systemctl', 'stop', 'ai-bridge-analysis.timer'])
    if baseline['hermes_active'] == 'active':
        user_systemctl(['stop', 'hermes-gateway.service'])

    if allow_gateway_unavailable:
        try:
            idle()
        except Exception:
            # Emergency recovery to D.6 must not depend on a broken candidate's
            # /status endpoint. With ingress closed, ComfyUI idleness is the
            # remaining external-work invariant.
            comfy_idle()
    else:
        for _ in range(60):
            try:
                idle()
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('runtime did not drain')

    require(run(['systemctl', 'show', 'ai-bridge-analysis.service',
                 '-p', 'ActiveState', '--value']) == 'inactive')


def resume_ingress(baseline):
    if baseline['hermes_active'] == 'active':
        user_systemctl(['start', 'hermes-gateway.service'])
        for _ in range(90):
            try:
                require(user_systemctl(['show', 'hermes-gateway.service',
                                        '-p', 'ActiveState', '--value']) == 'active')
                hermes_state()
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('Hermes did not reconnect')
    if baseline['analysis_timer_active'] == 'active':
        run(['systemctl', 'start', 'ai-bridge-analysis.timer'])


def media_preflight():
    wrapper = Path('/usr/local/bin/generate-video-ltx23')
    private_file(wrapper, True)
    require('/opt/ai-platform/current/services/ai-bridge' in wrapper.read_text())
    run([wrapper, '--preflight'], timeout=120)


def hermes_oneshot_smoke():
    before = {job['job_id'] for job in fetch(GATEWAY + '/status').get('recent_jobs', [])}
    name, uid, home = hermes_account()
    cli = Path(home) / '.local/bin/hermes'
    require(cli.is_file())
    output = run([
        'runuser', '-u', name, '--', 'env',
        f'HOME={home}',
        'HERMES_HOME=/srv/ai-data/hermes',
        f'XDG_RUNTIME_DIR=/run/user/{uid}',
        str(cli), '-z', 'Return the word OK.',
    ], timeout=180)
    require(bool(output.strip()))
    recent = fetch(GATEWAY + '/status').get('recent_jobs', [])
    fresh = [job for job in recent if job.get('job_id') not in before]
    require(any(
        job.get('domain') == 'shared'
        and job.get('capability') == 'chat'
        and job.get('state') == 'completed'
        and job.get('assigned_provider') == 'ollama-local'
        for job in fresh
    ))


def real_media_smoke():
    helper = ROOT / 'deploy/stage-e/validate_media_runtime.sh'
    require(helper.is_file())
    run(['bash', helper], timeout=1900)


def write_once(path, value):
    # O_EXCL prevents retry from silently replacing a rollback point/evidence.
    with path.open('x') as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


def read(path):
    return json.loads(path.read_text())


def preflight_step(name, function):
    try:
        return function()
    except BaseException:
        # The label is deliberately content-free and safe for operator logs.
        print('PREFLIGHT_FAIL=' + name, file=sys.stderr)
        raise


def preflight_runtime(cfg):
    preflight_step('gateway_identity', lambda: identity('ai-gateway.service'))
    preflight_step('bridge_identity', lambda: identity('ai-bridge.service'))

    gateway_pid = identity('ai-gateway.service')[0]
    bridge_pid = identity('ai-bridge.service')[0]
    preflight_step(
        'gateway_cwd',
        lambda: require(
            Path('/proc/' + gateway_pid + '/cwd').resolve(strict=True)
            == D6 / 'services' / 'ai-gateway'
        ),
    )
    preflight_step(
        'bridge_cwd',
        lambda: require(
            Path('/proc/' + bridge_pid + '/cwd').resolve(strict=True)
            == D6 / 'services' / 'ai-bridge'
        ),
    )
    preflight_step(
        'gateway_working_directory',
        lambda: require(
            run(['systemctl', 'show', 'ai-gateway.service', '-p', 'WorkingDirectory', '--value'])
            == '/opt/ai-platform/current/services/ai-gateway'
        ),
    )
    preflight_step(
        'bridge_working_directory',
        lambda: require(
            run(['systemctl', 'show', 'ai-bridge.service', '-p', 'WorkingDirectory', '--value'])
            == '/opt/ai-platform/current/services/ai-bridge'
        ),
    )
    preflight_step('gateway_health', lambda: require(fetch(GATEWAY + '/health')['status'] == 'ok'))
    url = preflight_step('bridge_health_url', bridge_health_url)
    preflight_step('bridge_health', lambda: require(fetch(url)['status'] == 'ok'))
    preflight_step('matched_clients', clients)


def preflight(cfg):
    preflight_step('active_release',
        lambda: require(CURRENT.resolve(strict=True) == D6))
    stamp = preflight_step('release_metadata', lambda: verify_release(D6, 'd'))
    preflight_step('release_source',
        lambda: require(stamp['source_git_sha'] == D6_SHA))
    # Background work may legitimately be active here. The cutover path closes
    # ingress and enforces idle in quiesce() immediately before mutation.
    preflight_runtime(cfg)
    for unit in ('ai-gateway.service', 'ai-bridge.service', 'ai-bridge-analysis.service'):
        preflight_step('systemd_reload_' + unit.split('.')[0],
            lambda unit=unit: require(run([
                'systemctl', 'show', unit, '-p', 'NeedDaemonReload', '--value'
            ]) == 'no'))
    preflight_step('recovery_snapshot',
        lambda: require(Path(
            '/srv/ai-data/platform/recovery/stage-d6-resource-manager-v2-20260922-r1-clients'
        ).is_dir()))
    preflight_step('hermes_service',
        lambda: require(user_systemctl([
            'show', 'hermes-gateway.service', '-p', 'ActiveState', '--value'
        ]) == 'active'))
    preflight_step('hermes_connected', hermes_state)
    preflight_step('media_preflight', media_preflight)


def switch(target, entry, cfg, baseline):
    require(CURRENT.resolve(strict=True) in (entry, target))
    require(verify_release(D6, 'd')['source_git_sha'] == D6_SHA)
    verify_release(target, 'd' if target == D6 else 'e')
    require(clients() == baseline['clients'])
    mutating = False
    healthy = False
    try:
        recovering_to_d6 = target == D6 and CURRENT.resolve(strict=True) == entry
        quiesce(baseline, allow_gateway_unavailable=recovering_to_d6)
        if recovering_to_d6:
            comfy_idle()
        else:
            idle()
        require(run(['systemctl', 'show', 'ai-bridge-analysis.service',
                     '-p', 'ActiveState', '--value']) == 'inactive')
        mutating = True
        run(['systemctl', 'stop', 'ai-gateway.service', 'ai-bridge.service'])
        temporary = CURRENT.with_name('.stage-e-current-' + uuid4().hex)
        temporary.symlink_to(target)
        os.replace(temporary, CURRENT)
        run(['systemctl', 'start', 'ai-gateway.service', 'ai-bridge.service'])
        for _ in range(30):
            try:
                runtime(target, cfg, baseline)
                healthy = True
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError('runtime failed')
    finally:
        # After a partial mutation keep ingress closed so the supervisor's
        # emergency rollback can restore the verified release first.
        if healthy or not mutating:
            resume_ingress(baseline)


def api_smoke(cfg):
    # A brand new client knows only the Platform API base URL and logical model.
    token = Path(cfg['api_token_file']).read_text().strip() if cfg['api_token_file'] else None
    base = GATEWAY + '/api/v1'
    require(fetch(base + '/health', token=token)['readiness'] is True)
    require(fetch(base + '/models', token=token)['models'][0]['logical_id'] == 'reasoning-main')
    require(fetch(base + '/systems', token=token)['systems'])
    request_id = 'req_' + uuid4().hex
    result = fetch(base + '/ai', {'capability': 'reasoning',
                   'context': {'request_id': request_id, 'domain': 'shared'},
                   'messages': [{'role': 'user', 'content': 'Return the word OK.'}]}, token)
    require(result['request_id'] == request_id and result['state'] == 'completed'
            and result['execution']['model'] == 'reasoning-main'
            and result.get('finish_reason') == 'stop')
    require(type(result['usage']['input_tokens']) is int and result['usage']['input_tokens'] > 0)
    require(type(result['usage']['output_tokens']) is int and result['usage']['output_tokens'] > 0)
    job = fetch(base + '/jobs/' + result['job_id'], token=token)['job']
    require(job['state'] == 'completed' and job['request_id'] == request_id)
    require(any(j['job_id'] == job['job_id'] for j in fetch(base + '/jobs', token=token)['jobs']))


def wvc_smoke():
    # Keep D.6 compatibility semantics and prove real inference. Resolve model
    # internally from the installed runtime config, never from a new API client.
    command = [CURRENT / 'services/ai-bridge/.venv/bin/python', '-c',
               'from ai_bridge.settings import Settings; print(Settings(_env_file="/etc/ai-bridge/ai-bridge.env").ollama_model)']
    model = run(command)
    result, headers = fetch(GATEWAY + '/clients/ventilation/api/chat', {
        'model': model, 'messages': [{'role': 'user', 'content': 'Return OK.'}],
        'stream': False, 'think': False}, with_headers=True)
    require(result.get('done') is True and result.get('prompt_eval_count', 0) > 0)
    status = fetch(GATEWAY + '/status')
    job = next(j for j in status['recent_jobs'] if j['job_id'] == headers['X-AI-Job-Id'])
    require(job['request_id'] == headers['X-AI-Request-Id'])
    require(job['domain'] == 'wvc' and job['priority_class'] == 'infrastructure'
            and job['state'] == 'completed')


def smoke(phase, target, cfg, baseline, state):
    runtime(target, cfg, baseline)
    before = [identity(unit) for unit in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')]
    challenge = uuid4().hex
    write_once(state / (phase + '-started.json'), {'challenge': challenge, 'release_id': target.name})
    if target != D6:
        api_smoke(cfg)
    wvc_smoke()
    hermes_state()
    hermes_oneshot_smoke()
    require(clients() == baseline['clients'])
    media_preflight()
    real_media_smoke()
    runtime(target, cfg, baseline)
    require(before == [identity(unit) for unit in ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')])
    write_once(state / (phase + '.json'), {'schema_version': 1, 'release_id': target.name,
               'challenge': challenge, 'checks': {key: True for key in (*CHECKS, 'wvc', 'health')},
               'platform_api': target != D6, 'time': int(time.time()), 'services': before})


def main(step):
    cfg = config()
    sha = git_run(['rev-parse', 'HEAD'])
    require(re.fullmatch('[0-9a-f]{40}', sha) is not None)
    candidate = Path('/opt/ai-platform/releases') / ('stage-e-' + sha[:12])
    state = STATE / sha
    if step == '00_preflight':
        preflight(cfg)  # Read-only, including no state directory or lock writes.
        return
    require(os.geteuid() == 0)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'executor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if step == '10_build_install':
            preflight(cfg)
            require(not state.exists() and not candidate.exists())
            require(not git_run(['status', '--porcelain']))
            state.mkdir(mode=0o700)
            baseline = {'rollback': D6.name, 'rollback_sha': D6_SHA, 'candidate': candidate.name,
                        'source_sha': sha, 'clients': clients(), 'comfy': identity('comfyui.service'),
                        'hermes_active': user_systemctl(['show', 'hermes-gateway.service',
                                                        '-p', 'ActiveState', '--value']),
                        'analysis_timer_active': run(['systemctl', 'show', 'ai-bridge-analysis.timer',
                                                      '-p', 'ActiveState', '--value']),
                        'rollback_checksums': digest(D6 / 'metadata/SHA256SUMS')}
            write_once(state / 'baseline.json', baseline)
            run(
                ['bash', ROOT / 'deploy/stage-e/build_release.sh', candidate, candidate.name],
                timeout=1800,
                cwd=ROOT,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'STAGE_E_SOURCE_SHA': sha},
            )
            require(verify_release(candidate, 'e')['source_git_sha'] == sha)
            # Matched D.6 clients must remain byte-identical in the new package.
            for source in CLIENTS.values():
                for service in ('ai-bridge', 'ai-gateway'):
                    require((candidate / 'services' / service / source).read_bytes()
                            == (D6 / 'services/ai-bridge' / source).read_bytes())
            runtime(D6, cfg, baseline)
            write_once(state / 'installed.json', {'candidate': candidate.name, 'source_sha': sha,
                       'checksums': digest(candidate / 'metadata/SHA256SUMS')})
            return
        baseline = read(state / 'baseline.json')
        require(baseline['source_sha'] == sha and baseline['rollback_sha'] == D6_SHA
                and baseline['candidate'] == candidate.name and baseline['rollback'] == D6.name)
        installed = read(state / 'installed.json')
        require(installed['source_sha'] == sha)
        require(digest(D6 / 'metadata/SHA256SUMS') == baseline['rollback_checksums'])
        require(digest(candidate / 'metadata/SHA256SUMS') == installed['checksums'])
        if step in ('20_cutover', '60_reactivate'):
            if step == '60_reactivate':
                require((state / 'rollback-smoke.json').is_file())
            else:
                require(not (state / 'rollback.json').exists())
            require(not (state / (step + '.json')).exists())
            switch(candidate, D6, cfg, baseline)
            if not (state / (step + '.json')).exists():
                write_once(state / (step + '.json'), {'release_id': candidate.name})
        elif step == '40_rollback':
            # Can run after a partial cutover even without a cutover PASS marker.
            switch(D6, candidate, cfg, baseline)
            if not (state / 'rollback.json').exists():
                write_once(state / 'rollback.json', {'release_id': D6.name})
        elif step in ('30_smoke', '50_rollback_smoke', '70_reactivate_smoke'):
            phase, target, prior = {
                '30_smoke': ('candidate-smoke', candidate, '20_cutover'),
                '50_rollback_smoke': ('rollback-smoke', D6, 'rollback'),
                '70_reactivate_smoke': ('final-smoke', candidate, '60_reactivate'),
            }[step]
            require((state / (prior + '.json')).is_file())
            smoke(phase, target, cfg, baseline, state)
        elif step == '90_finalize':
            require(verify_release(candidate, 'e')['source_git_sha'] == sha)
            runtime(candidate, cfg, baseline)
            evidence = [read(state / (phase + '.json')) for phase in
                        ('candidate-smoke', 'rollback-smoke', 'final-smoke')]
            require([e['release_id'] for e in evidence] == [candidate.name, D6.name, candidate.name])
            require(len({e['challenge'] for e in evidence}) == 3)
            require([e['platform_api'] for e in evidence] == [True, False, True])
            require(all(set(e['checks']) == set((*CHECKS, 'wvc', 'health'))
                        and all(v is True for v in e['checks'].values()) for e in evidence))
            require(evidence[0]['time'] <= evidence[1]['time'] <= evidence[2]['time'])
            require(evidence[2]['services'] == [identity(unit) for unit in
                    ('ai-gateway.service', 'ai-bridge.service', 'comfyui.service')])
            report = ('# Stage E production gate\n\nProduction validation: PASS\n\n'
                      f'Source: `{sha}`\n\nCandidate: `{candidate.name}`\n\n'
                      f'Rollback: `{D6.name}` with unchanged matched D.6 clients.\n\n'
                      'Candidate smoke, rollback smoke, final smoke: PASS.\n\n'
                      'Fresh Stage E gates: Platform API inference/jobs/models/systems/health, '
                      'WVC inference, Hermes messaging connectivity, matched-client byte integrity '
                      'and media preflight: PASS.\n\n'
                      'Fresh D.6 Telegram multiuser, /foto, /wideo, Discord and real-media evidence '
                      'is retained as the unchanged compatibility baseline; Stage E does not claim '
                      'a synthetic fresh user-path PASS for those flows.\n\n'
                      'D.0/D.6 and recovery snapshots retained; no cleanup or client mutation.\n')
            path = ROOT / 'docs/reports/AI_PLATFORM_STAGE_E_PRODUCTION_GATE.md'
            if path.exists():
                require(path.read_text() == report)
            else:
                with path.open('x') as stream:
                    stream.write(report)
        else:
            raise ValueError('unknown step')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except BaseException:
        # No exception text: it may contain URLs, prompts, tokens or worker logs.
        print('FAIL: Stage E production gate stopped; no PASS recorded for this step', file=sys.stderr)
        sys.exit(1)
    print('PASS: Stage E ' + sys.argv[1])
