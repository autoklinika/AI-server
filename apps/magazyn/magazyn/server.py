"""HTTP API and WebGUI for the isolated Magazyn application."""
from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .store import Problem, Store

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


def create_app(db_path: str | None = None, *, secure_cookie: bool = True) -> FastAPI:
    path = db_path or os.environ.get("MAGAZYN_DB_PATH")
    if not path:
        raise RuntimeError("Ustaw MAGAZYN_DB_PATH (lokalna baza izolowanej aplikacji)")
    store = Store(path)
    app = FastAPI(title="Magazyn V1 DEV", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.exception_handler(Problem)
    async def known_error(_request: Request, exc: Problem):
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
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
