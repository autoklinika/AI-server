"""CPU-only deploy/rollback control tests; no systemd commands allowed."""
import importlib.util
from pathlib import Path
from unittest import TestCase, mock

P = Path(__file__).parents[1] / "tools/deploy_rm_gateway_backport_v1.py"
spec = importlib.util.spec_from_file_location("rm_cutover", P)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CutoverTests(TestCase):
    def test_candidate_read_only_preflight_no_systemd_mutations(self):
        with mock.patch.object(m, "verify_candidate") as verify, \
                mock.patch.object(m, "current_idle") as idle, \
                mock.patch.object(m, "DROPIN") as dropin, \
                mock.patch.object(m, "cmd") as command:
            dropin.exists.return_value = False
            assert m.run("check") == 0
            verify.assert_called_once()
            idle.assert_called_once()
            command.assert_not_called()

    def test_apply_requires_operator_privileges(self):
        with mock.patch.object(m, "verify_candidate"), \
                mock.patch.object(m, "current_idle") as idle, \
                mock.patch.object(m.os, "geteuid", return_value=1000), \
                mock.patch.object(m, "cmd") as command:
            assert m.run("apply") == 2
            idle.assert_not_called()
            command.assert_not_called()

    def test_apply_one_gateway_only_no_driver_or_service_restart(self):
        calls = []
        def fake_command(*args):
            calls.append(args)
            return ""
        with mock.patch.object(m, "verify_candidate"), \
                mock.patch.object(m, "current_idle"), \
                mock.patch.object(m, "install_overlay") as install, \
                mock.patch.object(m, "set_override") as override, \
                mock.patch.object(m, "smoke") as smoke, \
                mock.patch.object(m, "DROPIN") as dropin, \
                mock.patch.object(m.os, "geteuid", return_value=0), \
                mock.patch.object(m.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(m, "cmd", side_effect=fake_command):
            dropin.exists.return_value = False
            assert m.run("apply") == 0
        install.assert_called_once()
        override.assert_called_once()
        smoke.assert_called_once_with(True)
        assert calls == [
            ("systemctl", "stop", "ai-gateway.service"),
            ("systemctl", "daemon-reload"),
            ("systemctl", "start", "ai-gateway.service"),
        ]

    def test_failed_new_gateway_rolls_back_old_binary(self):
        calls = []
        def fake_command(*args):
            calls.append(args)
        with mock.patch.object(m, "verify_candidate"), \
                mock.patch.object(m, "current_idle"), \
                mock.patch.object(m, "install_overlay"), \
                mock.patch.object(m, "set_override",
                                  side_effect=lambda: setattr(dropin.exists, "return_value", True)), \
                mock.patch.object(m, "smoke", side_effect=[RuntimeError("new unhealthy"), None]), \
                mock.patch.object(m, "DROPIN") as dropin, \
                mock.patch.object(m.os, "geteuid", return_value=0), \
                mock.patch.object(m.sys.stdin, "isatty", return_value=True), \
                mock.patch.object(m, "cmd", side_effect=fake_command):
            dropin.exists.return_value = False
            dropin.read_text.return_value = m.CONTENT
            assert m.run("apply") == 2
        dropin.unlink.assert_called_once()
        assert calls == [
            ("systemctl", "stop", "ai-gateway.service"),
            ("systemctl", "daemon-reload"),
            ("systemctl", "start", "ai-gateway.service"),
            ("systemctl", "stop", "ai-gateway.service"),
            ("systemctl", "daemon-reload"),
            ("systemctl", "start", "ai-gateway.service"),
        ]
