from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hermes_resource_queue_test",
    ROOT / "tools/hermes_resource_queue.py",
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def test_should_manage_only_local_gateway():
    assert mod.should_manage_base_url("http://127.0.0.1:11435/v1")
    assert mod.should_manage_base_url("http://localhost:11435/clients/hermes/v1")
    assert not mod.should_manage_base_url("http://127.0.0.1:11434/v1")
    assert not mod.should_manage_base_url("https://example.com:11435/v1")


def test_notification_targets_are_limited_to_telegram_and_discord():
    assert mod._notification_platform("telegram:123") == "telegram"
    assert mod._notification_platform("discord:456") == "discord"
    assert mod._notification_platform("discord:456:789") == "discord"
    assert mod._notification_platform("slack:C01") is None
    assert mod._notification_platform("discord") is None
    assert mod._notification_platform(None) is None


def test_discord_notification_uses_hermes_send(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(mod, "_hermes_bin", lambda: "/fake/hermes")
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or Result(),
    )

    mod._notify("discord:456", "WAIT")
    assert calls[0][0] == [
        "/fake/hermes",
        "send",
        "--to",
        "discord:456",
        "WAIT",
    ]


def test_acquire_notifies_only_after_real_queue_for_discord(monkeypatch):
    states = iter(
        [
            {"lease_id": "lease-A", "job_id": 7, "state": "queued"},
            {"lease_id": "lease-A", "job_id": 7, "state": "active"},
        ]
    )
    notices = []

    def fake_json(method, path, payload=None, timeout=5):
        if method == "POST" and path == "/resource/leases":
            return next(states)
        if method == "GET":
            return next(states)
        if method == "DELETE":
            return {"released": True}
        if path.endswith("/heartbeat"):
            return {"state": "queued"}
        raise AssertionError((method, path))

    monkeypatch.setattr(mod, "_json", fake_json)
    monkeypatch.setattr(
        mod,
        "_notify",
        lambda target, message: notices.append((target, message)),
    )
    monkeypatch.setattr(
        mod,
        "_float_env",
        lambda name, default, low, high: (
            0.0 if "NOTICE" in name else (0.001 if "POLL" in name else 30.0)
        ),
    )
    monkeypatch.setattr(mod.ResourceLease, "start_heartbeat", lambda self: None)

    handle = mod.acquire_resource(
        target="discord:456",
        source="discord-chat",
        queue_message="WAIT",
        start_message="START",
    )
    assert notices == [
        ("discord:456", "WAIT"),
        ("discord:456", "START"),
    ]
    handle.release()


def test_immediate_slot_sends_no_queue_noise(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_json",
        lambda *args, **kwargs: {
            "lease_id": "lease-B",
            "job_id": 8,
            "state": "active",
            "released": True,
        },
    )
    monkeypatch.setattr(mod.ResourceLease, "start_heartbeat", lambda self: None)
    notices = []
    monkeypatch.setattr(mod, "_notify", lambda target, message: notices.append(message))

    handle = mod.acquire_resource(
        target="discord:456",
        source="discord-chat",
        queue_message="WAIT",
        start_message="START",
    )
    assert notices == []
    handle.release()


def test_notification_failure_does_not_abort_queued_job(monkeypatch):
    states = iter(
        [
            {"lease_id": "lease-D", "job_id": 10, "state": "queued"},
            {"lease_id": "lease-D", "job_id": 10, "state": "active"},
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

    monkeypatch.setattr(mod, "_json", fake_json)
    monkeypatch.setattr(
        mod,
        "_notify",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("discord down")),
    )
    monkeypatch.setattr(
        mod,
        "_float_env",
        lambda name, default, low, high: (
            0.0 if "NOTICE" in name else (0.001 if "POLL" in name else 30.0)
        ),
    )
    monkeypatch.setattr(mod.ResourceLease, "start_heartbeat", lambda self: None)

    handle = mod.acquire_resource(
        target="discord:456",
        source="discord-chat",
        queue_message="WAIT",
        start_message="START",
    )
    assert handle.job_id == 10
    handle.release()


def test_unsupported_target_never_notifies(monkeypatch):
    calls = []
    monkeypatch.setattr(mod, "_hermes_bin", lambda: calls.append("bin") or "/fake/hermes")
    mod._notify("slack:C01", "WAIT")
    assert calls == []
