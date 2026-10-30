"""Magazyn DEV tests: no real user data or production services."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from magazyn.server import create_app
from magazyn.store import normalize, password_hash, password_verify


@pytest.fixture
def scenario(tmp_path):
    app = create_app(str(tmp_path / "private" / "inventory.sqlite3"), secure_cookie=False)
    s = app.state.store
    admin = s.create_user("admin1", "secure-test-password-123", "admin")
    worker = s.create_user("worker1", "second-test-password-456", "user")
    return TestClient(app), s, admin, worker


def auth(c, name="admin1", password="secure-test-password-123"):
    r = c.post("/api/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf"]}


def post(c, path, data, headers):
    return c.post(path, json=data, headers=headers)


def ecu(**kw):
    return dict({"kind": "ecu", "brand": "DAF", "brands": ["MAN"],
                 "designation": "Bosch EDC7", "manufacturer": "Bosch", "model": "EDC7",
                 "primary_number": "0 281 016 738",
                 "numbers": [{"number": "1943-026", "number_type": "OEM"}],
                 "hw": "H1", "sw": "S1"}, **kw)


def operation(item, loc, **kw):
    d = {"item_id": item, "location_id": loc, "action": "receive", "quantity": 2,
         "product_state": "used", "technical_state": "working"}
    d.update(kw)
    return d


def test_auth_csrf_login_failure_and_logout(scenario):
    c, s, a, w = scenario
    assert c.get("/api/items").status_code == 401
    assert c.post("/api/auth/login", json={"username": "admin1", "password": "bad"}).status_code == 401
    h = auth(c)
    assert c.get("/api/auth/me").json()["role"] == "admin"
    assert c.post("/api/locations", json={"code": "A1"}).status_code == 403
    assert post(c, "/api/locations", {"code": "A1"}, h).status_code == 201
    assert c.post("/api/auth/logout", json={}, headers=h).status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_alias_search_multiple_brands_count_once(scenario):
    c, s, a, w = scenario
    h = auth(c)
    loc = post(c, "/api/locations", {"code": "A1"}, h).json()["id"]
    r = post(c, "/api/items", ecu(), h)
    assert r.status_code == 201, r.text
    item = r.json()["id"]
    assert post(c, "/api/stock", operation(item, loc, quantity=3), h).status_code == 201
    assert c.get("/api/items?q=0281016738").json()[0]["id"] == item
    assert c.get("/api/items?q=1943026").json()[0]["id"] == item
    assert c.get("/api/items?q=edc7&brand=MAN").json()[0]["id"] == item
    assert not c.get("/api/items?q=edc7&brand=VOLVO").json()
    detail = c.get(f"/api/items/{item}").json()
    assert detail["total"] == 3
    assert len(detail["brands"]) == 2
    assert len(detail["numbers"]) == 2
    assert c.get("/api/stats").json()["units"] == 3


def test_multilocation_product_state_and_history(scenario):
    c, s, a, w = scenario
    h = auth(c)
    a1 = post(c, "/api/locations", {"code": "A1"}, h).json()["id"]
    b3 = post(c, "/api/locations", {"code": "B3"}, h).json()["id"]
    item = post(c, "/api/items", ecu(), h).json()["id"]
    assert post(c, "/api/stock", operation(item, a1, quantity=5), h).status_code == 201
    assert post(c, "/api/stock", operation(item, a1, quantity=2, product_state="new"), h).status_code == 201
    assert post(c, "/api/stock", operation(item, b3, quantity=4, technical_state="faulty"), h).status_code == 201
    assert c.get(f"/api/items/{item}").json()["total"] == 11
    assert len(c.get(f"/api/items/{item}").json()["balances"]) == 3
    assert post(c, "/api/stock", operation(item, a1, action="issue", quantity=1), h).status_code == 422
    hw = auth(c, "worker1", "second-test-password-456")
    sent = post(c, "/api/stock", operation(item, a1, action="issue", quantity=2,
                reason="repair", order_ref="ZL-1"), hw)
    assert sent.status_code == 201, sent.text
    assert (sent.json()["before"], sent.json()["after"]) == (5, 3)
    moved = post(c, "/api/stock", operation(item, a1, action="move",
                 to_location_id=b3, quantity=1), hw)
    assert moved.status_code == 201, moved.text
    assert moved.json()["after_target"] == 1
    assert c.get(f"/api/items/{item}").json()["total"] == 9
    events = c.get("/api/history").json()
    assert events[0]["actor_name"] == "worker1" and events[0]["action"] == "move"
    assert events[1]["reason"] == "repair" and events[1]["order_ref"] == "ZL-1"


def test_overdraft_rollback_zero_adjust(scenario):
    c, s, a, w = scenario
    h = auth(c)
    loc = post(c, "/api/locations", {"code": "A1"}, h).json()["id"]
    item = post(c, "/api/items", ecu(), h).json()["id"]
    assert post(c, "/api/stock", operation(item, loc, quantity=4), h).status_code == 201
    count = len(c.get("/api/history").json())
    assert post(c, "/api/stock", operation(item, loc, action="issue",
                                          quantity=7, reason="other"), h).status_code == 409
    assert c.get(f"/api/items/{item}").json()["total"] == 4
    assert len(c.get("/api/history").json()) == count
    assert post(c, "/api/stock", operation(item, loc, action="adjust",
                                          quantity=0), h).status_code == 201
    assert c.get(f"/api/items/{item}").json()["total"] == 0


def test_worker_blocked_and_admin_can_edit_delete_history(scenario):
    c, s, a, w = scenario
    ha = auth(c)
    loc = post(c, "/api/locations", {"code": "A1"}, ha).json()["id"]
    item = post(c, "/api/items", ecu(), ha).json()["id"]
    eid = post(c, "/api/stock", operation(item, loc), ha).json()["event_id"]
    hw = auth(c, "worker1", "second-test-password-456")
    assert c.get("/api/users").status_code == 403
    assert c.delete(f"/api/items/{item}", headers=hw).status_code == 403
    assert c.patch(f"/api/history/{eid}", json={"note": "bad"}, headers=hw).status_code == 403
    assert post(c, "/api/stock", operation(item, loc, action="adjust", quantity=1), hw).status_code == 403
    ha = auth(c)
    assert c.patch(f"/api/history/{eid}", json={"note": "admin edit"}, headers=ha).status_code == 200
    assert c.get("/api/history").json()[0]["note"] == "admin edit"
    assert c.delete(f"/api/history/{eid}", headers=ha).status_code == 200
    assert c.delete(f"/api/items/{item}", headers=ha).status_code == 200
    assert c.get(f"/api/items/{item}").status_code == 404


def test_minima_admin_only_and_recipient(scenario):
    c, s, a, w = scenario
    h = auth(c)
    item = post(c, "/api/items", ecu(), h).json()["id"]
    hw = auth(c, "worker1", "second-test-password-456")
    payload = {"minimum": 5, "recipient_user_id": w, "provider": "telegram"}
    assert c.put(f"/api/items/{item}/minimum", json=payload, headers=hw).status_code == 403
    h = auth(c)
    assert c.put(f"/api/items/{item}/minimum", json=payload, headers=h).status_code == 200
    rows = c.get("/api/low-stock").json()
    assert len(rows) == 1 and rows[0]["recipient_user_id"] == w
    assert c.put(f"/api/items/{item}/minimum", json={
        "minimum": 5, "provider": "discord"}, headers=h).status_code == 422


def test_electronics_no_automotive_condition(scenario):
    c, s, a, w = scenario
    h = auth(c)
    loc = post(c, "/api/locations", {"code": "A1"}, h).json()["id"]
    item = post(c, "/api/items", {"kind": "part", "designation": "IRF3205",
                "category": "MOSFET", "package": "TO-220"}, h).json()["id"]
    assert post(c, "/api/stock", operation(item, loc), h).status_code == 422
    assert post(c, "/api/stock", operation(item, loc,
                product_state="na", technical_state="na"), h).status_code == 201
    assert c.get("/api/items?q=IRF3205&kind=part").json()[0]["total"] == 2


def test_user_creation_deactivation(scenario):
    c, s, a, w = scenario
    h = auth(c)
    r = post(c, "/api/users", {"username": "helper",
             "password": "password-for-helper123", "role": "user"}, h)
    assert r.status_code == 201
    uid = r.json()["id"]
    assert c.patch(f"/api/users/{uid}", json={"active": False}, headers=h).status_code == 200
    assert c.post("/api/auth/login", json={
        "username": "helper", "password": "password-for-helper123"}).status_code == 401
    assert c.delete(f"/api/users/{uid}", headers=h).status_code == 200


def test_salted_password_and_number_normalization():
    a = password_hash("long-secret-password")
    b = password_hash("long-secret-password")
    assert a != b and password_verify("long-secret-password", a)
    assert not password_verify("wrong-long-password", a)
    assert normalize(" 0 281-016_738 ") == "0281016738"


def test_static_page_private_api(scenario):
    c, s, a, w = scenario
    r = c.get("/")
    assert r.status_code == 200 and "Magazyn" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/style.css").status_code == 200
    assert c.post("/api/users", json={"username": "evil", "password": "a"*12}).status_code == 401
    assert c.get("/api/low-stock").status_code == 401
    assert c.get("/api/history").status_code == 401


def test_concurrent_receipts_are_atomic(scenario):
    c, s, a, w = scenario
    loc = s.add_location("A1")
    item = s.add_item(ecu(), {"id": a, "username": "admin1", "role": "admin"})
    actor = {"id": a, "username": "admin1", "role": "admin"}
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(s.stock_operation, operation(item, loc, quantity=1), actor)
                for _ in range(20)]
        for job in jobs:
            job.result()
    assert s.item(item)["total"] == 20
    assert len(s.history(item_id=item)) == 20


def test_secure_cookie_by_default(tmp_path):
    app = create_app(str(tmp_path/"db.sqlite3"))
    app.state.store.create_user("root1", "sample-password-is-long", "admin")
    r = TestClient(app).post("/api/auth/login", json={
        "username": "root1", "password": "sample-password-is-long"})
    assert r.status_code == 200
    assert "secure" in r.headers["set-cookie"].lower()


def test_db_file_is_private(scenario):
    c, s, a, w = scenario
    from pathlib import Path
    mode = Path(s.path).stat().st_mode & 0o777
    assert mode == 0o600


def test_editing_primary_number_preserves_other_numbers_and_brands(scenario):
    c, s, a, w = scenario
    h = auth(c)
    item = post(c, "/api/items", ecu(), h).json()["id"]
    response = c.patch(f"/api/items/{item}", json={
        "primary_number": "0 281 016 739", "brand": "IVECO"}, headers=h)
    assert response.status_code == 200, response.text
    detail = c.get(f"/api/items/{item}").json()
    assert set(detail["brands"]) == {"IVECO", "MAN"}
    assert {"0 281 016 739", "1943-026"} == {r["number"] for r in detail["numbers"]}
    assert c.get("/api/items?q=1943026").json()[0]["id"] == item


def test_location_delete_after_inventory_empty(scenario):
    c, s, a, w = scenario
    h = auth(c)
    loc = post(c, "/api/locations", {"code": "A1"}, h).json()["id"]
    item = post(c, "/api/items", ecu(), h).json()["id"]
    post(c, "/api/stock", operation(item, loc, quantity=3), h)
    assert c.delete(f"/api/locations/{loc}", headers=h).status_code == 409
    assert post(c, "/api/stock", operation(item, loc, action="adjust", quantity=0), h).status_code == 201
    assert c.delete(f"/api/locations/{loc}", headers=h).status_code == 200


def test_non_issue_events_do_not_inherit_issue_reason(scenario):
    c, s, a, w = scenario
    h = auth(c)
    loc = post(c, "/api/locations", {"code": "A1"}, h).json()["id"]
    item = post(c, "/api/items", ecu(), h).json()["id"]
    r = post(c, "/api/stock", operation(item, loc, reason="repair", order_ref="wrong"), h)
    assert r.status_code == 201
    ev = c.get("/api/history").json()[0]
    assert ev["reason"] == "" and ev["order_ref"] == ""
