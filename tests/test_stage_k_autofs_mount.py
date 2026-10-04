from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
STAGE_K = ROOT / "deploy" / "stage-k"
sys.path.insert(0, str(STAGE_K))


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, STAGE_K / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


backup = load("stage_k_backup_autofs_test", "backup.py")
monitor = load("stage_k_monitor_autofs_test", "k5_monitor.py")


class StageKAutofsTests(unittest.TestCase):
    def test_backup_accepts_autofs_over_cifs(self):
        self.assertEqual(backup.select_network_fs("autofs\ncifs\n"), "cifs")

    def test_backup_accepts_direct_network_filesystems(self):
        self.assertEqual(backup.select_network_fs("nfs4\n"), "nfs4")

    def test_backup_rejects_local_filesystem_even_with_autofs(self):
        with self.assertRaisesRegex(RuntimeError, "not approved network FS"):
            backup.select_network_fs("autofs\next4\n")

    def test_monitor_selects_cifs_below_autofs(self):
        output = "systemd-1 autofs\n//globalnas.local/AI_Platform cifs\n"
        self.assertEqual(
            monitor.select_globalnas_mount(output),
            ("//globalnas.local/AI_Platform", "cifs"),
        )

    def test_monitor_rejects_wrong_source_or_local_layer(self):
        self.assertIsNone(
            monitor.select_globalnas_mount(
                "systemd-1 autofs\n/dev/nvme0n1p1 ext4\n"
            )
        )
        self.assertIsNone(
            monitor.select_globalnas_mount(
                "systemd-1 autofs\n//other/share cifs\n"
            )
        )

    def test_monitor_reads_marker_before_mount_probe(self):
        marker_loaded = False

        def fake_load_json(path):
            nonlocal marker_loaded
            if path == monitor.MARKER:
                marker_loaded = True
                return {
                    "purpose": "ai-platform-stage-k",
                    "nas": "GlobalNAS",
                    "share": "AI_Platform",
                }
            return None

        def fake_mount_state():
            self.assertTrue(marker_loaded)
            raise RuntimeError("mount-order-observed")

        with tempfile.TemporaryDirectory() as tempdir:
            with (
                patch.object(monitor, "STATUS_ROOT", Path(tempdir)),
                patch.object(monitor, "load_json", side_effect=fake_load_json),
                patch.object(monitor, "mount_state", side_effect=fake_mount_state),
            ):
                with self.assertRaisesRegex(RuntimeError, "mount-order-observed"):
                    monitor.check()


if __name__ == "__main__":
    unittest.main()
