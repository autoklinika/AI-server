"""Magazyn private messaging: verified account pairing, read-only queries, durable targeted alerts.

No network clients or bot tokens are required by this module. Database changes must be
performed in an existing SQLite transaction for stock consistency.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from .store import Problem, now, normalize

PROVIDERS = ("telegram", "discord")
PAIRING_TTL_MINUTES = 10
MAX_RESULT_ITEMS = 5


def _timestamp(seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _identity(value: str | int) -> str:
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,23}", value):
        raise Problem(422, "Nieprawidłowy identyfikator użytkownika komunikatora")
    return value


def create_pairing(store, user_id: int, provider: str, admin_id: int) -> dict:
    """An administrator creates a short-lived, one-use secret for a named user/provider."""
    if provider not in PROVIDERS:
        raise Problem(422, "Nieprawidłowy komunikator")
    with store.connect(write=True) as con:
        row = con.execute("SELECT username,active FROM users WHERE id=?", (user_id,)).fetchone()
        if not row or not row["active"]:
            raise Problem(404, "Nieaktywny lub nieistniejący użytkownik")
        if not con.execute("SELECT 1 FROM users WHERE id=? AND role='admin' AND active=1",
                           (admin_id,)).fetchone():
            raise Problem(403, "Tylko administrator może tworzyć kody")
        # Prevent several active secrets for the same account/provider.
        con.execute("DELETE FROM message_pairings WHERE user_id=? AND provider=?",
                    (user_id, provider))
        code = secrets.token_urlsafe(24)
        code_hash = hashlib.sha256(code.encode("ascii")).hexdigest()
        expiry = _timestamp(PAIRING_TTL_MINUTES*60)
        con.execute("DELETE FROM message_pairings WHERE expires_at<?", (now(),))
        con.execute("INSERT INTO message_pairings(code_hash,user_id,provider,expires_at,issued_at,issued_by) "
                    "VALUES (?,?,?,?,?,?)",
                    (code_hash,user_id,provider,expiry,now(),admin_id))
        return {"provider":provider, "username":row["username"], "user_id":user_id,
                "code":code,"expires_at":expiry}


def redeem_pairing(store, provider: str, external_user_id: str | int, code: str) -> bool:
    """Redeem a token only in a verified private DM. Caller enforces private-only."""
    if provider not in PROVIDERS:
        return False
    try:
        remote_id = _identity(external_user_id)
    except Problem:
        return False
    if not isinstance(code,str) or len(code)>80 or len(code)<20 or not re.fullmatch(r"[A-Za-z0-9_-]+",code):
        return False
    digest = hashlib.sha256(code.encode("ascii")).hexdigest()
    with store.connect(write=True) as con:
        row = con.execute(
            "SELECT p.user_id,u.active FROM message_pairings p "
            "JOIN users u ON u.id=p.user_id WHERE p.code_hash=? AND p.provider=? AND p.expires_at>?",
            (digest,provider,now())).fetchone()
        if not row or not row["active"]:
            return False
        target_id = row["user_id"]
        # Someone else's account must never be stolen by presenting a pairing code.
        existing = con.execute(
            "SELECT user_id FROM external_accounts WHERE provider=? AND external_user_id=? "
            "AND verified=1",(provider,remote_id)).fetchone()
        if existing and existing["user_id"] != target_id:
            return False
        old = con.execute(
            "SELECT external_user_id FROM external_accounts "
            "WHERE provider=? AND user_id=? AND verified=1",(provider,target_id)).fetchone()
        # Pairing the *same* account must not re-issue an already delivered low-stock alert.
        if old and old["external_user_id"] == remote_id:
            con.execute("DELETE FROM message_pairings WHERE code_hash=?", (digest,))
            return True
        waiting = {r["item_id"] for r in con.execute(
            "SELECT item_id FROM message_outbox WHERE user_id=? AND provider=? "
            "AND status IN ('pending','sending')",(target_id,provider))}
        # One verified external identity per user per provider; relinking revokes the old identity.
        con.execute("DELETE FROM external_accounts WHERE provider=? AND user_id=?",
                    (provider,target_id))
        con.execute(
            "INSERT INTO external_accounts(provider,external_user_id,user_id,verified) VALUES (?,?,?,1)",
            (provider,remote_id,target_id))
        con.execute("DELETE FROM message_pairings WHERE code_hash=?", (digest,))
        _cancel_pending(con, user_id=target_id, provider=provider)
        # Reset only undelivered alerts. Already-sent cycles stay latched.
        for minimum in con.execute("SELECT item_id FROM minima WHERE recipient_user_id=? AND provider=?",
                                   (target_id,provider)):
            if minimum["item_id"] in waiting:
                _reset_latch(con,minimum["item_id"])
            reconcile_alert(con,minimum["item_id"])
    return True


def linked_user(store, provider: str, external_user_id: str | int) -> dict | None:
    if provider not in PROVIDERS:
        return None
    try:
        remote_id = _identity(external_user_id)
    except Problem:
        return None
    with store.connect() as con:
        row = con.execute(
            "SELECT u.id,u.username,u.role FROM external_accounts a JOIN users u ON a.user_id=u.id "
            "WHERE a.provider=? AND a.external_user_id=? AND a.verified=1 AND u.active=1",
            (provider,remote_id)).fetchone()
        return dict(row) if row else None


def list_links(store) -> list[dict]:
    with store.connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT a.provider,a.external_user_id,a.user_id,u.username,u.active "
            "FROM external_accounts a JOIN users u ON a.user_id=u.id "
            "WHERE a.verified=1 ORDER BY u.username,a.provider")]


def unlink(store, provider: str, user_id: int) -> bool:
    if provider not in PROVIDERS:
        raise Problem(422, "Nieprawidłowy komunikator")
    with store.connect(write=True) as con:
        affected = con.execute(
            "DELETE FROM external_accounts WHERE provider=? AND user_id=? RETURNING user_id",
            (provider,user_id)).fetchone()
        con.execute("DELETE FROM message_pairings WHERE provider=? AND user_id=?",
                    (provider,user_id))
        if affected:
            waiting = {r["item_id"] for r in con.execute(
                "SELECT item_id FROM message_outbox WHERE user_id=? AND provider=? "
                "AND status IN ('pending','sending')",(user_id,provider))}
            _cancel_pending(con, user_id=user_id, provider=provider)
            for row in con.execute(
                    "SELECT item_id FROM minima WHERE provider=? AND recipient_user_id=?",
                    (provider,user_id)):
                if row["item_id"] in waiting:
                    _reset_latch(con,row["item_id"])
    return bool(affected)


def _cancel_pending(con, *, item_id=None, user_id=None, provider=None):
    filters = ["status IN ('pending','sending')"]
    args = []
    if item_id is not None:
        filters.append("item_id=?");args.append(item_id)
    if user_id is not None:
        filters.append("user_id=?");args.append(user_id)
    if provider is not None:
        filters.append("provider=?");args.append(provider)
    con.execute("UPDATE message_outbox SET status='cancelled',lease_until=NULL "
                "WHERE "+" AND ".join(filters),args)


def _reset_latch(con, item_id):
    con.execute(
        "INSERT INTO stock_alert_state(item_id,latched,cycle) VALUES (?,0,1) "
        "ON CONFLICT(item_id) DO UPDATE SET latched=0,cycle=stock_alert_state.cycle+1",
        (item_id,))


def _alert_text(con, item_id, minimum, quantity):
    item = con.execute("SELECT designation,brand FROM items WHERE id=?",
                       (item_id,)).fetchone()
    if not item:
        return None
    label = (item["brand"]+" / "+item["designation"]).strip(" /")
    return (f"Magazyn — niski stan\n{label}\n"
            f"Pozostało: {quantity} szt.\nStan minimalny: {minimum} szt.")


def reconcile_alert(con, item_id: int) -> None:
    """Adjust alert latch and outbox inside the same stock transaction. No network calls."""
    minimum = con.execute(
        "SELECT minimum,recipient_user_id,provider FROM minima WHERE item_id=?",
        (item_id,)).fetchone()
    if not minimum:
        return
    quantity = con.execute("SELECT COALESCE(SUM(quantity),0) FROM balances WHERE item_id=?",
                           (item_id,)).fetchone()[0]
    if quantity > minimum["minimum"]:
        state = con.execute("SELECT latched FROM stock_alert_state WHERE item_id=?",(item_id,)).fetchone()
        if state and state["latched"]:
            _reset_latch(con,item_id)
        _cancel_pending(con,item_id=item_id)
        return

    state = con.execute("SELECT latched,cycle FROM stock_alert_state WHERE item_id=?",
                        (item_id,)).fetchone()
    if state and state["latched"]:
        return
    recipient_id,provider = minimum["recipient_user_id"],minimum["provider"]
    if not recipient_id or provider not in PROVIDERS:
        return
    linked = con.execute(
        "SELECT 1 FROM external_accounts a JOIN users u ON a.user_id=u.id "
        "WHERE a.provider=? AND a.user_id=? AND a.verified=1 AND u.active=1",
        (provider,recipient_id)).fetchone()
    if not linked:
        return
    if state is None:
        con.execute("INSERT INTO stock_alert_state(item_id,latched,cycle) VALUES (?,0,0)",(item_id,))
        cycle = 0
    else:
        cycle = state["cycle"]
    message = _alert_text(con,item_id,minimum["minimum"],quantity)
    if message is None:
        return
    con.execute(
        "INSERT INTO message_outbox(item_id,user_id,provider,body,status,attempts,next_attempt_at,"
        "created_at,cycle) VALUES (?,?,?,?,'pending',0,?,?,?)",
        (item_id,recipient_id,provider,message,now(),now(),cycle))
    con.execute("UPDATE stock_alert_state SET latched=1 WHERE item_id=?",(item_id,))


def minimum_changed(con, item_id, *, reset: bool):
    if reset:
        _cancel_pending(con,item_id=item_id)
        _reset_latch(con,item_id)
    reconcile_alert(con,item_id)


def handle_account_deactivated(con, user_id):
    waiting = {r["item_id"] for r in con.execute(
        "SELECT item_id FROM message_outbox WHERE user_id=? "
        "AND status IN ('pending','sending')",(user_id,))}
    _cancel_pending(con,user_id=user_id)
    for row in con.execute(
            "SELECT item_id FROM minima WHERE recipient_user_id=?",
            (user_id,)):
        if row["item_id"] in waiting:
            _reset_latch(con,row["item_id"])


def _drop_text_prefix(value: str) -> str:
    value = value.strip()
    for pattern in (r"^ile\s+(?:mam\s+)?",r"^czy\s+mam\s+",r"^poka[żz]\s+",
                    r"^szukaj\s+",r"^stan\s+(?:magazynowy\s+)?"):
        value = re.sub(pattern,"",value,flags=re.IGNORECASE).strip()
    return value.strip(" ?.!:")


def format_results(store, term: str) -> str:
    term = _drop_text_prefix(term)
    if len(term) < 2 or len(term)>120:
        return "Podaj co najmniej 2 znaki oznaczenia lub numeru (maks. 120)."
    items = store.items(query=term,limit=MAX_RESULT_ITEMS+1)
    if not items:
        return "Nie znaleziono produktu o podanym oznaczeniu."
    more = len(items) > MAX_RESULT_ITEMS
    output = [f"Wyniki magazynu dla: {term}"]
    for entry in items[:MAX_RESULT_ITEMS]:
        details = store.item(entry["id"])
        label = (details["brand"] + " / " + details["designation"]).strip(" /")
        output.append(f"\n{label} — {details['total']} szt.")
        summary = []
        for b in details["balances"]:
            state = (("nowy" if b["product_state"]=="new" else "używany")+" / "+
                     {"working":"sprawny","faulty":"uszkodzony","unknown":"nieznany"}.get(
                         b["technical_state"],"?")) if details["kind"]=="ecu" else ""
            summary.append(f"{b['location']}: {b['quantity']}"+(f" ({state})" if state else ""))
        if summary:
            output.append("  "+", ".join(summary[:7]))
        if len(summary)>7:
            output.append("  …pozostałe lokalizacje w WebGUI.")
    if more:
        output.append("\nWięcej wyników — doprecyzuj zapytanie.")
    # Discord's max message is 2000 chars; leave space for escaping if adapters need it.
    return "\n".join(output)[:1700]


def process_private_message(store, provider: str, external_user_id: str | int,
                            content: str) -> str:
    """Domain layer; caller *must* verify DM context before invoking this method."""
    if provider not in PROVIDERS:
        return "Nieobsługiwany komunikator."
    if not isinstance(content,str) or len(content)>280:
        return "Zbyt długa wiadomość."
    content=content.strip()
    if not content:
        return "Użyj /stan NUMER albo /pomoc."
    if content.lower().startswith("/polacz "):
        code=content.split(maxsplit=1)[1].strip()
        if redeem_pairing(store,provider,external_user_id,code):
            return "Konto zostało powiązane z Magazynem. Dostęp tylko w rozmowie prywatnej."
        return "Nieprawidłowy lub wygasły kod. Poproś administratora o nowy kod."
    # Never reveal whether a product exists before authentication.
    user = linked_user(store, provider, external_user_id)
    if not user:
        return "Brak dostępu do Magazynu. Administrator musi powiązać Twoje konto."
    lower=content.lower()
    if lower in {"/start","/help","/pomoc","pomoc","help"}:
        return "Magazyn: /stan NUMER, /szukaj NAZWA lub zwykłe pytanie „ile mam ...”. Wyłącznie odczyt."
    if lower.startswith(("/stan ","/szukaj ","/ile ")):
        term = content.split(maxsplit=1)[1]
    elif content.startswith("/"):
        return "Nieznane polecenie. Użyj /pomoc."
    else:
        term=content
    return format_results(store,term)


def _delivery_valid(con, record):
    row=con.execute(
        "SELECT m.provider,m.recipient_user_id,m.minimum,i.id AS item_exists, "
        "COALESCE((SELECT SUM(quantity) FROM balances WHERE item_id=m.item_id),0) AS total "
        "FROM minima m JOIN items i ON i.id=m.item_id WHERE m.item_id=?",
        (record["item_id"],)).fetchone()
    if not row or row["provider"]!=record["provider"] or row["recipient_user_id"]!=record["user_id"]:
        return None
    if row["total"] > row["minimum"]:
        return None
    identity=con.execute(
        "SELECT a.external_user_id FROM external_accounts a JOIN users u ON u.id=a.user_id "
        "WHERE a.provider=? AND a.user_id=? AND a.verified=1 AND u.active=1",
        (record["provider"],record["user_id"])).fetchone()
    return identity["external_user_id"] if identity else None


def claim_next(store, provider: str) -> dict | None:
    """Atomically lease one alert for delivery; at-least-once, bounded retry."""
    if provider not in PROVIDERS:
        raise Problem(422,"Nieprawidłowy komunikator")
    with store.connect(write=True) as con:
        candidates=con.execute(
            "SELECT * FROM message_outbox WHERE provider=? AND "
            "((status='pending' AND next_attempt_at<=?) OR "
            "(status='sending' AND lease_until<=?)) "
            "ORDER BY id LIMIT 10", (provider,now(),now())).fetchall()
        for row in candidates:
            item=dict(row)
            external_id=_delivery_valid(con,item)
            if external_id is None:
                con.execute("UPDATE message_outbox SET status='cancelled',lease_until=NULL "
                            "WHERE id=?",(item["id"],))
                continue
            snapshot=con.execute(
                "SELECT minimum,COALESCE((SELECT SUM(quantity) FROM balances WHERE item_id=?),0) "
                "AS total FROM minima WHERE item_id=?",
                (item["item_id"],item["item_id"])).fetchone()
            body=_alert_text(con,item["item_id"],snapshot["minimum"],snapshot["total"])
            if body is None:
                con.execute("UPDATE message_outbox SET status='cancelled' WHERE id=?",
                            (item["id"],))
                continue
            lease=_timestamp(90)
            con.execute(
                "UPDATE message_outbox SET status='sending',attempts=attempts+1,lease_until=?,"
                "body=? WHERE id=?",(lease,body,item["id"]))
            item["external_user_id"]=external_id
            item["lease_until"]=lease
            item["body"]=body
            return item
    return None


def delivery_still_allowed(store, item: dict) -> bool:
    with store.connect() as con:
        row=con.execute("SELECT * FROM message_outbox WHERE id=? AND status='sending' "
                        "AND lease_until=?",(item["id"],item["lease_until"])).fetchone()
        if not row:
            return False
        return _delivery_valid(con,row)==item["external_user_id"]


def mark_delivered(store, item: dict) -> None:
    with store.connect(write=True) as con:
        con.execute("UPDATE message_outbox SET status='sent',lease_until=NULL,sent_at=? "
                    "WHERE id=? AND status='sending' AND lease_until=?",
                    (now(),item["id"],item["lease_until"]))


def mark_failed(store, item: dict) -> None:
    with store.connect(write=True) as con:
        row=con.execute("SELECT attempts FROM message_outbox WHERE id=? AND status='sending' "
                        "AND lease_until=?",(item["id"],item["lease_until"])).fetchone()
        if row:
            seconds=min(6*3600, 60*2**min(row["attempts"],8))
            con.execute(
                "UPDATE message_outbox SET status='pending',lease_until=NULL,next_attempt_at=? "
                "WHERE id=?",( _timestamp(seconds),item["id"]))


def outbox_status(store) -> dict:
    with store.connect() as con:
        return {r["status"]:r["count"] for r in con.execute(
            "SELECT status,COUNT(*) AS count FROM message_outbox GROUP BY status")}


def cancel_outbox(store, record_id):
    with store.connect(write=True) as con:
        row=con.execute("SELECT item_id FROM message_outbox WHERE id=?",(record_id,)).fetchone()
        if not row:
            raise Problem(404,"Nie ma wskazanego powiadomienia")
        con.execute("UPDATE message_outbox SET status='cancelled',lease_until=NULL "
                    "WHERE id=? AND status IN ('pending','sending')",(record_id,))
        # Manual cancellation only, next low-stock cycle will trigger after restock.
