"""Stage 1/2 UAT: complete stock operations and ordered delivery in synthetic SQLite.

No live Magazyn database, external bots, or NAS traffic.
"""
from concurrent.futures import ThreadPoolExecutor

from magazyn.store import Problem
from magazyn import messaging
from test_magazyn import scenario, auth, post, ecu


def person(user_id, username, role="admin"):
    return {"id": user_id, "username": username, "role": role}


def part(**changes):
    value={
        "kind":"part", "designation":"SN74HC595-UAT", "category":"Układy scalone",
        "primary_number":"UAT-SN74HC595", "manufacturer":"Synthetic",
        "location_id":1, "quantity":10,
    }
    value.update(changes)
    return value


def test_full_part_flow_receipt_issue_move_inventory_history_and_roles(scenario):
    c,s,a,u=scenario
    h=auth(c)
    a_loc=post(c,"/api/locations",{"code":"P-A1"},h).json()["id"]
    b_loc=post(c,"/api/locations",{"code":"P-B1"},h).json()["id"]
    created=post(c,"/api/items/receive",part(location_id=a_loc),h)
    assert created.status_code==201,created.text
    item=created.json()["id"]
    assert s.item(item)["total"]==10
    worker=auth(c,"worker1","second-test-password-456")
    got=post(c,"/api/stock",{
        "action":"receive","item_id":item,"location_id":a_loc,"quantity":2},worker)
    assert got.status_code==201,got.text
    assert got.json()["after"]==12
    denied=post(c,"/api/stock",{
        "action":"issue","item_id":item,"location_id":a_loc,
        "quantity":1},worker)
    assert denied.status_code==422
    issued=post(c,"/api/stock",{
        "action":"issue","item_id":item,"location_id":a_loc,
        "quantity":5,"reason":"repair","order_ref":"UAT/001"},worker)
    assert issued.status_code==201,issued.text
    assert issued.json()["after"]==7
    moved=post(c,"/api/stock",{
        "action":"move","item_id":item,"location_id":a_loc,
        "to_location_id":b_loc,"quantity":3},worker)
    assert moved.status_code==201,moved.text
    assert moved.json()["after"]==4 and moved.json()["after_target"]==3
    underflow=post(c,"/api/stock",{
        "action":"move","item_id":item,"location_id":a_loc,
        "to_location_id":b_loc,"quantity":5},worker)
    assert underflow.status_code==409
    assert s.item(item)["total"]==7

    # Worker can count and read, but only an admin may correct stock.
    inventory=c.get("/api/inventory",params={"location_id":b_loc}).json()
    assert len(inventory)==1
    assert inventory[0]["expected_quantity"]==3
    adjust={
        "location_id":b_loc,
        "rows":[{**inventory[0],"quantity":4}],
    }
    assert c.post("/api/inventory",json=adjust,headers=worker).status_code==403
    h=auth(c)
    applied=c.post("/api/inventory",json=adjust,headers=h)
    assert applied.status_code==200,applied.text
    assert s.item(item)["total"]==8
    assert applied.json()[0]["after"]==4
    stale=c.post("/api/inventory",json=adjust,headers=h)
    assert stale.status_code==409
    assert s.item(item)["total"]==8
    assert len(s.history(item_id=item))==5
    history=c.get("/api/history",params={"item_id":item}).json()
    assert [r["action"] for r in history]==["adjust","move","issue","receive","receive"]
    issue=next(x for x in history if x["action"]=="issue")
    assert issue["reason"]=="repair" and issue["order_ref"]=="UAT/001"
    assert issue["actor_name"]=="worker1"
    moved_event=next(x for x in history if x["action"]=="move")
    assert moved_event["to_location_code"]=="P-B1"
    assert c.get("/api/stats").json()["units"]==8


