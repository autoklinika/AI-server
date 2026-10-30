"""Telegram DEV provisioning: fake tokens, no Telegram API or other external services."""
import os
import stat
from pathlib import Path

import pytest

from magazyn import bots,telegram_setup
from magazyn.store import Store


FAKE_TOKEN="123456789:AA" + "a"*38  # Synthetic credential; never a real Telegram token.


def test_token_private_file_and_no_overwrite(tmp_path):
    parent=tmp_path/"private"
    parent.mkdir(mode=0o700)
    token_file=parent/"telegram.token"
    result=telegram_setup.save_token_exclusive(token_file,FAKE_TOKEN)
    assert result==token_file
    assert (result.stat().st_mode&0o777)==0o600
    assert telegram_setup.load_token(result)==FAKE_TOKEN
    with pytest.raises(telegram_setup.SetupFailure,match="istnieje"):
        telegram_setup.save_token_exclusive(result,FAKE_TOKEN)
    assert result.read_text().strip()==FAKE_TOKEN


def test_token_rejected_if_public_or_symlink(tmp_path):
    private=tmp_path/"private"
    private.mkdir(mode=0o700)
    token_file=telegram_setup.save_token_exclusive(private/"bot.token",FAKE_TOKEN)
    token_file.chmod(0o644)
    with pytest.raises(telegram_setup.SetupFailure,match="0600"):
        telegram_setup.load_token(token_file)
    token_file.chmod(0o600)
    shortcut=private/"shortcut"
    shortcut.symlink_to(token_file)
    with pytest.raises(telegram_setup.SetupFailure,match="dowiązaniem"):
        telegram_setup.load_token(shortcut)
    private.chmod(0o755)
    with pytest.raises(telegram_setup.SetupFailure,match="0700"):
        telegram_setup.save_token_exclusive(private/"another.token",FAKE_TOKEN)


@pytest.mark.parametrize("invalid",["","token-without-colon","abc:bad","12345:abc",
                                   "12345:"+"ż"*40, "  "+FAKE_TOKEN, FAKE_TOKEN+"\nnew"])
def test_bad_token_validation(invalid):
    with pytest.raises(telegram_setup.SetupFailure):
        telegram_setup.validate_token(invalid)


def test_bot_verification_mocked_no_webhook(monkeypatch):
    import httpx
    calls=[]
    class Response:
        def __init__(self, method):
            self.method=method
        def raise_for_status(self):
            pass
        def json(self):
            result=({"id":123456789,"is_bot":True,"username":"MagazynTest_bot",
                     "can_join_groups":True} if self.method=="getMe" else {"url":""})
            return {"ok":True,"result":result}
    class FakeClient:
        def __init__(self,**kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self,*args):
            pass
        def post(self,url,json):
            calls.append(url)
            return Response(url.rsplit("/",1)[-1])
    monkeypatch.setattr(httpx,"Client",FakeClient)
    record=telegram_setup.verify_telegram(FAKE_TOKEN)
    assert record["username"]=="MagazynTest_bot"
    assert record["can_join_groups"] is True
    assert len(calls)==2
    assert all(FAKE_TOKEN in u for u in calls)


def test_webhook_existing_rejected_no_autodeletion(monkeypatch):
    import httpx
    calls=[]
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json):
            calls.append(url.rsplit("/",1)[-1])
            class Response:
                def raise_for_status(self):pass
                def json(self):
                    return {"ok":True,"result":{"is_bot":True,"username":"Invent_bot"} if
                             url.endswith("getMe") else {"url":"https://test.invalid/hook"}}
            return Response()
    monkeypatch.setattr(httpx,"Client",FakeClient)
    with pytest.raises(telegram_setup.SetupFailure,match="webhook"):
        telegram_setup.verify_telegram(FAKE_TOKEN)
    assert calls==["getMe","getWebhookInfo"]


def test_http_exception_does_not_expose_secret(monkeypatch):
    import httpx
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,json):
            request=httpx.Request("POST",url)
            raise httpx.ConnectError("Failed "+url,request=request)
    monkeypatch.setattr(httpx,"Client",FakeClient)
    with pytest.raises(telegram_setup.SetupFailure) as err:
        telegram_setup.verify_telegram(FAKE_TOKEN)
    assert FAKE_TOKEN not in str(err.value)


def test_bot_service_reads_file_without_env_token(tmp_path,monkeypatch):
    private=tmp_path/"private"
    private.mkdir(mode=0o700)
    bot_token=telegram_setup.save_token_exclusive(private/"token",FAKE_TOKEN)
    db=private/"magazyn.sqlite3"
    store=Store(str(db))
    store.create_user("admin","this-is-a-dev-password","admin")
    captured=[]
    monkeypatch.setenv("MAGAZYN_BOTS_ENABLED","1")
    monkeypatch.delenv("MAGAZYN_TELEGRAM_BOT_TOKEN",raising=False)
    monkeypatch.setattr(bots,"run_telegram",lambda _store,token:captured.append(token))
    bots.main(["telegram","--db",str(db),"--token-file",str(bot_token)])
    assert captured==[FAKE_TOKEN]


def test_interactive_config_initializes_and_verifies_without_token_in_output(
        tmp_path,monkeypatch,capsys):
    private=tmp_path/"data"
    private.mkdir(mode=0o700)
    db=private/"inventory.db"
    file=private/"bot.token"
    from magazyn import telegram_setup as setup
    inputs=iter(["correct-long-password","correct-long-password",FAKE_TOKEN])
    monkeypatch.setattr(setup.getpass,"getpass",lambda *_:next(inputs))
    monkeypatch.setattr(setup,"verify_telegram",lambda token: {
        "username":"MyTest_bot","bot_id":123456789,"can_join_groups":False})
    result=setup.run_setup(db=str(db),token_file=str(file),admin_username="owner")
    assert result["admin"]=="owner" and result["bot_username"]=="MyTest_bot"
    assert Store(str(db)).users()[0]["username"]=="owner"
    assert setup.load_token(file)==FAKE_TOKEN
    captured=capsys.readouterr().out
    assert FAKE_TOKEN not in captured


def test_pair_requires_admin_password_and_is_one_use(tmp_path,monkeypatch):
    from magazyn import telegram_setup as setup
    private=tmp_path/"data"
    private.mkdir(mode=0o700)
    db=private/"inventory.sqlite3"
    store=Store(str(db))
    admin=store.create_user("owner","this-is-a-dev-password","admin")
    user=store.create_user("worker","worker-password-long","user")
    monkeypatch.setattr(setup.getpass,"getpass",lambda *_:"this-is-a-dev-password")
    pairing=setup.run_pair(db=str(db),admin_username="owner",username="worker")
    assert pairing["user_id"]==user and pairing["provider"]=="telegram"
    from magazyn.messaging import redeem_pairing
    assert redeem_pairing(store,"telegram",11223344,pairing["code"])
    assert not redeem_pairing(store,"telegram",99887766,pairing["code"])
