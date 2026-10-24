"""Negative CPU-only tests for sealed /foto staging admission; no GPU access."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/local_image/fullchain_gpu_window_preflight_dev.py"
spec = importlib.util.spec_from_file_location("fullchain_gate_tests", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.fixture()
def staging(tmp_path, monkeypatch):
    root = tmp_path / "guarded"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gate, "STAGING", root)
    monkeypatch.setattr(gate.snapshot, "TARGET", root)

    for name in ("tools", "src", "input", "output", "temp", "user",
                 "jobs", "hermes-inbound"):
        (root / name).mkdir(mode=0o700)
    shutil.copytree(ROOT / "src/ai_bridge", root / "src/ai_bridge",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    manifest = {
        "kind": "DEV_ISOLATED_SOURCES_ONLY",
        "gateway_port": 11656,
        "comfy_port": 11657,
        "snapshot": str(root),
        "files": {},
    }
    for rel in gate.snapshot.SOURCE_FILES:
        original = (ROOT / rel).read_bytes()
        transformed = gate.snapshot.transform(rel, original.decode()).encode()
        target = root / rel
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_bytes(transformed)
        target.chmod(0o700 if rel in gate.snapshot.GENERATORS else 0o600)
        manifest["files"][rel] = {
            "original_sha256": gate.sha(ROOT / rel),
            "snapshot_sha256": gate.sha(target),
        }
    (root / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return root


def checked(root, *markers):
    return gate.verify_snapshot(root, ROOT, markers=tuple(markers))


def test_clean_snapshot_statically_admitted(staging):
    result = checked(staging)
    assert result["gate"] == "PASS", result
    assert result["runtime"] == "NOT_STARTED"
    assert result["gpu_reuse_safe"] == "NOT_VERIFIED"


def test_changed_source_sha_refused(staging):
    path = staging / "tools/local_image/generate_image.py"
    path.write_text(path.read_text().replace("default=256)", "default=512)"))
    result = checked(staging)
    assert result["gate"] == "BLOCKED"
    assert any("snapshot/source mismatch" in x for x in result["problems"])


def test_live_delivery_change_refused(staging):
    path = staging / "tools/local_image/hermes_foto_dispatch.py"
    path.write_text(path.read_text().replace(
        'raise FotoDispatchError("DEV recipient refused")',
        'raise FotoDispatchError("NOT SAFE")'))
    result = checked(staging)
    assert result["gate"] == "BLOCKED"
    assert any("delivery" in x or "mismatch" in x for x in result["problems"])


def test_package_drift_detected(staging):
    path = staging / "src/ai_bridge/gateway/app.py"
    path.write_text(path.read_text() + "\n# unexpected change\n")
    result = checked(staging)
    assert result["gate"] == "BLOCKED"
    assert any("package snapshot source drift" in x for x in result["problems"])


def test_existing_recovery_marker_refused(staging):
    marker = staging / "dev-residency.blocked"
    marker.write_text("GPU owner uncertain")
    result = checked(staging, marker)
    assert result["gate"] == "BLOCKED"
    assert str(marker) in result["recovery_markers_present"]


def test_symlinked_generator_refused(staging):
    staged = staging / "tools/local_image/generate_image.py"
    original = ROOT / "tools/local_image/generate_image.py"
    staged.unlink()
    staged.symlink_to(original)
    result = checked(staging)
    assert result["gate"] == "BLOCKED"
    assert any("symlink" in x or "unsafe" in x or "mismatch" in x
               for x in result["problems"])


def test_missing_manifest_is_blocked(staging):
    (staging / "SOURCE_MANIFEST.json").unlink()
    result = checked(staging)
    assert result["gate"] == "BLOCKED"
    assert any("manifest" in x for x in result["problems"])
