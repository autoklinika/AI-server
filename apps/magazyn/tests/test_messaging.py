"""Private chat identity, security and targeted alert checks; synthetic fixtures only."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from magazyn import messaging, bots
from magazyn.store import Store, Problem, now
from test_magazyn import scenario, auth, ecu, operation, post


@pytest.fixture
def configured(scenario):
    client,store,admin,worker=scenario
    header=auth(client)
    loc=store.add_location("A1")
    item=store.add_item(ecu(),{"id":admin,"username":"admin1","role":"admin"})
    return client,store,header,admin,worker,loc,item


def code_for(client,head,user_id,provider):
    response=post(client,"/api/messaging/pairing",
                  {"user_id":user_id,"provider":provider},head)
    assert response.status_code==201,response.text
    return response.json()["code"]


def telegram_message(identity, text, *, chat_kind="private", chat_id=None, sender_bot=False):
    return {"update_id":1,"message":{
        "chat":{"type":chat_kind,"id": identity if chat_id is None else chat_id},
        "from":{"id":identity,"is_bot":sender_bot},
        "text":text}}


def discord_message(store, identity, text, channel_kind="dm", guild_id=None, is_bot=False):
    return bots.reply_for_discord(store,guild_id=guild_id,channel_kind=channel_kind,
       sender_id=identity,is_bot=is_bot,content=text)


def test_first_admin_pairing_private_telegram_only(configured):
    c,s,h,admin,user,loc,item=configured
    code=code_for(c,h,user,"telegram")
    assert len(code)>30
    with s.connect() as con:
        assert not con.execute("SELECT 1 FROM message_pairings WHERE code_hash=?",(code,)).fetchone()
    assert bots.reply_for_telegram(s,telegram_message(123456,f"/polacz {code}",
        chat_kind="supergroup")) is None
    assert bots.reply_for_telegram(s,telegram_message(123456,f"/polacz {code}",
        chat_id=-100)) is None
    assert bots.reply_for_telegram(s,telegram_message(123456,f"/polacz {code}",
        sender_bot=True)) is None
    # Unlinked user cannot enumerate even a known product.
    denied=bots.reply_for_telegram(s,telegram_message(123456,"/stan EDC7"))
    assert "Brak dostępu" in denied[1] and "Bosch" not in denied[1]
    linked=bots.reply_for_telegram(s,telegram_message(123456,f"/polacz {code}"))
    assert "powiązane" in linked[1] and "telegram" not in linked[1].lower()
    assert messaging.linked_user(s,"telegram",123456)["id"]==user
    assert messaging.linked_user(s,"discord",123456) is None
    assert "Nieprawidłowy" in bots.reply_for_telegram(s,telegram_message(999999,
                             f"/polacz {code}"))[1]
    assert c.get("/api/messaging/links").status_code==200
    query=bots.reply_for_telegram(s,telegram_message(123456,"ile mam Bosch EDC7?"))
    assert query[0]=="123456" and "Bosch EDC7" in query[1]
    assert "0 szt." in query[1]


def test_discord_private_only_authorized_user(configured):
    c,s,h,a,u,loc,item=configured
    code=code_for(c,h,u,"discord")
    assert discord_message(s,43210,f"/polacz {code}",channel_kind="group_dm") is None
    assert discord_message(s,43210,f"/polacz {code}",guild_id=42) is None
    assert discord_message(s,43210,f"/polacz {code}",is_bot=True) is None
    assert "powiązane" in discord_message(s,43210,f"/polacz {code}")[1]
    s.stock_operation(operation(item,loc,quantity=3),{"id":a,"username":"admin1","role":"admin"})
    answer=discord_message(s,43210,"/stan 0281016738")
    assert answer[0]=="43210" and "3 szt." in answer[1]
    assert "Brak dostępu" in discord_message(s,99999,"/stan 0281016738")[1]
    assert discord_message(s,43210,"/nieznane")[1].startswith("Nieznane")


def test_pairing_expiry_one_time_and_hijack_prevention(configured):
    c,s,h,a,u,loc,item=configured
    code=code_for(c,h,u,"telegram")
    with s.connect(write=True) as con:
        con.execute("UPDATE message_pairings SET expires_at='2020-01-01T00:00:00+00:00'")
    assert messaging.redeem_pairing(s,"telegram",1111,code) is False
    valid=code_for(c,h,u,"telegram")
    assert messaging.redeem_pairing(s,"telegram",1111,valid)
    other=s.create_user("seconduser","second-user-password","user")
    code_other=code_for(c,h,other,"telegram")
    assert not messaging.redeem_pairing(s,"telegram",1111,code_other)
    assert messaging.linked_user(s,"telegram",1111)["id"]==u
    assert messaging.redeem_pairing(s,"telegram",2222,code_other)
    assert not messaging.redeem_pairing(s,"telegram",3333,code_other)
    replacement=code_for(c,h,u,"telegram")
    assert messaging.redeem_pairing(s,"telegram",3333,replacement)
    assert messaging.linked_user(s,"telegram",1111) is None
    assert messaging.linked_user(s,"telegram",3333)["id"]==u


def test_pairing_requires_admin_csrf_and_active_user(configured):
    c,s,h,a,u,loc,item=configured
    hu=auth(c,"worker1","second-test-password-456")
    assert post(c,"/api/messaging/pairing",{"user_id":u,"provider":"telegram"},hu).status_code==403
    assert c.post("/api/messaging/pairing",
        json={"user_id":u,"provider":"telegram"}).status_code==403
    h=auth(c)
    assert post(c,"/api/messaging/pairing",{"user_id":u,"provider":"rss"},h).status_code==422
    assert post(c,"/api/messaging/pairing",{"user_id":99999,"provider":"discord"},h).status_code==404
    s.change_user(u,active=False)
    assert post(c,"/api/messaging/pairing",{"user_id":u,"provider":"discord"},h).status_code==404
    assert c.get("/api/messaging/status").status_code==200
    assert c.post("/api/auth/login",json={
        "username":"worker1","password":"second-test-password-456"}).status_code==401


def test_low_stock_targeted_single_recipient_and_latched(configured):
    c,s,h,a,u,loc,item=configured
    assert messaging.redeem_pairing(s,"telegram",56789,code_for(c,h,u,"telegram"))
    s.stock_operation(operation(item,loc,quantity=10),{"id":a,"username":"admin1","role":"admin"})
    assert c.put(f"/api/items/{item}/minimum",
                 json={"minimum":5,"recipient_user_id":u,"provider":"telegram"},
                 headers=h).status_code==200
    actor={"id":a,"username":"admin1","role":"admin"}
    s.stock_operation(operation(item,loc,quantity=6,action="issue",reason="repair"),actor)
    status=messaging.outbox_status(s)
    assert status.get("pending")==1
    sent=[]
    assert bots.dispatch_pending(s,"discord",lambda identity,body:sent.append((identity,body)))["sent"]==0
    assert bots.dispatch_pending(s,"telegram",lambda identity,body:sent.append((identity,body)))["sent"]==1
    assert len(sent)==1 and sent[0][0]=="56789"
    assert "Pozostało: 4 szt." in sent[0][1]
    s.stock_operation(operation(item,loc,quantity=1,action="issue",reason="sale"),actor)
    assert bots.dispatch_pending(s,"telegram",lambda identity,body:sent.append((identity,body)))["sent"]==0
    # Sending once per fall below threshold. Re-arm only after genuine restock > minimum.
    s.stock_operation(operation(item,loc,quantity=6,action="receive"),actor)
    s.stock_operation(operation(item,loc,quantity=5,action="issue",reason="other"),actor)
    assert bots.dispatch_pending(s,"telegram",lambda identity,body:sent.append((identity,body)))["sent"]==1
    assert len(sent)==2 and sent[1][0]=="56789"
    assert messaging.outbox_status(s)["sent"]==2


def test_unpaired_recipient_never_receives_and_link_while_low(configured):
    c,s,h,a,u,loc,item=configured
    actor={"id":a,"username":"admin1","role":"admin"}
    s.stock_operation(operation(item,loc,quantity=1),actor)
    s.set_minimum(item,5,u,"telegram")
    assert messaging.outbox_status(s)=={}
    assert c.get("/api/low-stock").json()[0]["item_id"]==item
    assert messaging.redeem_pairing(s,"telegram",112233,code_for(c,h,u,"telegram"))
    sent=[]
    bots.dispatch_pending(s,"telegram",lambda identity,body:sent.append(identity))
    assert sent==["112233"]


def test_unlink_and_disable_user_cancel_pending(configured):
    c,s,h,a,u,loc,item=configured
    actor={"id":a,"username":"admin1","role":"admin"}
    messaging.redeem_pairing(s,"discord",11223344,code_for(c,h,u,"discord"))
    s.stock_operation(operation(item,loc,quantity=1),actor)
    s.set_minimum(item,4,u,"discord")
    assert messaging.outbox_status(s)["pending"]==1
    response=c.delete(f"/api/messaging/links/discord/{u}",headers=h)
    assert response.status_code==200 and response.json()["removed"]
    assert messaging.linked_user(s,"discord",11223344) is None
    assert messaging.outbox_status(s)["cancelled"]==1
    assert bots.dispatch_pending(s,"discord",lambda *_:pytest.fail("leaked"))["sent"]==0
    code=code_for(c,h,u,"discord")
    messaging.redeem_pairing(s,"discord",11223344,code)
    assert messaging.outbox_status(s)["pending"]==1
    s.change_user(u,active=False)
    assert messaging.outbox_status(s)["cancelled"]==2
    assert messaging.linked_user(s,"discord",11223344) is None
    assert bots.dispatch_pending(s,"discord",lambda *_:pytest.fail("inactive leak"))["sent"]==0


def test_change_config_cancels_obsolete_recipient_and_idempotent_put(configured):
    c,s,h,a,u,loc,item=configured
    other=s.create_user("other","other-user-password-long","user")
    messaging.redeem_pairing(s,"telegram",123456,code_for(c,h,u,"telegram"))
    messaging.redeem_pairing(s,"telegram",789012,code_for(c,h,other,"telegram"))
    actor={"id":a,"username":"admin1","role":"admin"}
    s.set_minimum(item,0,u,"telegram")
    # stock initially zero: message pending for user u.
    assert messaging.outbox_status(s)["pending"]==1
    s.set_minimum(item,0,u,"telegram")
    assert messaging.outbox_status(s)["pending"]==1  # repeated identical PUT must not spam
    s.set_minimum(item,0,other,"telegram")
    assert messaging.outbox_status(s)["cancelled"]==1
    sent=[]
    bots.dispatch_pending(s,"telegram",lambda identity,body:sent.append(identity))
    assert sent==["789012"]


def test_delivery_failure_backoff_and_retry(configured):
    c,s,h,a,u,loc,item=configured
    messaging.redeem_pairing(s,"telegram",4466,code_for(c,h,u,"telegram"))
    s.set_minimum(item,0,u,"telegram")
    def fail(*_):
        raise RuntimeError("synthetic network outage")
    assert bots.dispatch_pending(s,"telegram",fail) == {"sent":0,"failed":1}
    assert messaging.outbox_status(s)["pending"]==1
    with s.connect() as con:
        row=con.execute("SELECT attempts,next_attempt_at,body FROM message_outbox").fetchone()
        assert row["attempts"]==1 and row["next_attempt_at"]>now()
    with s.connect(write=True) as con:
        con.execute("UPDATE message_outbox SET next_attempt_at=?",(now(),))
    target=[]
    assert bots.dispatch_pending(s,"telegram",lambda uid,body:target.append(uid))["sent"]==1
    assert target==["4466"] and messaging.outbox_status(s)["sent"]==1


def test_stale_claim_not_sent_after_revoke(configured):
    c,s,h,a,u,loc,item=configured
    messaging.redeem_pairing(s,"telegram",5566,code_for(c,h,u,"telegram"))
    s.set_minimum(item,0,u,"telegram")
    claimed=messaging.claim_next(s,"telegram")
    assert claimed and messaging.delivery_still_allowed(s,claimed)
    messaging.unlink(s,"telegram",u)
    assert not messaging.delivery_still_allowed(s,claimed)
    assert bots.dispatch_pending(s,"telegram",lambda *_:pytest.fail("stale alert"))["sent"]==0


def test_concurrent_workers_claim_unique_alert(configured):
    c,s,h,a,u,loc,item=configured
    messaging.redeem_pairing(s,"telegram",12399,code_for(c,h,u,"telegram"))
    s.set_minimum(item,0,u,"telegram")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:messaging.claim_next(s,"telegram"),range(2)))
    assert sum(x is not None for x in results)==1
    assert messaging.outbox_status(s)["sending"]==1


def test_dm_adapter_filters_and_length(configured):
    c,s,h,a,u,loc,item=configured
    assert bots.telegram_private_incoming(telegram_message(1,"x",chat_kind="group")) is None
    assert bots.telegram_private_incoming(telegram_message(1,"x",chat_id=2)) is None
    assert bots.telegram_private_incoming({"edited_message":telegram_message(1,"x")["message"]}) is None
    assert bots.telegram_private_incoming(telegram_message(1,"x",sender_bot=True)) is None
    assert bots.discord_private_incoming(guild_id=10,channel_kind="dm",sender_id=1,
        is_bot=False,content="/stan") is None
    assert bots.discord_private_incoming(guild_id=None,channel_kind="group_dm",sender_id=1,
        is_bot=False,content="/stan") is None
    assert bots.discord_private_incoming(guild_id=None,channel_kind="dm",sender_id="invalid",
        is_bot=False,content="/stan") is None
    assert bots.RateLimiter(cooldown_seconds=60).allow("telegram","1")
    assert "Brak dostępu" in messaging.process_private_message(s,"telegram","999","/stan 028")[0:250]
    assert len(messaging.process_private_message(s,"telegram","999","x"*1000))<100


def test_admin_api_and_migration_upgrade(configured,tmp_path):
    c,s,h,a,u,loc,item=configured
    assert c.get(f"/api/items/{item}/minimum").json()["minimum"] is None
    assert c.get("/api/messaging/status").json()["links"]==0
    with s.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0]==2
    assert c.get("/api/messaging/links").status_code==200
    db=tmp_path/"pre_v1.sqlite3"
    old=Store(str(db))
    old.create_user("migrated","migrated-password-long","admin")
    with old.connect(write=True) as con:
        con.execute("DROP TABLE message_outbox")
        con.execute("DROP TABLE message_pairings")
        con.execute("DROP TABLE stock_alert_state")
        con.execute("PRAGMA user_version=1")
    restored=Store(str(db))
    assert restored.users()[0]["username"]=="migrated"
    with restored.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0]==2


def test_bots_cannot_start_without_opt_in(tmp_path,monkeypatch):
    monkeypatch.delenv("MAGAZYN_BOTS_ENABLED",raising=False)
    with pytest.raises(SystemExit):
        bots.main(["telegram","--db",str(tmp_path/"never-create.db")])
    assert not (tmp_path/"never-create.db").exists()


def test_unicode_pairing_code_is_rejected_without_crashing_loop(configured):
    c,s,h,a,u,loc,item=configured
    code=code_for(c,h,u,"telegram")
    invalid=bots.reply_for_telegram(s,telegram_message(5511,"/polacz "+"ż"*35))
    assert invalid is not None and "Nieprawidłowy" in invalid[1]
    # The malformed command did not consume or disclose the valid one-use code.
    assert "powiązane" in bots.reply_for_telegram(s,telegram_message(
        5511,"/polacz "+code))[1]


def test_repair_same_or_new_identity_after_sent_does_not_repeat_alert(configured):
    c,s,h,a,u,loc,item=configured
    messaging.redeem_pairing(s,"telegram",99111,code_for(c,h,u,"telegram"))
    s.set_minimum(item,0,u,"telegram")
    delivered=[]
    assert bots.dispatch_pending(s,"telegram",
       lambda uid,body:delivered.append(uid))["sent"]==1
    assert delivered==["99111"]
    assert messaging.redeem_pairing(s,"telegram",99111,
                                   code_for(c,h,u,"telegram"))
    assert bots.dispatch_pending(s,"telegram",
       lambda *_:pytest.fail("same user re-pair spam"))["sent"]==0
    assert messaging.redeem_pairing(s,"telegram",99222,
                                   code_for(c,h,u,"telegram"))
    assert messaging.linked_user(s,"telegram",99111) is None
    assert bots.dispatch_pending(s,"telegram",
       lambda *_:pytest.fail("new identity after sent spam"))["sent"]==0


def test_repair_retargets_undelivered_pending_alert_only(configured):
    c,s,h,a,u,loc,item=configured
    messaging.redeem_pairing(s,"telegram",99111,code_for(c,h,u,"telegram"))
    s.set_minimum(item,0,u,"telegram")
    assert messaging.outbox_status(s)["pending"]==1
    messaging.redeem_pairing(s,"telegram",99222,code_for(c,h,u,"telegram"))
    statuses=messaging.outbox_status(s)
    assert statuses["cancelled"]==1 and statuses["pending"]==1
    delivered=[]
    bots.dispatch_pending(s,"telegram",lambda uid,body:delivered.append(uid))
    assert delivered==["99222"]


def test_bulk_inventory_net_low_does_not_rearm_sent_alert(configured):
    c,s,h,a,u,loc,item=configured
    actor={"id":a,"username":"admin1","role":"admin"}
    messaging.redeem_pairing(s,"telegram",66111,code_for(c,h,u,"telegram"))
    s.stock_operation(operation(item,loc,quantity=2,product_state="used"),actor)
    s.stock_operation(operation(item,loc,quantity=2,product_state="new"),actor)
    s.set_minimum(item,5,u,"telegram")
    assert bots.dispatch_pending(s,"telegram",lambda *_:None)["sent"]==1
    rows=[
        {"item_id":item,"product_state":"used","technical_state":"working",
         "expected_quantity":2,"quantity":5},
        {"item_id":item,"product_state":"new","technical_state":"working",
         "expected_quantity":2,"quantity":0},
    ]
    s.apply_inventory(loc,rows,actor)
    assert s.item(item)["total"]==5
    assert messaging.outbox_status(s)=={"sent":1}
    assert bots.dispatch_pending(s,"telegram",
       lambda *_:pytest.fail("intermediate inventory state rearmed"))["sent"]==0


def test_alert_body_uses_latest_quantity_when_claimed(configured):
    c,s,h,a,u,loc,item=configured
    actor={"id":a,"username":"admin1","role":"admin"}
    messaging.redeem_pairing(s,"telegram",76111,code_for(c,h,u,"telegram"))
    s.stock_operation(operation(item,loc,quantity=10),actor)
    s.set_minimum(item,5,u,"telegram")
    s.stock_operation(operation(item,loc,action="issue",quantity=6,reason="other"),actor)
    s.stock_operation(operation(item,loc,action="issue",quantity=2,reason="other"),actor)
    delivered=[]
    bots.dispatch_pending(s,"telegram",lambda user_id,text:delivered.append(text))
    assert len(delivered)==1
    assert "Pozostało: 2 szt." in delivered[0]


def test_discord_rechecks_link_after_network_await(configured,monkeypatch):
    """Revocation during the await fetch_user must stop the subsequent outbound send."""
    import asyncio
    import sys
    from types import SimpleNamespace

    c,s,h,a,u,loc,item=configured
    messaging.redeem_pairing(s,"discord",771188,code_for(c,h,u,"discord"))
    s.set_minimum(item,0,u,"discord")
    sent=[]
    instances=[]
    class DummyIntents:
        @classmethod
        def none(cls):
            return cls()
    class DummyDM:
        pass
    class DummyClient:
        def __init__(self, *, intents):
            self.intents=intents
            self.closed=False
            instances.append(self)
        def event(self,handler):
            setattr(self,handler.__name__,handler)
            return handler
        def run(self,*args,**kwargs):
            return
        def is_closed(self):
            return self.closed
        async def fetch_user(self,remote_user_id):
            assert remote_user_id==771188
            # The real adapter awaits fetch_user before initiating send.
            messaging.unlink(s,"discord",u)
            class Recipient:
                async def send(self,*_args,**_kwargs):
                    sent.append("leak")
            return Recipient()
    fake=SimpleNamespace(
        Client=DummyClient,Intents=DummyIntents,DMChannel=DummyDM,
        HTTPException=RuntimeError,Forbidden=PermissionError,
        AllowedMentions=SimpleNamespace(none=lambda:None))
    monkeypatch.setitem(sys.modules,"discord",fake)
    bots.run_discord(s,"synthetic-not-real-token")
    assert len(instances)==1
    client=instances[0]
    async def exercise():
        await client.on_ready()
        await asyncio.sleep(.05)
        client.closed=True
        client._magazyn_queue_task.cancel()
        try:
            await client._magazyn_queue_task
        except asyncio.CancelledError:
            pass
    asyncio.run(exercise())
    assert not sent and messaging.outbox_status(s)["cancelled"]==1


def test_discord_queue_recovers_after_transient_db_failure(configured,monkeypatch):
    import asyncio
    import sqlite3
    import sys
    from types import SimpleNamespace

    c,s,h,a,u,loc,item=configured
    instances=[]
    class DummyIntents:
        @classmethod
        def none(cls):
            return cls()
    class DummyClient:
        def __init__(self, *, intents):
            self.closed=False
            instances.append(self)
        def event(self,handler):
            setattr(self,handler.__name__,handler)
            return handler
        def run(self,*args,**kwargs):
            pass
        def is_closed(self):
            return self.closed
    fake=SimpleNamespace(
        Client=DummyClient,Intents=DummyIntents,DMChannel=type("DMChannel",(),{}),
        HTTPException=RuntimeError,Forbidden=PermissionError,
        AllowedMentions=SimpleNamespace(none=lambda:None))
    monkeypatch.setitem(sys.modules,"discord",fake)
    bots.run_discord(s,"synthetic-not-real-token")
    client=instances[0]
    iterations=[]
    def transient(_store,_provider):
        iterations.append(1)
        if len(iterations)==1:
            raise sqlite3.OperationalError("synthetic busy")
        client.closed=True
        return None
    monkeypatch.setattr(messaging,"claim_next",transient)
    original_sleep=asyncio.sleep
    async def very_short(_delay):
        await original_sleep(0)
    monkeypatch.setattr(bots.asyncio,"sleep",very_short)
    async def exercise():
        await client.on_ready()
        await asyncio.wait_for(client._magazyn_queue_task,timeout=.5)
    asyncio.run(exercise())
    assert len(iterations)==2
