"""Read-only Magazyn V1 production readiness gate.

Runs locally, no scheduler, service changes, privileged access, data writes,
network uploads, or production activation. Explicit human sign-offs remain
separate from machine-verifiable facts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import stat
import urllib.request
from pathlib import Path
import sqlite3
import sys
from xml.etree import ElementTree

from . import backup, yubikey_recovery_gate
from .stage_k_bridge import read_config

REQUIRED_WEEKLY_RESTORE = ("knowledge", "domains", "adapters")


def _age_hours(value: str, at: datetime) -> float:
    when=datetime.fromisoformat(value.replace("Z","+00:00"))
    if when.tzinfo is None:
        raise ValueError("Brak strefy czasowej")
    return (at-when.astimezone(timezone.utc)).total_seconds()/3600


def _read_json(path: Path) -> dict:
    data=json.loads(path.read_text("utf-8"))
    if not isinstance(data,dict):
        raise ValueError("Oczekiwany obiekt JSON")
    return data


def _pass(value: bool, success: str, failure: str) -> dict:
    return {"status":"PASS" if value else "BLOCKED",
            "note":success if value else failure}


def check_db(path: Path) -> dict:
    try:
        if not path.is_file() or path.is_symlink():
            raise ValueError("Brak lokalnej bazy SQLite")
        meta=path.stat()
        if stat.S_IMODE(meta.st_mode)!=0o600 or meta.st_uid!=os.geteuid():
            raise ValueError("Baza musi mieć uprawnienia 0600 i właściwego właściciela")
        con=sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True,timeout=8)
        try:
            schema=con.execute("PRAGMA user_version").fetchone()[0]
            integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys=con.execute("PRAGMA foreign_key_check").fetchall()
            docs=con.execute("SELECT content,sha256 FROM item_documents").fetchall()
            broken_docs=any(hashlib.sha256(raw).hexdigest()!=digest
                            for raw,digest in docs)
            admins=con.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1"
            ).fetchone()[0]
            return _pass(
                schema==3 and integrity=="ok" and not foreign_keys
                and not broken_docs and admins>=1,
                "SQLite v3 + relacje + dokumenty + aktywny administrator",
                "Błąd integralności SQLite, dokumentów lub kont administratora")
        finally:
            con.close()
    except (OSError,ValueError,sqlite3.Error) as exc:
        return {"status":"BLOCKED","note":"Baza nie przeszła kontroli: "+type(exc).__name__}


def check_magazyn_backup(config: dict[str,Path], at: datetime) -> dict:
    try:
        summary=backup.status(config["spool"])
        current=summary.get("bridge_health")=="PASS" and summary.get("pending")==0
        fresh=0 <= _age_hours(summary["bridge_last_snapshot_at"],at) <= 36
        synchronized=0 <= _age_hours(summary["last_synced_at"],at) <= 36
        nas=backup._nas_target(config["mount"])/"daily"
        paths=sorted(nas.glob("*"+backup.EXT),reverse=True)
        assert paths,"Brak archiwów dziennych Magazynu"
        validated=backup.verify_archive(paths[0],config["key_file"])
        assert validated["status"]=="PASS"
        return _pass(current and fresh and synchronized,
                     "Szyfrowane archiwum GlobalNAS zweryfikowane, bufor pusty, cykl świeży",
                     "Archiwum poprawne, ale cykl/monitor zaległy lub bufor niepusty")
    except Exception as exc:
        return {"status":"BLOCKED","note":"Kontrola backupu: "+type(exc).__name__}


def check_stage_k(stage_k_dir: Path, at: datetime) -> dict:
    try:
        daily=_read_json(stage_k_dir/"daily.json")
        weekly=_read_json(stage_k_dir/"weekly.json")
        daily_ok=daily.get("status")=="PASS" and (
            -1 <= _age_hours(daily["completed_at"],at) <= 48)
        restore=weekly.get("restore_validation") or {}
        restores_ok=all(isinstance(restore.get(domain),dict) and
                        restore[domain].get("status")=="PASS"
                        for domain in REQUIRED_WEEKLY_RESTORE)
        weekly_ok=(weekly.get("status")=="PASS" and restores_ok and
                   -1 <= _age_hours(weekly["completed_at"],at) <= 9*24)
        return {
            "daily":_pass(daily_ok,"Stage K daily niedawno PASS",
                          "Brak aktualnego PASS Stage K daily"),
            "weekly":_pass(weekly_ok,"Stage K weekly backup i wszystkie restore PASS",
                           "Brak aktualnego PASS tygodniowego backupu i pełnego restore Stage K"),
        }
    except (OSError,ValueError,TypeError,KeyError) as exc:
        failure={"status":"BLOCKED","note":"Nie można potwierdzić Stage K: "+type(exc).__name__}
        return {"daily":failure,"weekly":failure}


def check_https(url: str) -> dict:
    if not url.startswith("https://"):
        return {"status":"BLOCKED","note":"Wymagane HTTPS"}
    try:
        with urllib.request.urlopen(url.rstrip("/")+"/healthz",timeout=7) as response:
            result=json.loads(response.read(1024))
            valid=response.status==200 and result.get("status")=="ok"
        return _pass(valid,"Certyfikat TLS zweryfikowany i healthz=ok",
                     "HTTPS nie zwróciło poprawnego healthz")
    except (OSError,ValueError,TimeoutError) as exc:
        return {"status":"BLOCKED","note":"HTTPS niedostępne: "+type(exc).__name__}


def check_tests(report: Path | None) -> dict:
    if report is None:
        return {"status":"BLOCKED","note":"Brak końcowego raportu pytest/JUnit"}
    try:
        root=ElementTree.parse(report).getroot()
        if root.tag=="testsuites":
            suites=root.findall("testsuite")
        elif root.tag=="testsuite":
            suites=[root]
        else:
            raise ValueError("Nieprawidłowe JUnit")
        counts={field:sum(int(s.get(field,"0")) for s in suites)
                for field in ("tests","failures","errors","skipped")}
        ok=(counts["tests"]>=190 and counts["failures"]==0 and
            counts["errors"]==0)
        return _pass(ok,f"Pytest: {counts['tests']} testów, 0 błędów",
                     "Brak pełnego zestawu testów PASS")
    except (OSError,ValueError,ElementTree.ParseError) as exc:
        return {"status":"BLOCKED","note":"Niepoprawny raport testów: "+type(exc).__name__}


def production_readiness(config: dict[str,Path], stage_k_dir: Path,
                         *, at: datetime | None=None, junit: Path | None=None,
                         primary_yubikey_drill_verified: bool=False,
                         spare_yubikey_drill_report: Path | None=None,
                         primary_recipient_file: Path | None=None,
                         spare_recipient_file: Path | None=None,
                         daily_timer_verified: bool=False,
                         employee_acl_verified: bool=False,
                         https_url: str | None=None) -> dict:
    instant=at or datetime.now(timezone.utc)
    checks={"sqlite":check_db(config["db"]),
            "magazyn_backup":check_magazyn_backup(config,instant)}
    checks.update({"stage_k_"+name:result
                   for name,result in check_stage_k(stage_k_dir,instant).items()})
    checks["pytest"]=check_tests(junit)
    if https_url is not None:
        checks["https_tls"]=check_https(https_url)
    checks["offsite_recovery"]=yubikey_recovery_gate.check_dual_yubikey(config, primary_drill_verified=primary_yubikey_drill_verified, second_drill_report=spare_yubikey_drill_report, primary_recipient_file=primary_recipient_file, second_recipient_file=spare_recipient_file, at=instant)
    checks["daily_timer"]= _pass(
        daily_timer_verified,
        "Dzienny timer Stage K rzeczywiście uruchomił snapshot Magazynu",
        "Nie odebrano faktycznego automatycznego cyklu dziennego po integracji")
    checks["employee_access"]=_pass(
        employee_acl_verified,
        "Dostęp pracowników w Tailscale i role Magazynu odebrane",
        "Brak testu dostępu pracowników na docelowych urządzeniach/ACL")
    return {
        "release":"MAGAZYN_V1",
        "decision":"GO" if all(v["status"]=="PASS" for v in checks.values()) else "NO_GO",
        "checked_at":instant.isoformat(timespec="seconds"),
        "checks":checks,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Magazyn production go/no-go: audit only")
    parser.add_argument("--bridge-config",required=True)
    parser.add_argument("--stage-k-status-dir",default="/srv/ai-data/platform/backup-status/stage-k")
    parser.add_argument("--junit-report")
    parser.add_argument("--https-url",default="https://ai-server.tail759e12.ts.net:8443/")
    parser.add_argument("--primary-yubikey-drill-verified",action="store_true")
    parser.add_argument("--spare-yubikey-drill-report",type=Path)
    parser.add_argument("--primary-recipient-file",type=Path)
    parser.add_argument("--spare-recipient-file",type=Path)
    parser.add_argument("--daily-timer-verified",action="store_true",
                        help="Only after observing a real daily timer trigger")
    parser.add_argument("--employee-acl-verified",action="store_true",
                        help="Only after a real employee tailnet/HTTPS/RBAC check")
    args=parser.parse_args(argv)
    config=read_config(args.bridge_config)
    result=production_readiness(
        config,Path(args.stage_k_status_dir),
        junit=Path(args.junit_report) if args.junit_report else None,
        https_url=args.https_url,
        primary_yubikey_drill_verified=args.primary_yubikey_drill_verified,
        spare_yubikey_drill_report=args.spare_yubikey_drill_report,
        primary_recipient_file=args.primary_recipient_file,
        spare_recipient_file=args.spare_recipient_file,
        daily_timer_verified=args.daily_timer_verified,
        employee_acl_verified=args.employee_acl_verified)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2))
    return 0 if result["decision"]=="GO" else 2


if __name__=="__main__":
    sys.exit(main())
