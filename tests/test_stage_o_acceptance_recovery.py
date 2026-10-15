"""Offline regression of existing gates; no recovery acceptance is implemented."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = "5e104ea69d0bfa342209acdc8dc88145b34ae72e"


def load(relative):
    spec = importlib.util.spec_from_file_location("recovery_test_module", ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def transaction(monkeypatch, tmp_path):
    g = load("deploy/stage-o/autopilot/gate.py")
    # Every external boundary is replaced; unexpected commands/HTTP fail the test.
    monkeypatch.setattr(g.e, "run", lambda *a, **k: pytest.fail("external command"))
    monkeypatch.setattr(g.e, "fetch", lambda *a, **k: pytest.fail("external HTTP"))
    monkeypatch.setattr(g.e, "config", lambda: {})
    monkeypatch.setattr(g.e, "git_run", lambda args: SHA)
    monkeypatch.setattr(g.os, "geteuid", lambda: 0)
    candidate = tmp_path / ("stage-o-" + SHA[:12])
    candidate.mkdir()
    (candidate / "metadata").mkdir()
    (candidate / "metadata/SHA256SUMS").write_text("historical checksum list\n")
    state = tmp_path / "state" / SHA
    state.mkdir(parents=True)
    current = tmp_path / "current"
    current.symlink_to(candidate)
    monkeypatch.setattr(g, "STATE", state.parent)
    monkeypatch.setattr(g.e, "CURRENT", current)
    monkeypatch.setattr(g, "candidate_identity", lambda sha: candidate)
    monkeypatch.setattr(g, "baseline_release", lambda baseline: (tmp_path / "rollback", {}))
    monkeypatch.setattr(g, "schema_version", lambda: g.TARGET_REVISION)
    monkeypatch.setattr(g, "crt_tables", lambda: g.CRT_TABLES)
    baseline = {"source_sha": SHA, "schema": g.TARGET_REVISION,
                "clients": {}, "comfy": ["123", "old-invocation"]}
    installed = {"source_sha": SHA, "checksums": g.e.digest(candidate / "metadata/SHA256SUMS")}
    for name, value in (("baseline", baseline), ("installed", installed),
                        ("final-smoke", {"release_id": candidate.name})):
        (state / (name + ".json")).write_text(json.dumps(value))
    return g, candidate, state, baseline


@pytest.mark.parametrize("identity", [["456", "new-boot-invocation"],
                                      ["123", "new-boot-invocation"],
                                      ["456", "old-invocation"]])
def test_finalize_rejects_changed_comfy_identity(transaction, monkeypatch, tmp_path, identity):
    g, candidate, state, baseline = transaction
    original = (state / "baseline.json").read_bytes()
    # Exercise the real Stage E runtime check, including the identity comparison.
    for service in ("ai-gateway", "ai-bridge"):
        (candidate / "services" / service).mkdir(parents=True)
    proc_paths = {"/proc/11/cwd": candidate / "services/ai-gateway",
                  "/proc/12/cwd": candidate / "services/ai-bridge"}
    monkeypatch.setattr(g.e, "Path", lambda p: proc_paths.get(str(p), Path(p)))
    monkeypatch.setattr(g.e, "identity", lambda unit: identity if unit == "comfyui.service"
                        else ["11" if unit == "ai-gateway.service" else "12", "current"])
    monkeypatch.setattr(g.e, "run", lambda args: "/opt/ai-platform/current/services/" + args[2].removesuffix(".service"))
    monkeypatch.setattr(g.e, "bridge_health_url", lambda: "offline://health")
    monkeypatch.setattr(g.e, "fetch", lambda url: {"status": "ok"})
    monkeypatch.setattr(g.e, "idle", lambda: None)
    monkeypatch.setattr(g.e, "clients", lambda: {})
    with pytest.raises(RuntimeError, match="gate condition failed"):
        g.main("90_finalize")
    assert not (state / "accepted.json").exists()
    assert (state / "baseline.json").read_bytes() == original


@pytest.mark.parametrize("fault", ["missing_smoke", "source", "checksums", "symlink"])
def test_finalize_rejects_broken_transaction(transaction, monkeypatch, tmp_path, fault):
    g, candidate, state, baseline = transaction
    monkeypatch.setattr(g.e, "runtime", lambda *a: pytest.fail("must reject before runtime"))
    if fault == "missing_smoke":
        (state / "final-smoke.json").unlink()
    elif fault == "source":
        baseline["source_sha"] = "a" * 40
        (state / "baseline.json").write_text(json.dumps(baseline))
    elif fault == "checksums":
        (candidate / "metadata/SHA256SUMS").write_text("substituted\n")
    else:
        g.e.CURRENT.unlink()
        g.e.CURRENT.symlink_to(tmp_path)
    with pytest.raises(RuntimeError, match="gate condition failed"):
        g.main("90_finalize")
    assert not (state / "accepted.json").exists()


def test_preflight_rejects_unaccepted_current(transaction, monkeypatch):
    g, candidate, state, _ = transaction
    monkeypatch.setattr(g, "verify_release", lambda *a, **k: {"stage": "O", "source_git_sha": SHA})
    monkeypatch.setattr(g, "schema_version", lambda: pytest.fail("must reject before runtime"))
    with pytest.raises(FileNotFoundError):
        g.preflight({})
    assert not (state / "accepted.json").exists()


@pytest.fixture
def metadata(tmp_path):
    validator = load("deploy/stage-o/validate_release_metadata.py")
    base = validator.base
    stamp = {**validator.STAGE_O_VERSIONS, "release_id": "stage-o-" + SHA[:12],
             "source_git_sha": SHA, "provider_model_config_version": "1",
             "ai_bridge_git_sha": SHA, "ai_gateway_git_sha": SHA}
    release = {"id": stamp["release_id"], "source_git_sha": SHA,
               "provider_model_config_version": "1", "contract_versions": {}, "schema_versions": {}}
    for key, value in validator.STAGE_O_VERSIONS.items():
        if key.endswith("_contract_version"):
            release["contract_versions"][key.removesuffix("_contract_version")] = value
        elif key == "provider_registry_schema_version":
            release["schema_versions"]["provider_registry"] = value
        else:
            release[key] = value
    release["contract_versions"].update(dict.fromkeys(base.PROVIDERS, "1"))

    def yaml(mapping, level=0):
        return "".join(" " * level + key + ":" + ("\n" + yaml(value, level + 2)
                       if isinstance(value, dict) else " " + value + "\n") for key, value in mapping.items())

    (tmp_path / "metadata").mkdir()
    (tmp_path / "RELEASE").write_text("".join(f"{k}={v}\n" for k, v in stamp.items()))
    manifest = tmp_path / "metadata/release-manifest.yaml"
    manifest.write_text(yaml({"release": release, "ai_bridge": {"source_git_sha": SHA},
                              "ai_gateway": {"source_git_sha": SHA}}))
    # Test the real shared metadata/checksum validators without building any runtime.
    base.validate(tmp_path)
    checksums = "".join(hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() + "  " + name + "\n"
                        for name in ("RELEASE", "metadata/release-manifest.yaml"))
    (tmp_path / "metadata/SHA256SUMS").write_text(checksums)
    return base, tmp_path, manifest


def test_metadata_rejects_inconsistent_source(metadata):
    base, root, manifest = metadata
    manifest.write_text(manifest.read_text().replace(SHA, "a" * 40))
    with pytest.raises(ValueError, match="release identity mismatch"):
        base.validate(root)


def test_checksums_reject_manifest_drift(metadata, monkeypatch):
    _, root, manifest = metadata
    monkeypatch.syspath_prepend(str(ROOT / "deploy/stage-d"))
    checker = load("deploy/stage-d/validate_rollback_readiness.py")
    checker.verify_checksums(root)
    manifest.write_text(manifest.read_text() + "# changed\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        checker.verify_checksums(root)
