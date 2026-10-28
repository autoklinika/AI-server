"""Magazyn V1: independent second employee account end-to-end tests, synthetic DB only."""
from html.parser import HTMLParser

from fastapi.testclient import TestClient

from magazyn.server import create_app


def request_with_csrf(client, path, payload, csrf, method="POST"):
    return client.request(method, path, json=payload, headers={"X-CSRF-Token":csrf})


def test_admin_creates_worker_with_separate_login_sessions_and_stock_audit(tmp_path):
    app=create_app(str(tmp_path/"private"/"magazyn.sqlite3"),secure_cookie=False)
    admin_id=app.state.store.create_user("owner","owner-strong-test-password","admin")
    with TestClient(app) as admin,TestClient(app) as worker:
        signed=admin.post("/api/auth/login",
                          json={"username":"owner","password":"owner-strong-test-password"})
        assert signed.status_code==200
        admin_csrf=signed.json()["csrf"]
        loc=request_with_csrf(admin,"/api/locations",{"code":"SECOND-USER-A1"},admin_csrf)
        assert loc.status_code==201,loc.text
        item=request_with_csrf(admin,"/api/items/receive",{
            "kind":"part","designation":"Synthetic IC worker onboarding",
            "category":"Układy scalone","quantity":4,"location_id":loc.json()["id"],
            "primary_number":"WORKER-TEST-001"},admin_csrf)
        assert item.status_code==201,item.text
        item_id=item.json()["id"]
        data={"username":"pracownik02","password":"test-worker-password-123",
              "role":"user"}
        denied=worker.post("/api/users",json=data)
        assert denied.status_code==401
        created=request_with_csrf(admin,"/api/users",data,admin_csrf)
        assert created.status_code==201,created.text
        worker_id=created.json()["id"]
        assert worker_id != admin_id
        assert request_with_csrf(admin,"/api/users",data,admin_csrf).status_code==409
        listing=admin.get("/api/users").json()
        entry=next(u for u in listing if u["id"]==worker_id)
        assert entry["role"]=="user" and entry["active"]==1
        assert "password" not in repr(entry).lower()
        assert worker.get("/api/users").status_code==401

        signed=worker.post("/api/auth/login",json={
            "username":"pracownik02","password":"test-worker-password-123"})
        assert signed.status_code==200,signed.text
        assert signed.json()["role"]=="user"
        worker_csrf=signed.json()["csrf"]
        assert worker.get("/api/auth/me").json()["id"]==worker_id
        assert len(worker.get("/api/items").json())==1
        assert worker.get(f"/api/items/{item_id}").json()["total"]==4
        assert len(worker.get("/api/locations").json())==1
        assert worker.get("/api/history").status_code==200
        assert worker.get("/api/low-stock").status_code==200

        receipt=request_with_csrf(worker,"/api/stock",{
            "item_id":item_id,"location_id":loc.json()["id"],
            "action":"receive","quantity":2},worker_csrf)
        assert receipt.status_code==201,receipt.text
        issued=request_with_csrf(worker,"/api/stock",{
            "item_id":item_id,"location_id":loc.json()["id"],
            "action":"issue","quantity":3,"reason":"workshop"},worker_csrf)
        assert issued.status_code==201,issued.text
        assert worker.get(f"/api/items/{item_id}").json()["total"]==3
        events=worker.get("/api/history",params={"item_id":item_id}).json()
        assert events[0]["actor_id"]==worker_id and events[0]["actor_name"]=="pracownik02"
        assert events[0]["reason"]=="workshop"
        assert events[1]["actor_id"]==worker_id

        # Backend enforcement; no trust in hidden frontend navigation.
        assert worker.get("/api/users").status_code==403
        assert worker.get("/api/backup/status").status_code==403
        assert worker.get("/api/export").status_code==403
        assert worker.get("/api/messaging/status").status_code==403
        for path,body,method in [
            ("/api/users",data,"POST"),
            ("/api/locations",{"code":"FORBIDDEN"},"POST"),
            (f"/api/items/{item_id}",{"designation":"changed"},"PATCH"),
            (f"/api/items/{item_id}/order-status",
             {"status":"ordered","quantity":4},"PUT"),
            (f"/api/items/{item_id}/order-delivery",
             {"location_id":loc.json()["id"],"quantity":1},"POST"),
            ("/api/backup/manual",{},"POST"),
        ]:
            assert request_with_csrf(worker,path,body,worker_csrf,method).status_code==403,path

        assert request_with_csrf(worker,"/api/stock",{
            "item_id":item_id,"location_id":loc.json()["id"],
            "action":"adjust","quantity":0},worker_csrf).status_code==403
        assert worker.get(f"/api/items/{item_id}").json()["total"]==3

        # Immediate revocation of the employee's active cookie and login.
        stopped=request_with_csrf(admin,f"/api/users/{worker_id}",
                                  {"active":False},admin_csrf,"PATCH")
        assert stopped.status_code==200,stopped.text
        assert worker.get("/api/auth/me").status_code==401
        assert worker.get("/api/items").status_code==401
        assert worker.post("/api/auth/login",json={
            "username":"pracownik02","password":"test-worker-password-123"}).status_code==401
        assert admin.get("/api/auth/me").json()["role"]=="admin"
        assert request_with_csrf(admin,f"/api/users/{worker_id}",
                                 {"active":True},admin_csrf,"PATCH").status_code==200
        resumed=worker.post("/api/auth/login",json={
            "username":"pracownik02","password":"test-worker-password-123"})
        assert resumed.status_code==200
        assert worker.get(f"/api/items/{item_id}").json()["total"]==3
        # Password reset by administrator expires the worker session.
        assert request_with_csrf(admin,f"/api/users/{worker_id}",
              {"password":"another-strong-worker-pass"},admin_csrf,"PATCH").status_code==200
        assert worker.get("/api/auth/me").status_code==401
        assert worker.post("/api/auth/login",json={
            "username":"pracownik02","password":"another-strong-worker-pass"}).status_code==200
        assert worker.get("/api/auth/me").json()["role"]=="user"
        assert admin.get("/api/auth/me").json()["role"]=="admin"


class StaffFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scope=0
        self.fields={}
        self.roles=[]

    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if tag=="form" and data.get("id")=="user-form":
            self.scope=1
        elif self.scope and tag=="input":
            self.fields[data.get("name")]=data

    def handle_endtag(self,tag):
        if self.scope and tag=="form":
            self.scope=0


def test_employee_ui_has_fixed_role_and_safe_login_design(tmp_path):
    app=create_app(str(tmp_path/"ui.sqlite3"),secure_cookie=False)
    with TestClient(app) as c:
        page=c.get("/").text
        parser=StaffFormParser()
        parser.feed(page)
        assert parser.fields["role"]["type"]=="hidden"
        assert parser.fields["role"]["value"]=="user"
        assert parser.fields["username"]["pattern"]=="[A-Za-z0-9_.-]{3,40}"
        assert parser.fields["password"]["type"]=="password"
        assert parser.fields["password"]["minlength"]=="12"
        assert parser.fields["password"]["autocomplete"]=="new-password"
        assert "Dodaj pracownika" in page
        assert "Utwórz konto pracownika" in page
        assert 'id="user-form"' in page
        assert '<option value="admin">Administrator</option>' not in page
        script=c.get("/static/app.js").text
        assert 'u.role==="admin"?"Administrator":"Pracownik"' in script
        assert 'byId("user-form").reset()' in script
        assert "await api(\"/api/users\",{method:\"POST\"" in script
        assert 'if(tab==="admin"&&session.role!=="admin")return;' in script