def test_unauthorized_history_edits_do_not_change_stock(scenario):
    c,s,a,u=scenario
    h=auth(c); loc=s.add_location("A1")
    item=post(c,"/api/items/receive",part(location_id=loc,quantity=3),h).json()["id"]
    event_id=s.history(item_id=item)[0]["id"]
    worker=auth(c,"worker1","second-test-password-456")
    assert c.patch(f"/api/history/{event_id}",json={"note":"changed"},headers=worker).status_code==403
    assert c.delete(f"/api/history/{event_id}",headers=worker).status_code==403
    h=auth(c)
    assert c.patch(f"/api/history/{event_id}",json={"note":"Admin verified"},headers=h).status_code==200
    assert c.delete(f"/api/history/{event_id}",headers=h).status_code==200
    assert s.item(item)["total"]==3
    assert s.history(item_id=item)==[]


def test_inventory_multirow_conflict_rolls_back_every_row(scenario):
    c,s,a,u=scenario
    h=auth(c); loc=s.add_location("A1")
    first=post(c,"/api/items/receive",part(location_id=loc),h).json()["id"]
    second=post(c,"/api/items/receive",part(location_id=loc,designation="OTHER-UAT",
                                          primary_number="OTHER-UAT-001",quantity=4),h).json()["id"]
    rows=c.get("/api/inventory",params={"location_id":loc}).json()
    assert len(rows)==2
    payload=[]
    for entry in rows:
        if entry["item_id"]==first:
            payload.append({**entry,"quantity":6})
        else:
            payload.append({**entry,"expected_quantity":99,"quantity":8})
    events_before=len(s.history())
    result=c.post("/api/inventory",json={"location_id":loc,"rows":payload},headers=h)
    assert result.status_code==409,result.text
    assert len(s.history())==events_before
    assert s.item(first)["total"]==10
    assert s.item(second)["total"]==4


def test_overflow_cannot_create_more_than_max_stock_or_move(scenario):
    c,s,a,u=scenario
    h=auth(c); loc1=s.add_location("A1"); loc2=s.add_location("B1")
    item=post(c,"/api/items/receive",part(
        location_id=loc1,quantity=2_000_000_000),h).json()["id"]
    assert post(c,"/api/stock",{
        "action":"receive","item_id":item,"location_id":loc1,
        "quantity":1},h).status_code==422
    assert post(c,"/api/stock",{
        "action":"receive","item_id":item,"location_id":loc2,
        "quantity":1},h).status_code==201
    too_many=post(c,"/api/stock",{
        "action":"move","item_id":item,"location_id":loc2,
        "to_location_id":loc1,"quantity":1},h)
    assert too_many.status_code==422,too_many.text
    assert {x["location"]:x["quantity"] for x in s.item(item)["balances"]}=={
        "A1":2_000_000_000,"B1":1}
    assert len(s.history(item_id=item))==2


def test_partial_and_full_delivery_updates_order_and_real_stock_atomically(scenario):
    c,s,a,u=scenario
    h=auth(c); loc=s.add_location("A1")
    item=post(c,"/api/items/receive",part(location_id=loc,quantity=2),h).json()["id"]
    assert c.put(f"/api/items/{item}/minimum",json={"minimum":5},headers=h).status_code==200
    ordered=c.put(f"/api/items/{item}/order-status",json={
        "status":"ordered","quantity":7,"note":"UAT purchase"},headers=h)
    assert ordered.status_code==200
    assert c.get("/api/low-stock").json()[0]["order_status"]=="ordered"
    before_events=len(s.history(item_id=item))
    no_csrf=c.post(f"/api/items/{item}/order-delivery",
                   json={"location_id":loc,"quantity":3})
    assert no_csrf.status_code==403
    worker=auth(c,"worker1","second-test-password-456")
    assert post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":3},worker).status_code==403
    h=auth(c)
    first=post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":3},h)
    assert first.status_code==201,first.text
    assert first.json()["order_status"]=="ordered"
    assert first.json()["remaining_ordered"]==4
    assert s.item(item)["total"]==5
    assert len(s.history(item_id=item))==before_events+1
    assert c.get("/api/low-stock").json()[0]["ordered_quantity"]==4

    over=post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":5},h)
    assert over.status_code==409
    assert s.item(item)["total"]==5
    assert s.get_order_status(item)["quantity"]==4
    done=post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":4},h)
    assert done.status_code==201,done.text
    assert done.json()["order_status"]=="none"
    assert done.json()["remaining_ordered"]==0
    assert s.item(item)["total"]==9
    assert c.get("/api/low-stock").json()==[]
    assert post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":1},h).status_code==409
    assert s.item(item)["total"]==9


