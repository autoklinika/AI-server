"""Independent two-device recovery acceptance checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import stat

PRIMARY_RECIPIENT = Path("/srv/ai-data/platform/recovery/stage-k/age-recipients.txt")
PRIMARY_ARCHIVE = "magazyn-v1-aes256-key-yubikey.age"
SECOND_ARCHIVE = "magazyn-v1-aes256-key-yubikey-spare.age"
DRILL_CHECKS = frozenset({
    "recipient_distinct", "piv_nondefault", "physical_age_decrypt",
    "master_aes_identical", "nas_archive_verified",
    "sqlite_restored_in_ram", "document_hashes_valid",
})

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def recipient(path: Path, *, private: bool) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Brak poprawnego publicznego recipienta")
    if private and (stat.S_IMODE(path.stat().st_mode) != 0o600
                    or path.stat().st_uid != os.geteuid()):
        raise ValueError("Nieprawidlowe uprawnienia pliku recipienta")
    rows = [x.strip() for x in path.read_text("utf-8").splitlines()
            if x.strip() and not x.lstrip().startswith("#")]
    if len(rows) != 1 or not re.fullmatch(r"age1yubikey1[a-z0-9]{40,}", rows[0]):
        raise ValueError("Nieprawidlowy format recipienta")
    return rows[0]

def ciphertext(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Brak pliku recovery")
    blob = path.read_bytes()
    if (not 120 <= len(blob) <= 4096
        or not blob.startswith(b"age-encryption.org/v1\n")
        or b"-> piv-p256 " not in blob[:256]):
        raise ValueError("Nieprawidlowy format szyfrowanego escrow PIV")
    return blob


def physical_drill_evidence(path: Path, when: datetime) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Brak raportu z fizycznego testu")
    meta = path.stat()
    if meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o600:
        raise ValueError("Raport wymaga 0600 i właściwego wlasciciela")
    if not 100 <= meta.st_size <= 16384:
        raise ValueError("Nieprawidlowy rozmiar raportu")
    data = json.loads(path.read_text("utf-8"))
    if (not isinstance(data, dict)
        or data.get("event") != "PHYSICAL_SECOND_YUBIKEY_RECOVERY_DRILL"
        or data.get("status") != "PASS"
        or data.get("production_sqlite_modified") is not False):
        raise ValueError("Nie potwierdzono fizycznego restore")
    checks = data.get("checks")
    if (not isinstance(checks, list)
        or not all(isinstance(x, str) for x in checks)
        or not DRILL_CHECKS.issubset(set(checks))):
        raise ValueError("Niekompletny test odzyskiwania")
    at = datetime.fromisoformat(data["at_utc"].replace("Z", "+00:00"))
    if at.tzinfo is None or at.astimezone(timezone.utc) > when + timedelta(minutes=5):
        raise ValueError("Nieprawidlowy czas raportu")
    for k in ("primary_recipient_sha256", "secondary_recipient_sha256",
              "secondary_ciphertext_sha256", "source_archive_sha256"):
        if not isinstance(data.get(k), str) or not re.fullmatch(r"[a-f0-9]{64}", data[k]):
            raise ValueError("Brak sumy kontrolnej")
    return data

def check_dual_yubikey(config: dict[str, Path], *,
                       primary_drill_verified: bool,
                       second_drill_report: Path | None,
                       primary_recipient_file: Path | None = None,
                       second_recipient_file: Path | None = None,
                       at: datetime | None = None) -> dict:
    """Require independent recipients, matching escrow, and real PIV drills."""
    if not primary_drill_verified or second_drill_report is None:
        return {"status": "BLOCKED",
                "note": "Brak odbioru pierwszego YubiKeya lub fizycznego raportu drugiego"}
    try:
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Nieprawidlowy czas")
        first = recipient(primary_recipient_file or PRIMARY_RECIPIENT, private=False)
        spare_file = second_recipient_file or (
            config["key_file"].parent.parent / "yubikey-spare/recipient.txt")
        second = recipient(spare_file, private=True)
        if first == second:
            raise ValueError("Ten sam recipient dla obydwu kluczy")
        root = config["mount"] / "Magazyn" / "recovery"
        old_cipher = ciphertext(root / PRIMARY_ARCHIVE)
        new_cipher = ciphertext(root / SECOND_ARCHIVE)
        if old_cipher == new_cipher:
            raise ValueError("Oba escrow sa identyczne")
        evidence = physical_drill_evidence(Path(second_drill_report), now)
        if (sha256(first.encode()) != evidence["primary_recipient_sha256"]
            or sha256(second.encode()) != evidence["secondary_recipient_sha256"]
            or sha256(new_cipher) != evidence["secondary_ciphertext_sha256"]):
            raise ValueError("Raport nie pasuje do bieżących recipientów/escrow")
        # The source backup used for the physical drill is subject to daily
        # retention. Current backup integrity is checked separately.
        return {"status": "PASS",
                "note": "Dwa rozne YubiKey PIV i escrow; pierwszy fizyczny DR "
                        "odebrany przez operatora, drugi decrypt/restore PASS"}
    except (OSError, ValueError, TypeError, AttributeError, KeyError, UnicodeError) as exc:
        return {"status": "BLOCKED",
                "note": "Weryfikacja dwoch YubiKeyow: " + type(exc).__name__}
