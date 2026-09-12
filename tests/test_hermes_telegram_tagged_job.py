import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tagged_job", ROOT / "tools/inspect_hermes_telegram_tagged_job.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
TAG = "TEST_TRASY_B_0909_01"
LABELS = {"123456": "HOME_CHANNEL", "789012": "OTHER_ALLOWED_1"}


class TaggedJobTests(unittest.TestCase):
    def test_routes_and_invalid_input_never_expose_ids(self):
        self.assertEqual(mod.route_summary("telegram:123456", LABELS)["recipient"], "HOME_CHANNEL")
        self.assertEqual(mod.route_summary("telegram:789012:17", LABELS), {"recipient": "OTHER_ALLOWED_1", "topic_present": True})
        for value in (None, "secret", "telegram:0", "telegram:123456:secret"):
            self.assertEqual(mod.route_summary(value, LABELS)["recipient"], "unset_or_invalid")

    def test_only_exact_tag_is_reported_and_private_fields_are_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prompt in (("private-name", TAG + " private-prompt"), ("other", TAG + "_NO")):
                job = root / "hermes-foto-jobs" / name
                job.mkdir(parents=True)
                (job / "request.json").write_text(json.dumps({"prompt": prompt, "target": "telegram:789012", "mode": "generate", "created_at": "2026-09-09T10:00:00+02:00"}))
                (job / "result.json").write_text(json.dumps({"target": "telegram:123456", "ok": False, "error": "SECRET_ERROR"}))
            result = mod.inspect(root, TAG, LABELS)
            self.assertEqual(result["match_count"], 1)
            row = result["matches"][0]
            self.assertFalse(row["request_result_same_target"])
            self.assertEqual(row["created_at_utc"], "2026-09-09T08:00:00+00:00")
            output = json.dumps(result)
            for secret in ("123456", "789012", "private-name", "private-prompt", "SECRET_ERROR"):
                self.assertNotIn(secret, output)

    def test_pending_and_corrupt_result_are_distinguished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "hermes-video-jobs" / "job"
            job.mkdir(parents=True)
            (job / "request.json").write_text(json.dumps({"prompt": TAG, "target": "telegram:789012"}))
            row = mod.inspect(root, TAG, LABELS)["matches"][0]
            self.assertEqual(row["result_state"], "not_yet_present")
            self.assertIsNone(row["worker_reported_ok"])
            (job / "result.json").write_text("not-json secret")
            self.assertEqual(mod.inspect(root, TAG, LABELS)["matches"][0]["result_state"], "unreadable")

    def test_missing_root_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(mod.inspect(root, TAG, LABELS)["match_count"], 0)
            self.assertEqual(list(root.iterdir()), [])

    def test_invalid_tags_are_rejected(self):
        for tag in ("bad", "TAG ; echo SECRET", "a" * 100):
            with self.assertRaises(ValueError):
                mod.inspect(Path("/nonexistent"), tag, {})

    def test_invalid_time_does_not_leak(self):
        for value in ("secret-time", True, "2026-09-09", float("inf"), None):
            self.assertIsNone(mod.safe_time(value))

    def test_dotenv_labels_exclude_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text('TELEGRAM_BOT_TOKEN=SECRET_TOKEN\nTELEGRAM_HOME_CHANNEL="123456"\nTELEGRAM_ALLOWED_USERS="123456,789012"\n')
            labels, state = mod.routing_labels(root)
            self.assertEqual(labels, LABELS)
            self.assertEqual(state, "read")
            self.assertNotIn("SECRET_TOKEN", json.dumps(labels))


if __name__ == "__main__":
    unittest.main()
