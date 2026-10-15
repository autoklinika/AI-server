"""CPU-only evidence and refusal tests for the existing Stage O recovery rollback."""
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = "5e104ea69d0bfa342209acdc8dc88145b34ae72e"
MODULE = Path(__file__).resolve().parents[1] / "deploy/stage-o/autopilot/gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("stage_o_reboot_gate_dev", MODULE)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


@pytest.fixture
def setup(monkeypatch, tmp_path):
    g = load_gate()
    releases = tmp_path / "releases"
    releases.mkdir()
    active = releases / ("stage-o-" + SOURCE[:12])
    rollback = releases / "stage-o-older"
    active.mkdir()
    rollback.mkdir()
    (active / "metadata").mkdir()
    (active / "metadata/SHA256SUMS").write_text("original-manifest")
    link = tmp_path / "current"
    link.symlink_to(active)
    state_root = tmp_path / "state"
    state = state_root / SOURCE
    state.mkdir(parents=True)
    baseline = {
        "source_sha": SOURCE,
        "candidate": active.name,
        "schema": g.TARGET_REVISION,
        "rollback": rollback.name,
        "rollback_sha": "a" * 40,
        "rollback_stage": "O",
        "clients": {"/client": ["hash", 0o755, 0, 0]},
        "comfy": ["11", "historical-invocation"],
        "hermes_active": "active",
        "analysis_timer_active": "active",
        "preload_unit": "unchanged",
        "rollback_checksums": "baseline-digest",
    }
    installed = {"source_sha": SOURCE, "candidate": active.name, "checksums": "installed-digest"}
    (state / "baseline.json").write_text(json.dumps(baseline))
    (state / "installed.json").write_text(json.dumps(installed))
    (state / "20_cutover.json").write_text('{"release_id":"old"}')
    original_baseline = (state / "baseline.json").read_bytes()
    monkeypatch.setattr(g, "STATE", state_root)
    monkeypatch.setattr(g.e, "CURRENT", link)
    monkeypatch.setattr(g, "verify_release", lambda path: {"stage": "O", "source_git_sha": SOURCE})
    monkeypatch.setattr(g, "baseline_release", lambda original: (rollback, {"stage": "O"}))
    monkeypatch.setattr(g.e, "digest", lambda path: "installed-digest")
    calls = []
    monkeypatch.setattr(g.e, "comfy_idle", lambda: calls.append("idle"))
    monkeypatch.setattr(g.e, "identity", lambda unit: ["22", "current-invocation"])
    original_switch = g.switch
    monkeypatch.setattr(g, "_unpatched_switch_test_only", original_switch, raising=False)
    monkeypatch.setattr(g, "switch", lambda target, candidate, cfg, current: calls.append(
        ("switch", target, candidate, current)
    ))
    return g, state, active, rollback, calls, original_baseline


def test_recovery_uses_fresh_comfy_identity_without_mutating_history(setup):
    g, state, active, rollback, calls, history = setup
    g.recover_active_unaccepted_candidate({})
    assert calls[0] == "idle"
    assert calls[1][0] == "switch"
    _, target, candidate, current = calls[1]
    assert target == rollback and candidate == active
    assert current["comfy"] == ["22", "current-invocation"]
    assert current["clients"] == json.loads(history)["clients"]
    assert current["preload_unit"] == "unchanged"
    assert (state / "baseline.json").read_bytes() == history
    assert json.loads((state / "rollback.json").read_text()) == {
        "release_id": rollback.name, "recovery": True
    }
    assert not (state / "accepted.json").exists()


def test_existing_rollback_record_not_overwritten(setup):
    g, state, active, rollback, calls, history = setup
    initial = b'{"release_id":"stage-o-older"}'
    (state / "rollback.json").write_bytes(initial)
    g.recover_active_unaccepted_candidate({})
    assert (state / "rollback.json").read_bytes() == initial
    assert (state / "baseline.json").read_bytes() == history


@pytest.mark.parametrize("fault", ["unavailable_comfy", "busy_comfy", "wrong_sha",
                                    "wrong_candidate", "missing_cutover", "already_accepted",
                                    "bad_manifest", "missing_baseline", "wrong_schema"])
