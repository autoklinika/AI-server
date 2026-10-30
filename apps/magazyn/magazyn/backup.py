"""Isolated encrypted Magazyn backups. Never mounts NAS or changes production services."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import secrets
import sqlite3
import stat
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MAGIC = b"MAGAZYN_V1_BACKUP\n"
AAD = b"magazyn/v1/sqlite-backup"
EXT = ".mgzb"
TIERS = {"daily": 7, "weekly": 4, "monthly": 3}
MAX_ARCHIVE_SIZE = 512 * 1024 * 1024  # Reasonable upper bound for small inventory V1.


class BackupFailure(Exception):
    pass


def _crypto():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise BackupFailure("Zainstaluj cryptography tylko w odizolowanym środowisku Magazynu") from exc
    return AESGCM


def _secure_dir(path: str | Path) -> Path:
    directory = Path(path).expanduser()
    if directory.is_symlink():
        raise BackupFailure("Katalog nie może być dowiązaniem symbolicznym")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not directory.is_dir() or directory.is_symlink():
        raise BackupFailure("Nieprawidłowy katalog danych")
    # Only tighten permissions on directories created/managed by this tool.
    if stat.S_IMODE(directory.stat().st_mode) & 0o077:
        raise BackupFailure("Katalog bufora i kluczy musi być prywatny (0700)")
    return directory.resolve()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # A CIFS mount may not support fsync on directory; file sync still required.
        pass


def _write_atomic(path: Path, data: bytes):
    if path.exists() or path.is_symlink():
        raise BackupFailure("Archiwum o takiej nazwie już istnieje")
    if not path.parent.is_dir():
        raise BackupFailure("Katalog archiwum nie istnieje")
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=".incomplete-", suffix=".tmp")
    tmp = Path(tmp_path)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def init_key(key_path: str | Path) -> Path:
    key = Path(key_path).expanduser()
    _secure_dir(key.parent)
    if key.is_symlink():
        raise BackupFailure("Odmowa użycia dowiązania symbolicznego klucza")
    try:
        fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError as exc:
        raise BackupFailure("Klucz już istnieje — nigdy nie nadpisujemy klucza") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_dir(key.parent)
    except Exception:
        key.unlink(missing_ok=True)
        raise
    return key


def read_key(key_path: str | Path) -> bytes:
    key = Path(key_path).expanduser()
    if key.is_symlink():
        raise BackupFailure("Odmowa użycia dowiązania symbolicznego klucza")
    try:
        info = key.stat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise BackupFailure("Klucz musi być zwykłym plikiem z uprawnieniami 0600")
        if info.st_uid != os.geteuid():
            raise BackupFailure("Klucz należy do innego użytkownika systemu")
        with key.open("rb") as stream:
            data = stream.read(33)
    except OSError as exc:
        raise BackupFailure("Nie można odczytać klucza") from exc
    if len(data) != 32:
        raise BackupFailure("Klucz musi zawierać dokładnie 32 bajty")
    return data


def _check_sqlite_connection(con: sqlite3.Connection) -> None:
    result = con.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise BackupFailure("Błąd integralności bazy SQLite")
    required = {"users", "items", "balances", "events", "locations", "sessions"}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not required.issubset(tables):
        raise BackupFailure("Baza nie jest bazą danych Magazynu V1")


def _check_sqlite(db: Path) -> None:
    con = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=10)
    try:
        _check_sqlite_connection(con)
    finally:
        con.close()


def _verify_database_bytes(data: bytes):
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(data)
        _check_sqlite_connection(con)
    except sqlite3.DatabaseError as exc:
        raise BackupFailure("Archiwum zawiera uszkodzoną bazę SQLite") from exc
    finally:
        con.close()


def _snapshot(db_path: str | Path) -> bytes:
    db = Path(db_path).expanduser()
    if not db.is_file() or db.is_symlink():
        raise BackupFailure("Baza nie istnieje lub jest dowiązaniem")
    try:
        source = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True, timeout=10)
        destination = sqlite3.connect(":memory:")
        try:
            # SQLite online-backup produces one coherent snapshot, including WAL.
            # No plaintext temporary snapshot is written to disk.
            source.backup(destination)
            _check_sqlite_connection(destination)
            data = bytearray(destination.serialize())
            if not data.startswith(b"SQLite format 3\x00"):
                raise BackupFailure("Nieprawidłowy nagłówek SQLite")
            # SQLite online-backup includes committed WAL pages. The serialized
            # stand-alone image may still carry WAL read/write version flags (2,2),
            # which cannot be deserialized into :memory: without a WAL sidecar.
            # Convert only those documented SQLite header flags to rollback (1,1).
            if data[18:20] == b"\x02\x02":
                data[18:20] = b"\x01\x01"
            elif data[18:20] != b"\x01\x01":
                raise BackupFailure("Nieobsługiwany tryb obrazu SQLite")
            if len(data) > MAX_ARCHIVE_SIZE:
                raise BackupFailure("Baza przekracza limit archiwum DEV")
            result = bytes(data)
            _verify_database_bytes(result)
            return result
        finally:
            source.close()
            destination.close()
    except sqlite3.DatabaseError as exc:
        raise BackupFailure("Nie można wykonać spójnej kopii bazy") from exc


def _payload(sqlite_bytes: bytes, captured: datetime) -> bytes:
    metadata = {
        "schema_version": 1,
        "type": "magazyn-sqlite",
        "captured_at": captured.isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(sqlite_bytes).hexdigest(),
        "bytes": len(sqlite_bytes),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(metadata, sort_keys=True))
        archive.writestr("database.sqlite3", sqlite_bytes)
    return output.getvalue()


def _seal(data: bytes, key: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return MAGIC + nonce + _crypto()(key).encrypt(nonce, data, AAD)


def _open(ciphertext: bytes, key: bytes) -> tuple[bytes, dict]:
    if not ciphertext.startswith(MAGIC) or len(ciphertext) < len(MAGIC) + 12 + 16:
        raise BackupFailure("Nieprawidłowy format archiwum")
    nonce = ciphertext[len(MAGIC):len(MAGIC)+12]
    try:
        clear = _crypto()(key).decrypt(nonce, ciphertext[len(MAGIC)+12:], AAD)
    except Exception as exc:
        raise BackupFailure("Niepoprawny klucz lub uszkodzone archiwum") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(clear)) as archive:
            if set(archive.namelist()) != {"manifest.json", "database.sqlite3"}:
                raise BackupFailure("Archiwum zawiera nieoczekiwane pliki")
            manifest = json.loads(archive.read("manifest.json"))
            entry = archive.getinfo("database.sqlite3")
            if entry.file_size > MAX_ARCHIVE_SIZE:
                raise BackupFailure("Zbyt duża baza w archiwum")
            db = archive.read("database.sqlite3")
        if manifest.get("schema_version") != 1 or manifest.get("type") != "magazyn-sqlite":
            raise BackupFailure("Nieznana wersja formatu")
        if manifest.get("sha256") != hashlib.sha256(db).hexdigest() or manifest.get("bytes") != len(db):
            raise BackupFailure("Niezgodna suma kontrolna wewnątrz archiwum")
        return db, manifest
    except (ValueError, KeyError, zipfile.BadZipFile, OSError) as exc:
        raise BackupFailure("Nie można odczytać zawartości archiwum") from exc


def verify_archive(archive_path: str | Path, key_path: str | Path) -> dict:
    key = read_key(key_path)
    path = Path(archive_path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_ARCHIVE_SIZE + 16_384:
        raise BackupFailure("Archiwum nie istnieje lub jest zbyt duże")
    raw, metadata = _open(path.read_bytes(), key)
    _verify_database_bytes(raw)
    return {"status": "PASS", "captured_at": metadata["captured_at"], "bytes": metadata["bytes"]}


def _update_status(spool: Path, **changes):
    path = spool / "backup-status.json"
    status = {}
    if path.exists():
        try:
            status = json.loads(path.read_text("utf-8"))
        except (ValueError, OSError):
            status = {}
    status.update(changes)
    encoded = json.dumps(status, ensure_ascii=False, sort_keys=True).encode()
    fd, temporary = tempfile.mkstemp(dir=spool, prefix=".status-", suffix=".tmp")
    temp = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(encoded)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        _fsync_dir(spool)
    finally:
        temp.unlink(missing_ok=True)


def status(spool_path: str | Path):
    path = Path(spool_path).expanduser()
    if not path.is_dir():
        return {"configured": False, "pending": 0}
    pending = [p for tier in TIERS for p in (path / tier).glob(f"*{EXT}") if p.is_file()]
    record = {}
    try:
        record = json.loads((path / "backup-status.json").read_text("utf-8"))
    except (OSError, ValueError):
        pass
    return {"configured": True, "pending": len(pending),
            "pending_bytes": sum(p.stat().st_size for p in pending), **record}


def create_local(db_path, spool_path, key_path, *, captured_at: datetime | None=None,
                 kinds: tuple[str,...] | None=None, max_spool_bytes=2_000_000_000):
    spool = _secure_dir(spool_path)
    key = read_key(key_path)
    captured = captured_at or datetime.now(timezone.utc)
    if captured.tzinfo is None:
        raise BackupFailure("Czas musi zawierać strefę")
    captured = captured.astimezone(timezone.utc)
    kinds = kinds or ("daily",)
    if any(k not in TIERS for k in kinds) or not kinds:
        raise BackupFailure("Nieprawidłowa retencja/tier")
    existing = status(spool)["pending_bytes"]
    sqlite_bytes = _snapshot(db_path)
    encrypted = _seal(_payload(sqlite_bytes, captured), key)
    if existing + len(encrypted)*len(kinds) > max_spool_bytes:
        raise BackupFailure("Lokalny bufor pełny: brak miejsca na kolejne kopie")
    timestamp = captured.strftime("%Y%m%dT%H%M%SZ")
    names = []
    for kind in kinds:
        directory = _secure_dir(spool / kind)
        name = f"{timestamp}-{secrets.token_hex(4)}{EXT}"
        destination = directory / name
        _write_atomic(destination, encrypted)
        names.append(str(destination))
    _update_status(spool, last_local_backup=captured.isoformat(timespec="seconds"),
                   last_error="", last_created_tiers=list(kinds))
    return names


def daily_local(db_path, spool_path, key_path, captured_at: datetime | None=None):
    captured = captured_at or datetime.now(timezone.utc)
    utc = captured.astimezone(timezone.utc)
    kinds = ["daily"]
    if utc.weekday() == 6:  # Sunday
        kinds.append("weekly")
    if utc.day == 1:
        kinds.append("monthly")
    return create_local(db_path, spool_path, key_path, captured_at=utc, kinds=tuple(kinds))


def _nas_target(mount_path: str | Path) -> Path:
    mount = Path(mount_path).expanduser()
    if mount.is_symlink() or not os.path.ismount(mount):
        raise BackupFailure("GlobalNAS nie jest zamontowany — kopie pozostają lokalnie")
    try:
        result = subprocess.run(["findmnt","-n","-M",str(mount),"-o","FSTYPE,SOURCE"],
                                capture_output=True,text=True,timeout=4,check=True)
        # Linux systemd automount can show *both* layers at this exact mount
        # point: "autofs systemd-1" and "cifs //globalnas...". Require the
        # topmost (last) layer to be the correct CIFS share, not merely an
        # autofs placeholder or a hidden CIFS below a different overlay.
        mounts = [line.strip().split(None, 1) for line in result.stdout.splitlines()
                  if line.strip()]
        if not mounts or len(mounts[-1]) != 2:
            raise BackupFailure("Nie można potwierdzić zamontowanego udziału CIFS")
        fs_type, source = mounts[-1]
        # Host identity is a private deployment setting, never committed to Git.
        expected_host = os.environ.get("MAGAZYN_EXPECTED_NAS_HOST", "").strip().lower()
        if (not expected_host or len(expected_host)>253
                or expected_host.startswith((".", "-"))
                or expected_host.endswith((".", "-"))
                or ".." in expected_host
                or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-"
                       for c in expected_host)):
            raise BackupFailure("Brak poprawnej prywatnej konfiguracji hosta NAS")
        marker = json.loads((mount/".ai-platform-backup-target.json").read_text("utf-8"))
        if (fs_type.lower()!="cifs"
            or source.lower()!=f"//{expected_host}/ai_platform"
            or marker.get("schema_version")!=1
            or marker.get("purpose")!="ai-platform-stage-k"
            or marker.get("nas")!="GlobalNAS"
            or marker.get("host")!=expected_host
            or marker.get("share")!="AI_Platform"):
            raise BackupFailure("GlobalNAS ma nieoczekiwany udział lub marker")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise BackupFailure("Nie można potwierdzić tożsamości GlobalNAS") from exc
    root = mount / "Magazyn"
    if root.is_symlink():
        raise BackupFailure("Docelowy katalog Magazynu nie może być symlinkiem")
    root.mkdir(mode=0o700, exist_ok=True)
    if not root.resolve().is_relative_to(mount.resolve()):
        raise BackupFailure("Katalog Magazyn jest poza udziałem GlobalNAS")
    return root


def flush_to_nas(spool_path, mount_path, key_path):
    spool = _secure_dir(spool_path)
    target = _nas_target(mount_path)
    copied = 0
    for tier, keep in TIERS.items():
        destination = target / tier
        if destination.is_symlink():
            raise BackupFailure("Podkatalog archiwum nie może być symlinkiem")
        destination.mkdir(mode=0o700, exist_ok=True)
        for local_file in sorted((spool / tier).glob(f"*{EXT}")):
            if local_file.is_symlink() or not local_file.is_file():
                raise BackupFailure("Niebezpieczna ścieżka lokalnego archiwum")
            new = destination / local_file.name
            verify_archive(local_file, key_path)
            data = local_file.read_bytes()
            expected = hashlib.sha256(data).digest()
            if new.exists() or new.is_symlink():
                if new.is_symlink() or hashlib.sha256(new.read_bytes()).digest() != expected:
                    raise BackupFailure("Kolizja nazwy kopii na NAS")
            else:
                _write_atomic(new, data)
                if hashlib.sha256(new.read_bytes()).digest()!=expected:
                    raise BackupFailure("Niezgodność kopii po zapisaniu na NAS")
            verify_archive(new, key_path)
            local_file.unlink()
            copied += 1
        completed = sorted(destination.glob(f"*{EXT}"), reverse=True)
        for old in completed[keep:]:
            if old.is_symlink() or not old.is_file():
                raise BackupFailure("Niebezpieczna ścieżka w retencji")
            old.unlink()
    _update_status(spool, last_synced_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   last_error="")
    return {"uploaded": copied, "pending": status(spool)["pending"]}


def restore_archive(archive_path, destination_db, key_path):
    destination = Path(destination_db).expanduser()
    if destination.exists() or destination.is_symlink():
        raise BackupFailure("Odtwarzanie nigdy nie nadpisuje istniejącej bazy; użyj nowej ścieżki")
    _secure_dir(destination.parent)
    archive = Path(archive_path)
    if not archive.is_file() or archive.is_symlink():
        raise BackupFailure("Brak archiwum")
    raw, metadata = _open(archive.read_bytes(), read_key(key_path))
    fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".restore-", suffix=".sqlite3")
    temp = Path(name)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as out:
            out.write(raw);out.flush();os.fsync(out.fileno())
        _check_sqlite(temp)
        os.link(temp,destination)   # Fails if destination exists; never overwrites.
        _fsync_dir(destination.parent)
    finally:
        temp.unlink(missing_ok=True)
    return {"status":"PASS","restored_to":str(destination),"captured_at":metadata["captured_at"]}


def main(argv=None):
    p=argparse.ArgumentParser(description="Magazyn V1 — kopie szyfrowane (DEV, bez instalacji usług)")
    sub=p.add_subparsers(dest="command",required=True)
    key=sub.add_parser("init-key");key.add_argument("--key-file",required=True)
    snap=sub.add_parser("snapshot")
    snap.add_argument("--db",required=True);snap.add_argument("--spool",required=True)
    snap.add_argument("--key-file",required=True)
    upload=sub.add_parser("flush")
    upload.add_argument("--spool",required=True);upload.add_argument("--mount",required=True)
    upload.add_argument("--key-file",required=True)
    review=sub.add_parser("status");review.add_argument("--spool",required=True)
    verify=sub.add_parser("verify")
    verify.add_argument("--archive",required=True);verify.add_argument("--key-file",required=True)
    restore=sub.add_parser("restore")
    restore.add_argument("--archive",required=True);restore.add_argument("--key-file",required=True)
    restore.add_argument("--destination",required=True)
    a=p.parse_args(argv)
    try:
        if a.command=="init-key":
            answer={"key_created_at":str(init_key(a.key_file)), "note":"Zabezpiecz kopię klucza poza NAS"}
        elif a.command=="snapshot":
            answer={"created":daily_local(a.db,a.spool,a.key_file)}
        elif a.command=="flush":
            answer=flush_to_nas(a.spool,a.mount,a.key_file)
        elif a.command=="status":
            answer=status(a.spool)
        elif a.command=="verify":
            answer=verify_archive(a.archive,a.key_file)
        else:
            answer=restore_archive(a.archive,a.destination,a.key_file)
        print(json.dumps(answer,ensure_ascii=False))
        return 0
    except BackupFailure as exc:
        print(json.dumps({"status":"FAIL","reason":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
