"""First-location creation is atomic with product receipt (synthetic SQLite only)."""
from test_magazyn import scenario, auth, post, ecu
from magazyn.store import Problem


def test_admin_creates_first_location_and_receives_electronics_atomically(scenario):
    client, store, admin, worker = scenario
    headers = auth(client)
    assert store.locations() == []
    response = post(client, "/api/items/receive", {
        "kind":"part", "designation":"TEST-INSTRUMENT",
        "manufacturer":"Synthetic", "category":"Testowe",
        "primary_number":"TST-NEW-001", "quantity":7,
        "specs":{"voltage":"3.3 V"},
        "new_location_code":"  REGAŁ-1  ",
        "new_location_description":" Szuflada testowa ",
    }, headers)
    assert response.status_code==201, response.text
    item=store.item(response.json()["id"])
    assert item["total"]==7
    assert item["specs"]["voltage"]=="3.3 V"
    assert len(store.locations())==1
    assert store.locations()[0]["code"]=="REGAŁ-1"
    assert store.locations()[0]["description"]=="Szuflada testowa"
    assert item["balances"][0]["location"]=="REGAŁ-1"
    assert len(store.history())==1
    assert store.history()[0]["action"]=="receive"


def test_admin_creates_first_location_with_ecu(scenario):
    client,store,admin,worker=scenario
    headers=auth(client)
    result=post(client,"/api/items/receive",{
        **ecu(),"quantity":2,"new_location_code":"A1",
        "new_location_description":"Pierwsza lokalizacja",
    },headers)
    assert result.status_code==201,result.text
    assert store.item(result.json()["id"])["total"]==2
    assert store.locations()[0]["code"]=="A1"
    assert len(store.history())==1


def test_non_admin_cannot_create_location_through_receipt(scenario):
    client,store,admin,worker=scenario
    headers=auth(client,"worker1","second-test-password-456")
    result=post(client,"/api/items/receive",{
        "kind":"part","designation":"SHOULD NOT BE CREATED",
        "category":"Testowe","quantity":5,"new_location_code":"HACK",
    },headers)
    assert result.status_code==403,result.text
    assert store.statistics()["items"]==0
    assert store.locations()==[]


def test_validation_error_rolls_back_new_location(scenario):
    client,store,admin,worker=scenario
    headers=auth(client)
    result=post(client,"/api/items/receive",{
        "kind":"ecu","designation":"Missing brand",
        "quantity":3,"new_location_code":"TEMP-A",
    },headers)
    assert result.status_code==422,result.text
    assert store.locations()==[]
    assert store.statistics()["items"]==0
    assert store.history()==[]


def test_existing_location_cannot_be_combined_with_new_code(scenario):
    client,store,admin,worker=scenario
    headers=auth(client)
    loc=store.add_location("A1")
    result=post(client,"/api/items/receive",{
        "kind":"part","designation":"Mixed",
        "category":"Testowe","quantity":1,
        "location_id":loc,"new_location_code":"B1",
    },headers)
    assert result.status_code==422,result.text
    assert len(store.locations())==1
    assert store.statistics()["items"]==0


def test_empty_code_is_explained_instead_of_creating_item(scenario):
    client,store,admin,worker=scenario
    headers=auth(client)
    result=post(client,"/api/items/receive",{
        "kind":"part","designation":"No location",
        "category":"Testowe","quantity":1,
    },headers)
    assert result.status_code==422
    assert "lokalizację" in result.text.lower()
    assert store.locations()==[]


def test_first_location_duplicate_and_concurrent_existing_data_is_safe(scenario):
    client,store,admin,worker=scenario
    headers=auth(client)
    store.add_location("A1")
    result=post(client,"/api/items/receive",{
        "kind":"part","designation":"New entry","category":"Test",
        "quantity":2,"new_location_code":"a1",
    },headers)
    assert result.status_code==409,result.text
    assert store.statistics()["items"]==0
    assert len(store.locations())==1


def test_create_product_with_existing_location_still_works(scenario):
    client,store,admin,worker=scenario
    headers=auth(client,"worker1","second-test-password-456")
    loc=store.add_location("X1")
    result=post(client,"/api/items/receive",{
        "kind":"part","designation":"REGULAR PART",
        "category":"Elektronika","quantity":9,"location_id":loc,
    },headers)
    assert result.status_code==201,result.text
    assert store.item(result.json()["id"])["total"]==9
    assert len(store.locations())==1


def test_form_displays_required_first_location_inputs(scenario):
    client,*_=scenario
    html=client.get("/").text
    assert 'id="part-first-location-help"' in html
    assert 'id="ecu-first-location-help"' in html
    for key in ("part-location-code","quick-location-code",
                "part-submit","item-submit"):
        assert f'id="{key}"' in html
    js=client.get("/static/electronics.js").text
    assert "new_location_code" in js
    assert 'byId("part-location").required=!firstLocation' in js
    assert 'byId("part-submit").disabled=false' in js
    assert "await loadLocations()" in js
    main=client.get("/static/app.js").text
    assert "new_location_code" in main
    assert 'byId("new-location").required=!firstLocation' in main
