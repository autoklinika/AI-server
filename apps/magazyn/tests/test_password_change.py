"""Employee password management and account access: isolated SQLite only."""
from html.parser import HTMLParser

from fastapi.testclient import TestClient
import pytest

from magazyn.server import create_app
from magazyn.store import password_verify


@pytest.fixture
def accounts(tmp_path):
    application=create_app(str(tmp_path/"private"/"magazyn.sqlite3"),secure_cookie=False)
    s=application.state.store
    admin_id=s.create_user("owner","owner-original-strong-password","admin")
    worker_id=s.create_user("employee","employee-original-strong-pass","user")
    return application,s,admin_id,worker_id


def login(client,user,password):
    response=client.post("/api/auth/login",json={"username":user,"password":password})
    assert response.status_code==200,response.text
    return response.json()["csrf"]


def rotate(client,csrf,old,new):
    return client.post("/api/auth/change-password",
                       json={"current_password":old,"new_password":new},
                       headers={"X-CSRF-Token":csrf})


def test_employee_changes_password_revokes_all_sessions(accounts):
    app,s,admin_id,worker_id=accounts
    with (TestClient(app) as first,TestClient(app) as second,TestClient(app) as admin):
        old="employee-original-strong-pass"
        new="employee-new-strong-password"
        admin_csrf=login(admin,"owner","owner-original-strong-password")
        first_csrf=login(first,"employee",old)
        second_csrf=login(second,"employee",old)
        assert first_csrf!=second_csrf
        assert first.get("/api/auth/me").json()["role"]=="user"
        assert first.get("/api/users").status_code==403
        before=s.users()
        assert rotate(first,first_csrf,old,new).status_code==200
        assert first.get("/api/auth/me").status_code==401
        assert second.get("/api/auth/me").status_code==401
        assert admin.get("/api/auth/me").status_code==200
        assert first.post("/api/auth/login",json={"username":"employee","password":old}).status_code==401
        login(first,"employee",new)
        assert first.get("/api/auth/me").json()["id"]==worker_id
        assert first.get("/api/users").status_code==403
        assert first.get("/api/backup/status").status_code==403
        assert s.users()==before
        with s.connect() as con:
            row=con.execute("SELECT password_hash FROM users WHERE id=?",(worker_id,)).fetchone()
        assert password_verify(new,row[0])
        assert not password_verify(old,row[0])


def test_wrong_password_same_password_csrf_and_length_rejected(accounts):
    app,s,admin_id,worker_id=accounts
    with TestClient(app) as worker:
        old="employee-original-strong-pass"
        csrf=login(worker,"employee",old)
        payload={"current_password":old,"new_password":"different-strong-password"}
        assert worker.post("/api/auth/change-password",json=payload).status_code==403
        assert worker.post("/api/auth/change-password",json=payload,
                           headers={"X-CSRF-Token":"invalid"}).status_code==403
        assert rotate(worker,csrf,old,old).status_code==422
        assert rotate(worker,csrf,old,"too-short").status_code==422
        denied=rotate(worker,csrf,"wrong-current-password","different-strong-password")
        assert denied.status_code==403
        assert worker.get("/api/auth/me").status_code==200
        assert s.authenticate("employee",old)["id"]==worker_id
        with s.connect() as con:
            sessions=con.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?",
                                 (worker_id,)).fetchone()[0]
        assert sessions==1


def test_wrong_old_password_attempts_are_rate_limited(accounts):
    app,s,_,_=accounts
    with TestClient(app) as employee:
        csrf=login(employee,"employee","employee-original-strong-pass")
        results=[]
        for _ in range(5):
            response=rotate(employee,csrf,"definitely-incorrect","new-worker-strong-password")
            results.append(response.status_code)
        assert results[:4]==[403]*4
        assert results[4]==429
        assert employee.get("/api/auth/me").status_code==200
        assert s.authenticate("employee","employee-original-strong-pass")
        blocked=rotate(employee,csrf,"employee-original-strong-pass",
                       "new-worker-strong-password")
        assert blocked.status_code==429
        assert int(blocked.headers["Retry-After"])>0


def test_admin_reset_employee_password_immediately_revokes_worker(accounts):
    app,s,admin_id,worker_id=accounts
    with TestClient(app) as admin,TestClient(app) as worker:
        admin_csrf=login(admin,"owner","owner-original-strong-password")
        worker_csrf=login(worker,"employee","employee-original-strong-pass")
        assert worker.patch(f"/api/users/{worker_id}",
                            json={"password":"not-allowed"},
                            headers={"X-CSRF-Token":worker_csrf}).status_code==403
        response=admin.patch(f"/api/users/{worker_id}",
                             json={"password":"reset-employee-strong-pass"},
                             headers={"X-CSRF-Token":admin_csrf})
        assert response.status_code==200,response.text
        assert worker.get("/api/auth/me").status_code==401
        assert worker.post("/api/auth/login",
                           json={"username":"employee","password":"employee-original-strong-pass"}).status_code==401
        login(worker,"employee","reset-employee-strong-pass")
        assert worker.get("/api/auth/me").json()["role"]=="user"
        assert admin.get("/api/auth/me").json()["role"]=="admin"
        with s.connect() as con:
            assert con.execute("SELECT role FROM users WHERE id=?",(admin_id,)).fetchone()[0]=="admin"


def test_last_admin_can_rotate_own_password_without_role_change(accounts):
    app,s,admin_id,_=accounts
    with TestClient(app) as admin:
        csrf=login(admin,"owner","owner-original-strong-password")
        response=rotate(admin,csrf,"owner-original-strong-password","owner-new-strong-password")
        assert response.status_code==200
        assert admin.get("/api/auth/me").status_code==401
        login(admin,"owner","owner-new-strong-password")
        assert admin.get("/api/auth/me").json()["role"]=="admin"
        assert len([u for u in s.users() if u["role"]=="admin" and u["active"]])==1


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=set()
    def handle_starttag(self,tag,attrs):
        ident=dict(attrs).get("id")
        if ident:
            assert ident not in self.ids,ident
            self.ids.add(ident)


def test_ui_and_policy_keep_password_actions_same_origin(accounts):
    app,*_=accounts
    with TestClient(app) as client:
        response=client.get("/")
        markup=response.text
        ids=IdCollector()
        ids.feed(markup)
        for name in ("change-own-password","own-password-dialog","own-password-form",
                     "staff-password-dialog","staff-password-form","staff-password-username"):
            assert name in ids.ids
        assert markup.count('src="/static/account.js"')==1
        assert "autocomplete=\"current-password\"" in markup
        assert "autocomplete=\"new-password\"" in markup
        assert 'type="password"' in markup
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        code=client.get("/static/account.js").text
        assert '"/api/auth/change-password"' in code
        assert "confirm_password" in code
        assert 'method:"PATCH"' in code
        assert 'current_password:current,new_password:replacement' in code
        assert "localStorage" not in code and "sessionStorage" not in code
        assert "fetch(" not in code
        assert client.post("/api/auth/change-password",json={
            "current_password":"fake-old-password","new_password":"fake-new-password"
        }).status_code==401
