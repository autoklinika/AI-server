"""Secure local setup of a dedicated Telegram bot for Magazyn DEV.

The bot token is *only* typed on the user's server terminal. Never print it,
save it in Git, put it in a command-line argument, or reuse Hermes secrets.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from .store import Problem, Store
from . import messaging

TOKEN_RE = re.compile(r"[1-9][0-9]{4,15}:[A-Za-z0-9_-]{25,120}\Z")


class SetupFailure(ValueError):
    pass


def _private_folder(path: Path) -> None:
    if path.is_symlink():
        raise SetupFailure("Katalog jest dowiązaniem symbolicznym")
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:
        raise SetupFailure("Katalog musi należeć do użytkownika i mieć prawa 0700")


def validate_token(token: str) -> str:
    if not isinstance(token,str) or TOKEN_RE.fullmatch(token) is None:
        raise SetupFailure("Nieprawidłowy format tokenu Telegram; nie zapisano go")
    return token


def load_token(filename: str | Path) -> str:
    path=Path(filename).expanduser()
    if path.is_symlink():
        raise SetupFailure("Plik tokenu nie może być dowiązaniem")
    fd=None
    try:
        fd=os.open(path,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)&0o077:
            raise SetupFailure("Token musi należeć do użytkownika i mieć prawa 0600")
        with os.fdopen(fd,"r",encoding="ascii") as handle:
            fd=None
            token=handle.read(170).strip()
        return validate_token(token)
    except (OSError,UnicodeError) as exc:
        raise SetupFailure("Nie można bezpiecznie odczytać pliku tokenu") from exc
    finally:
        if fd is not None:
            os.close(fd)


def verify_telegram(token: str) -> dict:
    """Safe-only bot metadata lookups; exceptions never include the token-bearing URL."""
    validate_token(token)
    import httpx
    try:
        with httpx.Client(timeout=httpx.Timeout(12,connect=6),follow_redirects=False) as http:
            def call(method):
                reply=http.post(f"https://api.telegram.org/bot{token}/{method}",json={})
                reply.raise_for_status()
                answer=reply.json()
                if not isinstance(answer,dict) or answer.get("ok") is not True:
                    raise SetupFailure("Telegram odrzucił żądanie weryfikacji")
                return answer.get("result")
            details=call("getMe")
            hook=call("getWebhookInfo")
    except (httpx.RequestError,httpx.HTTPStatusError,ValueError,KeyError,TypeError) as exc:
        # httpx error repr could contain credential in URL: deliberately suppress it.
        raise SetupFailure("Nie można zweryfikować tokenu przez Telegram API (bez zapisu tokenu)") from None
    if not isinstance(details,dict) or details.get("is_bot") is not True:
        raise SetupFailure("Podany token nie należy do bota Telegram")
    username=details.get("username")
    if not isinstance(username,str) or not username.lower().endswith("bot"):
        raise SetupFailure("Telegram nie zwrócił poprawnej nazwy bota")
    if not isinstance(hook,dict) or hook.get("url"):
        raise SetupFailure("Bot ma już webhook; nie usuwamy go automatycznie ani nie przejmujemy innej integracji")
    return {"username":username,"bot_id":details.get("id"),
            "can_join_groups":details.get("can_join_groups")}


def save_token_exclusive(filename: str | Path, token: str) -> Path:
    validate_token(token)
    path=Path(filename).expanduser()
    _private_folder(path.parent)
    if path.exists() or path.is_symlink():
        raise SetupFailure("Plik tokenu już istnieje. Nie wolno go nadpisywać")
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"w",encoding="ascii") as handle:
            handle.write(token+"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _authorize_admin(store: Store, username: str | None, *, create_if_missing: bool):
    admins=[u for u in store.users() if u["role"]=="admin" and u["active"]]
    if not admins:
        if not create_if_missing:
            raise SetupFailure("Najpierw utwórz administratora Magazynu")
        username=(username or input("Login nowego administratora: ")).strip()
        secret=getpass.getpass("Nowe hasło administratora (min. 12 znaków): ")
        repeat=getpass.getpass("Powtórz hasło administratora: ")
        if secret!=repeat:
            raise SetupFailure("Hasła się różnią; przerwano")
        try:
            store.create_user(username,secret,"admin")
        except Problem as exc:
            raise SetupFailure(exc.detail) from None
        return store.authenticate(username,secret)
    username=(username or input("Login istniejącego administratora: ")).strip()
    secret=getpass.getpass("Hasło administratora Magazynu: ")
    try:
        user=store.authenticate(username,secret)
    except Problem as exc:
        raise SetupFailure("Błędne dane logowania administratora") from None
    if user["role"]!="admin":
        raise SetupFailure("Nie masz uprawnień administratora")
    return user


def run_setup(*, db: str, token_file: str, admin_username: str | None=None) -> dict:
    store=Store(db)
    admin=_authorize_admin(store,admin_username,create_if_missing=True)
    token=getpass.getpass("Token z BotFather (ukryty, nie wklejaj do ChatGPT): ").strip()
    validate_token(token)
    details=verify_telegram(token)
    save_token_exclusive(token_file,token)
    return {"bot_username":details["username"],"bot_id":details["bot_id"],
            "private_group_access_should_be_disabled":details["can_join_groups"] is not False,
            "admin":admin["username"],"ready_for_start":True}


def run_pair(*, db: str, provider: str="telegram", admin_username: str | None=None,
             username: str | None=None) -> dict:
    store=Store(db)
    admin=_authorize_admin(store,admin_username,create_if_missing=False)
    target_username=username or admin["username"]
    found=[u for u in store.users() if u["username"].casefold()==target_username.casefold() and u["active"]]
    if not found:
        raise SetupFailure("Użytkownik docelowy nie istnieje lub jest nieaktywny")
    return messaging.create_pairing(store,found[0]["id"],provider,admin["id"])


def run_rename_admin(*, db: str, admin_username: str | None=None,
                     new_username: str | None=None) -> dict:
    """Change the admin login in place, preserving user ID and Telegram pairing."""
    store=Store(db)
    admin=_authorize_admin(store,admin_username,create_if_missing=False)
    desired=(new_username if new_username is not None
             else input("Nowy login administratora: ")).strip()
    confirmation=input("Powtórz nowy login: ").strip()
    if desired != confirmation:
        raise SetupFailure("Nowe loginy są różne — nie wprowadzono zmian")
    if desired == admin["username"]:
        raise SetupFailure("Nowy login jest taki sam jak obecny")
    store.change_user(admin["id"],username=desired)
    # Stable FK user id is used by Telegram links, minima and outbox.
    updated=next((u for u in store.users() if u["id"]==admin["id"]),None)
    if not updated or updated["username"]!=desired or updated["role"]!="admin":
        raise SetupFailure("Nie udało się potwierdzić nowego loginu")
    return {"old_username":admin["username"],"username":desired,
            "id_preserved":True,"role_preserved":True}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Telegram Magazyn DEV — bezpieczny konfigurator")
    commands=parser.add_subparsers(dest="command",required=True)
    common=argparse.ArgumentParser(add_help=False)
    common.add_argument("--db",required=True)
    common.add_argument("--admin-username",default=None)
    init=commands.add_parser("configure",parents=[common])
    init.add_argument("--token-file",required=True)
    pair=commands.add_parser("pair",parents=[common])
    pair.add_argument("--user",default=None,help="Powiąż wskazanego użytkownika; domyślnie administrator")
    commands.add_parser("rename-admin",parents=[common],
                        help="Zmienia login bez tworzenia nowego konta i bez utraty Telegram")
    status=commands.add_parser("status")
    status.add_argument("--db",required=True)
    status.add_argument("--token-file",required=True)
    arguments=parser.parse_args(argv)
    try:
        if arguments.command=="configure":
            result=run_setup(db=arguments.db,token_file=arguments.token_file,
                             admin_username=arguments.admin_username)
            print("TELEGRAM_BOT_VERIFIED=PASS")
            print("BOT_USERNAME=@"+result["bot_username"])
            print("ADMIN="+result["admin"])
            print("TOKEN_SAVED_PRIVATELY=PASS")
            if result["private_group_access_should_be_disabled"]:
                print("BOTFATHER_ACTION=disable group addition via /setjoingroups")
            print("NEXT=Uruchom usługę, następnie wykonaj polecenie pair")
        elif arguments.command=="pair":
            result=run_pair(db=arguments.db,admin_username=arguments.admin_username,
                            username=arguments.user)
            print("PAIRING_USER="+result["username"])
            print("PAIRING_EXPIRES_AT="+result["expires_at"])
            print("SEND_IN_PRIVATE_DM=/polacz "+result["code"])
        elif arguments.command=="rename-admin":
            result=run_rename_admin(db=arguments.db,admin_username=arguments.admin_username)
            print("ADMIN_LOGIN_UPDATED=PASS")
            print("OLD_LOGIN="+result["old_username"])
            print("NEW_LOGIN="+result["username"])
            print("ACCOUNT_ID_PRESERVED=PASS")
            print("TELEGRAM_PAIRING_PRESERVED=PASS")
        else:
            store=Store(arguments.db)
            active_admins=[u for u in store.users() if u["role"]=="admin" and u["active"]]
            present=Path(arguments.token_file).is_file()
            valid=False
            if present:
                try:
                    load_token(arguments.token_file)
                    valid=True
                except SetupFailure:
                    valid=False
            print("MAGAZYN_DB=READY")
            print("ACTIVE_ADMINS="+str(len(active_admins)))
            print("TELEGRAM_SECRET="+("READY" if valid else "MISSING_OR_INVALID"))
            print("BOT_ENABLED_BY_CONFIG="+("YES" if valid and active_admins else "NO"))
        return 0
    except (SetupFailure,Problem) as exc:
        print("SETUP_BLOCKED: "+str(exc),file=__import__("sys").stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
