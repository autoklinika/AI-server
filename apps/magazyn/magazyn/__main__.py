"""Administrative CLI: no plaintext password argument and no automatic installation."""
import argparse
import getpass
import os

from .store import Store, Problem


def main():
    parser=argparse.ArgumentParser(description="Magazyn V1 (isolated DEV)")
    parser.add_argument("command",choices=("create-admin","run","list-users"))
    parser.add_argument("--db",default=os.getenv("MAGAZYN_DB_PATH"),help="Local SQLite database path")
    parser.add_argument("--host",default="127.0.0.1",help="Default: loopback only")
    parser.add_argument("--port",type=int,default=18765)
    parser.add_argument("--username",default="")
    args=parser.parse_args()
    if not args.db:
        parser.error("Podaj --db lub MAGAZYN_DB_PATH; baza nie jest tworzona w repozytorium")
    store=Store(args.db)
    try:
        if args.command=="create-admin":
            username=args.username or input("Login administratora: ").strip()
            pwd=getpass.getpass("Hasło (minimum 12 znaków): ")
            confirmation=getpass.getpass("Powtórz hasło: ")
            if pwd!=confirmation:
                parser.error("Hasła się nie zgadzają")
            store.create_user(username,pwd,"admin")
            print("ADMIN_CREATED",username)
        elif args.command=="list-users":
            for user in store.users():
                print(user["id"],user["username"],user["role"],"active" if user["active"] else "disabled")
        elif args.command=="run":
            import uvicorn
            from .server import create_app
            if not any(u["role"]=="admin" and u["active"] for u in store.users()):
                parser.error("Najpierw utwórz administratora: create-admin")
            secure=os.getenv("MAGAZYN_COOKIE_SECURE","1")=="1"
            if not secure and args.host not in ("127.0.0.1","localhost","::1"):
                parser.error("Nieszyfrowane ciasteczka dopuszczalne tylko na loopback")
            uvicorn.run(create_app(args.db,secure_cookie=secure),
                        host=args.host,port=args.port,access_log=False)
    except Problem as exc:
        parser.error(exc.detail)


if __name__=="__main__":
    main()
