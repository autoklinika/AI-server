"""Hermetyczne obserwacje; żaden test nie korzysta z produkcyjnego transportu."""
import copy
import importlib.util
from pathlib import Path

import pytest
from test_stage_o_recovery_check import documents

PATH = Path(__file__).resolve().parents[1] / 'deploy/stage-o/recover_acceptance_observe.py'
spec = importlib.util.spec_from_file_location('observe_test', PATH)
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)


class Fixture:
    def __init__(self, baseline):
        self.baseline = baseline
        self.boot_id = '11111111-2222-3333-4444-555555555555'
        self.payload = dict(gateway={'status': 'ok'}, bridge={'status': 'ok'},
            control_center={'readiness': True}, jobs=dict(active_count=0, queued_count=0, resource_leases={'lease_count': 0}),
            queue={'queue_running': [], 'queue_pending': []},
            residency={'models': [{'name': o.a.MODEL, 'digest': 'a' * 64}]})

    def get(self, name):
        return copy.deepcopy(self.payload[name])

    def boot(self):
        return self.boot_id

    def file(self, path):
        if path.endswith('ollama-preload.service'):
            return self.baseline['preload_unit'].encode(), []
        return b'', self.baseline['clients'][path]

    def link(self, path):
        if path == o.p.CURRENT:
            return o.p.RELEASE
        return o.p.RELEASE + '/services/' + ('ai-gateway' if '/123/' in path else 'ai-bridge')

    def unit(self, name):
        return dict(ActiveState='active', MainPID='123' if name == o.UNITS[0] else '124',
            InvocationID='b' * 32, NeedDaemonReload='no',
            WorkingDirectory=o.p.CURRENT + '/services/' + name[:-8])


@pytest.fixture
def fixture(documents, monkeypatch):
    monkeypatch.setattr(o.ReadOnly, 'get', lambda *_: pytest.fail('real HTTP'))
    monkeypatch.setattr(o.ReadOnly, 'file', lambda *_: pytest.fail('real file'))
    monkeypatch.setattr(o.subprocess, 'run', lambda *_a, **_k: pytest.fail('real command'))
    return Fixture(copy.deepcopy(documents['baseline'])), {'baseline': (documents['baseline'],)}


def test_consistent(fixture):
    io, records = fixture
    result = o.observe(io, records)
    assert result['model']['name'] == o.a.MODEL
    assert result['units']['comfyui.service']['MainPID'] != records['baseline'][0]['comfy'][0]


@pytest.mark.parametrize('fault', ['gateway', 'bridge', 'control_center', 'lease', 'job', 'queue', 'model', 'digest', 'residency', 'clients', 'preload', 'unit', 'cwd', 'current', 'boot', 'generation', 'unknown', 'denied'])
def test_reject(fixture, fault):
    io, records = fixture
    if fault in ('gateway', 'bridge'):
        io.payload[fault]['status'] = 'bad'
    elif fault == 'control_center':
        io.payload[fault]['readiness'] = 1
    elif fault == 'lease':
        io.payload['jobs']['resource_leases']['lease_count'] = True
    elif fault == 'job':
        io.payload['jobs']['active_count'] = 1
    elif fault == 'queue':
        io.payload['queue']['queue_pending'] = [1]
    elif fault in ('model', 'digest'):
        io.payload['residency']['models'][0]['name' if fault == 'model' else 'digest'] = 'wrong'
    elif fault == 'residency':
        io.payload['residency']['models'] = []
    elif fault == 'clients':
        next(iter(io.baseline['clients'].values()))[1] ^= 1
    elif fault == 'preload':
        io.baseline['preload_unit'] += 'drift'
    elif fault == 'unit':
        unit = io.unit
        io.unit = lambda name: dict(unit(name), NeedDaemonReload='yes')
    elif fault in ('cwd', 'current'):
        link = io.link
        io.link = lambda path: 'wrong' if (path == o.p.CURRENT) == (fault == 'current') else link(path)
    elif fault == 'boot':
        io.boot_id = 'bad'
    elif fault == 'generation':
        boots = iter([io.boot_id, '22222222-2222-3333-4444-555555555555'])
        io.boot = lambda: next(boots)
    elif fault == 'unknown':
        del io.payload['jobs']['active_count']
    else:
        def denied():
            raise PermissionError('fixture')
        io.boot = denied
    with pytest.raises((ValueError, KeyError, OSError)):
        o.observe(io, records)


