"""Safe, admin-only restore checks for Magazyn V1.

Never replaces the working SQLite database. Archives are selected only from a
private spool or the verified GlobalNAS/Magazyn directory.
"""
from __future__ import annotations

from pathlib import Path
import re
import tempfile

from . import backup

ARCHIVE_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\.mgzb$")
MAX_DISPLAY = 60


def _listed_archives(directory: Path, source: str, tier: str) -> list[dict]:
    if directory.is_symlink() or not directory.is_dir():
        return []
    candidates = []
    for path in directory.iterdir():
        if (not ARCHIVE_NAME.fullmatch(path.name)
                or path.is_symlink() or not path.is_file()):
            continue
        size = path.stat().st_size
        if 0 < size <= backup.MAX_ARCHIVE_SIZE + 16_384:
            candidates.append({
                "source": source, "tier": tier, "name": path.name,
                "bytes": size,
            })
    return candidates


def list_archives(spool_path: str | Path, mount_path: str | Path) -> dict:
    """Public result has no product quantities, usernames, or secret paths."""
    spool = Path(spool_path)
    if not spool.is_dir() or spool.is_symlink():
        raise backup.BackupFailure("Lokalny bufor backupu nie jest skonfigurowany")
    entries = []
    for tier in backup.TIERS:
        entries.extend(_listed_archives(spool / tier, "local", tier))
    nas_online = False
    try:
        nas_root = backup._nas_target(mount_path)
        nas_online = True
        for tier in backup.TIERS:
            entries.extend(_listed_archives(nas_root / tier, "nas", tier))
    except (backup.BackupFailure, OSError):
        # The administrator can still select pending local copies.
        pass
    entries.sort(key=lambda x: x["name"], reverse=True)
    return {"nas_online": nas_online, "archives": entries[:MAX_DISPLAY]}


def resolve_archive(source: str, tier: str, name: str,
                    spool_path: str | Path, mount_path: str | Path) -> Path:
    if source not in ("nas", "local") or tier not in backup.TIERS or not ARCHIVE_NAME.fullmatch(name):
        raise backup.BackupFailure("Nieprawidłowy identyfikator kopii")
    if source == "nas":
        base = backup._nas_target(mount_path)
    else:
        base = Path(spool_path)
        if not base.is_dir() or base.is_symlink():
            raise backup.BackupFailure("Brak lokalnego bufora")
    directory = base / tier
    if directory.is_symlink() or not directory.is_dir():
        raise backup.BackupFailure("Nieprawidłowy katalog archiwum")
    archive = directory / name
    if archive.is_symlink() or not archive.is_file():
        raise backup.BackupFailure("Wybrana kopia nie istnieje")
    return archive


def test_restore(source: str, tier: str, name: str,
                 spool_path: str | Path, mount_path: str | Path,
                 key_file: str | Path) -> dict:
    archive = resolve_archive(source, tier, name, spool_path, mount_path)
    # A second read/verify checks archive integrity independently of the index.
    verified = backup.verify_archive(archive, key_file)
    with tempfile.TemporaryDirectory(prefix="magazyn-restore-check-", dir="/dev/shm") as folder:
        destination = Path(folder) / "restored.sqlite3"
        restored = backup.restore_archive(archive, destination, key_file)
        if not destination.is_file() or restored["status"] != "PASS":
            raise backup.BackupFailure("Odtworzenie kontrolne nie powiodło się")
    return {
        "status": "PASS",
        "source": source, "tier": tier, "name": name,
        "captured_at": verified["captured_at"],
        "integrity": "ok",
        "temporary_plaintext_removed": True,
        "working_database_unchanged": True,
    }
