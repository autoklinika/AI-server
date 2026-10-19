"""CPU-only, stdlib suite: python3 -m unittest discover -s tests -p test_host_gpu_audit.py."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/ai_bridge/gateway"))
import host_gpu_audit as audit
import os_gpu_boundary as boundary


class HostAuditTests(unittest.TestCase):
    def test_unknown_blocks_without_open_or_secrets(self):
        def unavailable(*args):
            raise PermissionError("secret must not appear")
        with patch.object(boundary, "_access", side_effect=AssertionError), \
                patch.object(audit.os, "open", side_effect=AssertionError):
            result = audit.audit(device_reader=unavailable, user_reader=unavailable,
                                 process_reader=unavailable, unit_reader=unavailable)
        self.assertEqual(result.decision, "BLOCKED")
        self.assertEqual(result.driver_reuse, "NOT_VERIFIED")
        self.assertNotIn("secret", json.dumps(result.as_dict()))
        self.assertTrue(all(v == audit.unknown() for v in result.checks["devices"].values()))
        with self.assertRaises(TypeError):
            bool(result)

    def test_apparent_success_and_bypass_never_grant(self):
        result = audit.audit(device_reader=lambda _: {"expected_dac": True},
                             user_reader=lambda _: {"groups": ["render", "video"]},
                             process_reader=lambda: {"matches": [{"pid": 123}]},
                             unit_reader=lambda _: {"ActiveState": "inactive"})
        self.assertEqual(result.decision, "BLOCKED")
        self.assertEqual(result.os_device_access, "UNVERIFIED")
        self.assertTrue(result.checks["inherited_gpu_groups"]["matches"])

    def test_unit_parser_and_read_only_command(self):
        for stdout, code in [("", 0), ("LoadState=loaded\n", 0),
                ("LoadState=loaded\nLoadState=loaded\n", 0), ("", 1)]:
            self.assertEqual(audit.unit("ollama.service", lambda *a: SimpleNamespace(
                stdout=stdout, returncode=code)), audit.unknown())
        def command(*args):
            self.assertEqual(args[:3], ("systemctl", "--system", "show"))
            return SimpleNamespace(returncode=0, stdout="\n".join(
                f"{key}=enabled" for key in audit.FIELDS))
        self.assertEqual(audit.unit("ollama.service", command)["UnitFileState"], "enabled")

    def test_systemd_omitted_optional_properties_preserve_known_state(self):
        values = ("LoadState=loaded", "ActiveState=inactive",
                  "UnitFileState=enabled", "DevicePolicy=auto", "MainPID=0")
        result = audit.unit("ollama.service", lambda *a: SimpleNamespace(
            returncode=0, stdout="\n".join(values)))
        self.assertEqual(result["ActiveState"], "inactive")
        self.assertEqual(result["UnitFileState"], "enabled")
        self.assertEqual(result["property_coverage"], "PARTIAL_UNREPORTED_FIELDS")
        self.assertIn("DeviceAllow", result["unreported_fields"])

    def test_video_card_and_render_nodes_are_all_in_inventory(self):
        self.assertIn("/dev/dri/card0", audit.DEVICE_NODES)
        self.assertIn("/dev/kfd", audit.DEVICE_NODES)
        self.assertIn("/dev/dri/renderD128", audit.DEVICE_NODES)
        self.assertEqual(audit.audit(device_reader=lambda name: {"name": name},
                          user_reader=lambda _: {}, process_reader=lambda: {},
                          unit_reader=lambda _: {}).decision, "BLOCKED")

    def test_primary_and_stale_supplementary_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for pid, groups, gid in [(1, "991", "1000"), (2, "", "44"), (3, "", "1000")]:
                directory = root / str(pid)
                directory.mkdir()
                (directory / "status").write_text(
                    f"Uid:\t1000 1000 1000 1000\nGid:\t{gid} {gid} {gid} {gid}\nGroups:\t{groups}\n")
            (root / "4").mkdir()
            with patch.object(audit.grp, "getgrnam", side_effect=lambda name: SimpleNamespace(
                    gr_gid={"render": 991, "video": 44}[name])):
                result = audit.processes(root)
        self.assertEqual(sorted(p["pid"] for p in result["matches"]), [1, 2])
        self.assertEqual(result["unreadable_or_raced"], 1)
        self.assertTrue(result["coverage"].startswith("UNVERIFIED"))

    def test_metadata_does_not_open_device(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ordinary-file"
            path.touch()
            with patch.object(audit.os, "open", side_effect=AssertionError):
                result = audit.device(path, lambda *args: SimpleNamespace(returncode=1, stdout=""))
        self.assertFalse(result["character_device"])
        self.assertFalse(result["expected_dac"])
        self.assertEqual(result["acl"], "UNKNOWN")

    def test_cli_exit_blocked(self):
        with patch.object(audit, "audit", return_value=boundary.Boundary(
                1, "BLOCKED", "UNVERIFIED", "NOT_VERIFIED", {})), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(audit.main(), 2)
        self.assertEqual(json.loads(output.getvalue())["decision"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
