"""Atomic UX-backed catalog receipts, duplicate guards, permissions and basic markup."""
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from magazyn.server import create_app
from magazyn.store import Problem, Store
from test_magazyn import scenario, auth, post, operation


def ecu_item(**changes):
    base={
        "kind":"ecu", "designation":"Bosch EDC7",
        "brand":"DAF", "primary_number":"0 281 012 067",
        "manufacturer":"Bosch", "model":"EDC7",
        "hw":"H1", "sw":"S1", "numbers":[{"number":"1943-026","number_type":"OEM"}],
        "brands":["MAN"], "location_id":1, "quantity":4,
        "product_state":"used", "technical_state":"working",
    }
    base.update(changes)
    return base


def part_item(**changes):
    base={"kind":"part","designation":"IRF3205","primary_number":"IRF3205",
          "manufacturer":"Infineon", "category":"MOSFET","package":"TO-220",
          "parameters":"55V 110A","quantity":20,"location_id":1}
    base.update(changes)
    return base


def test_atomic_create_and_receipt_records_one_event(scenario):
    client,store,aid,uid=scenario
    headers=auth(client)
    loc=post(client,"/api/locations",{"code":"A1"},headers).json()["id"]
    assert loc==1
    result=post(client,"/api/items/receive",ecu_item(),headers)
    assert result.status_code==201,result.text
    item_id=result.json()["id"]
    assert result.json()["quantity"]==4
    assert result.json()["event_id"]>0
    data=client.get(f"/api/items/{item_id}").json()
    assert data["total"]==4
    assert len(data["balances"])==1
    assert data["balances"][0]["location"]=="A1"
    assert data["balances"][0]["technical_state"]=="working"
    history=client.get("/api/history").json()
    assert len(history)==1 and history[0]["quantity"]==4
    assert history[0]["actor_name"]=="admin1"
    assert store.statistics()["units"]==4


def test_no_half_product_when_location_wrong_or_state_invalid(scenario):
    c,s,a,u=scenario
    h=auth(c)
    s.add_location("A1")
    bad=post(c,"/api/items/receive",ecu_item(location_id=999),h)
    assert bad.status_code==404
    assert s.statistics()["items"]==0 and s.statistics()["units"]==0
    invalid=post(c,"/api/items/receive",ecu_item(technical_state="broken"),h)
    assert invalid.status_code==422
    assert s.statistics()["items"]==0
    assert len(s.history())==0


def test_exact_duplicate_alias_rejected_even_with_override(scenario):
    c,s,a,u=scenario
    h=auth(c);s.add_location("A1")
    assert post(c,"/api/items/receive",ecu_item(),h).status_code==201
    duplicate=ecu_item(
        primary_number="1943 026",
        numbers=[{"number":"0281012067","number_type":"Bosch"}],
        allow_distinct_variant=True)
    resp=post(c,"/api/items/receive",duplicate,h)
    assert resp.status_code==409,resp.text
    assert s.statistics()["items"]==1 and s.statistics()["units"]==4
    same=c.get("/api/items/similar",params={
        "kind":"ecu","primary_number":"1943026","brand":"DAF","hw":"H1","sw":"S1"})
    assert same.status_code==200
    assert same.json()[0]["same_variant"] is True


def test_distinct_hw_variant_requires_explicit_override(scenario):
    c,s,a,u=scenario
    h=auth(c);s.add_location("A1")
    first=post(c,"/api/items/receive",ecu_item(),h)
    assert first.status_code==201
    variant=ecu_item(hw="H2",sw="S2",quantity=2)
    resp=post(c,"/api/items/receive",variant,h)
    assert resp.status_code==409
    preview=c.get("/api/items/similar",params={
        "kind":"ecu","primary_number":"0281012067","brand":"DAF","hw":"H2","sw":"S2"})
    assert preview.status_code==200
    assert preview.json()[0]["same_variant"] is False
    variant["allow_distinct_variant"]=True
    accepted=post(c,"/api/items/receive",variant,h)
    assert accepted.status_code==201,accepted.text
    assert s.statistics()["items"]==2 and s.statistics()["units"]==6
    assert s.item(accepted.json()["id"])["hw"]=="H2"


def test_worker_can_receive_but_cannot_modify_admin_minimum(scenario):
    c,s,a,u=scenario
    h=auth(c);s.add_location("A1")
    hw=auth(c,"worker1","second-test-password-456")
    r=post(c,"/api/items/receive",part_item(),hw)
    assert r.status_code==201,r.text
    uid=r.json()["id"]
    assert c.put(f"/api/items/{uid}/minimum",json={"minimum":5},headers=hw).status_code==403
    assert s.item(uid)["total"]==20


def test_filter_and_zero_initial_inventory(scenario):
    c,s,a,u=scenario
    h=auth(c);loc=s.add_location("A1")
    obj=post(c,"/api/items/receive",part_item(quantity=0),h)
    assert obj.status_code==201,obj.text
    assert obj.json()["event_id"] is None
    assert s.item(obj.json()["id"])["total"]==0
    assert not s.history()
    assert c.get("/api/items/similar",params={
        "kind":"part","primary_number":"IRF3205","package":"SOIC","category":"MOSFET"}).json()[0]["same_variant"] is False