@pytest.mark.parametrize('error', [TimeoutError, PermissionError, KeyError, ValueError])
def test_cli_redacts_and_blocks(monkeypatch, capsys, error):
    def fail():
        raise error('secret value from external source')
    monkeypatch.setattr(o, 'production_observe', fail)
    assert o.main(['--observe']) == 2
    output = capsys.readouterr().out
    assert 'secret value from external source' not in output
    assert 'PROD_BLOCKED' in output


def test_no_apply_option():
    with pytest.raises(SystemExit):
        o.main(['--apply'])


@pytest.mark.parametrize('fault', ['none', 'symlink', 'mode', 'owner', 'large'])
def test_safe_file_reader(tmp_path, monkeypatch, fault):
    import os
    path = tmp_path / 'client'
    path.write_bytes(b'client')
    path.chmod(0o600)
    monkeypatch.setattr(o.p, 'directory', lambda _: os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY))
    monkeypatch.setattr(o.p, 'ROOT_UID', os.getuid() + (fault == 'owner'))
    monkeypatch.setattr(o.p, 'ROOT_GID', os.getgid())
    if fault == 'symlink':
        path.unlink()
        path.symlink_to(tmp_path / 'missing')
    elif fault == 'mode':
        path.chmod(0o666)
    elif fault == 'large':
        path.write_bytes(b'x' * (o.LIMIT + 1))
    if fault == 'none':
        assert o.ReadOnly().file(str(path))[0] == b'client'
    else:
        with pytest.raises((ValueError, OSError)):
            o.ReadOnly().file(str(path))


@pytest.mark.parametrize('status,raw', [(302, b'{}'), (200, b'{"a":1,"a":2}'),
    (200, b'{"a":NaN}'), (200, b'x' * (o.LIMIT + 1)), (200, b'not json')])
def test_http_rejects(monkeypatch, status, raw):
    calls = []
    class Connection:
        def __init__(self, host, port, timeout):
            assert host == '127.0.0.1' and port == 11435 and timeout == 2
        def request(self, method, path, headers):
            assert (method, path) == ('GET', '/health')
        def getresponse(self):
            return self
        def read(self, size):
            assert size == o.LIMIT + 1
            return raw
        def close(self):
            calls.append('closed')
    Connection.status = status
    monkeypatch.setattr(o.http.client, 'HTTPConnection', Connection)
    with pytest.raises(ValueError):
        o.ReadOnly().get('gateway')
    assert calls == ['closed']


def test_total_timeout(monkeypatch, capsys):
    import signal
    import time
    def stall():
        signal.setitimer(signal.ITIMER_REAL, .01)
        time.sleep(1)
        pytest.fail('deadline ignored')
    monkeypatch.setattr(o, 'production_observe', stall)
    assert o.main(['--observe']) == 2
    assert 'REJECTED' in capsys.readouterr().out
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize('name,host,port,path', [
    ('gateway', '127.0.0.1', 11435, '/health'),
    ('bridge', '192.168.1.55', 8080, '/health'),
    ('control_center', '192.168.1.55', 8080, '/control/api/v1/health'),
    ('jobs', '127.0.0.1', 11435, '/status'),
])
def test_pinned_endpoint_hosts(monkeypatch, name, host, port, path):
    calls = []
    class Connection:
        status = 200
        def __init__(self, actual_host, actual_port, timeout):
            assert (actual_host, actual_port, timeout) == (host, port, 2)
        def request(self, method, actual_path, headers):
            assert (method, actual_path) == ('GET', path)
        def getresponse(self):
            return self
        def read(self, size):
            assert size == o.LIMIT + 1
            return b'{"status":"ok"}'
        def close(self):
            calls.append('closed')
    monkeypatch.setattr(o.http.client, 'HTTPConnection', Connection)
    assert o.ReadOnly().get(name) == {'status': 'ok'}
    assert calls == ['closed']
