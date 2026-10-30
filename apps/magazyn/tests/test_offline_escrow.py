"""Offline age recipient tests: synthetic AES and identities, no real key material."""
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from magazyn import backup, offline_escrow
from test_magazyn import scenario


def offline_identity(tmp_path):
    identity = tmp_path / "offline-identity.txt"
    created = subprocess.run(["age-keygen", "-o", str(identity)],
                             capture_output=True, text=True, check=True)
    public = next(line.split(": ", 1)[1].strip() for line in created.stderr.splitlines()
                  if line.startswith("Public key: "))
    recipient = tmp_path / "public-recipient.txt"
    recipient.write_text(public + "\n", encoding="utf-8")
    return identity, recipient


def mock_nas(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGAZYN_EXPECTED_NAS_HOST", "nas.fixture.invalid")
    mount = tmp_path / "fake-nas"
    mount.mkdir(mode=0o700)
    (mount / ".ai-platform-backup-target.json").write_text(
        '{"schema_version":1,"purpose":"ai-platform-stage-k",'
        '"nas":"GlobalNAS","host":"nas.fixture.invalid","share":"AI_Platform"}')
    original_ismount = backup.os.path.ismount
    original_run = subprocess.run
    monkeypatch.setattr(backup.os.path, "ismount",
                        lambda path: Path(path) == mount or original_ismount(path))

    def run(command, *args, **kwargs):
        if command[0] == "findmnt":
            return SimpleNamespace(stdout="cifs //nas.fixture.invalid/AI_Platform\n")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(backup.subprocess, "run", run)
    return mount, original_run


def test_offline_wrap_real_encryption_and_private_identity_not_copied(tmp_path, monkeypatch):
    aes_file = backup.init_key(tmp_path / "protected" / "aes.key")
    identity, recipient = offline_identity(tmp_path)
    mount, original_run = mock_nas(tmp_path, monkeypatch)
    result = offline_escrow.wrap_offline(aes_file, recipient, mount)
    assert result["status"] == "OFFLINE_RECOVERY_CIPHERTEXT_PASS"
    assert result["private_identity_not_required_or_used"] is True
    archive = mount / "Magazyn" / "recovery" / offline_escrow.ARCHIVE_NAME
    ciphertext = archive.read_bytes()
    assert ciphertext.startswith(offline_escrow.AGE_HEADER)
    assert backup.read_key(aes_file) not in ciphertext
    assert not (mount / "Magazyn" / "recovery" / identity.name).exists()
    decrypted = original_run(["age", "-d", "-i", str(identity)], input=ciphertext,
                             capture_output=True, check=True).stdout
    assert decrypted == backup.read_key(aes_file)
    with pytest.raises(backup.BackupFailure, match="już istnieje"):
        offline_escrow.wrap_offline(aes_file, recipient, mount)


def test_offline_requires_one_x25519_recipient(tmp_path):
    recipient = tmp_path / "recipient"
    recipient.write_text("age1yubikey1something-bogus\n")
    with pytest.raises(backup.BackupFailure):
        offline_escrow.read_public_recipient(recipient)
    recipient.write_text("not-a-valid-age-identity\n")
    with pytest.raises(backup.BackupFailure):
        offline_escrow.read_public_recipient(recipient)
    recipient.write_text("age1" + "a" * 59 + "\nage1" + "b" * 59)
    with pytest.raises(backup.BackupFailure):
        offline_escrow.read_public_recipient(recipient)
    recipient.unlink()
    with pytest.raises(backup.BackupFailure):
        offline_escrow.read_public_recipient(recipient)


def test_offline_no_nas_no_secret_copy(tmp_path):
    key = backup.init_key(tmp_path / "key" / "aes.key")
    identity, recipient = offline_identity(tmp_path)
    nonexistent = tmp_path / "no-nas"
    nonexistent.mkdir()
    with pytest.raises(backup.BackupFailure, match="nie jest zamontowany"):
        offline_escrow.wrap_offline(key, recipient, nonexistent)
    assert backup.read_key(key)