def test_invalid_evidence_fails_before_switch(setup, monkeypatch, fault):
    g, state, active, rollback, calls, history = setup
    if fault == "unavailable_comfy":
        def denied(unit):
            raise RuntimeError("comfyui not active")
        monkeypatch.setattr(g.e, "identity", denied)
    elif fault == "busy_comfy":
        def busy():
            raise RuntimeError("ComfyUI queue not idle")
        monkeypatch.setattr(g.e, "comfy_idle", busy)
    elif fault == "wrong_sha":
        data = json.loads((state / "baseline.json").read_text())
        data["source_sha"] = "f" * 40
        (state / "baseline.json").write_text(json.dumps(data))
    elif fault == "wrong_candidate":
        data = json.loads((state / "installed.json").read_text())
        data["candidate"] = "stage-o-wrong"
        (state / "installed.json").write_text(json.dumps(data))
    elif fault == "missing_cutover":
        (state / "20_cutover.json").unlink()
    elif fault == "already_accepted":
        (state / "accepted.json").write_text('{"status":"PASS"}')
    elif fault == "bad_manifest":
        monkeypatch.setattr(g.e, "digest", lambda path: "wrong")
    elif fault == "missing_baseline":
        (state / "baseline.json").unlink()
    else:
        data = json.loads((state / "baseline.json").read_text())
        data["schema"] = "wrong"
        (state / "baseline.json").write_text(json.dumps(data))
    with pytest.raises((RuntimeError, OSError, KeyError, ValueError)):
        g.recover_active_unaccepted_candidate({})
    assert not any(isinstance(item, tuple) and item[0] == "switch" for item in calls)


def test_failed_switch_does_not_report_success_or_write_rollback(setup, monkeypatch):
    g, state, active, rollback, calls, history = setup
    def fail_switch(target, candidate, cfg, baseline):
        assert baseline["comfy"] == ["22", "current-invocation"]
        raise RuntimeError("runtime drift after quiescence")
    monkeypatch.setattr(g, "switch", fail_switch)
    with pytest.raises(RuntimeError, match="runtime drift"):
        g.recover_active_unaccepted_candidate({})
    assert not (state / "rollback.json").exists()
    assert (state / "baseline.json").read_bytes() == history


def test_normal_runtime_contract_remains_strict():
    text = (MODULE.parents[2] / "stage-e/autopilot/gate.py").read_text()
    assert "require(identity('comfyui.service') == baseline['comfy'])" in text


def _patch_switch_runtime(monkeypatch, setup, *, drift_after_quiesce=False):
    g, state, active, rollback, calls, _ = setup
    current_comfy = ["22", "current-invocation"]
    monkeypatch.setattr(g.e, "identity", lambda unit: current_comfy.copy())
    monkeypatch.setattr(g, "switch", g._unpatched_switch_test_only)
    monkeypatch.setattr(g.e, "clients", lambda: json.loads((state / "baseline.json").read_text())["clients"])
    monkeypatch.setattr(g, "schema_version", lambda: g.TARGET_REVISION)
    monkeypatch.setattr(g, "crt_tables", lambda: g.CRT_TABLES)
    monkeypatch.setattr(g, "restore_preload_baseline", lambda b: calls.append("restore_preload"))
    monkeypatch.setattr(g.e, "resume_ingress", lambda b: calls.append("resume"))
    monkeypatch.setattr(g.time, "sleep", lambda _: None)

    def quiesce(b, allow_gateway_unavailable=False):
        calls.append("quiesce")
        assert allow_gateway_unavailable
        if drift_after_quiesce:
            current_comfy[1] = "changed-invocation"

    monkeypatch.setattr(g.e, "quiesce", quiesce)

    def systemctl(args, *unused, **kwargs):
        if args[:2] == ["systemctl", "show"]:
            return "inactive"
        assert args[0] == "systemctl"
        calls.append(tuple(args))
        return ""

    monkeypatch.setattr(g.e, "run", systemctl)

    def set_current(release):
        g.e.CURRENT.unlink()
        g.e.CURRENT.symlink_to(release)
        calls.append("cutover")

    monkeypatch.setattr(g, "atomic_current", set_current)

    def runtime(release, cfg, baseline):
        assert g.e.CURRENT.resolve(strict=True) == release
        assert baseline["clients"] == json.loads((state / "baseline.json").read_text())["clients"]
        g.require(g.e.identity("comfyui.service") == baseline["comfy"])
        calls.append("healthy")

    monkeypatch.setattr(g.e, "runtime", runtime)
    return calls


def test_existing_switch_succeeds_with_stable_post_reboot_comfy(setup, monkeypatch):
    g, state, active, rollback, calls, original = setup
    _patch_switch_runtime(monkeypatch, setup)
    g.recover_active_unaccepted_candidate({})
    assert g.e.CURRENT.resolve() == rollback
    assert calls.count("cutover") == 1
    assert "healthy" in calls and "resume" in calls
    assert (state / "baseline.json").read_bytes() == original
    assert not (state / "accepted.json").exists()


def test_existing_switch_rejects_comfy_restart_during_quiescence(setup, monkeypatch):
    g, state, active, rollback, calls, original = setup
    _patch_switch_runtime(monkeypatch, setup, drift_after_quiesce=True)
    with pytest.raises(RuntimeError, match="runtime failed after switch"):
        g.recover_active_unaccepted_candidate({})
    assert calls.count("cutover") == 1
    assert "healthy" not in calls
    assert "resume" not in calls  # Preserve Stage O fail-closed policy after partial mutation.
    assert not (state / "rollback.json").exists()
    assert (state / "baseline.json").read_bytes() == original