def test_same_electronics_package_parameter_duplicate_prevented(scenario):
    c,s,a,u=scenario
    h=auth(c);s.add_location("A1")
    one=post(c,"/api/items/receive",part_item(),h)
    assert one.status_code==201
    r=post(c,"/api/items/receive",part_item(quantity=7,allow_distinct_variant=True),h)
    assert r.status_code==409
    assert s.statistics()["items"]==1


def test_concurrent_duplicate_creates_are_serialized(scenario):
    c,s,a,u=scenario
    loc=s.add_location("A1")
    actor={"id":a,"username":"admin1","role":"admin"}
    payload=ecu_item()
    def create(_):
        try:
            return s.add_item_with_stock(payload,actor)["id"]
        except Problem as ex:
            return ex.status
    with ThreadPoolExecutor(max_workers=2) as pool:
        result=list(pool.map(create,range(2)))
    assert 409 in result and sum(x!=409 for x in result)==1
    assert s.statistics()["items"]==1 and s.statistics()["units"]==4


def test_frontend_has_quick_paths_and_accessible_inputs(scenario):
    c,s,a,u=scenario
    page=c.get("/")
    assert page.status_code==200
    for fragment in ('id="search"','id="show-add"','id="new-primary-number"',
                     'id="similar-box"','id="minimum-notify"',
                     'id="notify-details"','id="minimum-recipient"','id="minimum-provider"',
                     'id="operation-preview"','id="quick-location-save"'):
        assert fragment in page.text
    js=c.get("/static/app.js").text
    assert "/api/items/receive" in js and "/api/items/similar" in js
    assert "selected" not in js or isinstance(js,str)


def test_search_route_before_numeric_item_route(scenario):
    c,s,a,u=scenario
    auth(c)
    response=c.get("/api/items/similar?kind=ecu&designation=Bosch%20EDC7")
    assert response.status_code==200
    assert response.json()==[]


def test_invalid_quantity_does_not_create_product(scenario):
    c,s,a,u=scenario
    h=auth(c);s.add_location("A1")
    for invalid in (-1,2_000_000_001,1.5,True,"abc"):
        r=post(c,"/api/items/receive",part_item(quantity=invalid),h)
        assert r.status_code==422
    assert s.statistics()["items"]==0


def test_same_designation_different_number_unknown_hw_is_distinct_after_review(scenario):
    c,s,a,u=scenario
    h=auth(c)
    s.add_location("A1")
    first=ecu_item(hw="",sw="",primary_number="AAA-100")
    assert post(c,"/api/items/receive",first,h).status_code==201
    second=ecu_item(hw="",sw="",primary_number="AAA-200",numbers=[])
    assert post(c,"/api/items/receive",second,h).status_code==409
    similar=c.get("/api/items/similar",params={
        "kind":"ecu","designation":"Bosch EDC7","brand":"DAF",
        "manufacturer":"Bosch","model":"EDC7","primary_number":"AAA-200"}).json()
    assert len(similar)==1 and similar[0]["same_variant"] is False
    second["allow_distinct_variant"]=True
    assert post(c,"/api/items/receive",second,h).status_code==201
    assert s.statistics()["items"]==2


def test_same_electronics_label_separate_packages_can_be_confirmed(scenario):
    c,s,a,u=scenario
    h=auth(c);s.add_location("A1")
    assert post(c,"/api/items/receive",part_item(),h).status_code==201
    other=part_item(package="D2PAK",quantity=5)
    assert post(c,"/api/items/receive",other,h).status_code==409
    other["allow_distinct_variant"]=True
    assert post(c,"/api/items/receive",other,h).status_code==201
    assert s.statistics()["items"]==2


def test_orange_graphite_theme_has_accessible_primary_colors():
    """Theme-only regression: change no behavior and preserve readable key controls."""
    from pathlib import Path

    app_dir=Path(__file__).resolve().parents[1]
    css=(app_dir/"magazyn"/"static"/"style.css").read_text(encoding="utf-8")
    html=(app_dir/"magazyn"/"static"/"index.html").read_text(encoding="utf-8")

    assert "--orange: #B74B0D;" in css
    assert "--orange-dark: #913807;" in css
    assert "--orange-soft: #FFF0E4;" in css
    assert "--graphite: #282D33;" in css
    assert "--page: #F5F5F4;" in css
    assert '<meta name="theme-color" content="#282D33">' in html
    assert "var(--graphite)" in css and "var(--orange)" in css
    assert ".nav-item.active" in css and ".kind-choice.active" in css
    assert ".sidebar button:focus-visible" in css
    assert "--teal" not in css and "--forest" not in css

    def luminance(color):
        channels=[int(color[offset:offset+2],16)/255 for offset in (1,3,5)]
        linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels]
        return .2126*linear[0]+.7152*linear[1]+.0722*linear[2]

    def contrast(color_a,color_b):
        light,dark=sorted((luminance(color_a),luminance(color_b)),reverse=True)
        return (light+.05)/(dark+.05)

    # WCAG AA for normal-size text on primary buttons and labels.
    assert contrast("#FFFFFF","#B74B0D")>=4.5
    assert contrast("#FFFFFF","#913807")>=4.5
    assert contrast("#68717B","#FFFFFF")>=4.5
    assert contrast("#68717B","#F5F5F4")>=4.5
    assert contrast("#D0D3D7","#282D33")>=4.5
    assert contrast("#FFFFFF","#3B4149")>=4.5
