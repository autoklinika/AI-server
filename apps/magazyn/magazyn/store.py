"""Isolated Magazyn V1 persistence. Never opens an AI Platform production database."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

KINDS = {"ecu", "part"}
PRODUCT_STATES = {"new", "used"}
TECH_STATES = {"working", "faulty", "unknown"}
REASONS = {"repair", "sale", "workshop", "scrap", "other"}
OPERATIONS = {"receive", "issue", "move", "adjust"}


class Problem(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize(value: str) -> str:
    return "".join(c for c in value.upper() if c.isalnum())


def password_hash(password: str) -> str:
    if not (12 <= len(password) <= 200):
        raise Problem(422, "Hasło musi mieć 12–200 znaków")
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$16384$" + salt.hex() + "$" + key.hex()


def password_verify(password: str, encoded: str) -> bool:
    try:
        method, work, salt_hex, reference_hex = encoded.split("$")
        if method != "scrypt" or int(work) != 16384 or len(password) > 200:
            return False
        derived = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                 n=int(work), r=8, p=1, dklen=32)
        return hmac.compare_digest(derived, bytes.fromhex(reference_hex))
    except (ValueError, TypeError):
        return False


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('ecu','part')),
    brand TEXT NOT NULL DEFAULT '', designation TEXT NOT NULL, manufacturer TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    primary_number TEXT NOT NULL DEFAULT '', hw TEXT NOT NULL DEFAULT '', sw TEXT NOT NULL DEFAULT '',
    package TEXT NOT NULL DEFAULT '', parameters TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_brands (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    brand TEXT NOT NULL, PRIMARY KEY (item_id,brand)
);
CREATE TABLE IF NOT EXISTS item_numbers (
    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    number TEXT NOT NULL, normalized TEXT NOT NULL,
    number_type TEXT NOT NULL DEFAULT 'other',
    UNIQUE(item_id,normalized)
);
CREATE INDEX IF NOT EXISTS ix_numbers_normalized ON item_numbers(normalized);
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS balances (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id),
    product_state TEXT NOT NULL, technical_state TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity>=0),
    PRIMARY KEY(item_id,location_id,product_state,technical_state)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
    item_label TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name TEXT NOT NULL,
    action TEXT NOT NULL, location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    location_code TEXT NOT NULL,
    to_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    to_location_code TEXT NOT NULL DEFAULT '',
    product_state TEXT NOT NULL, technical_state TEXT NOT NULL,
    quantity INTEGER NOT NULL, before_source INTEGER NOT NULL, after_source INTEGER NOT NULL,
    before_target INTEGER, after_target INTEGER,
    reason TEXT NOT NULL DEFAULT '', order_ref TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_item_time ON events(item_id,created_at);
CREATE TABLE IF NOT EXISTS minima (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    minimum INTEGER NOT NULL CHECK(minimum>=0),
    recipient_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT '' CHECK(provider IN ('','telegram','discord'))
);
CREATE TABLE IF NOT EXISTS external_accounts (
    provider TEXT NOT NULL CHECK(provider IN ('telegram','discord')),
    external_user_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    verified INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(provider,external_user_id)
);
PRAGMA user_version=1;
"""


