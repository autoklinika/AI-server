"""Explicit cold-boot diagnostic-to-systemd handoff; never an admission retry."""
import os
from pathlib import Path
import signal
import time
from uuid import uuid4


def recover_if_needed(g):
    e, f, run, require = g.e, g.f, g.run, g.require
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    marker = g.STATE / 'gpu-blocked.json'
    completed = g.STATE / ('cold-recovery-' + boot + '.json')
    if completed.exists() or not marker.exists():
        return
    require(e.read(marker)['boot_id'] != boot)
    require(e.CURRENT.resolve() == g.BASE)
    require(g.verify(g.BASE)['source_git_sha'] == g.BASE_SHA)
    f.require_kernel_clear()
    e.require_hermes_stopped()
    run(['systemctl', 'stop', 'ai-bridge-analysis.timer', 'ai-bridge-analysis.service'])
    f.require_no_media_workers()
    e.comfy_idle()
    state = g.STATE / ('cold-recovery-evidence-' + uuid4().hex)
    state.mkdir(mode=0o700)
    before = e.fetch(e.GATEWAY + '/status')
    e.write_once(state / 'gateway-before.json', before)
    require(before['admission_blocked'] is True)
    require(before['queued_count'] == 0)
    require(before['resource_leases']['lease_count'] == 1)
    require(before['resource_leases']['leases'][0]['source'] == 'gpu-isolation-diagnostic')
    run(['systemctl', 'stop', 'ai-gateway.service'])
    # This handoff is specifically authorized for the recorded diagnostic PID.
    # pidfd pins identity; check its owner, argv and release before signaling.
    proc = Path('/proc/10872')
    if proc.exists():
        fd = os.pidfd_open(10872)
        try:
            require(proc.stat().st_uid == 1000)
            require((proc / 'cwd').resolve() == g.BASE / 'services/ai-gateway')
            require((proc / 'cmdline').read_bytes().split(b'\0') == [
                b'/opt/ai-platform/current/services/ai-gateway/.venv/bin/python',
                b'-m', b'ai_bridge.gateway.main', b''])
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            for _ in range(100):
                if not proc.exists() or ') Z ' in (proc / 'stat').read_text():
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('diagnostic Gateway did not stop')
        finally:
            os.close(fd)
    f.require_no_media_workers()
    f.recover_gpu_quiesced(state)
    f.require_kernel_clear()
    # Archive the manual process's separate default marker as well. It is not
    # the managed marker and must never be silently reused on another launch.
    diagnostic = Path('/home/harrypotter/.local/state/ai-platform/gpu-residency.blocked')
    if diagnostic.exists():
        (state / 'diagnostic-marker').write_bytes(diagnostic.read_bytes())
        diagnostic.unlink()
    run(['systemctl', 'start', 'ai-gateway.service'])
    for attempt in range(60):
        try:
            e.runtime(g.BASE, e.config())
            require(e.fetch(e.GATEWAY + '/status')['gpu_residency']['state'] == 'llm')
            break
        except Exception:
            if attempt == 59:
                raise
            time.sleep(1)
    e.require_hermes_stopped()
    e.write_once(completed, {'boot_id': boot, 'evidence': str(state),
                            'release': str(g.BASE), 'ingress': 'PAUSED'})
