import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "discord_secret", Path(__file__).parents[1] / "tools/install_hermes_discord_secret.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SecretMergeTest(unittest.TestCase):
    def test_preserves_other_settings(self):
        original = "OTHER_SETTING=keep\n# existing comment\n"
        result = module.extend(original, "SYNTHETIC_PLACEHOLDER", "100")
        self.assertTrue(result.startswith(original))
        self.assertIn("DISCORD_ALLOWED_USERS=100\n", result)

    def test_refuses_existing_settings(self):
        for original in ("DISCORD_BOT_TOKEN=placeholder\n",
                         " export DISCORD_ALLOWED_USERS =100\n"):
            with self.assertRaises(ValueError):
                module.extend(original, "SYNTHETIC_PLACEHOLDER", "100")

    def test_rejects_invalid_secret_without_echo(self):
        with self.assertRaises(ValueError) as context:
            module.validate("SYNTHETIC_PLACEHOLDER", "100", "200")
        self.assertNotIn("SYNTHETIC_PLACEHOLDER", str(context.exception))

    def test_rejects_newline_in_owner(self):
        with self.assertRaises(ValueError):
            module.validate("SYNTHETIC_PLACEHOLDER", "100", "200\nOTHER_SETTING=bad")


if __name__ == "__main__":
    unittest.main()
