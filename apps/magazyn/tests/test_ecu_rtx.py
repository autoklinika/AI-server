"""No-GPU contract tests for on-demand RTX OCR and shared RM admission."""
import base64
import time

import pytest

from magazyn import ecu_rtx
from magazyn.store import Problem


class FakeServices:
    def __init__(self, *, busy_rm=False, resident=None, lease_state="active"):
        self.busy_rm = busy_rm
        self.resident = list(resident or [])
        self.lease_state = lease_state
        self.calls = []
        self.lease_released = False

    def __call__(self, method, url, payload=None, *, timeout=6):
        self.calls.append((method, url, payload))
        if url == ecu_rtx.RM_URL + "/status":
            return {
                "admission_blocked": False, "active_count": int(self.busy_rm),
                "queued_count": 0, "gpu_residency": {"state": "llm"}
            }
        if url == ecu_rtx.RTX_URL + "/api/ps":
            return {"models": [{"name": x} for x in self.resident]}
        if url == ecu_rtx.RM_URL + "/resource/leases" and method == "POST":
            return {"lease_id": "test-lease", "state": self.lease_state}
        if url.endswith("/resource/leases/test-lease") and method == "DELETE":
            self.lease_released = True
            return {"released": True}
        if url.endswith("/resource/leases/test-lease/heartbeat"):
            return {"state": "active"}
        if url == ecu_rtx.RTX_URL + "/api/generate":
            if payload.get("keep_alive") == 0:
                self.resident = [x for x in self.resident if x != ecu_rtx.MODEL]
            else:
                if ecu_rtx.MODEL not in self.resident:
                    self.resident.append(ecu_rtx.MODEL)
            return {"done": True}
        if url == ecu_rtx.RTX_URL + "/api/chat":
            is_warm = payload["options"]["num_predict"] <= 32
            return {"message": {
                "content": "READY" if is_warm else "BOSCH\n0 281 016 738\nHW: H1\nSW: S3"
            }}
        raise AssertionError(f"Unexpected network request: {method} {url}")


def await_phase(session, owner, valid=("ready", "busy", "error")):
    for _ in range(150):
        result = session.status(owner)
        if result["phase"] in valid:
            return result
        time.sleep(0.01)
    raise AssertionError("Activation worker did not reach final stage")


def photo():
    return base64.b64encode(b"\xff\xd8\xff" + b"A" * 100 + b"\xff\xd9").decode()


def test_automatic_warmup_rtx_and_scan_are_rm_gated(monkeypatch):
    services = FakeServices(resident=["bge-m3:latest"])
    monkeypatch.setattr(ecu_rtx, "_json", services)
    monkeypatch.setattr(ecu_rtx, "_gpu", lambda: (14000, 16311))
    session = ecu_rtx.RtxSession(idle_seconds=120)
    first = session.activate(10)
    assert first["phase"] in ("checking", "reserving", "loading", "warming", "ready")
    state = await_phase(session, 10)
    assert state["phase"] == "ready", state
    assert state["ready"]
    assert state["session_id"]
    assert state["progress"] == 100
    assert session.status(11)["phase"] == "busy"

    # A different Magazyn user cannot hijack this reservation.
    with pytest.raises(Problem) as cross_user:
        session.activate(11)
    assert cross_user.value.status == 409

    result = session.scan(10, state["session_id"], photo(),
                          "BOSCH\n0 281 016 738", [])
    assert result["primaryNumber"] == "0281016738"
    assert result["hardware"] == "H1"
    assert result["software"] == "S3"
    assert result["gpu"] == "RTX 5060 Ti"
    assert session.status(10)["phase"] == "ready"
    assert any(m == "POST" and u == ecu_rtx.RM_URL + "/resource/leases"
               for m, u, _ in services.calls)
    assert all(u != ecu_rtx.RM_URL + "/api/chat" for _m, u, _p in services.calls)
    assert services.resident == ["bge-m3:latest", ecu_rtx.MODEL]
    session.deactivate(10, state["session_id"])
    assert services.lease_released
    assert services.resident == ["bge-m3:latest"]
    assert session.status(10)["phase"] == "off"


def test_insufficient_vram_returns_ocr_and_never_reserves(monkeypatch):
    services = FakeServices()
    monkeypatch.setattr(ecu_rtx, "_json", services)
    monkeypatch.setattr(ecu_rtx, "_gpu", lambda: (3000, 16311))
    session = ecu_rtx.RtxSession()
    session.activate(10)
    state = await_phase(session, 10)
    assert state["phase"] == "busy"
    assert "pamięci" in state["message"]
    assert not state["ready"]
    assert not any("/resource/leases" in u for _, u, _ in services.calls)


def test_rm_busy_refuses_without_touching_cuda(monkeypatch):
    services = FakeServices(busy_rm=True)
    monkeypatch.setattr(ecu_rtx, "_json", services)
    monkeypatch.setattr(ecu_rtx, "_gpu",
                        lambda: (_ for _ in ()).throw(AssertionError("No CUDA preflight")))
    session = ecu_rtx.RtxSession()
    session.activate(10)
    state = await_phase(session, 10)
    assert state["phase"] == "busy"
    assert "Resource Manager" in state["message"]
    assert not services.lease_released


def test_rm_queued_lease_released_without_loading_model(monkeypatch):
    services = FakeServices(lease_state="queued")
    monkeypatch.setattr(ecu_rtx, "_json", services)
    monkeypatch.setattr(ecu_rtx, "_gpu", lambda: (15000, 16311))
    session = ecu_rtx.RtxSession()
    session.activate(10)
    state = await_phase(session, 10)
    assert state["phase"] == "busy"
    assert services.lease_released
    assert not any(u == ecu_rtx.RTX_URL + "/api/chat"
                   for _, u, _ in services.calls)


def test_two_existing_models_refuse_new_model(monkeypatch):
    services = FakeServices(resident=["bge-m3:latest", "granite4:1b"])
    monkeypatch.setattr(ecu_rtx, "_json", services)
    monkeypatch.setattr(ecu_rtx, "_gpu", lambda: (14000, 16311))
    session = ecu_rtx.RtxSession()
    session.activate(10)
    state = await_phase(session, 10)
    assert state["phase"] == "busy"
    assert "dwa" in state["message"]
    assert not any(u == ecu_rtx.RTX_URL + "/api/chat"
                   for _, u, _ in services.calls)


def test_scan_requires_active_user_and_session(monkeypatch):
    services = FakeServices()
    monkeypatch.setattr(ecu_rtx, "_json", services)
    monkeypatch.setattr(ecu_rtx, "_gpu", lambda: (14000, 16311))
    session = ecu_rtx.RtxSession()
    session.activate(10)
    state = await_phase(session, 10)
    with pytest.raises(Problem) as wrong:
        session.scan(11, state["session_id"], photo(), "", [])
    assert wrong.value.status == 409
    with pytest.raises(Problem) as missing:
        session.scan(10, "wrong-session-id", photo(), "", [])
    assert missing.value.status == 409
    session.deactivate(10, state["session_id"])
    with pytest.raises(Problem) as off:
        session.scan(10, state["session_id"], photo(), "", [])
    assert off.value.status == 409
