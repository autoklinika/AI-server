"""One-time YubiKey/age protection for the existing Magazyn AES recovery key.

This complements AES-256-GCM archives. Normal unattended backups keep using
the existing private AES key. Only recovery after loss of the server requires
the physical YubiKey with its non-exportable PIV key and PIN.

Encryption works from Stage K's age public recipient without the YubiKey
connected. Never write plaintext keys into logs, repo, CLI args, or NAS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from . import backup

DEFAULT_AGE = "/srv/ai-data/tools/age/usr/bin/age"
DEFAULT_RECIPIENTS = "/srv/ai-data/platform/recovery/stage-k/age-recipients.txt"
RECOVERY_FILENAME = "magazyn-v1-aes256-key-yubikey.age"
AGE_HEADER = b"age-encryption.org/v1\n"


def _public_yubikey_recipient(path: str | Path) -> str:
    public_file = Path(path).expanduser()
    if public_file.is_symlink() or not public_file.is_file():
        raise backup.BackupFailure("Brak bezpiecznego pliku publicznego recipienta Stage K")
    try:
        rows = [row.strip() for row in public_file.read_text("utf-8").splitlines()
                if row.strip() and not row.lstrip().startswith("#")]
    except (OSError, UnicodeError) as exc:
        raise backup.BackupFailure("Błąd odczytu recipienta Stage K") from exc
    if (len(rows) != 1 or not rows[0].startswith("age1yubikey1")
            or len(rows[0]) < 45 or not re.fullmatch(r"[a-z0-9]+", rows[0])):
        raise backup.BackupFailure(
            "Wymagany dokładnie jeden recipient age-plugin-yubikey")
    return rows[0]


def encrypt_key_for_recovery(key_file: str | Path, recipient_file: str | Path,
                             *, age_bin: str = DEFAULT_AGE) -> bytes:
    """Only age ciphertext is returned; never print or persist plaintext."""
    key = backup.read_key(key_file)
    _public_yubikey_recipient(recipient_file)
    age = Path(age_bin)
    plugin = age.parent / "age-plugin-yubikey"
    if not age.is_file() or not plugin.is_file() or not os.access(plugin, os.X_OK):
        raise backup.BackupFailure("Brak age lub age-plugin-yubikey Stage K")
    environment = dict(os.environ)
    environment["PATH"] = str(age.parent) + os.pathsep + environment.get("PATH", "")
    try:
        proc = subprocess.run(
            [str(age), "-R", str(recipient_file)],
            input=key, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=25, check=False, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise backup.BackupFailure(
            "Nie można zaszyfrować klucza odzyskiwania przez age") from None
    # stderr may include command-line context, so never surface it.
    encrypted = proc.stdout
    if (proc.returncode != 0 or not encrypted.startswith(AGE_HEADER)
            or len(encrypted) < 120 or len(encrypted) > 4096
            or key in encrypted):
        raise backup.BackupFailure(
            "Niepowodzenie szyfrowania klucza dla YubiKey")
    return encrypted


def write_recovery_to_nas(
    key_file: str | Path,
    recipient_file: str | Path = DEFAULT_RECIPIENTS,
    mount_path: str | Path = "/mnt/AI_Platform",
    *, age_bin: str = DEFAULT_AGE,
) -> dict:
    """Create exactly one ciphertext inside verified GlobalNAS/Magazyn.

    Existing key archives and Stage K backup files are never overwritten.
    """
    encrypted = encrypt_key_for_recovery(key_file, recipient_file, age_bin=age_bin)
    # Validates real CIFS mount and Stage K marker *before* making directories.
    magazyn = backup._nas_target(mount_path)
    folder = magazyn / "recovery"
    if folder.is_symlink():
        raise backup.BackupFailure("Katalog odzyskiwania jest symlinkiem")
    folder.mkdir(mode=0o700, exist_ok=True)
    if not folder.resolve().is_relative_to(magazyn.resolve()):
        raise backup.BackupFailure("Nieprawidłowa ścieżka odzyskiwania")
    destination = folder / RECOVERY_FILENAME
    if destination.is_symlink() or destination.exists():
        raise backup.BackupFailure(
            "Kopia klucza już istnieje; nie nadpisujemy jej ani nie zmieniamy AES")
    backup._write_atomic(destination, encrypted)
    readback = destination.read_bytes()
    if (readback != encrypted or not readback.startswith(AGE_HEADER)
            or hashlib.sha256(readback).digest() != hashlib.sha256(encrypted).digest()):
        raise backup.BackupFailure(
            "Błąd kontroli zaszyfrowanego klucza po zapisie na NAS")
    return {
        "status": "YUBIKEY_AES_RECOVERY_KEY_WRAP_PASS",
        "archive": str(destination),
        "ciphertext_bytes": len(readback),
        "recipients": 1,
        "physical_yubikey_used_for_encryption": False,
        "decrypt_verified_with_physical_key": False,
        "existing_aes_key_unchanged": True,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Magazyn DEV — zapisz zaszyfrowany YubiKey recovery klucz AES na NAS")
    parser.add_argument("command", choices=("wrap",))
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--recipients", default=DEFAULT_RECIPIENTS)
    parser.add_argument("--mount", default="/mnt/AI_Platform")
    arguments = parser.parse_args(argv)
    try:
        result = write_recovery_to_nas(
            arguments.key_file, arguments.recipients, arguments.mount)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except backup.BackupFailure as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)},
                         ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
