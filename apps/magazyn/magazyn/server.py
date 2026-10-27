"""HTTP API and WebGUI for the isolated Magazyn application."""
from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
import secrets
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt

from .store import Problem, Store
from . import transfers, backup, messaging, restore_checks

COOKIE = "magazyn_session"
STATIC = Path(__file__).parent / "static"


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class Account(BaseModel):
    username: str
    password: str
    role: str = "user"


class AccountUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None
    password: str | None = None
    username: str | None = None


class Location(BaseModel):
    code: str
    description: str = ""


class StockOperation(BaseModel):
    item_id: int
    location_id: int
    action: str
    quantity: int
    product_state: str | None = None
    technical_state: str | None = None
    to_location_id: int | None = None
    reason: str = ""
    order_ref: str = ""
    note: str = ""


class ReceiveNewItem(BaseModel):
    kind: str
    designation: str
    brand: str = ""
    manufacturer: str = ""
    category: str = ""
    model: str = ""
    primary_number: str = ""
    hw: str = ""
    sw: str = ""
    package: str = ""
    parameters: str = ""
    notes: str = ""
    specs: dict[str,str] = Field(default_factory=dict)
    brands: list[str] = Field(default_factory=list)
    numbers: list[dict[str, str]] = Field(default_factory=list)
    # The first location can be created atomically with the first item.
    # Only administrators may supply a new location.
    location_id: StrictInt | None = Field(default=None, gt=0)
    new_location_code: str = Field(default="", max_length=64)
    new_location_description: str = Field(default="", max_length=300)
    quantity: StrictInt = Field(ge=0, le=2_000_000_000)
    product_state: str = "used"
    technical_state: str = "unknown"
    allow_distinct_variant: bool = False


class Minimum(BaseModel):
    minimum: int
    recipient_user_id: int | None = None
    provider: str = ""


class OrderStatusUpdate(BaseModel):
    status: str = Field(pattern="^(none|ordered)$")
    quantity: StrictInt = Field(ge=0, le=2_000_000_000)
    note: str = Field(default="", max_length=300)


class OrderedDelivery(BaseModel):
    location_id: StrictInt = Field(gt=0)
    quantity: StrictInt = Field(ge=1, le=2_000_000_000)
    product_state: str | None = None
    technical_state: str | None = None


class DocumentUpload(BaseModel):
    filename: str = Field(min_length=5, max_length=140)
    doc_type: str = Field(pattern="^(datasheet|schematic|other)$")
    content_base64: str = Field(min_length=1, max_length=11_184_812)


class PairingRequest(BaseModel):
    user_id: StrictInt = Field(gt=0)
    provider: str = Field(pattern="^(telegram|discord)$")

class InventoryRow(BaseModel):
    item_id: StrictInt = Field(gt=0)
    product_state: str = Field(min_length=1, max_length=16)
    technical_state: str = Field(min_length=1, max_length=16)
    expected_quantity: StrictInt = Field(ge=0, le=2_000_000_000)
    quantity: StrictInt = Field(ge=0, le=2_000_000_000)


class InventoryUpdate(BaseModel):
    location_id: StrictInt = Field(gt=0)
    rows: list[InventoryRow] = Field(min_length=1, max_length=1000)


class Upload(BaseModel):
    format: str = Field(pattern="^(csv|xlsx)$")
    content_base64: str = Field(max_length=1_333_336)
    token: str = Field(default="", max_length=100, pattern=r"^(?:|[0-9]{1,12}\.[a-f0-9]{64})$")


class RestoreCheckRequest(BaseModel):
    source: str = Field(pattern="^(nas|local)$")
    tier: str = Field(pattern="^(daily|weekly|monthly)$")
    name: str = Field(min_length=20, max_length=50)