class Store:
    def __init__(self, path: str):
        if not path:
            raise RuntimeError("Ścieżka bazy MAGAZYN_DB_PATH jest wymagana")
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        if not Path(self.path).exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            os.close(descriptor)
        os.chmod(self.path, 0o600)
        with self.connect() as con:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("Nieobsługiwana wersja schematu Magazynu")
            con.executescript(SCHEMA)
            con.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connect(self, write=False):
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        try:
            if write:
                con.execute("BEGIN IMMEDIATE")
            yield con
            if write:
                con.execute("COMMIT")
        except Exception:
            if write and con.in_transaction:
                con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def create_user(self, username, password, role="user"):
        username = (username or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,40}", username):
            raise Problem(422, "Login: 3–40 znaków A-Z, 0-9, _, ., -")
        if role not in ("admin", "user"):
            raise Problem(422, "Nieprawidłowa rola")
        encoded = password_hash(password)
        try:
            with self.connect(write=True) as con:
                row = con.execute("INSERT INTO users(username,password_hash,role,created_at) "
                                  "VALUES (?,?,?,?) RETURNING id",
                                  (username,encoded,role,now())).fetchone()
                return row["id"]
        except sqlite3.IntegrityError:
            raise Problem(409, "Login jest już zajęty")

    def authenticate(self, username, password):
        with self.connect() as con:
            user = con.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
        if not user or not password_verify(password, user["password_hash"]):
            raise Problem(401, "Nieprawidłowe dane logowania")
        return dict(user)

    def create_session(self, user_id):
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(32)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
        with self.connect(write=True) as con:
            con.execute("DELETE FROM sessions WHERE expires_at < ?", (now(),))
            con.execute("INSERT INTO sessions(token_hash,user_id,csrf,expires_at) VALUES (?,?,?,?)",
                        (hashlib.sha256(token.encode()).hexdigest(),user_id,csrf,expiry))
        return token, csrf

    def session_user(self, token):
        if not token or len(token)>200:
            raise Problem(401, "Wymagane logowanie")
        key = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as con:
            row = con.execute(
                "SELECT u.id,u.username,u.role,u.active,s.csrf FROM users u "
                "JOIN sessions s ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? ",
                (key, now())).fetchone()
        if not row or not row["active"]:
            raise Problem(401, "Sesja wygasła lub jest nieaktywna")
        return dict(row)

    def logout(self, token):
        if token:
            with self.connect(write=True) as con:
                con.execute("DELETE FROM sessions WHERE token_hash=?",
                            (hashlib.sha256(token.encode()).hexdigest(),))

    def users(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT id,username,role,active,created_at FROM users ORDER BY username")]

    def change_user(self, user_id, role=None, active=None, password=None):
        with self.connect(write=True) as con:
            if con.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone() is None:
                raise Problem(404, "Brak użytkownika")
            if role is not None:
                if role not in ("admin", "user"):
                    raise Problem(422, "Nieprawidłowa rola")
                con.execute("UPDATE users SET role=? WHERE id=?", (role,user_id))
            if active is not None:
                con.execute("UPDATE users SET active=? WHERE id=?", (int(active),user_id))
                if not active:
                    con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            if password is not None:
                con.execute("UPDATE users SET password_hash=? WHERE id=?",
                            (password_hash(password),user_id))
                con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def delete_user(self, user_id):
        with self.connect(write=True) as con:
            if not con.execute("DELETE FROM users WHERE id=? RETURNING id", (user_id,)).fetchone():
                raise Problem(404, "Brak użytkownika")

    def locations(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM locations ORDER BY code")]

    def add_location(self, code, description=""):
        code = (code or "").strip()
        if not (1 <= len(code) <= 64):
            raise Problem(422, "Nieprawidłowa lokalizacja")
        try:
            with self.connect(write=True) as con:
                return con.execute("INSERT INTO locations(code,description) VALUES (?,?) RETURNING id",
                                   (code,description[:300])).fetchone()[0]
        except sqlite3.IntegrityError:
            raise Problem(409, "Lokalizacja już istnieje")

    def update_location(self, location_id, code=None, description=None):
        with self.connect(write=True) as con:
            if not con.execute("SELECT 1 FROM locations WHERE id=?", (location_id,)).fetchone():
                raise Problem(404, "Brak lokalizacji")
            if code is not None:
                if not code.strip():
                    raise Problem(422,"Kod lokalizacji jest wymagany")
                con.execute("UPDATE locations SET code=? WHERE id=?", (code.strip(),location_id))
            if description is not None:
                con.execute("UPDATE locations SET description=? WHERE id=?", (description,location_id))

    def delete_location(self, location_id):
        with self.connect(write=True) as con:
            if not con.execute("SELECT 1 FROM locations WHERE id=?",(location_id,)).fetchone():
                raise Problem(404,"Brak lokalizacji")
            stock = con.execute("SELECT COALESCE(SUM(quantity),0) FROM balances "
                                "WHERE location_id=?",(location_id,)).fetchone()[0]
            if stock:
                raise Problem(409,"Najpierw przenieś lub skoryguj pozostały stan")
            con.execute("DELETE FROM balances WHERE location_id=?",(location_id,))
            con.execute("DELETE FROM locations WHERE id=?",(location_id,))

    def add_item(self, data, actor, *, connection=None):
        kind = data.get("kind")
        if kind not in KINDS or not data.get("designation","").strip():
            raise Problem(422, "Rodzaj produktu i oznaczenie są wymagane")
        brand = data.get("brand","").strip()
        if kind == "ecu" and not brand:
            raise Problem(422, "Marka pojazdu jest wymagana")
        fields = ("kind","brand","designation","manufacturer","category","model",
                  "primary_number","hw","sw","package","parameters","notes")
        values = [str(data.get(x) or "").strip() for x in fields]
        if any(len(x)>2000 for x in values):
            raise Problem(422,"Zbyt długie dane produktu")
        timestamp = now()
        with (nullcontext(connection) if connection is not None else self.connect(write=True)) as con:
            item_id = con.execute("INSERT INTO items(" + ",".join(fields) +
                    ",created_at,updated_at) VALUES (" + ",".join(["?"]*(len(fields)+2)) +
                    ") RETURNING id", [*values,timestamp,timestamp]).fetchone()[0]
            brands = set([brand] if brand else [])
            brands.update(x.strip() for x in data.get("brands",[]) if x.strip())
            for b in sorted(brands):
                con.execute("INSERT INTO item_brands(item_id,brand) VALUES (?,?)",(item_id,b))
            numbers = [(data.get("primary_number",""), "main")]
            numbers.extend((r.get("number",""),r.get("number_type","other"))
                           for r in data.get("numbers",[]))
            self._add_numbers(con,item_id,numbers)
        return item_id

    @staticmethod
    def _add_numbers(con,item_id,numbers):
        for number, category in numbers:
            number = str(number).strip()
            if not number:
                continue
            key = normalize(number)
            if not key:
                continue
            if len(number)>160:
                raise Problem(422,"Numer jest za długi")
            con.execute("INSERT OR IGNORE INTO item_numbers(item_id,number,normalized,number_type) "
                        "VALUES (?,?,?,?)",(item_id,number,key,str(category)[:30]))

    def edit_item(self, item_id, data):
        fields = {"brand","designation","manufacturer","category","model",
                  "primary_number","hw","sw","package","parameters","notes"}
        with self.connect(write=True) as con:
            original = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if original is None:
                raise Problem(404,"Brak produktu")
            values = {key: str(val or "").strip() for key,val in data.items() if key in fields}
            if any(len(v)>2000 for v in values.values()):
                raise Problem(422,"Zbyt długie dane")
            if original["kind"]=="ecu" and values.get("brand",original["brand"])=="":
                raise Problem(422,"Marka pojazdu jest wymagana")
            if "designation" in values and not values["designation"]:
                raise Problem(422,"Oznaczenie jest wymagane")
            if values:
                con.execute("UPDATE items SET " + ",".join(k+"=?" for k in values) +
                            ",updated_at=? WHERE id=?",(*values.values(),now(),item_id))
            if "brands" in data or "brand" in data:
                brand = values.get("brand",original["brand"])
                brands = {brand} if brand else set()
                existing_brands = [r[0] for r in con.execute(
                    "SELECT brand FROM item_brands WHERE item_id=?",(item_id,))]
                extras = data["brands"] if "brands" in data else [
                    b for b in existing_brands if b!=original["brand"]]
                brands.update(x.strip() for x in extras if x.strip())
                con.execute("DELETE FROM item_brands WHERE item_id=?",(item_id,))
                for b in sorted(brands):
                    con.execute("INSERT INTO item_brands(item_id,brand) VALUES (?,?)",(item_id,b))
            if "numbers" in data or "primary_number" in data:
                extras = data.get("numbers")
                if extras is None:
                    extras=[dict(number=r["number"],number_type=r["number_type"])
                            for r in con.execute(
                                "SELECT number,number_type FROM item_numbers "
                                "WHERE item_id=? AND number_type!='main'",(item_id,))]
                con.execute("DELETE FROM item_numbers WHERE item_id=?",(item_id,))
                current = values.get("primary_number",original["primary_number"])
                nums=[(current,"main")]
                nums.extend((r.get("number",""),r.get("number_type","other")) for r in extras)
                self._add_numbers(con,item_id,nums)

    def delete_item(self, item_id):
        with self.connect(write=True) as con:
            if not con.execute("DELETE FROM items WHERE id=? RETURNING id",(item_id,)).fetchone():
                raise Problem(404,"Brak produktu")

    def _get_item(self, con, item_id):
        row = con.execute("SELECT * FROM items WHERE id=?",(item_id,)).fetchone()
        if row is None:
            raise Problem(404,"Brak produktu")
        return row

    def item(self,item_id):
        with self.connect() as con:
            item=dict(self._get_item(con,item_id))
            item["brands"]=[r[0] for r in con.execute(
                "SELECT brand FROM item_brands WHERE item_id=? ORDER BY brand",(item_id,))]
            item["numbers"]=[dict(r) for r in con.execute(
                "SELECT id,number,number_type FROM item_numbers WHERE item_id=? ORDER BY number",(item_id,))]
            item["balances"]=[dict(r) for r in con.execute(
                "SELECT b.location_id,l.code AS location,b.product_state,b.technical_state,b.quantity "
                "FROM balances b JOIN locations l ON l.id=b.location_id WHERE item_id=? AND quantity>0 "
                "ORDER BY l.code, b.product_state,b.technical_state",(item_id,))]
            item["total"]=sum(r["quantity"] for r in item["balances"])
            return item

    def items(self, query="", kind=None, brand=None, manufacturer=None,
              product_state=None, technical_state=None, location_id=None, available=None, limit=100):
        if kind is not None and kind not in KINDS:
            raise Problem(422,"Nieprawidłowy rodzaj")
        if limit<1 or limit>500:
            raise Problem(422,"Nieprawidłowy limit")
        with self.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM items ORDER BY id DESC")]
            result=[]
            q=normalize(query)
            for item in rows:
                if kind and item["kind"]!=kind:
                    continue
                brands=[r[0] for r in con.execute("SELECT brand FROM item_brands WHERE item_id=?",(item["id"],))]
                if brand and brand.casefold() not in [x.casefold() for x in brands]:
                    continue
                if manufacturer and manufacturer.casefold() not in item["manufacturer"].casefold():
                    continue
                numbers=[r[0] for r in con.execute("SELECT number FROM item_numbers WHERE item_id=?",(item["id"],))]
                haystack=[item[k] for k in ("brand","designation","manufacturer","category",
                          "model","primary_number","hw","sw","package","parameters","notes")]
                if q and not any(q in normalize(str(v)) for v in [*haystack,*brands,*numbers]):
                    continue
                balances=[dict(r) for r in con.execute(
                    "SELECT location_id,product_state,technical_state,quantity FROM balances "
                    "WHERE item_id=? AND quantity>0",(item["id"],))]
                filtered=[b for b in balances if
                    (not product_state or b["product_state"]==product_state) and
                    (not technical_state or b["technical_state"]==technical_state) and
                    (location_id is None or b["location_id"]==location_id)]
                if (product_state or technical_state or location_id) and not filtered:
                    continue
                total=sum(b["quantity"] for b in balances)
                if available is True and total==0:
                    continue
                if available is False and total>0:
                    continue
                item["total"]=total
                item["filtered_total"]=sum(b["quantity"] for b in filtered)
                item["brands"]=brands
                result.append(item)
                if len(result)>=limit:
                    break
            return result

    def stock_operation(self, data, actor, *, connection=None):
        action=data.get("action")
        if action not in OPERATIONS:
            raise Problem(422,"Nieprawidłowa operacja")
        item_id, location_id = data.get("item_id"), data.get("location_id")
        qty=data.get("quantity")
        if not isinstance(qty,int) or isinstance(qty,bool) or qty<0 or qty>2_000_000_000 or (action!="adjust" and qty==0):
            raise Problem(422,"Nieprawidłowa ilość")
        if action=="issue" and data.get("reason") not in REASONS:
            raise Problem(422,"Powód wydania jest obowiązkowy")
        if action=="adjust" and actor["role"]!="admin":
            raise Problem(403,"Korekta wymaga administratora")
        with (nullcontext(connection) if connection is not None else self.connect(write=True)) as con:
            item=self._get_item(con,item_id)
            origin=con.execute("SELECT * FROM locations WHERE id=?",(location_id,)).fetchone()
            if origin is None:
                raise Problem(404,"Brak lokalizacji")
            ps = data.get("product_state") or ("used" if item["kind"]=="ecu" else "na")
            ts = data.get("technical_state") or ("unknown" if item["kind"]=="ecu" else "na")
            if item["kind"]=="ecu":
                if ps not in PRODUCT_STATES or ts not in TECH_STATES:
                    raise Problem(422,"Nieprawidłowy stan sterownika")
            elif ps!="na" or ts!="na":
                raise Problem(422,"Stan Nowy/Używany dotyczy tylko sterowników")
            def balance(loc):
                row=con.execute("SELECT quantity FROM balances WHERE item_id=? AND location_id=? "
                                "AND product_state=? AND technical_state=?",
                                (item_id,loc,ps,ts)).fetchone()
                return row[0] if row else 0
            before=balance(location_id)
            if "expected_quantity" in data and before != data["expected_quantity"]:
                raise Problem(409,"Stan zmienił się od odczytu. Odśwież inwentaryzację")
            target_id, target_code, before_target, after_target = None,"",None,None
            if action=="receive":
                after=before+qty
            elif action=="issue":
                after=before-qty
            elif action=="adjust":
                after=qty
            else:
                target_id=data.get("to_location_id")
                target=con.execute("SELECT * FROM locations WHERE id=?",(target_id,)).fetchone()
                if target is None:
                    raise Problem(404,"Brak lokalizacji docelowej")
                if target_id==location_id:
                    raise Problem(422,"Lokalizacje muszą być różne")
                target_code=target["code"]
                before_target=balance(target_id)
                after_target=before_target+qty
                after=before-qty
            if after<0:
                raise Problem(409,"Niewystarczająca ilość w wybranej lokalizacji i stanie")
            def put(loc,amount):
                con.execute("INSERT INTO balances(item_id,location_id,product_state,technical_state,quantity) "
                            "VALUES (?,?,?,?,?) ON CONFLICT(item_id,location_id,product_state,technical_state) "
                            "DO UPDATE SET quantity=excluded.quantity",
                            (item_id,loc,ps,ts,amount))
            put(location_id,after)
            if target_id is not None:
                put(target_id,after_target)
            label=(item["brand"]+" / "+item["designation"]).strip(" /")
            event_id=con.execute(
                "INSERT INTO events(item_id,item_label,actor_id,actor_name,action,location_id,"
                "location_code,to_location_id,to_location_code,product_state,technical_state,"
                "quantity,before_source,after_source,before_target,after_target,reason,order_ref,"
                "note,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
                (item_id,label,actor["id"],actor["username"],action,location_id,origin["code"],
                 target_id,target_code,ps,ts,after-before if data.get("inventory") else qty,before,after,before_target,after_target,
                 (data.get("reason","") or "") if action=="issue" else "",
                 (data.get("order_ref","") or "") if action=="issue" else "",
                 data.get("note","") or "",now())).fetchone()[0]
            return {"event_id":event_id,"before":before,"after":after,
                    "before_target":before_target,"after_target":after_target}

    def history(self, item_id=None, actor_id=None, limit=100):
        if limit<1 or limit>500:
            raise Problem(422,"Nieprawidłowy limit")
        sql="SELECT * FROM events WHERE 1=1"
        args=[]
        if item_id is not None:
            sql+=" AND item_id=?"
            args.append(item_id)
        if actor_id is not None:
            sql+=" AND actor_id=?"
            args.append(actor_id)
        sql+=" ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.connect() as con:
            return [dict(r) for r in con.execute(sql,args)]

    def edit_event(self, event_id, data):
        fields={"actor_name","item_label","action","location_code","to_location_code",
                "product_state","technical_state","quantity","before_source",
                "after_source","before_target","after_target","reason","order_ref",
                "note","created_at"}
        changes={k:v for k,v in data.items() if k in fields}
        if not changes:
            raise Problem(422,"Brak pól do aktualizacji")
        with self.connect(write=True) as con:
            if not con.execute("SELECT 1 FROM events WHERE id=?",(event_id,)).fetchone():
                raise Problem(404,"Brak zdarzenia")
            con.execute("UPDATE events SET "+",".join(f+"=?" for f in changes)+" WHERE id=?",
                        (*changes.values(),event_id))

    def delete_event(self,event_id):
        with self.connect(write=True) as con:
            if not con.execute("DELETE FROM events WHERE id=? RETURNING id",(event_id,)).fetchone():
                raise Problem(404,"Brak zdarzenia")

    def set_minimum(self, item_id, minimum, recipient_user_id=None, provider=""):
        if not isinstance(minimum,int) or isinstance(minimum,bool) or minimum<0:
            raise Problem(422,"Nieprawidłowy próg")
        if provider not in ("","telegram","discord"):
            raise Problem(422,"Nieprawidłowy komunikator")
        if (provider and recipient_user_id is None) or (recipient_user_id is not None and not provider):
            raise Problem(422,"Wybierz odbiorcę i komunikator razem")
        with self.connect(write=True) as con:
            self._get_item(con,item_id)
            if recipient_user_id is not None and not con.execute(
                "SELECT 1 FROM users WHERE id=? AND active=1",(recipient_user_id,)).fetchone():
                raise Problem(422,"Odbiorca nie istnieje lub jest nieaktywny")
            con.execute("INSERT INTO minima(item_id,minimum,recipient_user_id,provider) VALUES(?,?,?,?) "
                        "ON CONFLICT(item_id) DO UPDATE SET minimum=excluded.minimum,"
                        "recipient_user_id=excluded.recipient_user_id,provider=excluded.provider",
                        (item_id,minimum,recipient_user_id,provider))

    def low_stock(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT m.item_id,i.designation,i.brand,m.minimum,m.recipient_user_id,m.provider,"
                "COALESCE((SELECT SUM(quantity) FROM balances WHERE item_id=m.item_id),0) AS total "
                "FROM minima m JOIN items i ON i.id=m.item_id "
                "WHERE COALESCE((SELECT SUM(quantity) FROM balances WHERE item_id=m.item_id),0)<=m.minimum "
                "ORDER BY i.designation")]

    def statistics(self):
        with self.connect() as con:
            return {
                "items":con.execute("SELECT COUNT(*) FROM items").fetchone()[0],
                "units":con.execute("SELECT COALESCE(SUM(quantity),0) FROM balances").fetchone()[0],
                "locations":con.execute("SELECT COUNT(*) FROM locations").fetchone()[0],
            }

    def inventory(self, location_id):
        # A read transaction keeps the catalogue and balances in one snapshot.
        with self.connect() as con:
            con.execute("BEGIN")
            if not con.execute("SELECT 1 FROM locations WHERE id=?", (location_id,)).fetchone():
                raise Problem(404,"Brak lokalizacji")
            rows=[]
            for item in con.execute("SELECT id,designation,kind FROM items ORDER BY id"):
                states = [(p,t) for p in sorted(PRODUCT_STATES) for t in sorted(TECH_STATES)] if item["kind"]=="ecu" else [("na","na")]
                for ps,ts in states:
                    balance=con.execute("SELECT quantity FROM balances WHERE item_id=? AND location_id=? AND product_state=? AND technical_state=?",
                                        (item["id"],location_id,ps,ts)).fetchone()
                    rows.append(dict(item_id=item["id"],designation=item["designation"],
                                     product_state=ps,technical_state=ts,
                                     expected_quantity=balance[0] if balance else 0))
            return rows

    def apply_inventory(self, location_id, rows, actor):
        if actor["role"]!="admin":
            raise Problem(403,"Korekta wymaga administratora")
        if not rows or len(rows)>1000:
            raise Problem(422,"Inwentaryzacja wymaga 1–1000 wierszy")
        seen=set()
        with self.connect(write=True) as con:
            results=[]
            for row in rows:
                key=(row["item_id"],row["product_state"],row["technical_state"])
                if key in seen:
                    raise Problem(422,"Powtórzona pozycja inwentaryzacji")
                seen.add(key)
                for field in ("quantity","expected_quantity"):
                    if type(row[field]) is not int or not 0 <= row[field] <= 2_000_000_000:
                        raise Problem(422,"Nieprawidłowa ilość")
                results.append(self.stock_operation(dict(row,location_id=location_id,
                    action="adjust",inventory=True,note="Inwentaryzacja"),actor,connection=con))
            return results
