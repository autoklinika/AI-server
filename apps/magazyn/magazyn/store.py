"""Isolated Magazyn V1 persistence. Never opens an AI Platform production database."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

KINDS = {"ecu", "part"}
PRODUCT_STATES = {"new", "used"}
TECH_STATES = {"working", "faulty", "unknown"}
REASONS = {"repair", "sale", "workshop", "scrap", "other"}
OPERATIONS = {"receive", "issue", "move", "adjust"}
ELECTRONIC_SPEC_FIELDS = ("voltage", "current", "power", "resistance", "capacitance",
                          "tolerance", "pin_count", "temperature", "interface")
DOC_MIME = {"pdf": "application/pdf", "png": "image/png",
            "jpg": "image/jpeg", "jpeg": "image/jpeg"}
DOC_TYPES = {"datasheet", "schematic", "other"}
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DOCUMENTS_PER_ITEM = 6
MAX_TOTAL_DOCUMENT_BYTES = 256 * 1024 * 1024


class Problem(Exception):
    def __init__(self, status: int, detail: str, *, retry_after: int | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


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


# HTTP login controls are intentionally separate from the CLI password check.
# Failed attempts are persisted in SQLite (not per-process RAM), so restarts
# cannot reset brute-force counters. Keys are SHA-256 digests: no raw login,
# source address, or password is stored in the throttle table.
AUTH_WINDOW_SECONDS = 5 * 60
AUTH_BLOCK_SECONDS = 10 * 60
AUTH_ACCOUNT_FAILURES = 5
AUTH_CLIENT_FAILURES = 30
_DUMMY_AUTH_HASH = password_hash("magazyn-invalid-account-timing-placeholder")


def _auth_digest(scope: str, value: str) -> str:
    return hashlib.sha256((scope + "\0" + value).encode("utf-8")).hexdigest()


def _auth_throttle_keys(username: str, client: str) -> tuple[tuple[str, int], tuple[str, int]]:
    account_key = _auth_digest("login-account-client", username.casefold() + "\0" + client)
    client_key = _auth_digest("login-client", client)
    return ((account_key, AUTH_ACCOUNT_FAILURES),
            (client_key, AUTH_CLIENT_FAILURES))


def _blocked_for(con, keys: tuple[tuple[str, int], ...], current: float) -> int:
    """Return whole seconds of remaining block time (zero means allowed)."""
    remaining = 0.0
    for key, _max_failures in keys:
        row = con.execute("SELECT blocked_until FROM auth_login_throttles WHERE key_hash=?",
                          (key,)).fetchone()
        if row and row["blocked_until"] > current:
            remaining = max(remaining, row["blocked_until"] - current)
    return max(1, int(remaining + .999)) if remaining else 0


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
CREATE TABLE IF NOT EXISTS auth_login_throttles (
    key_hash TEXT PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0,
    window_started_at REAL NOT NULL,
    blocked_until REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_auth_login_throttles_expiry
    ON auth_login_throttles(blocked_until,window_started_at);
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
CREATE TABLE IF NOT EXISTS message_pairings (
    code_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('telegram','discord')),
    expires_at TEXT NOT NULL, issued_at TEXT NOT NULL,
    issued_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_pairings_expiry ON message_pairings(expires_at);
CREATE TABLE IF NOT EXISTS stock_alert_state (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    latched INTEGER NOT NULL DEFAULT 0 CHECK(latched IN (0,1)),
    cycle INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS message_outbox (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK(provider IN ('telegram','discord')),
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
       CHECK(status IN ('pending','sending','sent','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL,
    lease_until TEXT, created_at TEXT NOT NULL, sent_at TEXT,
    cycle INTEGER NOT NULL,
    UNIQUE(item_id,cycle)
);
CREATE INDEX IF NOT EXISTS idx_message_outbox_dispatch
    ON message_outbox(provider,status,next_attempt_at,lease_until);
CREATE TABLE IF NOT EXISTS electronic_specs (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    voltage TEXT NOT NULL DEFAULT '',
    current TEXT NOT NULL DEFAULT '',
    power TEXT NOT NULL DEFAULT '',
    resistance TEXT NOT NULL DEFAULT '',
    capacitance TEXT NOT NULL DEFAULT '',
    tolerance TEXT NOT NULL DEFAULT '',
    pin_count TEXT NOT NULL DEFAULT '',
    temperature TEXT NOT NULL DEFAULT '',
    interface TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS item_documents (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    filename TEXT NOT NULL COLLATE NOCASE,
    doc_type TEXT NOT NULL CHECK(doc_type IN ('datasheet','schematic','other')),
    mime TEXT NOT NULL, bytes INTEGER NOT NULL CHECK(bytes > 0),
    sha256 TEXT NOT NULL, content BLOB NOT NULL,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL, UNIQUE(item_id,filename)
);
CREATE INDEX IF NOT EXISTS ix_item_documents_item ON item_documents(item_id);
CREATE TABLE IF NOT EXISTS purchase_state (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('none','ordered')),
    quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity>=0),
    note TEXT NOT NULL DEFAULT '',
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=3;
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
            if version not in (0, 1, 2, 3):
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

    def authenticate_login(self, username: str, password: str, client: str,
                           *, current_time: float | None = None) -> dict:
        """Web login: persistent per-account+client and per-client rate limits.

        Only the socket peer is trusted as client identity. Never use a
        user-supplied X-Forwarded-For header without an audited reverse proxy.
        The local CLI authenticate() remains unrestricted for offline recovery.
        """
        username = (username or "").strip()
        client = (client or "unknown")[:256]
        instant = time.time() if current_time is None else float(current_time)
        keys = _auth_throttle_keys(username, client)
        generic_error = "Nieprawidłowe dane logowania"
        slow_down_error = "Zbyt wiele prób logowania. Spróbuj ponownie później."

        with self.connect() as con:
            wait = _blocked_for(con, keys, instant)
            if wait:
                raise Problem(429, slow_down_error, retry_after=wait)
            found = con.execute("SELECT * FROM users WHERE username=? AND active=1",
                                (username,)).fetchone()

        # Equalize the expensive password verification for unknown users, so
        # unsuccessful requests do not trivially reveal which login exists.
        candidate_hash = found["password_hash"] if found else _DUMMY_AUTH_HASH
        verified = password_verify(password, candidate_hash)
        accepted = None
        wait = 0

        with self.connect(write=True) as con:
            # Recheck under BEGIN IMMEDIATE: concurrent attempts are serialized
            # at the point where failures become authoritative.
            wait = _blocked_for(con, keys, instant)
            if not wait and verified and found:
                current = con.execute(
                    "SELECT * FROM users WHERE id=? AND active=1", (found["id"],)
                ).fetchone()
                if current and hmac.compare_digest(
                        current["password_hash"], found["password_hash"]):
                    accepted = dict(current)
                    # Clear only the successful account's failures. Other
                    # attempted usernames still contribute to the client cap.
                    con.execute("DELETE FROM auth_login_throttles WHERE key_hash=?",
                                (keys[0][0],))
            elif not wait:
                # Bound growth; entries with an expired window and ban have no
                # enforcement value. This never removes an active penalty.
                con.execute(
                    "DELETE FROM auth_login_throttles "
                    "WHERE window_started_at<? AND blocked_until<=?",
                    (instant - AUTH_WINDOW_SECONDS - AUTH_BLOCK_SECONDS, instant)
                )
                for key, threshold in keys:
                    row = con.execute(
                        "SELECT failures,window_started_at FROM auth_login_throttles "
                        "WHERE key_hash=?", (key,)
                    ).fetchone()
                    if not row or instant - row["window_started_at"] >= AUTH_WINDOW_SECONDS:
                        count, started_at = 1, instant
                    else:
                        count, started_at = row["failures"] + 1, row["window_started_at"]
                    until = instant + AUTH_BLOCK_SECONDS if count >= threshold else 0
                    con.execute(
                        "INSERT INTO auth_login_throttles "
                        "(key_hash,failures,window_started_at,blocked_until) "
                        "VALUES(?,?,?,?) ON CONFLICT(key_hash) DO UPDATE SET "
                        "failures=excluded.failures, "
                        "window_started_at=excluded.window_started_at, "
                        "blocked_until=excluded.blocked_until",
                        (key, count, started_at, until),
                    )
                    if until > instant:
                        wait = max(wait, AUTH_BLOCK_SECONDS)

        if accepted is not None:
            return accepted
        if wait:
            raise Problem(429, slow_down_error, retry_after=wait)
        raise Problem(401, generic_error)

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

    def change_password_self(self, user_id: int, current_password: str,
                             new_password: str) -> None:
        """Confirm old password and revoke all sessions in one SQLite transaction."""
        if current_password == new_password:
            raise Problem(422, "Nowe hasło musi być inne niż dotychczasowe")
        with self.connect(write=True) as con:
            record = con.execute(
                "SELECT password_hash FROM users WHERE id=? AND active=1",
                (user_id,)).fetchone()
            if not record:
                raise Problem(401, "Konto nieaktywne")
            if not password_verify(current_password, record["password_hash"]):
                raise Problem(403, "Nieprawidłowe obecne hasło")
            replacement_hash = password_hash(new_password)
            con.execute("UPDATE users SET password_hash=? WHERE id=?",
                        (replacement_hash, user_id))
            con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def change_user(self, user_id, role=None, active=None, password=None, username=None):
        with self.connect(write=True) as con:
            existing_user = con.execute("SELECT role,active FROM users WHERE id=?",
                                        (user_id,)).fetchone()
            if existing_user is None:
                raise Problem(404, "Brak użytkownika")
            if (existing_user["role"] == "admin" and existing_user["active"]
                    and (role == "user" or active is False)):
                admins = con.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1"
                ).fetchone()[0]
                if admins <= 1:
                    raise Problem(409, "Musi pozostać co najmniej jeden aktywny administrator")
            if username is not None:
                username = username.strip()
                if not re.fullmatch(r"[a-zA-Z0-9_.-]{3,40}", username):
                    raise Problem(422, "Login: 3–40 znaków A-Z, 0-9, _, ., -")
                exists = con.execute(
                    "SELECT 1 FROM users WHERE username=? COLLATE NOCASE AND id<>?",
                    (username, user_id)).fetchone()
                if exists:
                    raise Problem(409, "Login jest już zajęty")
                con.execute("UPDATE users SET username=? WHERE id=?", (username, user_id))
            if role is not None:
                if role not in ("admin", "user"):
                    raise Problem(422, "Nieprawidłowa rola")
                con.execute("UPDATE users SET role=? WHERE id=?", (role,user_id))
            if active is not None:
                con.execute("UPDATE users SET active=? WHERE id=?", (int(active),user_id))
                if not active:
                    con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                    from .messaging import handle_account_deactivated
                    handle_account_deactivated(con,user_id)
                else:
                    from .messaging import reconcile_alert
                    for row in con.execute("SELECT item_id FROM minima WHERE recipient_user_id=?",
                                           (user_id,)):
                        reconcile_alert(con,row["item_id"])
            if password is not None:
                con.execute("UPDATE users SET password_hash=? WHERE id=?",
                            (password_hash(password),user_id))
                con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def delete_user(self, user_id):
        with self.connect(write=True) as con:
            existing_user = con.execute("SELECT role,active FROM users WHERE id=?",
                                        (user_id,)).fetchone()
            if existing_user is None:
                raise Problem(404, "Brak użytkownika")
            if existing_user["role"] == "admin" and existing_user["active"]:
                admins = con.execute(
                    "SELECT COUNT(*) FROM users WHERE role='admin' AND active=1"
                ).fetchone()[0]
                if admins <= 1:
                    raise Problem(409, "Nie można usunąć ostatniego aktywnego administratora")
            con.execute("DELETE FROM users WHERE id=?", (user_id,))

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

    def similar_items(self, data, *, connection=None, limit=8):
        """Potential duplicate positions, including cross-reference numbers.

        A matching identifier on a different HW/SW variant is a warning, not
        permission to silently merge or block a genuinely distinct controller.
        """
        kind = data.get("kind")
        if kind not in KINDS:
            raise Problem(422, "Nieprawidłowy rodzaj produktu")
        numbers = {normalize(str(data.get("primary_number") or ""))}
        for entry in data.get("numbers", []):
            if not isinstance(entry, dict):
                raise Problem(422, "Nieprawidłowe numery dodatkowe")
            numbers.add(normalize(str(entry.get("number") or "")))
        numbers.discard("")
        name = normalize(str(data.get("designation") or ""))
        brand = normalize(str(data.get("brand") or ""))
        manufacturer = normalize(str(data.get("manufacturer") or ""))
        model = normalize(str(data.get("model") or ""))
        own_hw = normalize(str(data.get("hw") or ""))
        own_sw = normalize(str(data.get("sw") or ""))
        own_package = normalize(str(data.get("package") or ""))
        own_parameters = normalize(str(data.get("parameters") or ""))
        own_category = normalize(str(data.get("category") or ""))
        context = nullcontext(connection) if connection is not None else self.connect()
        with context as con:
            matches = []
            for item in con.execute("SELECT * FROM items WHERE kind=? ORDER BY id DESC", (kind,)):
                item_id = item["id"]
                item_numbers = {row[0] for row in con.execute(
                    "SELECT normalized FROM item_numbers WHERE item_id=?", (item_id,))}
                number_match = bool(numbers & item_numbers)
                item_brands = [row[0] for row in con.execute(
                    "SELECT brand FROM item_brands WHERE item_id=?", (item_id,))]
                brand_match = not brand or any(normalize(b) == brand for b in item_brands)
                name_match = bool(name) and name == normalize(item["designation"])
                maker_match = not manufacturer or manufacturer == normalize(item["manufacturer"])
                model_match = not model or model == normalize(item["model"])
                if not (number_match or (name_match and maker_match and model_match and brand_match)):
                    continue
                # Identical name alone does not prove identical hardware.
                # Different primary numbers without a shared alias must be
                # allowed as a distinct variant after explicit confirmation.
                exact_identifier = number_match or (not numbers and not item_numbers)
                if kind == "ecu":
                    same_variant = (
                        exact_identifier and
                        own_hw == normalize(item["hw"]) and
                        own_sw == normalize(item["sw"]) and brand_match
                    )
                else:
                    incoming_specs = data.get("specs")
                    specs_match = True
                    if incoming_specs is not None:
                        wanted = self._validated_specs(incoming_specs)
                        present = con.execute(
                            "SELECT * FROM electronic_specs WHERE item_id=?", (item_id,)).fetchone()
                        specs_match = all(
                            normalize(wanted[field]) == normalize(present[field] if present else "")
                            for field in ELECTRONIC_SPEC_FIELDS)
                    same_variant = (
                        exact_identifier and
                        own_package == normalize(item["package"]) and
                        own_parameters == normalize(item["parameters"]) and
                        own_category == normalize(item["category"]) and specs_match
                    )
                existing_qty = con.execute(
                    "SELECT COALESCE(SUM(quantity),0) FROM balances WHERE item_id=?",
                    (item_id,)).fetchone()[0]
                matches.append({
                    "id": item_id,
                    "designation": item["designation"],
                    "brand": item["brand"],
                    "primary_number": item["primary_number"],
                    "hw": item["hw"], "sw": item["sw"],
                    "quantity": existing_qty,
                    "reason": "Ten sam numer / numer zamienny" if number_match else "Podobne oznaczenie",
                    "same_variant": same_variant,
                })
                if len(matches) >= limit:
                    break
            return matches

    def add_item_with_stock(self, data, actor, *, allow_distinct_variant=False):
        """One transaction covers duplicate guard, catalog and initial receipt."""
        quantity = data.get("quantity")
        location_id = data.get("location_id")
        location_code = data.get("new_location_code") or ""
        location_description = data.get("new_location_description") or ""
        if type(quantity) is not int or not 0 <= quantity <= 2_000_000_000:
            raise Problem(422, "Ilość musi być liczbą całkowitą od 0 do 2000000000")
        if not isinstance(location_code, str) or not isinstance(location_description, str):
            raise Problem(422, "Nieprawidłowe dane lokalizacji")
        location_code = location_code.strip()
        location_description = location_description.strip()
        if location_code:
            if actor["role"] != "admin":
                raise Problem(403, "Nową lokalizację może utworzyć tylko administrator")
            if location_id is not None:
                raise Problem(422, "Wybierz istniejącą lokalizację albo utwórz nową")
            if (len(location_code) > 64 or len(location_description) > 300
                    or any(ord(char) < 32 or ord(char) == 127 for char in location_code)):
                raise Problem(422, "Nieprawidłowy kod lokalizacji")
        elif type(location_id) is not int or location_id < 1:
            raise Problem(422, "Wskaż lokalizację lub podaj kod nowego miejsca")
        kind = data.get("kind")
        if kind not in KINDS:
            raise Problem(422, "Nieprawidłowy rodzaj produktu")
        with self.connect(write=True) as con:
            if location_code:
                # Creation, duplicate detection and initial stock receipt share
                # one transaction. Any later validation error rolls this back.
                try:
                    location_id = con.execute(
                        "INSERT INTO locations(code,description) VALUES (?,?) RETURNING id",
                        (location_code, location_description)).fetchone()[0]
                except sqlite3.IntegrityError as exc:
                    raise Problem(409, "Ta lokalizacja już istnieje; odśwież listę") from exc
            elif con.execute("SELECT 1 FROM locations WHERE id=?", (location_id,)).fetchone() is None:
                raise Problem(404, "Nie ma podanej lokalizacji")
            similar = self.similar_items(data, connection=con)
            if any(s["same_variant"] for s in similar):
                raise Problem(409, "Pozycja o tym oznaczeniu i wariancie już istnieje. Otwórz istniejący produkt i przyjmij sztuki.")
            if similar and not allow_distinct_variant:
                raise Problem(409, "Znaleziono podobny produkt lub numer zamienny. Sprawdź wariant HW/SW i potwierdź świadome dodanie nowego wpisu.")
            if kind == "ecu":
                ps = data.get("product_state")
                ts = data.get("technical_state")
                if ps not in PRODUCT_STATES or ts not in TECH_STATES:
                    raise Problem(422, "Wybierz stan produktu i sprawność sterownika")
            else:
                ps, ts = "na", "na"
            item_id = self.add_item(data, actor, connection=con)
            event_id = None
            if quantity:
                received = self.stock_operation({
                    "action": "receive", "item_id": item_id,
                    "location_id": location_id, "quantity": quantity,
                    "product_state": ps, "technical_state": ts,
                    "note": "Przyjęcie przy tworzeniu nowej pozycji",
                }, actor, connection=con)
                event_id = received["event_id"]
            return {"id": item_id, "quantity": quantity, "event_id": event_id}

    @staticmethod
    def _validated_specs(raw):
        if raw is None:
            return {name: "" for name in ELECTRONIC_SPEC_FIELDS}
        if not isinstance(raw, dict) or set(raw) - set(ELECTRONIC_SPEC_FIELDS):
            raise Problem(422, "Nieprawidłowe pola parametrów elektroniki")
        values = {}
        for name in ELECTRONIC_SPEC_FIELDS:
            value = raw.get(name, "")
            if not isinstance(value, str) or len(value.strip()) > 120 or any(
                    ord(ch) < 32 for ch in value):
                raise Problem(422, "Nieprawidłowa wartość parametru elektroniki")
            values[name] = value.strip()
        return values

    @classmethod
    def _upsert_specs(cls, con, item_id, raw):
        values = cls._validated_specs(raw)
        fields = ELECTRONIC_SPEC_FIELDS
        con.execute(
            "INSERT INTO electronic_specs(item_id," + ",".join(fields) + ") VALUES(" +
            ",".join(["?"]*(len(fields)+1)) + ") ON CONFLICT(item_id) DO UPDATE SET " +
            ",".join(f"{f}=excluded.{f}" for f in fields),
            (item_id, *(values[name] for name in fields)))

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
            if kind == "part":
                self._upsert_specs(con, item_id, data.get("specs"))
            elif data.get("specs"):
                raise Problem(422, "Parametry elektroniczne dotyczą tylko elektroniki")
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
            if "specs" in data and original["kind"] != "part":
                raise Problem(422, "Parametry elektroniki nie dotyczą sterowników")
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
            if "specs" in data:
                self._upsert_specs(con, item_id, data["specs"])
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

    def add_document(self, item_id: int, filename: str, doc_type: str,
                     content: bytes, actor: dict) -> dict:
        filename = filename.strip() if isinstance(filename,str) else ""
        if (not filename or len(filename) > 140 or filename.startswith(".")
            or "/" in filename or "\\" in filename or
            any(ord(c)<32 or ord(c)==127 for c in filename)):
            raise Problem(422, "Nieprawidłowa nazwa dokumentu")
        if doc_type not in DOC_TYPES:
            raise Problem(422, "Wybierz typ dokumentacji")
        extension = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
        if extension not in DOC_MIME:
            raise Problem(422, "Dokumentacja: obsługujemy PDF, PNG i JPG")
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_DOCUMENT_BYTES:
            raise Problem(413, "Plik dokumentacji nie może przekraczać 8 MB")
        if (extension == "pdf" and
            (not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:])):
            raise Problem(422, "Plik nie jest prawidłowym PDF")
        if extension == "png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise Problem(422, "Plik nie jest prawidłowym PNG")
        if extension in ("jpg","jpeg") and not (content.startswith(b"\xff\xd8\xff")
                                               and content.endswith(b"\xff\xd9")):
            raise Problem(422, "Plik nie jest prawidłowym JPG")
        with self.connect(write=True) as con:
            item = self._get_item(con,item_id)
            if item["kind"] != "part":
                raise Problem(422, "Dokumentacja techniczna dotyczy elementów elektronicznych")
            count, used = con.execute(
                "SELECT COUNT(*),COALESCE(SUM(bytes),0) FROM item_documents WHERE item_id=?",
                (item_id,)).fetchone()
            if count >= MAX_DOCUMENTS_PER_ITEM:
                raise Problem(409, "Maksymalnie 6 dokumentów dla elementu")
            overall = con.execute("SELECT COALESCE(SUM(bytes),0) FROM item_documents").fetchone()[0]
            if overall + len(content) > MAX_TOTAL_DOCUMENT_BYTES:
                raise Problem(413, "Osiągnięto bezpieczny limit dokumentacji Magazynu")
            try:
                row = con.execute(
                    "INSERT INTO item_documents(item_id,filename,doc_type,mime,bytes,sha256,"
                    "content,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?) RETURNING id",
                    (item_id,filename,doc_type,DOC_MIME[extension],len(content),
                     hashlib.sha256(content).hexdigest(),sqlite3.Binary(content),
                     actor["id"],now())).fetchone()
            except sqlite3.IntegrityError as exc:
                raise Problem(409, "Dokument o tej nazwie już istnieje") from exc
            return {"id":row["id"],"filename":filename,"bytes":len(content),
                    "doc_type":doc_type}

    def list_documents(self, item_id: int) -> list[dict]:
        with self.connect() as con:
            item = self._get_item(con,item_id)
            if item["kind"] != "part":
                raise Problem(422, "Dokumenty techniczne dotyczą elektroniki")
            return [dict(row) for row in con.execute(
                "SELECT id,filename,doc_type,mime,bytes,sha256,created_at FROM item_documents "
                "WHERE item_id=? ORDER BY id DESC", (item_id,))]

    def read_document(self, item_id: int, document_id: int) -> dict:
        with self.connect() as con:
            self._get_item(con,item_id)
            row=con.execute("SELECT * FROM item_documents WHERE item_id=? AND id=?",
                            (item_id,document_id)).fetchone()
            if row is None:
                raise Problem(404, "Brak dokumentu")
            document=dict(row)
            if hashlib.sha256(document["content"]).hexdigest()!=document["sha256"]:
                raise Problem(503, "Błąd integralności dokumentu")
            return document

    def delete_document(self, item_id: int, document_id: int) -> None:
        with self.connect(write=True) as con:
            self._get_item(con,item_id)
            removed=con.execute("DELETE FROM item_documents WHERE item_id=? AND id=? RETURNING id",
                                (item_id,document_id)).fetchone()
            if removed is None:
                raise Problem(404, "Brak dokumentu")

    def set_order_status(self, item_id: int, status: str, quantity: int,
                         note: str, actor: dict) -> dict:
        if status not in ("none","ordered") or type(quantity) is not int:
            raise Problem(422, "Nieprawidłowy status zamówienia")
        if not isinstance(note,str) or len(note.strip()) > 300:
            raise Problem(422, "Za długa notatka o zamówieniu")
        if (status=="ordered" and not 1<=quantity<=2_000_000_000) or (
                status=="none" and quantity!=0):
            raise Problem(422, "Podaj prawidłową liczbę zamówionych sztuk")
        with self.connect(write=True) as con:
            self._get_item(con,item_id)
            con.execute(
                "INSERT INTO purchase_state(item_id,status,quantity,note,updated_by,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET "
                "status=excluded.status,quantity=excluded.quantity,note=excluded.note,"
                "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                (item_id,status,quantity,note.strip(),actor["id"],now()))
        return self.get_order_status(item_id)

    def receive_order_delivery(self, item_id: int, location_id: int, quantity: int,
                               actor: dict, *, product_state: str | None = None,
                               technical_state: str | None = None) -> dict:
        """Atomically receive actual delivered goods and reduce pending order units.

        Separate from ordinary receipt: only a confirmed delivery changes
        purchase_state. SQLite BEGIN IMMEDIATE protects concurrent deliveries.
        """
        if actor.get("role") != "admin":
            raise Problem(403, "Przyjęcie zamówienia wymaga administratora")
        if (type(item_id) is not int or item_id < 1 or type(location_id) is not int
                or location_id < 1 or type(quantity) is not int
                or not 1 <= quantity <= 2_000_000_000):
            raise Problem(422, "Nieprawidłowe dane dostawy")
        with self.connect(write=True) as con:
            product = self._get_item(con, item_id)
            row = con.execute(
                "SELECT status, quantity, note FROM purchase_state WHERE item_id=?",
                (item_id,)).fetchone()
            if row is None or row["status"] != "ordered" or row["quantity"] < quantity:
                raise Problem(409, "Brak aktywnego zamówienia lub dostawa przekracza oczekującą ilość")
            if product["kind"] == "ecu":
                ps = product_state if product_state is not None else "new"
                ts = technical_state if technical_state is not None else "unknown"
                if ps not in PRODUCT_STATES or ts not in TECH_STATES:
                    raise Problem(422, "Wybierz stan i sprawność dostarczonego sterownika")
            else:
                ps, ts = "na", "na"
                if product_state not in (None, "na") or technical_state not in (None, "na"):
                    raise Problem(422, "Elektronika nie używa stanów ECU")
            receipt = self.stock_operation({
                "action": "receive", "item_id": item_id, "location_id": location_id,
                "quantity": quantity, "product_state": ps, "technical_state": ts,
                "note": "Przyjęcie dostawy zamówionego produktu",
            }, actor, connection=con)
            remaining = row["quantity"] - quantity
            status = "ordered" if remaining else "none"
            con.execute(
                "UPDATE purchase_state SET status=?, quantity=?, note=?, "
                "updated_by=?, updated_at=? WHERE item_id=?",
                (status, remaining, row["note"] if remaining else "",
                 actor["id"], now(), item_id))
            return {
                "status": "PASS", "receipt_event_id": receipt["event_id"],
                "received": quantity, "remaining_ordered": remaining,
                "order_status": status, "stock_after_location": receipt["after"],
            }

    def get_order_status(self,item_id: int) -> dict:
        with self.connect() as con:
            self._get_item(con,item_id)
            row=con.execute("SELECT status,quantity,note,updated_at FROM purchase_state WHERE item_id=?",
                            (item_id,)).fetchone()
            return dict(row) if row else {
                "status":"none","quantity":0,"note":"","updated_at":None}

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
            status = con.execute("SELECT status,quantity,note,updated_at FROM purchase_state WHERE item_id=?",
                                 (item_id,)).fetchone()
            item["order_status"] = dict(status) if status else {
                "status":"none","quantity":0,"note":"","updated_at":None}
            if item["kind"] == "part":
                spec = con.execute("SELECT * FROM electronic_specs WHERE item_id=?",
                                   (item_id,)).fetchone()
                item["specs"] = {field:spec[field] if spec else "" for field in ELECTRONIC_SPEC_FIELDS}
                item["documents"] = [dict(r) for r in con.execute(
                    "SELECT id, filename, doc_type, mime, bytes, sha256, created_at "
                    "FROM item_documents WHERE item_id=? ORDER BY id DESC", (item_id,))]
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
                if q and item["kind"]=="part":
                    spec = con.execute("SELECT * FROM electronic_specs WHERE item_id=?",
                                       (item["id"],)).fetchone()
                    if spec:
                        haystack.extend(spec[field] for field in ELECTRONIC_SPEC_FIELDS)
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
                status=con.execute("SELECT status,quantity FROM purchase_state WHERE item_id=?",
                                   (item["id"],)).fetchone()
                item["order_status"]=status["status"] if status else "none"
                item["ordered_quantity"]=status["quantity"] if status else 0
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
            if after>2_000_000_000 or (after_target is not None and after_target>2_000_000_000):
                raise Problem(422,"Przekroczono maksymalny stan w lokalizacji")
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
            if action != "move" and not data.get("defer_alert"):
                from .messaging import reconcile_alert
                reconcile_alert(con, item_id)
            return {"event_id":event_id,"before":before,"after":after,
                    "before_target":before_target,"after_target":after_target}

    def history(self, item_id=None, actor_id=None, limit=100, *,
                query="", date_from=None, date_to=None):
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
        if query.strip():
            sql+=" AND instr(lower(item_label),lower(?))>0"
            args.append(query.strip())
        if date_from is not None:
            sql+=" AND substr(created_at,1,10)>=?"
            args.append(date_from.isoformat())
        if date_to is not None:
            sql+=" AND substr(created_at,1,10)<=?"
            args.append(date_to.isoformat())
        sql+=" ORDER BY created_at DESC,id DESC LIMIT ?"
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
            previous = con.execute(
                "SELECT minimum,recipient_user_id,provider FROM minima WHERE item_id=?",
                (item_id,)).fetchone()
            con.execute("INSERT INTO minima(item_id,minimum,recipient_user_id,provider) VALUES(?,?,?,?) "
                        "ON CONFLICT(item_id) DO UPDATE SET minimum=excluded.minimum,"
                        "recipient_user_id=excluded.recipient_user_id,provider=excluded.provider",
                        (item_id,minimum,recipient_user_id,provider))
            # Re-evaluate only on changed settings; identical PUT must not re-notify.
            changed = previous is None or (
                previous["minimum"] != minimum or
                previous["recipient_user_id"] != recipient_user_id or
                previous["provider"] != provider)
            from .messaging import minimum_changed
            minimum_changed(con,item_id,reset=changed)

    def minimum_settings(self, item_id):
        with self.connect() as con:
            self._get_item(con,item_id)
            record=con.execute(
                "SELECT minimum,recipient_user_id,provider FROM minima WHERE item_id=?",
                (item_id,)).fetchone()
            return dict(record) if record else {
                "minimum":None,"recipient_user_id":None,"provider":""}

    def low_stock(self):
        with self.connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT m.item_id,i.designation,i.brand,m.minimum,m.recipient_user_id,m.provider,"
                "COALESCE(p.status,'none') AS order_status,"
                "COALESCE(p.quantity,0) AS ordered_quantity,p.updated_at AS ordered_at,"
                "COALESCE((SELECT SUM(quantity) FROM balances WHERE item_id=m.item_id),0) AS total "
                "FROM minima m JOIN items i ON i.id=m.item_id "
                "LEFT JOIN purchase_state p ON p.item_id=m.item_id "
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
            touched=set()
            for row in rows:
                key=(row["item_id"],row["product_state"],row["technical_state"])
                if key in seen:
                    raise Problem(422,"Powtórzona pozycja inwentaryzacji")
                seen.add(key)
                for field in ("quantity","expected_quantity"):
                    if type(row[field]) is not int or not 0 <= row[field] <= 2_000_000_000:
                        raise Problem(422,"Nieprawidłowa ilość")
                results.append(self.stock_operation(dict(row,location_id=location_id,
                    action="adjust",inventory=True,defer_alert=True,
                    note="Inwentaryzacja"),actor,connection=con))
                touched.add(row["item_id"])
            from .messaging import reconcile_alert
            for item_id in touched:
                reconcile_alert(con,item_id)
            return results
