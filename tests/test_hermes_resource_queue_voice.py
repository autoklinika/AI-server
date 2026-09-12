from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hermes_resource_queue_voice_test",
    ROOT / "tools/hermes_resource_queue.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def _queued_then_active_json():
    states = iter(
        [
            {"lease_id": "lease-V", "job_id": 21, "state": "queued"},
            {"lease_id": "lease-V", "job_id": 21, "state": "active"},
        ]
    )

    def fake_json(method, path, payload=None, timeout=5):
        if method == "POST" and path == "/resource/leases":
            return next(states)
        if method == "GET":
            return next(states)
        if method == "DELETE":
            return {"released": True}
        raise AssertionError((method, path))

    return fake_json


def _fast_queue_timing(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_float_env",
        lambda name, default, low, high: (
            0.0 if "NOTICE" in name else (0.001 if "POLL" in name else 30.0)
        ),
    )
    monkeypatch.setattr(mod.ResourceLease, "start_heartbeat", lambda self: None)


def test_voice_callback_follows_real_queue_transition(monkeypatch):
    monkeypatch.setattr(mod, "_json", _queued_then_active_json())
    monkeypatch.setattr(mod, "_notify", lambda *args, **kwargs: None)
    _fast_queue_timing(monkeypatch)
    events = []

    handle = mod.acquire_resource(
        target="discord:456",
        source="discord-chat",
        queue_message="WAIT",
        start_message="START",
        status_callback=events.append,
    )

    assert events == ["queued", "active"]
    handle.release()


def test_immediate_slot_does_not_fire_voice_callback(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_json",
        lambda *args, **kwargs: {
            "lease_id": "lease-I",
            "job_id": 22,
            "state": "active",
            "released": True,
        },
    )
    monkeypatch.setattr(mod.ResourceLease, "start_heartbeat", lambda self: None)
    events = []

    handle = mod.acquire_resource(
        target="discord:456",
        source="discord-chat",
        queue_message="WAIT",
        start_message="START",
        status_callback=events.append,
    )

    assert events == []
    handle.release()


def test_voice_callback_failure_never_aborts_job(monkeypatch):
    monkeypatch.setattr(mod, "_json", _queued_then_active_json())
    monkeypatch.setattr(mod, "_notify", lambda *args, **kwargs: None)
    _fast_queue_timing(monkeypatch)

    def broken_callback(event):
        raise RuntimeError(f"voice unavailable: {event}")

    handle = mod.acquire_resource(
        target="discord:456",
        source="discord-chat",
        queue_message="WAIT",
        start_message="START",
        status_callback=broken_callback,
    )

    assert handle.job_id == 21
    handle.release()
