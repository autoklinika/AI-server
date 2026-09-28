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

def test_rollback_metadata_uses_legacy_compatible_validator(monkeypatch, tmp_path):
    release = tmp_path / "stage-o-legacy"
    release.mkdir()
    (release / "RELEASE").write_text(
        "stage=O\nsource_git_sha=" + ("a" * 40) + "\n",
        encoding="utf-8",
    )

    calls = []

    class Validator:
        @staticmethod
        def validate_rollback_compatible(path):
            calls.append(Path(path))

    monkeypatch.setattr(gate.e, "load_module", lambda *args, **kwargs: Validator)
    monkeypatch.setattr(
        gate,
        "_original_verify",
        lambda *args, **kwargs: pytest.fail(
            "legacy rollback baseline must not use strict current validator"
        ),
    )

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "validate_rollback_readiness",
        SimpleNamespace(verify_checksums=lambda path: None),
    )

    stamp = gate.verify_release(release, rollback_compatible=True)

    assert stamp["stage"] == "O"
    assert stamp["source_git_sha"] == "a" * 40
    assert calls == [release]


def test_candidate_metadata_remains_strict(monkeypatch, tmp_path):
    release = tmp_path / "stage-o-current"
    release.mkdir()
    (release / "RELEASE").write_text(
        "stage=O\nsource_git_sha=" + ("b" * 40) + "\n",
        encoding="utf-8",
    )

    calls = []

    def strict(path, stage):
        calls.append((Path(path), stage))
        raise ValueError("RELEASE contract mismatch: technical_conversation_contract_version")

    monkeypatch.setattr(gate, "_original_verify", strict)

    with pytest.raises(
        ValueError,
        match="technical_conversation_contract_version",
    ):
        gate.verify_release(release)

    assert calls == [(release, "o")]


def test_candidate_benchmark_contract_smoke_requires_raw_and_reranked_search(monkeypatch):
    calls = []

    def fetch(url, payload=None):
        calls.append((url, payload))
        if url.endswith("/api/v1/benchmarks"):
            return {
                "suites": [
                    {"suite_id": "automotive-reasoning", "status": "foundation", "case_count": 58, "run_count": 0},
                    {"suite_id": "decision-models", "status": "foundation", "case_count": 51, "run_count": 0},
                    {"suite_id": "rag-knowledge", "status": "foundation", "case_count": 61, "run_count": 0},
                ]
            }
        if url.endswith("/api/v1/knowledge/search"):
            assert payload["rerank"] in (False, True)
            return {"results": [{"source": {"uri": "github://ers/component"}}]}
        raise AssertionError((url, payload))

    monkeypatch.setattr(gate.e, "GATEWAY", "http://gateway")
    monkeypatch.setattr(gate.e, "fetch", fetch)

    evidence = gate.benchmark_contract_smoke()

    assert evidence["status"] == "PASS"
    search_calls = [payload for url, payload in calls if url.endswith("/knowledge/search")]
    assert [payload["rerank"] for payload in search_calls] == [False, True]
