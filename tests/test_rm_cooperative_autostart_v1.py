"""CPU-only checks for operator autostart/ComfyUI procedure. Never touch systemd."""
import importlib.util
from pathlib import Path
import sys
import subprocess
from unittest import TestCase, mock

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
sp = importlib.util.spec_from_file_location("autostart", TOOLS / "rm_cooperative_autostart_v1.py")
a = importlib.util.module_from_spec(sp)
sp.loader.exec_module(a)


class AutostartTests(TestCase):
    def test_read_only_preflight_no_privileged_ops(self):
        with mock.patch.object(a.base, "baseline") as check, \
                mock.patch.object(a, "expected_known_enablement") as enabled, \
                mock.patch.object(a, "no_active_work") as busy, \
                mock.patch.object(a.base, "idle") as idle, \
                mock.patch.object(a, "command") as cmd:
            a.check_before()
            check.assert_called_once_with(started=a.CORE)
            enabled.assert_called_once_with()
            busy.assert_called_once_with()
            idle.assert_called_once_with(False)
            cmd.assert_not_called()

    def test_apply_exact_sequence_and_guardrails(self):
        effects = []
        states = {unit: "enabled" for unit in a.AUTOSTART}
        def action(*args):
            effects.append(args)
            if args[:2] == ("systemctl", "is-enabled"):
                return states[args[2]]
            if args[:4] == ("sudo", "-n", "systemctl", "disable"):
                for unit in args[4:]:
                    states[unit] = "disabled"
            return ""
        with mock.patch.object(a, "check_before") as check, \
                mock.patch.object(a.base, "baseline"), \
                mock.patch.object(a, "no_active_work"), \
                mock.patch.object(a, "no_other_gpu_users") as owners, \
                mock.patch.object(a, "command", side_effect=action), \
                mock.patch.object(a, "wait_ready") as ready, \
                mock.patch.object(a.base, "prop", return_value="active"), \
                mock.patch.object(a.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(a.sys.stdout, "isatty", return_value=True):
            a.apply()
        check.assert_called_once_with()
        ready.assert_called_once_with()
        self.assertEqual(owners.call_count, 2)
        self.assertEqual(effects[0], ("sudo", "-v"))
        self.assertIn(("sudo", "-n", "systemctl", "disable", *a.AUTOSTART), effects)
        self.assertIn(("sudo", "-n", "systemctl", "start", "comfyui.service"), effects)
        self.assertNotIn(("sudo", "-n", "systemctl", "start", "ollama.service"), effects)

    def test_unsafe_busy_state_cannot_disable(self):
        with mock.patch.object(a, "check_before", side_effect=RuntimeError("busy")), \
                mock.patch.object(a, "command") as command:
            with self.assertRaisesRegex(RuntimeError, "busy"):
                a.apply()
            command.assert_not_called()

    def test_failed_comfy_readiness_stops_only_own_engine(self):
        effects = []
        states = {unit: "enabled" for unit in a.AUTOSTART}
        def action(*args):
            effects.append(args)
            if args[:2] == ("systemctl", "is-enabled"):
                return states[args[2]]
            if args[:4] == ("sudo", "-n", "systemctl", "disable"):
                for unit in args[4:]:
                    states[unit] = "disabled"
            return ""
        with mock.patch.object(a, "check_before"), \
                mock.patch.object(a.base, "baseline"), \
                mock.patch.object(a, "no_active_work"), \
                mock.patch.object(a, "no_other_gpu_users"), \
                mock.patch.object(a, "command", side_effect=action), \
                mock.patch.object(a, "wait_ready", side_effect=RuntimeError("bad comfy")), \
                mock.patch.object(a.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(a.sys.stdout, "isatty", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "bad comfy"):
                a.apply()
        self.assertIn(("sudo", "-n", "systemctl", "stop", "comfyui.service"), effects)
        self.assertNotIn(("sudo", "-n", "systemctl", "stop", "ollama.service"), effects)
        self.assertNotIn(("sudo", "-n", "systemctl", "stop", "ai-gateway.service"), effects)

    def test_comfy_extension_requires_empty_queue(self):
        with mock.patch.object(a.base, "prop", return_value="active"), \
                mock.patch.object(a, "local_json", side_effect=[
                    {"devices": [{"name": "AMD Radeon 890M Graphics"}]},
                    {"schema_version": 1, "queue_running": 1, "queue_pending": 0,
                     "loaded_models": 0, "cleanup_pending": False}]):
            with self.assertRaisesRegex(RuntimeError, "not idle"):
                a.read_comfy_ready()

    def test_readiness_correct_when_idle(self):
        with mock.patch.object(a.base, "prop", return_value="active"), \
                mock.patch.object(a, "local_json", side_effect=[
                    {"devices": [{"name": "AMD Radeon 890M Graphics : native"}]},
                    {"schema_version": 1, "queue_running": 0, "queue_pending": 0,
                     "loaded_models": 0, "cleanup_pending": False},
                    {"queue_running": [], "queue_pending": []}]):
            self.assertIsNone(a.read_comfy_ready())

    def test_isenabled_disabled_rc1_is_not_a_failure(self):
        with mock.patch.object(a.subprocess, "run", return_value=subprocess.CompletedProcess(
                ["systemctl"], 1, "disabled\n", "")):
            self.assertEqual(a.command("systemctl", "is-enabled", "comfyui.service"), "disabled")

    def test_isenabled_ambiguous_state_is_rejected(self):
        for rc, stdout in ((1, "masked\n"), (1, "enabled\n"),
                           (0, "disabled\n"), (4, ""), (3, "static\n")):
            with self.subTest(rc=rc, state=stdout), mock.patch.object(
                    a.subprocess, "run", return_value=subprocess.CompletedProcess(
                        ["systemctl"], rc, stdout, "")):
                with self.assertRaisesRegex(RuntimeError, "unexpected unit enablement"):
                    a.command("systemctl", "is-enabled", "comfyui.service")

    def test_resume_with_all_disabled_skips_redundant_disable(self):
        effects = []
        def action(*args):
            effects.append(args)
            if args[:2] == ("systemctl", "is-enabled"):
                return "disabled"
            return ""
        with mock.patch.object(a, "check_before"), \
                mock.patch.object(a.base, "baseline"), \
                mock.patch.object(a, "no_active_work"), \
                mock.patch.object(a, "no_other_gpu_users"), \
                mock.patch.object(a, "command", side_effect=action), \
                mock.patch.object(a, "wait_ready"), \
                mock.patch.object(a.base, "prop", return_value="active"), \
                mock.patch.object(a.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(a.sys.stdout, "isatty", return_value=True):
            a.apply()
        self.assertIn(("sudo", "-n", "systemctl", "start", "comfyui.service"), effects)
        self.assertFalse(any(e[:4] == ("sudo", "-n", "systemctl", "disable") for e in effects))

    def test_resume_partial_disable_only_remaining_enabled_units(self):
        states = {unit: ("enabled" if i == 1 else "disabled")
                  for i, unit in enumerate(a.AUTOSTART)}
        effects = []
        def action(*args):
            effects.append(args)
            if args[:2] == ("systemctl", "is-enabled"):
                return states[args[2]]
            if args[:4] == ("sudo", "-n", "systemctl", "disable"):
                for unit in args[4:]:
                    states[unit] = "disabled"
            return ""
        with mock.patch.object(a, "check_before"), \
                mock.patch.object(a.base, "baseline"), \
                mock.patch.object(a, "no_active_work"), \
                mock.patch.object(a, "no_other_gpu_users"), \
                mock.patch.object(a, "command", side_effect=action), \
                mock.patch.object(a, "wait_ready"), \
                mock.patch.object(a.base, "prop", return_value="active"), \
                mock.patch.object(a.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(a.sys.stdout, "isatty", return_value=True):
            a.apply()
        self.assertIn(("sudo", "-n", "systemctl", "disable", a.AUTOSTART[1]), effects)
        self.assertEqual(set(states.values()), {"disabled"})

    def test_ollama_model_loaded_blocks_all(self):
        with mock.patch.object(a, "local_json", side_effect=[
                {"status": "ok", "ollama": "ok"},
                {"gpu_residency": {"state": "llm", "recovery_required": False},
                 "max_concurrency": 1, "admission_blocked": False,
                 "active_count": 0, "queued_count": 0,
                 "resource_leases": {"lease_count": 0}},
                {"models": [{"name": "qwen"}]}]):
            with self.assertRaisesRegex(RuntimeError, "loaded models"):
                a.no_active_work()

    def test_no_gpu_reuse_safety_authorization(self):
        s=(TOOLS / "rm_cooperative_autostart_v1.py").read_text()
        self.assertIn('"automatic_n1": "NOT_ADMITTED"', s)
        self.assertNotIn("N1_REAL_GPU_GRANT=VERIFIED", s)
        self.assertNotIn("systemctl restart", s)
        self.assertNotIn("chmod /dev", s)
        self.assertNotIn("chown /dev", s)
