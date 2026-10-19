"""Offline-only regressions for manual Ollama/ComfyUI transition smoke.

No service starts, hardware access, networking, or root operations.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "tools/rm_engine_transition_smoke_dev.py"
spec = importlib.util.spec_from_file_location("rm_engine_transition_smoke_dev", SOURCE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_idle_checker_requires_all_services_inactive(monkeypatch):
    called = []
    def fake_run(argv, **kwargs):
        called.append(argv[-1])
        return SimpleNamespace(stdout="inactive\n", returncode=3)
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)
    assert smoke.verify_offline() is True
    assert set(called) == set(smoke.SERVICES)


def test_active_or_missing_service_fails_closed(monkeypatch):
    monkeypatch.setattr(smoke.subprocess, "run", lambda argv, **kwargs:
        SimpleNamespace(stdout="active\n", returncode=0))
    with pytest.raises(RuntimeError, match="not inactive"):
        smoke.verify_offline()


def test_gpu_idle_refuses_owners(monkeypatch):
    monkeypatch.setattr(smoke, "verify_offline", lambda: True)
    monkeypatch.setattr(smoke, "gpu_clients", lambda: {"kfd": ("200",), "fuser": ()})
    with pytest.raises(RuntimeError, match="GPU has visible owners"):
        smoke.require_idle()


def test_three_consecutive_empty_samples_required(monkeypatch):
    samples = iter((
        {"kfd": ("11",), "fuser": ()},
        {"kfd": (), "fuser": ()},
        {"kfd": ("11",), "fuser": ()},
        {"kfd": (), "fuser": ()},
        {"kfd": (), "fuser": ()},
        {"kfd": (), "fuser": ()},
    ))
    monkeypatch.setattr(smoke, "gpu_clients", lambda: next(samples))
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    assert len(smoke.observe_empty_repeated()) == 6


def test_never_accepts_persistent_gpu_owner(monkeypatch):
    monkeypatch.setattr(smoke, "gpu_clients", lambda: {"kfd": (), "fuser": ("12",)})
    monkeypatch.setattr(smoke.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="remained occupied"):
        smoke.observe_empty_repeated()


def test_validates_remote_gpu_inventory_exit_codes(monkeypatch, tmp_path):
    (tmp_path / "proc").mkdir()
    monkeypatch.setattr(smoke.Path, "iterdir", lambda _: [])
    monkeypatch.setattr(smoke.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=2, stdout="", stderr="denied"))
    with pytest.raises(RuntimeError, match="unavailable"):
        smoke.gpu_clients()


def test_requires_known_engine_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "LOGROOT", tmp_path)
    monkeypatch.setattr(smoke, "require_idle", lambda: {"kfd": (), "fuser": ()})
    report = smoke.run("unknown", "test-unsupported")
    assert report["status"] == "DIRTY"
    assert report["gpu_reuse_safe"] == "NOT_VERIFIED"
    assert "error" in report
