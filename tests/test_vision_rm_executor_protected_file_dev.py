"""Regression for root-controlled Vision RM credential files (CPU-only, no network)."""
from __future__ import annotations

from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

# Direct loading avoids importing unrelated runtime dependencies on lean DEV hosts.
EXECUTOR = Path(__file__).resolve().parents[1] / "src/ai_bridge/benchmarks/vision_rm_executor.py"
SPEC = importlib.util.spec_from_file_location("vision_rm_executor_protected_file_dev", EXECUTOR)
assert SPEC and SPEC.loader
rm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rm)


class FakeResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class TestProtectedFileTransport(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.credential_file = Path(self.folder.name) / "controller.token"
        self.credential_file.write_text("fake-controller-token-for-test\n")
        self.saved_stat = Path.stat

    def root_owned_file_stat(self, target, *args, **kwargs):
        actual = self.saved_stat(target, *args, **kwargs)
        if target == self.credential_file:
            # Simulate root:control-group mode 0640 without privileges.
            return os.stat_result((
                stat.S_IFREG | 0o640,
                actual.st_ino, actual.st_dev, actual.st_nlink, 0,
                actual.st_gid, actual.st_size, actual.st_atime,
                actual.st_mtime, actual.st_ctime,
            ))
        return actual

    def transport(self, req, timeout):
        self.assertEqual(timeout, 6)
        self.assertEqual(req.full_url,
                         f"http://127.0.0.1:11575{self.request_path}")
        self.assertEqual(req.get_method(), self.request_method)
        self.assertEqual(req.get_header("X-ai-vision-executor-token"),
                         "fake-controller-token-for-test")
        if self.request_method == "POST":
            self.assertEqual(json.loads(req.data), {"source": "unit-test"})
        return FakeResponse(b'{"state":"active"}')

    def test_protected_file_keeps_api_path_for_post_get_and_delete(self):
        with patch.dict(os.environ, {
                "VISION_RM_EXECUTOR_TOKEN_FILE": str(self.credential_file),
                "VISION_RM_EXECUTOR_TOKEN": "",
            }), patch.object(Path, "stat", autospec=True,
                             side_effect=self.root_owned_file_stat), patch.object(
                                 rm, "urlopen", side_effect=self.transport):
            for method, path in [
                ("POST", "/resource/leases"),
                ("GET", "/resource/leases/test-id"),
                ("DELETE", "/resource/leases/test-id")]:
                with self.subTest(method=method):
                    self.request_method = method
                    self.request_path = path
                    result = rm.call("http://127.0.0.1:11575", method, path,
                                     {"source": "unit-test"} if method == "POST" else None)
                    self.assertEqual(result, {"state": "active"})

    def test_bearer_and_file_combination_denied(self):
        with patch.dict(os.environ, {
                "VISION_RM_EXECUTOR_TOKEN_FILE": str(self.credential_file),
                "VISION_RM_EXECUTOR_TOKEN": "should-not-be-used",
            }), patch.object(rm, "urlopen") as network:
            with self.assertRaisesRegex(rm.VisionExecutionError, "ambiguous"):
                rm.call("http://127.0.0.1:11575", "POST", "/resource/leases")
            network.assert_not_called()

    def test_untrusted_file_denied_before_network(self):
        with patch.dict(os.environ, {
                "VISION_RM_EXECUTOR_TOKEN_FILE": str(self.credential_file),
                "VISION_RM_EXECUTOR_TOKEN": "",
            }), patch.object(rm, "urlopen") as network:
            with self.assertRaisesRegex(rm.VisionExecutionError, "untrusted"):
                rm.call("http://127.0.0.1:11575", "POST", "/resource/leases")
            network.assert_not_called()

    def test_symlink_credential_denied_even_if_target_is_root_owned(self):
        alias = Path(self.folder.name) / "alias.token"
        alias.symlink_to(self.credential_file)
        with patch.dict(os.environ, {
                "VISION_RM_EXECUTOR_TOKEN_FILE": str(alias),
                "VISION_RM_EXECUTOR_TOKEN": "",
            }), patch.object(Path, "stat", autospec=True,
                             side_effect=self.root_owned_file_stat), patch.object(
                                 rm, "urlopen") as network:
            with self.assertRaisesRegex(rm.VisionExecutionError, "untrusted"):
                rm.call("http://127.0.0.1:11575", "POST", "/resource/leases")
            network.assert_not_called()

    def test_invalid_gateway_host_denied_before_network(self):
        with patch.dict(os.environ, {
                "VISION_RM_EXECUTOR_TOKEN_FILE": str(self.credential_file),
                "VISION_RM_EXECUTOR_TOKEN": "",
            }), patch.object(rm, "urlopen") as network:
            for base in ("http://external.test", "http://127.0.0.1:11575@evil.example",
                         "https://127.0.0.1:11575", "http://127.0.0.1:11575/path",
                         "http://127.0.0.1:11575?redirect=yes", "http://localhost:bad"):
                with self.subTest(base=base), self.assertRaises(ValueError):
                    rm.call(base, "GET", "/resource/leases")
            with self.assertRaises(ValueError):
                rm.call("http://127.0.0.1:11575", "GET", "//evil.example")
            network.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
