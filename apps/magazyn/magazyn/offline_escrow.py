"""Wrap the existing Magazyn AES key to an independent OFF-HOST age recipient.

This command never generates or stores the private recovery identity on the AI
server. An operator must generate the identity on an independent computer and
keep it offline. A public recipient alone is safe to import.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from . import backup

ARCHIVE_NAME = "magazyn-v1-aes256-key-offline.age"
AGE_HEADER = b"age-encryption.org/v1\n"


def read_public_recipient(recipient_file: str | Path) -> str:
    path = Path(recipient_file)
    if path.is_symlink() or not path.is_file():
        raise backup.BackupFailure("Brak publicznego recipienta offline")
    try:
        recipients = [x.strip() for x in path.read_text("utf-8").splitlines()
                      if x.strip() and not x.lstrip().startswith("#")]
    except (UnicodeError, OSError) as exc:
        raise backup.BackupFailure("Nieprawidłowy plik publicznego recipienta") from exc
    if (len(recipients) != 1 or
            not re.fullmatch(r"age1[a-z0-9]{40,90}", recipients[0]) or
            recipients[0].startswith("age1yubikey1")):
        raise backup.BackupFailure("Wymagany jeden publiczny age X25519 recipient")
    return recipients[0]


def wrap_offline(key_file: str | Path, recipient_file: str | Path,
                 mount_path: str | Path, *, age_bin="/usr/bin/age") -> dict:
    """Write only age ciphertext to an exclusive filename on verified NAS."""
    recipient = read_public_recipient(recipient_file)
    aes_key = backup.read_key(key_file)
    if not Path(age_bin).is_file():
        raise backup.BackupFailure("Narzędzie age nie jest dostępne")
    try:
        proc = subprocess.run(
            [age_bin, "-r", recipient], input=aes_key, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise backup.BackupFailure("Niedostępne szyfrowanie zewnętrznego recipienta") from exc
    ciphertext = proc.stdout
    if (proc.returncode != 0 or not ciphertext.startswith(AGE_HEADER)
            or len(ciphertext) < 100 or len(ciphertext) > 4096
            or aes_key in ciphertext):
        raise backup.BackupFailure("Nie można zaszyfrować klucza dla offline recovery")
    root = backup._nas_target(mount_path)
    folder = root / "recovery"
    if folder.is_symlink():
        raise backup.BackupFailure("Katalog recovery jest dowiązaniem")
    folder.mkdir(mode=0o700, exist_ok=True)
    if not folder.resolve().is_relative_to(root.resolve()):
        raise backup.BackupFailure("Nieprawidłowa ścieżka recovery")
    archive = folder / ARCHIVE_NAME
    backup._write_atomic(archive, ciphertext)
    if hashlib.sha256(archive.read_bytes()).digest() != hashlib.sha256(ciphertext).digest():
        raise backup.BackupFailure("Błąd zapisu zaszyfrowanego klucza na NAS")
    return {
        "status": "OFFLINE_RECOVERY_CIPHERTEXT_PASS",
        "ciphertext_bytes": archive.stat().st_size,
        "recipient_fingerprint": hashlib.sha256(recipient.encode()).hexdigest()[:16],
        "private_identity_was_on_server": False,
        "off_host_private_key_restore_verified": False,
        "existing_aes_key_unchanged": True,
        "archive_name": ARCHIVE_NAME,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline AES escrow, no private key on AI Platform")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--public-recipient-file", required=True)
    parser.add_argument("--mount", default="/mnt/AI_Platform")
    args = parser.parse_args(argv)
    try:
        result = wrap_offline(args.key_file, args.public_recipient_file, args.mount)
    except backup.BackupFailure as exc:
        result = {"status": "BLOCKED", "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "OFFLINE_RECOVERY_CIPHERTEXT_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
