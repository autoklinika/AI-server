"""HTTP API and WebGUI for the isolated Magazyn application."""
from __future__ import annotations

import hmac
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt

from .store import Problem, Store
from . import transfers

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


class Minimum(BaseModel):
    minimum: int
    recipient_user_id: int | None = None
    provider: str = ""


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
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.url.path.startswith(("/api/import/", "/api/inventory")) and request.method == "POST":
            # Bound the actual streamed body, including requests without Content-Length.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > transfers.MAX_BODY:
                    return JSONResponse(status_code=413, content={"detail":"Zbyt duże żądanie"})
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
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
    def login(body: Login):
        user = store.authenticate(body.username,body.password)
        token,csrf = store.create_session(user["id"])
        response = JSONResponse({"id":user["id"],"username":user["username"],
                                 "role":user["role"],"csrf":csrf})
        response.set_cookie(COOKIE,token,httponly=True,secure=secure_cookie,
                            samesite="strict",max_age=8*3600,path="/")
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
                limit: int=100, _user: dict = Depends(require_user)):
        return store.history(item_id,actor_id,limit)

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
