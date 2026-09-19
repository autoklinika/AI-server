import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("routing_audit", ROOT / "tools/audit_hermes_telegram_routing.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class RoutingAuditTests(unittest.TestCase):
    def test_aliases_are_consistent_and_distinct(self):
        labels = audit.Labels()
        self.assertEqual(labels.identity("12345"), "ID_1")
        self.assertEqual(labels.target("telegram:12345"), "telegram:ID_1")
        self.assertEqual(labels.target("telegram:67890"), "telegram:ID_2")
        self.assertEqual(labels.target("telegram:-100123:77"), "telegram:ID_3:topic_present")

    def test_invalid_targets_are_redacted(self):
        labels = audit.Labels()
        for target in ("telegram", "telegram:secret-token", "discord:private", "telegram:0"):
            self.assertEqual(labels.target(target), "invalid_or_non_telegram_redacted")
        self.assertEqual(labels.target(None), "unset")

    def test_dotenv_ignores_credentials(self):
        text = 'TELEGRAM_BOT_TOKEN=very-secret\nexport TELEGRAM_HOME_CHANNEL="12345"\nHERMES_SESSION_CHAT_ID=67890\n'
        values = audit.env_assignments(text)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", values)
        safe = json.dumps(audit.safe_env(values, audit.Labels()))
        for secret in ("very-secret", "12345", "67890"):
            self.assertNotIn(secret, safe)

    def test_config_does_not_print_custom_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(json.dumps({"TELEGRAM_BOT_TOKEN": "private-token", "quick_commands": {
                "foto": {"type": "exec", "command": "/usr/local/bin/hermes-foto-dispatch"},
                "wideo": {"type": "exec", "command": "HERMES_SESSION_CHAT_ID=67890 run --key=private-token"}}}))
            safe = audit.safe_config(path, audit.Labels())
            self.assertTrue(safe["quick_commands"]["foto"]["exact_expected_wrapper"])
            self.assertTrue(safe["quick_commands"]["wideo"]["mentions_session_override"])
            self.assertNotIn("private-token", json.dumps(safe))
            self.assertNotIn("67890", json.dumps(safe))

    def test_jobs_detect_mismatch_without_exposing_prompt_or_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "private-filename"
            job.mkdir()
            (job / "request.json").write_text(json.dumps({"target": "telegram:12345", "prompt": "private-prompt", "mode": "t2v"}))
            (job / "result.json").write_text(json.dumps({"target": "telegram:67890", "error": "secret-error", "ok": False}))
            rows = audit.safe_jobs(root, audit.Labels(), 8)
            self.assertTrue(rows[0]["target_mismatch"])
            for secret in ("12345", "67890", "private-prompt", "private-filename", "secret-error"):
                self.assertNotIn(secret, json.dumps(rows))

    def test_corrupt_job_is_reported_without_raw_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "job").mkdir()
            (root / "job/request.json").write_text("secret invalid JSON")
            rows = audit.safe_jobs(root, audit.Labels(), 8)
            self.assertEqual(rows[0]["status"], "unreadable_or_invalid_record")
            self.assertNotIn("secret", json.dumps(rows))

    def test_missing_files_are_not_reported_as_matching(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "command", return_value="baseline"):
            item = audit.compare_installed(Path(tmp) / "missing", Path(tmp), "file.py")
            self.assertFalse(item["present"])
            self.assertIsNone(item["matches_production_baseline"])

    def test_report_does_not_write_files(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "command", return_value=""):
            root = Path(tmp)
            out = audit.report(root, root, root, root, 8)
            self.assertEqual(list(root.iterdir()), [])
            self.assertEqual(out["distinct_numeric_identities"], 0)
            self.assertFalse(out["service_active"])


if __name__ == "__main__":
    unittest.main()
