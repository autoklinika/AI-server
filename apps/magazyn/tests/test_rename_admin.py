"""Admin login rename: synthetic DEV users only, Telegram link must survive."""
import sys
from pathlib import Path

import pytest

from magazyn import bots, messaging, telegram_setup
from magazyn.store import Store, Problem
from test_magazyn import scenario, auth, ecu, operation, post


def setup_linked_admin(s):
    admin=s.create_user("admin_old","test-admin-password-long","admin")
    loc=s.add_location("A1")
    item=s.add_item(ecu(),{"id":admin,"username":"admin_old","role":"admin"})
    s.stock_operation(operation(item,loc,quantity=3),
                      {"id":admin,"username":"admin_old","role":"admin"})
    s.set_minimum(item,5,admin,"telegram")
    with s.connect(write=True) as con:
        con.execute(
            "INSERT INTO external_accounts(provider,external_user_id,user_id,verified)"
            " VALUES ('telegram','123456789',?,1)",(admin,))
    return admin,item


def test_rename_preserves_admin_id_password_and_telegram(tmp_path,monkeypatch):
    db=tmp_path/"magazyn.sqlite3"
    s=Store(str(db))
    admin,item=setup_linked_admin(s)
    old_history_count=len(s.history())
    prompts=iter(["new_admin","new_admin"])
    monkeypatch.setattr(telegram_setup.getpass,"getpass",
                        lambda *_:"test-admin-password-long")
    monkeypatch.setattr("builtins.input",lambda *_:next(prompts))
    result=telegram_setup.run_rename_admin(db=str(db),admin_username="admin_old")
    assert result["username"]=="new_admin" and result["id_preserved"]
    assert s.authenticate("new_admin","test-admin-password-long")["id"]==admin
    with pytest.raises(Problem) as failure:
        s.authenticate("admin_old","test-admin-password-long")
    assert failure.value.status==401
    assert messaging.linked_user(s,"telegram",123456789)["id"]==admin
    assert messaging.linked_user(s,"telegram",123456789)["username"]=="new_admin"
    assert s.minimum_settings(item)["recipient_user_id"]==admin
    assert "Magazyn:" in bots.reply_for_telegram(s,{"message":{
        "chat":{"type":"private","id":123456789},
        "from":{"id":123456789,"is_bot":False},
        "text":"/pomoc"}})[1]
    assert len(s.history())==old_history_count
    # Historical snapshot should remain historical. No rewrite of event actor_name.
    assert s.history()[0]["actor_name"]=="admin_old"


def test_rename_rejects_invalid_confirmation_and_bad_password(tmp_path,monkeypatch):
    db=tmp_path/"magazyn.sqlite3"
    s=Store(str(db))
    uid,_=setup_linked_admin(s)
    monkeypatch.setattr(telegram_setup.getpass,"getpass",
                        lambda *_:"test-admin-password-long")
    typed=iter(["new_admin","typo_admin"])
    monkeypatch.setattr("builtins.input",lambda *_:next(typed))
    with pytest.raises(telegram_setup.SetupFailure,match="różne"):
        telegram_setup.run_rename_admin(db=str(db),admin_username="admin_old")
    assert s.users()[0]["username"]=="admin_old"
    monkeypatch.setattr(telegram_setup.getpass,"getpass",lambda *_:"not-the-password")
    with pytest.raises(telegram_setup.SetupFailure,match="Błędne"):
        telegram_setup.run_rename_admin(db=str(db),admin_username="admin_old")
    assert messaging.linked_user(s,"telegram",123456789)["id"]==uid


def test_rename_rejects_existing_login_and_illegal_name(tmp_path,monkeypatch):
    db=tmp_path/"magazyn.sqlite3"
    s=Store(str(db))
    admin,_=setup_linked_admin(s)
    s.create_user("taken","test-user-password-long","user")
    monkeypatch.setattr(telegram_setup.getpass,"getpass",
                        lambda *_:"test-admin-password-long")
    monkeypatch.setattr("builtins.input",lambda *_:next(iter(["taken","taken"])))
    with pytest.raises(Problem) as error:
        telegram_setup.run_rename_admin(db=str(db),admin_username="admin_old")
    assert error.value.status==409
    monkeypatch.setattr("builtins.input",lambda *_:next(iter(["!!","!!"])))
    with pytest.raises(Problem) as error:
        telegram_setup.run_rename_admin(db=str(db),admin_username="admin_old")
    assert error.value.status==422
    assert s.users()[0]["username"]=="admin_old"
    assert messaging.linked_user(s,"telegram",123456789)["id"]==admin


def test_api_admin_rename_preserves_session_and_blocks_worker(scenario):
    client,s,admin,worker=scenario
    head=auth(client)
    # Another employee cannot rename admin through the admin API.
    worker_head=auth(client,"worker1","second-test-password-456")
    assert client.patch(f"/api/users/{admin}",
                        json={"username":"manager1"},headers=worker_head).status_code==403
    assert s.authenticate("admin1","secure-test-password-123")["id"]==admin
    head=auth(client)
    response=client.patch(f"/api/users/{admin}",
        json={"username":"manager1"},headers=head)
    assert response.status_code==200,response.text
    assert s.authenticate("manager1","secure-test-password-123")["id"]==admin
    assert client.get("/api/auth/me").json()["username"]=="manager1"
    assert client.get("/api/auth/me").json()["role"]=="admin"
    assert client.post("/api/auth/login",json={
        "username":"admin1","password":"secure-test-password-123"}).status_code==401


def test_rename_cli_output_does_not_show_password(tmp_path,monkeypatch,capsys):
    db=tmp_path/"magazyn.sqlite3"
    s=Store(str(db))
    s.create_user("before","my-admin-password-long","admin")
    monkeypatch.setattr(telegram_setup.getpass,"getpass",
                        lambda *_:"my-admin-password-long")
    monkeypatch.setattr("builtins.input",lambda *_:next(iter(["after","after"])))
    result=telegram_setup.run_rename_admin(db=str(db),admin_username="before")
    assert result["role_preserved"]
    output=capsys.readouterr().out
    assert "my-admin-password-long" not in output
    assert Store(str(db)).users()[0]["username"]=="after"


def test_new_admin_login_cli_keeps_account_count(tmp_path,monkeypatch,capsys):
    db=tmp_path/"magazyn.sqlite3"
    s=Store(str(db))
    original=setup_linked_admin(s)
    monkeypatch.setattr(telegram_setup.getpass,"getpass",
                        lambda *_:"test-admin-password-long")
    monkeypatch.setattr("builtins.input",lambda *_:next(iter(["admin_next","admin_next"])))
    monkeypatch.setattr(sys,"argv",["magazyn.telegram_setup","rename-admin",
        "--db",str(db),"--admin-username","admin_old"])
    assert telegram_setup.main()==0
    printed=capsys.readouterr().out
    assert "ADMIN_LOGIN_UPDATED=PASS" in printed
    assert "ACCOUNT_ID_PRESERVED=PASS" in printed
    assert "TELEGRAM_PAIRING_PRESERVED=PASS" in printed
    assert len(s.users())==1 and s.users()[0]["username"]=="admin_next"
    assert messaging.linked_user(s,"telegram",123456789)["id"]==original[0]
