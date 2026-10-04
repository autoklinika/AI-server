from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
STAGE_K = ROOT / "deploy" / "stage-k"
sys.path.insert(0, str(STAGE_K))

spec = importlib.util.spec_from_file_location("stage_k_adapters", STAGE_K / "k4_adapters.py")
assert spec and spec.loader
adapters = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapters)


class StageKAdapterBackupTests(unittest.TestCase):
    def make_adapter(self, root: Path, name: str, *, deployed: bool = True) -> tuple[Path, Path]:
        source_root = root / "source"
        runtime_root = root / "runtime"
        selected = source_root / name / "run-1"
        selected.mkdir(parents=True)
        weights = selected / "adapter_model.safetensors"
        weights.write_bytes(b"selected-production-adapter-weights")
        source_sha = hashlib.sha256(weights.read_bytes()).hexdigest()
        (selected / "adapter_config.json").write_text('{"r": 8}\n')
        (selected / "training_manifest.json").write_text(json.dumps({
            "status": "TRAINING_INTEGRITY_PASS",
            "adapter_sha256": source_sha,
        }) + "\n")
        (selected / "README.md").write_text("approved adapter\n")
        (source_root / name / "current").symlink_to(selected)

        runtime_dir = runtime_root / name
        runtime_dir.mkdir(parents=True)
        runtime = runtime_dir / "immutable.gguf"
        runtime.write_bytes(b"runtime-gguf")
        (runtime_dir / "Modelfile").write_text("FROM base\n")
        if deployed:
            (runtime_dir / "current.gguf").symlink_to(runtime)
        return source_root, runtime_root

    def test_only_runtime_selected_adapters_are_active(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_root, runtime_root = self.make_adapter(root, "production", deployed=True)
            self.make_adapter(root, "source-only", deployed=False)
            with (
                patch.object(adapters, "SOURCE_ROOT", source_root),
                patch.object(adapters, "RUNTIME_ROOT", runtime_root),
            ):
                self.assertEqual(adapters.active_adapter_names(), ["production"])

    def test_deployed_adapter_requires_matching_source_current(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_root = root / "source"
            runtime_root = root / "runtime"
            source_root.mkdir()
            runtime_dir = runtime_root / "broken"
            runtime_dir.mkdir(parents=True)
            runtime = runtime_dir / "immutable.gguf"
            runtime.write_bytes(b"runtime")
            (runtime_dir / "current.gguf").symlink_to(runtime)
            with (
                patch.object(adapters, "SOURCE_ROOT", source_root),
                patch.object(adapters, "RUNTIME_ROOT", runtime_root),
            ):
                with self.assertRaisesRegex(Exception, "missing source current"):
                    adapters.active_adapter_names()

    def test_backup_verify_and_restore_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_root, runtime_root = self.make_adapter(root, "production", deployed=True)
            target = root / "AI_Platform"
            target.mkdir()
            evidence = root / "evidence"
            with (
                patch.object(adapters, "SOURCE_ROOT", source_root),
                patch.object(adapters, "RUNTIME_ROOT", runtime_root),
                patch.object(adapters, "EVIDENCE_ROOT", evidence),
            ):
                result = adapters.create_backup(target, "manual", True)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["adapters"], ["production"])
                manifest_dir = Path(result["adapter_manifest"])

                verified = adapters.verify(manifest_dir)
                self.assertEqual(verified["status"], "PASS")
                self.assertEqual(verified["adapter_count"], 1)

                restored = adapters.restore_validate(manifest_dir)
                self.assertEqual(restored["status"], "PASS")
                self.assertFalse(restored["production_modified"])
                restored_root = Path(restored["evidence_dir"]) / "production"
                self.assertTrue((restored_root / "source" / "adapter_model.safetensors").is_file())
                self.assertTrue((restored_root / "runtime.gguf").is_file())
                self.assertTrue((restored_root / "runtime-metadata" / "Modelfile").is_file())

    def test_k5_orchestrator_includes_adapter_backup_verify_and_restore(self):
        text = (STAGE_K / "k5_run.py").read_text()
        self.assertIn('"adapter_backup"', text)
        self.assertIn('"verify_adapters"', text)
        self.assertIn('"restore_adapters"', text)
        self.assertIn('"adapter_backup_id"', text)

    def test_retention_covers_adapter_snapshots(self):
        text = (STAGE_K / "k5_retention.py").read_text()
        self.assertIn("def prune_adapters(", text)
        self.assertIn('"removed_adapters": prune_adapters', text)
        self.assertIn("adapter-restore-validation", text)


if __name__ == "__main__":
    unittest.main()
