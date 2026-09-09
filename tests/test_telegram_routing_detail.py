import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("routing_detail", ROOT / "tools/audit_hermes_telegram_routing_detail.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

BLOCK = '''        # STAGE26_WIDEO_ROUTE_ENV: exact event route
        _stage26_platform = source.platform.value if source.platform else ""
        _stage26_chat_id = str(source.chat_id or "")
        _stage26_thread_id = str(source.thread_id or "")
        if _stage26_platform and _stage26_chat_id:
            _stage26_route_env = " ".join((
                "HERMES_SESSION_PLATFORM=" + _stage26_shlex.quote(_stage26_platform),
                "HERMES_SESSION_CHAT_ID=" + _stage26_shlex.quote(_stage26_chat_id),
                "HERMES_SESSION_THREAD_ID=" + _stage26_shlex.quote(_stage26_thread_id),
            ))
            exec_cmd = f"{_stage26_route_env} {exec_cmd}"
        # STAGE28_FOTO_MEDIA_ENV
'''


class DetailTests(unittest.TestCase):
    def test_exact_route_builder_distinguishes_users_and_topic(self):
        result = audit.route_detail(BLOCK)
        self.assertTrue(result["probe_executed"])
        for key in ("A", "B", "B_topic"):
            self.assertTrue(result["synthetic_cases"][key]["correct_source_route"])
        self.assertFalse(result["synthetic_cases"]["missing"]["explicit_chat_prefix"])

    def test_pinned_route_detected_and_redacted(self):
        text = BLOCK.replace('str(source.chat_id or "")', '"private-pinned-id"')
        result = audit.route_detail(text)
        self.assertTrue(result["probe_executed"])
        self.assertFalse(result["synthetic_cases"]["A"]["correct_source_route"])
        self.assertNotIn("private-pinned-id", json.dumps(result))

    def test_arbitrary_calls_refused(self):
        for expression in ('open("secret")', '__import__("os").system("touch secret")',
                           '_stage26_shlex.os.system("touch secret")'):
            with self.subTest(expression=expression):
                result = audit.route_detail(BLOCK.replace('str(source.chat_id or "")', expression))
                self.assertFalse(result["probe_executed"])

    def test_source_assignment_refused(self):
        result = audit.route_detail(BLOCK.replace('_stage26_chat_id = ', 'source.chat_id = '))
        self.assertFalse(result["probe_executed"])

    def test_missing_or_duplicate_marker_never_claims_success(self):
        for text in ("", BLOCK + BLOCK, "# STAGE26_WIDEO_ROUTE_ENV\nx = 1"):
            self.assertFalse(audit.route_detail(text)["probe_executed"])

    def test_summaries_redact_secrets(self):
        text = 'def _send(target: str, message: str):\n    """secret docstring"""\n    token = "private-token"\n    chat = 5844876074\n    return target\n'
        output = json.dumps(audit.method_summary(text, "_send"))
        for private in ("private-token", "5844876074", "secret docstring"):
            self.assertNotIn(private, output)
        self.assertIn("return target", output)

    def test_correct_foto_path_and_stage30_reference(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "run", return_value="code\n"):
            root = Path(tmp)
            binpath = root / "bin"
            libpath = root / "lib"
            binpath.mkdir()
            libpath.mkdir()
            (binpath / "hermes-foto-dispatch").write_text("code\n")
            result = audit.report(root, root, binpath, libpath)
            self.assertTrue(result["installed"]["foto_actual_entrypoint"]["matches_main_stage30"])
            self.assertFalse(result["installed"]["video_active_base_stage30"]["present"])

    def test_missing_paths_no_writes_no_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "run", return_value=""):
            root = Path(tmp)
            result = audit.report(root, root, root, root)
            self.assertEqual(list(root.iterdir()), [])
            self.assertFalse(result["gateway_route"]["probe_executed"])


if __name__ == "__main__":
    unittest.main()
