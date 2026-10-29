#!/usr/bin/env python3
"""Wrap existing production Magazyn AES for a SECOND independent YubiKey.
Does not initialize hardware, rotate AES, overwrite old escrow, or change services.
"""
from pathlib import Path
import hashlib
import os
import re
import sys

ROOT=Path("/srv/ai-data/magazyn-v1")
SPARE=ROOT/"private/yubikey-spare/recipient.txt"
FIRST=Path("/srv/ai-data/platform/recovery/stage-k/age-recipients.txt")
KEY=ROOT/"private/backup-keys/magazyn.key"
NAS=Path("/mnt/AI_Platform")
EXISTING=NAS/"Magazyn/recovery/magazyn-v1-aes256-key-yubikey.age"
NAME="magazyn-v1-aes256-key-yubikey-spare.age"
APP=ROOT/"releases/529af02029e1/apps/magazyn"
sys.path.insert(0,str(APP))
from magazyn import backup,key_escrow


def eligible():
    if os.geteuid()==0:
        raise RuntimeError("Nie uruchamiaj jako root")
    for path in (KEY,FIRST,SPARE,EXISTING):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("Brak wymaganego pliku albo jest symlinkiem")
    if (KEY.stat().st_mode & 0o777)!=0o600 or KEY.stat().st_size!=32:
        raise RuntimeError("Klucz AES nie ma prawidłowych zabezpieczeń")
    if (SPARE.stat().st_mode & 0o777)!=0o600:
        raise RuntimeError("Plik recipienta drugiego YubiKeya nie jest prywatny")
    one=key_escrow._public_yubikey_recipient(FIRST)
    two=key_escrow._public_yubikey_recipient(SPARE)
    if one==two:
        raise RuntimeError("Drugi recipient jest identyczny z pierwszym")
    folder=backup._nas_target(NAS)/"recovery"
    if not folder.is_dir() or folder.is_symlink():
        raise RuntimeError("Brak bezpiecznego katalogu recovery na GlobalNAS")
    target=folder/NAME
    if target.exists() or target.is_symlink():
        raise RuntimeError("Zapasowe escrow już istnieje, NIE nadpisujemy")
    original=EXISTING.read_bytes()
    assert original.startswith(key_escrow.AGE_HEADER)
    archive=sorted((backup._nas_target(NAS)/"daily").glob("*.mgzb"),reverse=True)
    if not archive:
        raise RuntimeError("Brak backupu z GlobalNAS")
    assert backup.verify_archive(archive[0],KEY)["status"]=="PASS"
    return target,hashlib.sha256(original).hexdigest(),hashlib.sha256(KEY.read_bytes()).hexdigest(),archive[0]


def seal():
    target,hash_first,hash_aes,source=eligible()
    print("PRODUCTION_AES_AND_ORIGINAL_YUBIKEY_ESCROW_VERIFIED=PASS",flush=True)
    encrypted=key_escrow.encrypt_key_for_recovery(KEY,SPARE)
    if len(encrypted)<120 or len(encrypted)>4096:
        raise RuntimeError("Nieprawidłowy ciphertext")
    backup._write_atomic(target,encrypted)
    if target.read_bytes()!=encrypted:
        raise RuntimeError("Odczyt recovery escrow z GlobalNAS jest niezgodny")
    if hashlib.sha256(EXISTING.read_bytes()).hexdigest()!=hash_first:
        raise RuntimeError("Nieoczekiwana zmiana pierwszego escrow")
    if hashlib.sha256(KEY.read_bytes()).hexdigest()!=hash_aes:
        raise RuntimeError("Nieoczekiwana zmiana AES produkcji")
    assert backup.verify_archive(source,KEY)["status"]=="PASS"
    print("SECOND_YUBIKEY_AES_ESCROW_WRITTEN_TO_GLOBALNAS=PASS")
    print("ORIGINAL_ESCROW_MASTER_AES_AND_BACKUPS_UNCHANGED=PASS")
    print("PENDING_PHYSICAL_SECOND_YUBIKEY_DECRYPT_RESTORE_TEST")


if __name__=="__main__":
    try:
        if len(sys.argv)!=2 or sys.argv[1] not in ("--check","--seal"):
            raise RuntimeError("Użyj --check lub --seal")
        if sys.argv[1]=="--check":
            eligible()
            print("SECOND_YUBIKEY_RECIPIENT_AND_NAS_PREFLIGHT=PASS")
        else:
            seal()
    except Exception as error:
        print("SECOND_YUBIKEY_ESCROW_BLOCKED:",type(error).__name__)
        raise SystemExit(2)
