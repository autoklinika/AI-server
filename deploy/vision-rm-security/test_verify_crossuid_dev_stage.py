#!/usr/bin/env python3
"""Unit and live read-only acceptance tests for cross-UID staging attestation."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("stage_verifier", HERE / "verify-crossuid-dev-stage.py")
assert spec and spec.loader
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class StageAttestationTests(unittest.TestCase):
    def test_live_complete_stage_is_verified_read_only(self):
        with contextlib.redirect_stdout(io.StringIO()) as capture:
            v.verify()
        self.assertIn("DEV_STAGING_INTEGRITY=PASS", capture.getvalue())

    def test_static_is_not_mistaken_for_autostart(self):
        state = v.systemd_properties("ai-vision-rm-dev-gateway")
        self.assertEqual(state["UnitFileState"], "static")
        self.assertEqual(v.EXPECTED_STATES["ai-vision-rm-dev-gateway"], "static")

    def test_enabled_unit_is_rejected(self):
        real = v.systemd_properties
        def unexpected(service):
            props = real(service)
            if service == "ai-vision-rm-broker":
                props["UnitFileState"] = "enabled"
            return props
        with patch.object(v, "systemd_properties", side_effect=unexpected):
            with self.assertRaisesRegex(v.StageError, "DEV_UNIT_UNEXPECTED_STATE"):
                v.verify()

    def test_active_unit_is_rejected(self):
        real = v.systemd_properties
        def unexpected(service):
            props = real(service)
            if service == "ai-vision-rm-runner":
                props["ActiveState"] = "active"
            return props
        with patch.object(v, "systemd_properties", side_effect=unexpected):
            with self.assertRaisesRegex(v.StageError, "DEV_UNIT_UNEXPECTEDLY_ACTIVE"):
                v.verify()

    def test_autostart_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "ai-vision-rm-broker.service"
            target.write_text("fake target")
            wants = root / "multi-user.target.wants"
            wants.mkdir()
            (wants / target.name).symlink_to(target)
            # Substitute scan roots through os.walk for this small focused test.
            real_walk = v.os.walk
            def scoped_walk(arg, *args, **kwargs):
                if Path(arg) in (Path("/etc/systemd/system"), Path("/run/systemd/system")):
                    return real_walk(root, *args, **kwargs)
                return real_walk(arg, *args, **kwargs)
            with patch.object(v.os, "walk", side_effect=scoped_walk):
                with self.assertRaisesRegex(v.StageError, "DEV_UNIT_UNEXPECTED_AUTOSTART_LINK"):
                    v.check_autostart_symlinks()

    def test_non_root_owned_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "test.py"
            p.write_text("test")
            if p.stat().st_uid == 0:
                self.skipTest("Test requires unprivileged user")
            with self.assertRaisesRegex(v.StageError, "STAGE_NOT_ROOT_OWNED"):
                v.root_owned(p)

    def test_content_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            src = Path(directory) / "src.py"
            dst = Path(directory) / "dst.py"
            src.write_text("a")
            dst.write_text("b")
            with patch.object(v, "root_owned", return_value=None):
                with self.assertRaisesRegex(v.StageError, "STAGE_CONTENT_MISMATCH"):
                    v.same_file(src, dst)


if __name__ == "__main__":
    unittest.main(verbosity=2)
