"""Magazyn V1 adapter for EXISTING Stage K user-systemd timers.

No scheduler, unit installation, production write, GPU, or Stage K code changes.
The caller is responsible for using a bounded systemd ExecStartPre command with
a leading '-' so Magazyn failures never inhibit Stage K.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

from . import backup

REQUIRED = ("db", "spool", "key_file", "mount")
MAX_BACKUP_AGE_HOURS = 36


class BridgeFailure(Exception):
    pass


def read_config(config_file: str | Path) -> dict[str, Path]:
    path = Path(config_file)
    if path.is_symlink():
        raise BridgeFailure("Konfiguracja nie może być dowiązaniem")
    try:
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) & 0o077
                or info.st_uid != os.geteuid()):
            raise BridgeFailure("Konfiguracja musi być prywatnym plikiem właściciela 0600")
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise BridgeFailure("Brak lub nieprawidłowa konfiguracja prywatna") from exc
    if not isinstance(value, dict) or set(value) != set(REQUIRED):
        raise BridgeFailure("Konfiguracja wymaga db, spool, key_file, mount")
    paths = {}
    for name in REQUIRED:
        raw = value[name]
        if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
            raise BridgeFailure("Ścieżki konfiguracji muszą być absolutne")
        paths[name] = Path(raw)
    # The working DB, the AES key and the pending encrypted spool must stay local.
    for name in ("db", "spool", "key_file"):
        if paths[name] == paths["mount"] or paths[name].is_relative_to(paths["mount"]):
            raise BridgeFailure("Dane robocze nie mogą znajdować się na GlobalNAS")
    return paths


def _acquire_lock(spool: Path) -> int | None:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(spool / ".stage-k-bridge.lock", flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise BridgeFailure("Niebezpieczny plik blokady Magazynu")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd
    except Exception:
        os.close(fd)
        raise


def _pending_oldest_hours(spool: Path, now: datetime) -> float | None:
    files = [p for tier in backup.TIERS for p in (spool / tier).glob(f"*{backup.EXT}")
             if p.is_file() and not p.is_symlink()]
    if not files:
        return None
    oldest = min(p.stat().st_mtime for p in files)
    return round(max(0.0, (now.timestamp() - oldest) / 3600.0), 2)


def execute(mode: str, config: dict[str, Path], *, at: datetime | None = None) -> dict:
    if mode not in ("cycle", "retry"):
        raise BridgeFailure("Nieobsługiwany tryb")
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise BridgeFailure("Czas musi mieć strefę")
    now = now.astimezone(timezone.utc)
    spool = backup._secure_dir(config["spool"])
    lock = _acquire_lock(spool)
    if lock is None:
        return {"status": "BUSY", "mode": mode, "note": "Inny cykl trwa"}
    try:
        backup._update_status(spool, bridge_health="RUNNING",
                              bridge_last_check_at=now.isoformat(timespec="seconds"),
                              bridge_last_result=mode)
        snapshot_count = 0
        uploaded = 0
        errors: list[str] = []
        if mode == "cycle":
            previous = backup.status(spool)
            date = now.date().isoformat()
            if previous.get("bridge_last_snapshot_date") != date:
                try:
                    created = backup.daily_local(
                        config["db"], spool, config["key_file"], captured_at=now)
                    snapshot_count = len(created)
                    backup._update_status(
                        spool, bridge_last_snapshot_date=date,
                        bridge_last_snapshot_at=now.isoformat(timespec="seconds"))
                except (backup.BackupFailure, OSError, ValueError) as exc:
                    errors.append("Nie udało się utworzyć kopii lokalnej: " + str(exc))
        # Always retry old archives: if NAS is offline, new snapshots stay local.
        try:
            transferred = backup.flush_to_nas(spool, config["mount"], config["key_file"])
            uploaded = transferred["uploaded"]
        except (backup.BackupFailure, OSError, ValueError) as exc:
            errors.append("Wysyłka GlobalNAS: " + str(exc))

        state = backup.status(spool)
        pending = state["pending"]
        oldest_pending_hours = _pending_oldest_hours(spool, now)
        if pending:
            errors.append(f"Kopie oczekujące w lokalnym buforze: {pending}")
            if oldest_pending_hours is not None and oldest_pending_hours > 24:
                errors.append("Najstarsza zaległa kopia ma ponad 24 godziny")
        previous_snapshot = state.get("bridge_last_snapshot_at")
        if not previous_snapshot:
            errors.append("Brak dotychczasowej kopii z harmonogramu")
        else:
            try:
                previous_time = datetime.fromisoformat(previous_snapshot)
                age_hours = (now - previous_time.astimezone(timezone.utc)).total_seconds() / 3600
                if age_hours > MAX_BACKUP_AGE_HOURS:
                    errors.append("Automatyczna kopia jest starsza niż 36 godzin")
            except (TypeError, ValueError):
                errors.append("Nieprawidłowa data poprzedniej kopii")
        if errors:
            state_label = "FAIL" if any(
                t.startswith(("Nie udało się", "Brak dotychczasowej", "Nieprawidłowa", "Automatyczna"))
                for t in errors) else "DEGRADED"
        else:
            state_label = "PASS"

        result = {
            "status": state_label,
            "mode": mode,
            "created": snapshot_count,
            "uploaded": uploaded,
            "pending": pending,
            "oldest_pending_hours": oldest_pending_hours,
            "issues": errors,
        }
        fields = {
            "bridge_health": state_label,
            "bridge_last_check_at": now.isoformat(timespec="seconds"),
            "bridge_last_result": mode,
            "bridge_issues": errors,
            "bridge_oldest_pending_hours": oldest_pending_hours,
            "last_error": "; ".join(errors),
        }
        if mode == "cycle":
            fields["bridge_last_cycle_at"] = now.isoformat(timespec="seconds")
        else:
            fields["bridge_last_retry_at"] = now.isoformat(timespec="seconds")
        backup._update_status(spool, **fields)
        return result
    finally:
        os.close(lock)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Magazyn DEV / Stage K bridge")
    parser.add_argument("mode", choices=("cycle", "retry"))
    parser.add_argument("--config", required=True, help="Prywatny plik JSON 0600 (bez klucza AES)")
    arguments = parser.parse_args(argv)
    try:
        result = execute(arguments.mode, read_config(arguments.config))
    except (BridgeFailure, backup.BackupFailure, OSError) as exc:
        result = {"status": "FAIL", "reason": str(exc)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] in ("PASS", "BUSY") else 2


if __name__ == "__main__":
    sys.exit(main())
