#!/usr/bin/env python3
"""Independent, read-only verification and optional restore of Magazyn .mgzb.

This file deliberately does NOT import Magazyn, connect to the server or NAS,
or create/decrypt files automatically. AES key stays in memory (age stdout).
Requires Python 3.11+, cryptography and age.exe/age on the recovery computer.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import zipfile

MAGIC = b"MAGAZYN_V1_BACKUP\n"
AAD = b"magazyn/v1/sqlite-backup"
MAX_SIZE = 512 * 1024 * 1024
MAX_WRAPPED_KEY = 4096
REQUIRED_TABLES = {"users", "items", "locations", "balances", "events", "sessions"}


class RecoveryError(Exception):
    pass


def read_wrapped_key(identity: Path, wrapped_key: Path, age_bin: str = "age") -> bytes:
    """Use only an independent, OFF-SERVER private age identity."""
    if not identity.is_file() or identity.is_symlink():
        raise RecoveryError("Brak prywatnego klucza age na zaszyfrowanym nośniku")
    if not wrapped_key.is_file() or wrapped_key.is_symlink():
        raise RecoveryError("Brak zaszyfrowanej kopii klucza AES (.age)")
    if not 100 <= wrapped_key.stat().st_size <= MAX_WRAPPED_KEY:
        raise RecoveryError("Nieprawidłowy rozmiar pliku .age")
    if not wrapped_key.read_bytes().startswith(b"age-encryption.org/v1\n"):
        raise RecoveryError("Nieprawidłowy format szyfrowanej kopii klucza")
    program=shutil.which(age_bin)
    if not program and age_bin=="age":
        # USB is self-contained even when age is not installed on this Windows.
        bundled=Path(__file__).resolve().parent/("age.exe" if os.name=="nt" else "age")
        if bundled.is_file():
            program=str(bundled)
    if not program:
        raise RecoveryError("Brak age: zainstaluj FiloSottile.age lub skopiuj oficjalne age.exe obok tego skryptu")
    try:
        result=subprocess.run(
            [program, "-d", "-i", str(identity), str(wrapped_key)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryError("Nie można uruchomić age lub upłynął limit czasu") from exc
    if result.returncode != 0 or len(result.stdout) != 32:
        raise RecoveryError("Odszyfrowanie klucza AES nie powiodło się")
    return result.stdout


def verify_database(contents: bytes) -> dict:
    if len(contents)>MAX_SIZE or not contents.startswith(b"SQLite format 3\x00"):
        raise RecoveryError("Nieprawidłowy lub zbyt duży obraz bazy SQLite")
    con=sqlite3.connect(":memory:")
    try:
        con.deserialize(contents)
        if con.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise RecoveryError("Błąd integralności odtworzonej SQLite")
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise RecoveryError("Błędy relacji w odtworzonej SQLite")
        tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not REQUIRED_TABLES.issubset(tables):
            raise RecoveryError("To nie jest baza Magazynu V1")
        documents=0
        if "item_documents" in tables:
            for body,digest in con.execute("SELECT content,sha256 FROM item_documents"):
                if hashlib.sha256(body).hexdigest()!=digest:
                    raise RecoveryError("Uszkodzona dokumentacja techniczna")
                documents+=1
        return {"schema":con.execute("PRAGMA user_version").fetchone()[0],
                "documents":documents,
                "items":con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                "integrity":"ok"}
    except sqlite3.DatabaseError as exc:
        raise RecoveryError("SQLite nie może otworzyć odtworzonej bazy") from exc
    finally:
        con.close()


def decrypt_backup(backup_path: Path, key: bytes) -> tuple[bytes,dict]:
    if not backup_path.is_file() or backup_path.is_symlink():
        raise RecoveryError("Brak archiwum .mgzb")
    size=backup_path.stat().st_size
    if not len(MAGIC)+12+16<size<=MAX_SIZE+16_384:
        raise RecoveryError("Nieprawidłowy rozmiar archiwum .mgzb")
    sealed=backup_path.read_bytes()
    if not sealed.startswith(MAGIC):
        raise RecoveryError("Nieprawidłowy nagłówek archiwum Magazynu")
    nonce=sealed[len(MAGIC):len(MAGIC)+12]
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RecoveryError("Brak biblioteki cryptography (python -m pip install cryptography)") from exc
    try:
        clear=AESGCM(key).decrypt(nonce,sealed[len(MAGIC)+12:],AAD)
    except Exception as exc:
        raise RecoveryError("Zły klucz AES lub uszkodzone archiwum .mgzb") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(clear)) as contents:
            if set(contents.namelist()) != {"manifest.json", "database.sqlite3"}:
                raise RecoveryError("Nieoczekiwane pliki wewnątrz backupu")
            manifest_info=contents.getinfo("manifest.json")
            image_info=contents.getinfo("database.sqlite3")
            if manifest_info.file_size>16_384 or image_info.file_size>MAX_SIZE:
                raise RecoveryError("Niebezpieczny rozmiar zawartości ZIP")
            manifest=json.loads(contents.read("manifest.json"))
            image=contents.read("database.sqlite3")
    except (zipfile.BadZipFile,KeyError,ValueError,TypeError) as exc:
        raise RecoveryError("Nieprawidłowa zawartość backupu") from exc
    if (not isinstance(manifest,dict) or manifest.get("schema_version")!=1
            or manifest.get("type")!="magazyn-sqlite"
            or manifest.get("bytes")!=len(image)
            or manifest.get("sha256")!=hashlib.sha256(image).hexdigest()):
        raise RecoveryError("Niezgodna suma kontrolna/manifest kopii")
    verified=verify_database(image)
    return image,{"captured_at":manifest.get("captured_at","unknown"),**verified}


def recovery_verify(identity: Path, wrapped_key: Path, archive: Path,
                    *, age_bin: str = "age") -> dict:
    key=read_wrapped_key(identity,wrapped_key,age_bin)
    _,result=decrypt_backup(archive,key)
    return result


def recovery_restore(identity: Path, wrapped_key: Path, archive: Path, target: Path,
                     *, age_bin: str="age") -> dict:
    key=read_wrapped_key(identity,wrapped_key,age_bin)
    image,result=decrypt_backup(archive,key)
    if target.suffix.lower()!=".sqlite3" or target.is_symlink():
        raise RecoveryError("Plik wyjściowy musi być nową nazwą .sqlite3")
    if not target.parent.is_dir() or target.exists():
        raise RecoveryError("Katalog musi istnieć, a docelowa SQLite nie może już istnieć")
    if os.name=="nt" and identity.drive.lower()!=target.drive.lower():
        raise RecoveryError("Jawna SQLite musi pozostać na tym samym zaszyfrowanym USB co klucz age")
    created=False
    try:
        with target.open("xb") as stream:
            created=True
            stream.write(image)
            stream.flush()
            os.fsync(stream.fileno())
        # Verify again from the actual output file without calling Magazyn.
        if verify_database(target.read_bytes())!=dict(
                schema=result["schema"],documents=result["documents"],
                items=result["items"],integrity=result["integrity"]):
            raise RecoveryError("Nie udało się zweryfikować zapisanego pliku")
    except Exception:
        if created:
            target.unlink(missing_ok=True)  # never remove somebody else's file
        raise
    return result


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(
        description="Magazyn V1: całkowicie niezależny test odzyskiwania na Windows")
    parser.add_argument("command",choices=["verify","restore"])
    parser.add_argument("--identity",type=Path,required=True)
    parser.add_argument("--wrapped-key",type=Path,required=True)
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--age-bin",default="age")
    parser.add_argument("--output",type=Path,help="Tylko restore; powstanie jawna baza SQLite!")
    args=parser.parse_args(argv)
    try:
        if args.command=="verify":
            if args.output is not None:
                raise RecoveryError("verify nie przyjmuje --output (niczego nie zapisuje)")
            result=recovery_verify(args.identity,args.wrapped_key,args.archive,
                                   age_bin=args.age_bin)
        else:
            if args.output is None:
                raise RecoveryError("Przy restore wymagane --output")
            result=recovery_restore(args.identity,args.wrapped_key,args.archive,
                                    args.output,age_bin=args.age_bin)
        print(json.dumps({"status":"PASS","command":args.command,**result},
                         ensure_ascii=False,sort_keys=True))
        return 0
    except (RecoveryError, OSError, ValueError) as exc:
        # Never print age stderr or any AES key bytes.
        print(json.dumps({"status":"FAIL","error":str(exc)},ensure_ascii=False))
        return 2


if __name__=="__main__":
    sys.exit(main())
