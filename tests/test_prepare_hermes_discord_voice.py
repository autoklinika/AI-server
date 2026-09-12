import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "discord_config", Path(__file__).parents[1] / "tools/prepare_hermes_discord_voice.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiscordConfigTest(unittest.TestCase):
    def setUp(self):
        self.original = {
            "model": {"default": "existing-model", "provider": "custom"},
            "telegram": {"enabled": True},
            "agent": {"reasoning_effort": "none", "max_turns": 500},
            "platform_toolsets": {"telegram": ["terminal", "file", "web"]},
            "stt": {"openai": {"model": "existing-stt"}},
            "custom_providers": [{"name": "original", "model": "existing-model"}],
            "discord": {"free_response_channels": ["900"], "channel_overrides": {
                "900": {"model": "unrelated"}}},
        }

    def run_prepare(self, config):
        return module.prepare(config, "100", "200", "http://127.0.0.1:11435/clients/hermes/v1")

    def test_preserves_default_telegram_and_unrelated_settings(self):
        before = copy.deepcopy(self.original)
        result = self.run_prepare(self.original)
        self.assertEqual(self.original, before)
        for key in ("model", "telegram", "agent"):
            self.assertEqual(result[key], before[key])
        self.assertEqual(result["platform_toolsets"]["telegram"], before["platform_toolsets"]["telegram"])
        self.assertEqual(result["stt"]["openai"], before["stt"]["openai"])
        self.assertEqual(result["custom_providers"][0], before["custom_providers"][0])
        self.assertEqual(result["discord"]["channel_overrides"]["900"], {"model": "unrelated"})

    def test_idempotent(self):
        result = self.run_prepare(self.original)
        self.assertEqual(self.run_prepare(result), result)

    def test_gpu_channel_scope_and_global_title_change(self):
        result = self.run_prepare(self.original)
        for channel in ("100", "200"):
            self.assertEqual(result["discord"]["channel_overrides"][channel]["model"], module.MODEL)
        self.assertFalse(result["auxiliary"]["title_generation"]["enabled"])
        self.assertEqual(result["custom_providers"][-1]["extra_body"]["reasoning_effort"], "none")

    def test_rejects_ambiguous_provider(self):
        self.original["custom_providers"] = [{"name": module.PROVIDER}] * 2
        with self.assertRaises(ValueError):
            self.run_prepare(self.original)

    def test_rejects_invalid_channels_and_external_gateway(self):
        for text, voice, url in [("<TEXT>", "200", "http://localhost:11435"),
                                  ("100", "100", "http://localhost:11435"),
                                  ("100", "200", "https://example.com")]:
            with self.assertRaises(ValueError):
                module.prepare({}, text, voice, url)

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "CLI needs PyYAML in Hermes venv")
    def test_cli_writes_candidate_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "config.yaml"
            target = Path(directory) / "candidate.yaml"
            source.write_text("model:\n  default: existing-model\ntelegram:\n  enabled: true\n", encoding="utf-8")
            original = source.read_bytes()
            command = [sys.executable, str(Path(module.__file__)), "--input", str(source),
                       "--output", str(target), "--text-channel", "100", "--voice-channel", "200"]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            candidate = target.read_bytes()
            self.assertEqual(json.loads(candidate)["model"]["default"], "existing-model")
            self.assertEqual(source.read_bytes(), original)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(target.read_bytes(), candidate)
            command[command.index("--output") + 1] = str(source)
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