def test_invalid_delivery_location_rolls_back_order_and_history(scenario):
    c,s,a,u=scenario
    h=auth(c); loc=s.add_location("A1")
    item=post(c,"/api/items/receive",part(location_id=loc),h).json()["id"]
    c.put(f"/api/items/{item}/order-status",json={"status":"ordered","quantity":3},headers=h)
    events_before=len(s.history(item_id=item))
    denied=post(c,f"/api/items/{item}/order-delivery",{
        "location_id":99999,"quantity":2},h)
    assert denied.status_code==404,denied.text
    assert s.get_order_status(item)["quantity"]==3
    assert s.item(item)["total"]==10
    assert len(s.history(item_id=item))==events_before


def test_ecu_delivery_keeps_variant_condition_and_supplier_receipt(scenario):
    c,s,a,u=scenario
    h=auth(c)
    loc=s.add_location("A1")
    created=post(c,"/api/items/receive",{
        **ecu(), "quantity":0,"location_id":loc,
        "product_state":"used","technical_state":"unknown"},h)
    assert created.status_code==201,created.text
    item=created.json()["id"]
    c.put(f"/api/items/{item}/order-status",json={
        "status":"ordered","quantity":2},headers=h)
    bad=post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":1,"product_state":"broken",
        "technical_state":"working"},h)
    assert bad.status_code==422
    success=post(c,f"/api/items/{item}/order-delivery",{
        "location_id":loc,"quantity":2,"product_state":"new",
        "technical_state":"working"},h)
    assert success.status_code==201,success.text
    balance=s.item(item)["balances"]
    assert len(balance)==1 and balance[0]["product_state"]=="new"
    assert balance[0]["technical_state"]=="working"
    assert s.item(item)["total"]==2
    assert s.get_order_status(item)["status"]=="none"


def test_concurrent_delivery_only_one_succeeds(scenario):
    c,s,a,u=scenario
    h=auth(c); loc=s.add_location("A1")
    item=post(c,"/api/items/receive",part(location_id=loc,quantity=0),h).json()["id"]
    s.set_order_status(item,"ordered",3,"",person(a,"admin1"))
    def consume():
        try:
            return s.receive_order_delivery(item,loc,3,person(a,"admin1"))["status"]
        except Problem as exc:
            return exc.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:consume(),range(2)))
    assert sorted(map(str,results))==["409","PASS"]
    assert s.item(item)["total"]==3
    assert s.get_order_status(item)["status"]=="none"
    assert len(s.history(item_id=item))==1


def test_low_stock_alert_not_duplicated_by_orders_and_partial_delivery(scenario):
    c,s,a,u=scenario
    h=auth(c);loc=s.add_location("A1")
    item=post(c,"/api/items/receive",part(location_id=loc,quantity=2),h).json()["id"]
    pairing=messaging.create_pairing(s,u,"telegram",a)
    assert messaging.redeem_pairing(s,"telegram",777888999,pairing["code"])
    s.set_minimum(item,5,u,"telegram")
    with s.connect() as con:
        assert con.execute("SELECT count(*) FROM message_outbox WHERE item_id=?",(item,)).fetchone()[0]==1
    s.set_order_status(item,"ordered",6,"",person(a,"admin1"))
    s.receive_order_delivery(item,loc,2,person(a,"admin1"))
    with s.connect() as con:
        assert con.execute("SELECT count(*) FROM message_outbox WHERE item_id=?",(item,)).fetchone()[0]==1
    s.receive_order_delivery(item,loc,4,person(a,"admin1"))
    with s.connect() as con:
        assert con.execute(
            "SELECT status FROM message_outbox WHERE item_id=?",(item,)).fetchone()[0]=="cancelled"
    assert s.item(item)["total"]==8
    assert s.get_order_status(item)["status"]=="none"
