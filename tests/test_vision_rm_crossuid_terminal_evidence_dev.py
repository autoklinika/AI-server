"""DEV security regression: terminal user scope must not be guessed cross-UID.

Demonstrates that the current cross-UID cleanup remains fail-closed if its
kernel cgroup disappears before systemd status can be attested. This is
not yet a positive acceptance test of terminal-state evidence.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

MOD = Path(__file__).resolve().parents[1] / "src/ai_bridge/gateway/vision_residency_evidence.py"
spec = importlib.util.spec_from_file_location("vision_residency_evidence_crossuid", MOD)
assert spec and spec.loader
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class CrossUidTerminalTests(unittest.TestCase):
    def test_missing_worker_scope_under_another_uid_must_not_claim_empty(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value=None), patch(
                "os.getuid", return_value=993), patch(
                "subprocess.run") as process:
            self.assertIsNone(evidence.scope_members_or_terminal(scope))
            process.assert_not_called()

    def test_missing_scope_with_matching_uid_but_unavailable_systemd_denied(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value=None), patch(
                "os.getuid", return_value=994), patch(
                "subprocess.run") as process:
            process.return_value.returncode = 1
            process.return_value.stdout = ""
            self.assertIsNone(evidence.scope_members_or_terminal(scope))

    def test_nonexistent_scope_is_not_terminal_proof_even_with_rc_zero(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value=None), patch(
                "os.getuid", return_value=994), patch("subprocess.run") as process:
            process.return_value.returncode = 0
            process.return_value.stdout = (
                "LoadState=not-found\nActiveState=inactive\n"
                "SubState=dead\nControlGroup=\n"
            )
            self.assertIsNone(evidence.scope_members_or_terminal(scope))
            args, kwargs = process.call_args
            self.assertIn("LoadState", args[0])

    def test_terminal_loaded_scope_requires_all_exact_fields(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value=None), patch(
                "os.getuid", return_value=994), patch("subprocess.run") as process:
            process.return_value.returncode = 0
            process.return_value.stdout = (
                "LoadState=loaded\nActiveState=inactive\nSubState=dead\nControlGroup=\n"
            )
            self.assertEqual(evidence.scope_members_or_terminal(scope), set())
            for altered in ("LoadState=not-found", "ActiveState=active",
                            "SubState=running", "ControlGroup=/stale", "ControlGroup"):
                original = process.return_value.stdout
                if altered == "ControlGroup":
                    process.return_value.stdout = original.replace("ControlGroup=\n", "")
                else:
                    key = altered.split("=", 1)[0]
                    process.return_value.stdout = original.replace(
                        next(line for line in original.splitlines() if line.startswith(key+"=")),
                        altered)
                with self.subTest(change=altered):
                    self.assertIsNone(evidence.scope_members_or_terminal(scope))
                process.return_value.stdout = original

    def test_empty_cgroup_does_not_override_active_systemd_scope(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value=set()), patch(
                "os.getuid", return_value=994), patch("subprocess.run") as process:
            process.return_value.returncode = 0
            process.return_value.stdout = (
                "LoadState=loaded\nActiveState=active\n"
                "SubState=running\nControlGroup=/user.slice/...\n"
            )
            self.assertIsNone(evidence.scope_members_or_terminal(scope))
            process.assert_called_once()

    def test_empty_cgroup_and_verified_terminal_scope_is_clean(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value=set()), patch(
                "os.getuid", return_value=994), patch("subprocess.run") as process:
            process.return_value.returncode = 0
            process.return_value.stdout = (
                "LoadState=loaded\nActiveState=inactive\n"
                "SubState=dead\nControlGroup=\n"
            )
            self.assertEqual(evidence.scope_members_or_terminal(scope), set())

    def test_present_scope_with_process_must_not_claim_empty(self):
        scope = ("/user.slice/user-994.slice/user@994.service/app.slice/"
                 "vision-bench-c68e5f31bac6.scope")
        with patch.object(evidence, "scoped_processes", return_value={1274}):
            self.assertEqual(evidence.scope_members_or_terminal(scope), {1274})


if __name__ == "__main__":
    unittest.main(verbosity=2)