def create_app(db_path: str | None = None, *, secure_cookie: bool = True) -> FastAPI:
    path = db_path or os.environ.get("MAGAZYN_DB_PATH")
    if not path:
        raise RuntimeError("Ustaw MAGAZYN_DB_PATH (lokalna baza izolowanej aplikacji)")
    store = Store(path)
    app = FastAPI(title="Magazyn V1 DEV", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    preview_secret = secrets.token_bytes(32)

    @app.exception_handler(Problem)
    async def known_error(_request: Request, exc: Problem):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else {}
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail},
                            headers=headers)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method == "POST":
            is_document = (request.url.path.startswith("/api/items/")
                           and request.url.path.endswith("/documents"))
            is_small_upload = request.url.path.startswith(("/api/import/", "/api/inventory"))
            if is_document or is_small_upload:
                # Bound streamed uploads even without Content-Length; no multipart dependency.
                limit = 12 * 1024 * 1024 if is_document else transfers.MAX_BODY
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > limit:
                        return JSONResponse(status_code=413, content={"detail":"Zbyt duże żądanie"})
                request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; frame-src blob:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        return response

    def require_user(request: Request):
        return store.session_user(request.cookies.get(COOKIE))

    def require_admin(user: dict = Depends(require_user)):
        if user["role"] != "admin":
            raise Problem(403, "Funkcja dostępna tylko dla administratora")
        return user

    def require_write(request: Request, csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
                      user: dict = Depends(require_user)):
        if not csrf or not hmac.compare_digest(csrf, user["csrf"]):
            raise Problem(403, "Brak prawidłowego tokenu CSRF")
        return user

    def require_admin_write(user: dict = Depends(require_write)):
        if user["role"] != "admin":
            raise Problem(403, "Funkcja dostępna tylko dla administratora")
        return user

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "magazyn-dev"}

    @app.post("/api/auth/login")
    def login(body: Login, request: Request):
        # Only the actual TCP peer is used. Forwarded headers are untrusted.
        user = store.authenticate_login(
            body.username, body.password,
            request.client.host if request.client else "unknown")
        token,csrf = store.create_session(user["id"])
        response = JSONResponse({"id":user["id"],"username":user["username"],
                                 "role":user["role"],"csrf":csrf})
        # When the DEV loopback HTTP fallback remains enabled, the existing
        # Tailscale Serve HTTPS endpoint must still set the Secure cookie flag.
        # Production enforces Secure on every request via secure_cookie=True.
        response.set_cookie(COOKIE, token, httponly=True,
                            secure=secure_cookie or request.url.scheme == "https",
                            samesite="strict", max_age=8*3600, path="/")
        return response

    @app.get("/api/auth/me")
    def me(user: dict = Depends(require_user)):
        return {k:user[k] for k in ("id","username","role","csrf")}

    @app.post("/api/auth/logout")
    def logout(request: Request, _user: dict = Depends(require_write)):
        store.logout(request.cookies.get(COOKIE))
        response=JSONResponse({"ok":True})
        response.delete_cookie(COOKIE,path="/")
        return response

    @app.get("/api/stats")
    def stats(_user: dict = Depends(require_user)):
        return store.statistics()

    @app.get("/api/locations")
    def locations(_user: dict = Depends(require_user)):
        return store.locations()

    @app.post("/api/locations", status_code=201)
    def add_location(body: Location, _user: dict = Depends(require_admin_write)):
        return {"id":store.add_location(body.code,body.description)}

    @app.patch("/api/locations/{location_id}")
    def edit_location(location_id: int, data: dict[str, Any], _user: dict = Depends(require_admin_write)):
        store.update_location(location_id,**{k:v for k,v in data.items()
                                            if k in ("code","description")})
        return {"ok":True}

    @app.delete("/api/locations/{location_id}")
    def delete_location(location_id: int, _user: dict = Depends(require_admin_write)):
        store.delete_location(location_id)
        return {"ok":True}

    @app.get("/api/items")
    def items(q: str="", kind: str | None=None, brand: str | None=None,
              manufacturer: str | None=None, product_state: str | None=None,
              technical_state: str | None=None, location_id: int | None=None,
              available: bool | None=None, limit: int=100,
              _user: dict = Depends(require_user)):
        return store.items(q,kind,brand,manufacturer,product_state,
                           technical_state,location_id,available,limit)

    @app.get("/api/items/similar")
    def similar_items(kind: str, designation: str = "", brand: str = "",
                      manufacturer: str = "", model: str = "", primary_number: str = "",
                      hw: str = "", sw: str = "", package: str = "",
                      parameters: str = "", category: str = "",
                      specs_json: str = "",
                      _user: dict = Depends(require_user)):
        specs = None
        if specs_json:
            if len(specs_json) > 1700:
                raise Problem(422, "Zbyt długie parametry elektroniki")
            try:
                specs = json.loads(specs_json)
            except (ValueError, TypeError) as exc:
                raise Problem(422, "Nieprawidłowe parametry elektroniki") from exc
        return store.similar_items({
            "kind":kind, "designation":designation, "brand":brand,
            "manufacturer":manufacturer, "model":model,
            "primary_number":primary_number, "hw":hw, "sw":sw,
            "package":package, "parameters":parameters, "category":category,
            "specs":specs})

    @app.post("/api/items/receive", status_code=201)
    def new_item_with_receipt(body: ReceiveNewItem, actor: dict = Depends(require_write)):
        return store.add_item_with_stock(body.model_dump(), actor,
            allow_distinct_variant=body.allow_distinct_variant)

    @app.get("/api/items/{item_id}")
    def item(item_id: int, _user: dict = Depends(require_user)):
        return store.item(item_id)

    @app.post("/api/items", status_code=201)
    def add_item(data: dict[str,Any], actor: dict = Depends(require_write)):
        return {"id":store.add_item(data,actor)}

    @app.patch("/api/items/{item_id}")
    def edit_item(item_id: int, data: dict[str,Any], _user: dict = Depends(require_admin_write)):
        store.edit_item(item_id,data)
        return {"ok":True}

    @app.delete("/api/items/{item_id}")
    def delete_item(item_id: int, _user: dict = Depends(require_admin_write)):
        store.delete_item(item_id)
        return {"ok":True}

    @app.post("/api/items/{item_id}/documents", status_code=201)
    def upload_document(item_id: int, body: DocumentUpload,
                        actor: dict = Depends(require_write)):
        try:
            content = base64.b64decode(body.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise Problem(422, "Niepoprawne dane załącznika") from exc
        return store.add_document(item_id, body.filename, body.doc_type, content, actor)

    @app.get("/api/items/{item_id}/documents")
    def item_documents(item_id: int, _user: dict = Depends(require_user)):
        return store.list_documents(item_id)

    @app.get("/api/items/{item_id}/documents/{document_id}")
    def download_document(item_id: int, document_id: int, _user: dict = Depends(require_user)):
        record=store.read_document(item_id, document_id)
        return Response(
            record["content"], media_type=record["mime"],
            headers={"Content-Disposition":"attachment; filename*=UTF-8''" + quote(record["filename"]),
                     "X-Content-Type-Options":"nosniff"})

    @app.delete("/api/items/{item_id}/documents/{document_id}")
    def remove_document(item_id: int, document_id: int,
                        _user: dict = Depends(require_admin_write)):
        store.delete_document(item_id, document_id)
        return {"ok":True}

    @app.get("/api/items/{item_id}/order-status")
    def get_order_status(item_id: int, _user: dict = Depends(require_user)):
        return store.get_order_status(item_id)

    @app.put("/api/items/{item_id}/order-status")
    def put_order_status(item_id: int, body: OrderStatusUpdate,
                         actor: dict = Depends(require_admin_write)):
        return store.set_order_status(item_id, body.status, body.quantity, body.note, actor)

    @app.post("/api/items/{item_id}/order-delivery", status_code=201)
    def order_delivery(item_id: int, body: OrderedDelivery,
                       actor: dict = Depends(require_admin_write)):
        return store.receive_order_delivery(
            item_id, body.location_id, body.quantity, actor,
            product_state=body.product_state, technical_state=body.technical_state)

    @app.post("/api/stock",status_code=201)
    def stock(body: StockOperation,actor: dict = Depends(require_write)):
        return store.stock_operation(body.model_dump(),actor)

    @app.get("/api/inventory")
    def inventory(location_id: int, _user: dict = Depends(require_user)):
        return store.inventory(location_id)

    @app.post("/api/inventory")
    def apply_inventory(body: InventoryUpdate, actor: dict = Depends(require_admin_write)):
        return store.apply_inventory(body.location_id, [r.model_dump() for r in body.rows], actor)

    def download(data, fmt, name):
        media = "text/csv; charset=utf-8" if fmt == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return Response(data, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})

    @app.get("/api/export")
    def export(format: str = "csv", kind: str | None = None, brand: str | None = None,
               _user: dict = Depends(require_admin)):
        return download(transfers.export_catalog(store, format, kind, brand), format, "magazyn-snapshot")

    @app.get("/api/import/template")
    def import_template(format: str = "csv", _user: dict = Depends(require_admin)):
        return download(transfers.encode_table(transfers.IMPORT_HEADERS, [], format), format, "magazyn-new")

    @app.post("/api/import/preview")
    def preview(body: Upload, actor: dict = Depends(require_admin_write)):
        return transfers.import_preview(store, transfers.decode_upload(body.content_base64),
                                        body.format, actor, preview_secret)

    @app.post("/api/import/apply", status_code=201)
    def apply_import(body: Upload, actor: dict = Depends(require_admin_write)):
        return transfers.import_apply(store, transfers.decode_upload(body.content_base64),
                                      body.format, actor, preview_secret, body.token)

    @app.get("/api/history")
    def history(item_id: int | None=None, actor_id: int | None=None,
                q: str="", date_from: date | None=None, date_to: date | None=None,
                limit: int=100, _user: dict = Depends(require_user)):
        if (len(q) > 120 or (date_from and date_to and date_from > date_to)):
            raise Problem(422, "Nieprawidłowe filtry historii")
        return store.history(item_id, actor_id, limit, query=q,
                             date_from=date_from, date_to=date_to)

    @app.patch("/api/history/{event_id}")
    def edit_history(event_id: int,data: dict[str,Any],_user: dict = Depends(require_admin_write)):
        store.edit_event(event_id,data)
        return {"ok":True}

    @app.delete("/api/history/{event_id}")
    def delete_history(event_id: int,_user: dict = Depends(require_admin_write)):
        store.delete_event(event_id)
        return {"ok":True}

    @app.get("/api/low-stock")
    def low_stock(_user: dict = Depends(require_user)):
        return store.low_stock()

    @app.put("/api/items/{item_id}/minimum")
    def minimum(item_id: int, body: Minimum, _user: dict = Depends(require_admin_write)):
        store.set_minimum(item_id,body.minimum,body.recipient_user_id,body.provider)
        return {"ok":True}

    @app.get("/api/items/{item_id}/minimum")
    def minimum_settings(item_id: int, _user: dict = Depends(require_user)):
        return store.minimum_settings(item_id)

    @app.get("/api/messaging/links")
    def messaging_links(_user: dict = Depends(require_admin)):
        return messaging.list_links(store)

    @app.post("/api/messaging/pairing", status_code=201)
    def create_pairing(body: PairingRequest, actor: dict = Depends(require_admin_write)):
        return messaging.create_pairing(store,body.user_id,body.provider,actor["id"])

    @app.delete("/api/messaging/links/{provider}/{user_id}")
    def remove_link(provider: str, user_id: int,
                    _user: dict = Depends(require_admin_write)):
        return {"removed":messaging.unlink(store,provider,user_id)}

    @app.get("/api/messaging/status")
    def messaging_status(_user: dict = Depends(require_admin)):
        return {"links":len(messaging.list_links(store)),
                "outbox":messaging.outbox_status(store),
                "bots_activated":os.getenv("MAGAZYN_BOTS_ENABLED")=="1"}

    @app.post("/api/messaging/outbox/{record_id}/cancel")
    def cancel_notification(record_id: int, _user: dict = Depends(require_admin_write)):
        messaging.cancel_outbox(store,record_id)
        return {"ok":True}

    @app.get("/api/backup/status")
    def backup_status(_user: dict = Depends(require_admin)):
        spool = os.environ.get("MAGAZYN_BACKUP_SPOOL", "")
        return backup.status(spool) if spool else {"configured": False, "pending": 0}

    @app.post("/api/backup/manual", status_code=201)
    def backup_manual(_user: dict = Depends(require_admin_write)):
        spool = os.environ.get("MAGAZYN_BACKUP_SPOOL", "")
        key_file = os.environ.get("MAGAZYN_BACKUP_KEY_FILE", "")
        if not spool or not key_file:
            raise Problem(503, "Backup nie jest jeszcze skonfigurowany")
        try:
            paths = backup.create_local(store.path, spool, key_file, kinds=("daily",))
            return {"ok": True, "created": len(paths), "pending": backup.status(spool)["pending"]}
        except backup.BackupFailure as exc:
            raise Problem(503, str(exc)) from exc

    @app.get("/api/backup/archives")
    def backup_archives(_user: dict = Depends(require_admin)):
        spool = os.environ.get("MAGAZYN_BACKUP_SPOOL", "")
        if not spool:
            raise Problem(503, "Backup nie jest skonfigurowany")
        try:
            return restore_checks.list_archives(
                spool, os.environ.get("MAGAZYN_BACKUP_MOUNT", "/mnt/AI_Platform"))
        except (backup.BackupFailure, OSError) as exc:
            raise Problem(503, "Nie można odczytać archiwów Magazynu") from exc

    @app.post("/api/backup/restore-check")
    def backup_restore_check(body: RestoreCheckRequest,
                             _user: dict = Depends(require_admin_write)):
        spool = os.environ.get("MAGAZYN_BACKUP_SPOOL", "")
        key_file = os.environ.get("MAGAZYN_BACKUP_KEY_FILE", "")
        if not spool or not key_file:
            raise Problem(503, "Backup nie jest skonfigurowany")
        try:
            return restore_checks.test_restore(
                body.source, body.tier, body.name, spool,
                os.environ.get("MAGAZYN_BACKUP_MOUNT", "/mnt/AI_Platform"),
                key_file)
        except (backup.BackupFailure, OSError) as exc:
            raise Problem(503, "Próba odtworzenia nie powiodła się") from exc

    @app.get("/api/users")
    def users(_user: dict = Depends(require_admin)):
        return store.users()

    @app.post("/api/users",status_code=201)
    def add_user(body: Account, _user: dict = Depends(require_admin_write)):
        return {"id":store.create_user(body.username,body.password,body.role)}

    @app.patch("/api/users/{user_id}")
    def edit_user(user_id: int,body: AccountUpdate,_user: dict = Depends(require_admin_write)):
        store.change_user(user_id,**body.model_dump(exclude_unset=True))
        return {"ok":True}

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: int,_user: dict = Depends(require_admin_write)):
        store.delete_user(user_id)
        return {"ok":True}

    @app.get("/")
    def index():
        return FileResponse(STATIC/"index.html",media_type="text/html")

    app.mount("/static",StaticFiles(directory=STATIC),name="static")
    return app
