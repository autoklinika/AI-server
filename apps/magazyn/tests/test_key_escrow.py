"""YubiKey age AES recovery wrapping uses only synthetic secrets and fake NAS."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from magazyn import backup, key_escrow


PUBLIC_TEST_RECIPIENT = "age1yubikey1" + "q" * 55


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    keys = private / "keys"
    path = backup.init_key(keys / "aes.key")
    recipient = private / "recipients.txt"
    recipient.write_text(PUBLIC_TEST_RECIPIENT + "\n", encoding="utf-8")
    fakeage = private / "runtime" / "age"
    fakeage.parent.mkdir(mode=0o700)
    fakeage.write_text("synthetic", encoding="ascii")
    plugin = fakeage.parent / "age-plugin-yubikey"
    plugin.write_text("synthetic", encoding="ascii")
    plugin.chmod(0o700)
    nas = private / "fake-nas" / "Magazyn"
    nas.mkdir(mode=0o700, parents=True)
    monkeypatch.setattr(backup, "_nas_target", lambda _mount: nas)

    calls = []
    def fake_subprocess(args, *, input, stdout, stderr, timeout, check, env):
        calls.append((args, input))
        assert args == [str(fakeage), "-R", str(recipient)]
        assert len(input) == 32
        assert env["PATH"].startswith(str(fakeage.parent))
        return SimpleNamespace(
            returncode=0,
            stdout=key_escrow.AGE_HEADER + b"-> age1yubikey1mock\n" + b"x"*190,
            stderr=b"",
        )
    monkeypatch.setattr(key_escrow.subprocess, "run", fake_subprocess)
    return path, recipient, fakeage, nas, calls


def test_wrap_to_verified_nas_without_plaintext(synthetic):
    source, recipient, age, nas, calls = synthetic
    before = source.read_bytes()
    result = key_escrow.write_recovery_to_nas(
        source, recipient, nas.parent, age_bin=str(age))
    assert result["status"] == "YUBIKEY_AES_RECOVERY_KEY_WRAP_PASS"
    assert result["recipients"] == 1
    assert result["physical_yubikey_used_for_encryption"] is False
    target = nas / "recovery" / key_escrow.RECOVERY_FILENAME
    data = target.read_bytes()
    assert data.startswith(key_escrow.AGE_HEADER)
    assert before not in data
    assert source.read_bytes() == before
    assert (target.stat().st_mode & 0o777) == 0o600
    assert len(calls) == 1
    with pytest.raises(backup.BackupFailure, match="istnieje"):
        key_escrow.write_recovery_to_nas(
            source, recipient, nas.parent, age_bin=str(age))
    assert target.read_bytes() == data


def test_invalid_recipient_rejected_before_any_nas_write(synthetic):
    source, recipient, age, nas, calls = synthetic
    recipient.write_text("ssh-ed25519 AAAAFAKE\n", encoding="utf-8")
    with pytest.raises(backup.BackupFailure, match="age-plugin-yubikey"):
        key_escrow.write_recovery_to_nas(
            source, recipient, nas.parent, age_bin=str(age))
    assert calls == []
    assert not (nas/"recovery").exists()


def test_insecure_key_refused(synthetic):
    source, recipient, age, nas, calls = synthetic
    source.chmod(0o644)
    with pytest.raises(backup.BackupFailure, match="0600"):
        key_escrow.write_recovery_to_nas(
            source, recipient, nas.parent, age_bin=str(age))
    assert calls == []


def test_age_failure_does_not_leak_secret_or_create_file(synthetic, monkeypatch):
    source, recipient, age, nas, calls = synthetic
    secret = source.read_bytes()
    monkeypatch.setattr(key_escrow.subprocess, "run", lambda *args, **kwargs:
        SimpleNamespace(returncode=1, stdout=b"", stderr=b"token secret leak"))
    with pytest.raises(backup.BackupFailure) as caught:
        key_escrow.write_recovery_to_nas(
            source, recipient, nas.parent, age_bin=str(age))
    assert secret.hex() not in str(caught.value)
    assert "token secret leak" not in str(caught.value)
    assert not (nas/"recovery").exists()


def test_nas_rejection_blocks_write(synthetic, monkeypatch):
    source, recipient, age, nas, calls = synthetic
    monkeypatch.setattr(backup, "_nas_target", lambda _mount: (_ for _ in ()).throw(
        backup.BackupFailure("GlobalNAS ma nieoczekiwany udział lub marker")))
    with pytest.raises(backup.BackupFailure, match="GlobalNAS"):
        key_escrow.write_recovery_to_nas(
            source, recipient, nas.parent, age_bin=str(age))
    assert not (nas/"recovery").exists()


def test_recovery_path_symlink_is_blocked(synthetic):
    source, recipient, age, nas, calls = synthetic
    elsewhere = nas.parent / "not-a-recovery"
    elsewhere.mkdir(mode=0o700)
    (nas / "recovery").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(backup.BackupFailure, match="symlinkiem"):
        key_escrow.write_recovery_to_nas(
            source, recipient, nas.parent, age_bin=str(age))
    assert list(elsewhere.iterdir()) == []
