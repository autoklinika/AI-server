import importlib.util
from pathlib import Path
from urllib.error import HTTPError

import pytest


MODULE_PATH = Path(__file__).parents[1] / "deploy/stage-o/autopilot/gate.py"
SPEC = importlib.util.spec_from_file_location("stage_o_rollback_compat", MODULE_PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(gate)


LEGACY_JAVASCRIPT = 'const API_BASE = "/control/api/v1";\nfunction legacyControlCenter() {}\n'


def _legacy_text_fetch(url: str):
    if url.endswith("/control/assets/app.js"):
        return 200, LEGACY_JAVASCRIPT, {}
    if url.endswith("/control/"):
        return 200, "<html>AI Control Center</html>", {
            "content-security-policy": "default-src 'self'; frame-ancestors 'none'"
        }
    raise AssertionError(url)


def _legacy_fetch(url: str, payload=None):
    if url.endswith("/control/manifest.webmanifest"):
        return {"start_url": "/control/", "display": "standalone"}
    if url.endswith("/control/api/v1/health"):
        return {"readiness": True}
    if url.endswith("/control/api/v1/operations"):
        return {
            "release": {"stage": "O"},
            "storage": [],
            "backup": {},
        }
    if url.endswith("/control/api/v1/apps"):
        return {
            "apps": [
                {"id": "knowledge"},
                {"id": "benchmarks"},
                {"id": "ers"},
            ]
        }
    if url.endswith("/control/api/v1/knowledge/search"):
        return {"results": [{"result_id": "legacy-result"}]}
    if url.endswith("/control/api/v1/ai"):
        raise HTTPError(url, 403, "forbidden", hdrs=None, fp=None)
    raise AssertionError((url, payload))


def test_rollback_smoke_accepts_older_accepted_stage_o_gui(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate, "bridge_base", lambda: "http://bridge")
    monkeypatch.setattr(gate, "text_fetch", _legacy_text_fetch)
    monkeypatch.setattr(gate.e, "fetch", _legacy_fetch)
    monkeypatch.setattr(gate.e, "GATEWAY", "http://gateway")

    evidence = gate.control_center_smoke(require_operations=False)

    assert evidence["status"] == "PASS"
    assert evidence["apps"] == ["knowledge", "benchmarks", "ers"]


def test_candidate_smoke_requires_current_source_viewer_surface(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gate, "bridge_base", lambda: "http://bridge")
    monkeypatch.setattr(gate, "text_fetch", _legacy_text_fetch)
    monkeypatch.setattr(gate.e, "fetch", _legacy_fetch)
    monkeypatch.setattr(gate.e, "GATEWAY", "http://gateway")

    with pytest.raises(RuntimeError, match="gate condition failed"):
        gate.control_center_smoke(require_operations=True)
