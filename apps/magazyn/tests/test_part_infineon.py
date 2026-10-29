"""DEV regression: BTS134D is found without Mouser credentials.

All HTTP responses are mocked in CI. Additional live manufacturer retrieval
is exercised separately against the actual Infineon page on the dev server.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from magazyn import part_datasheets as ds, part_infineon as inf
from magazyn.server import create_app
from magazyn.store import Problem


def _fixture(name="BTS134D", sku="BTS134D", url="https://www.infineon.com/part/BTS134D"):
    product = {
        "@id": url+"#product",
        "@type": "ProductGroup",
        "name": name,
        "productID": sku,
        "sku": sku,
        "url": url,
        "category": "Classic HITFET™ 12V",
        "description": "N channel vertical power FET in Smart SIPMOS technology",
        "additionalProperty": [
            {"@type":"PropertyValue", "name":"VDS max", "value":"42 V"},
            {"@type":"PropertyValue", "name":"Nominal Load Current per channel", "value":"3.5 A"},
            {"@type":"PropertyValue", "name":"Ptot max", "value":"43 W"},
            {"@type":"PropertyValue", "name":"RDS (on) (@ Tj = 25°C)", "value":"45 mΩ"},
            {"@type":"PropertyValue", "name":"Operating Temperature range", "value":"-40 °C to 150 °C"},
        ],
        "hasVariant":[{
            "@type":"Product","name":"BTS134DATMA1",
            "mpn":"BTS134DATMA1",
            "additionalProperty":[
                {"@type":"PropertyValue","name":"Infineon Package","value":"PG-TO252-3"},
                {"@type":"PropertyValue","name":"Package Name","value":"DPAK"},
            ],
        }],
        "subjectOf":[{
            "@type":"DigitalDocument",
            "name":"BTS 134D Data Sheet",
            "url":"https://www.infineon.com/assets/row/public/documents/10/49/infineon-bts134d-datasheet-en.pdf",
            "encodingFormat":"pdf","description":"Datasheet",
        }],
    }
    return (
        "<!DOCTYPE html><html><head>"
        "<script type=\"application/ld+json\">  </script>"
        "<script type=\"application/ld+json\">"+
        json.dumps({"@context":"https://schema.org","@graph":[product]})+
        "</script></head><body>Manufacturer data</body></html>"
    ).encode()


def test_bts134d_official_product_fields_and_datasheet_url():
    profile = inf.parse_product(_fixture(),"BTS134D")
    assert profile["part_no"]=="BTS134D"
    assert profile["source_url"]=="https://www.infineon.com/part/BTS134D"
    assert profile["datasheet_url"].endswith("infineon-bts134d-datasheet-en.pdf")
    result = inf.inspect_product(profile)
    assert result["source_kind"]=="manufacturer_product"
    assert result["source_name"]=="Infineon — oficjalna karta produktu"
    assert result["pdf_base64"]==""
    assert result["filename"]==""
    extracted = {s["field"]:s for s in result["suggestions"]}
    assert extracted["primary_number"]["value"]=="BTS134D"
    assert extracted["manufacturer"]["value"]=="Infineon Technologies"
    assert extracted["package"]["value"]=="DPAK"
    assert extracted["spec_voltage"]["value"]=="42 V (VDS max)"
    assert extracted["spec_current"]["value"]=="3.5 A (prąd nominalny)"
    assert extracted["spec_power"]["value"]=="43 W (Ptot max)"
    assert extracted["spec_resistance"]["value"].startswith("45 mΩ")
    assert extracted["spec_temperature"]["value"]=="-40 °C to 150 °C"
    assert "spec_pin_count" not in extracted
    assert "spec_capacitance" not in extracted
    assert len(result["warnings"]) >= 1
    assert all(s["page"]==0 and s["evidence"] for s in result["suggestions"])


def test_wrong_or_near_matching_part_number_refused():
    for page in (_fixture(name="BTS134DX",sku="BTS134DX"),
                 _fixture(name="BTS3134D",sku="BTS3134D"),
                 _fixture(url="https://www.infineon.com/part/BTS3134D")):
        with pytest.raises(Problem):
            inf.parse_product(page, "BTS134D")


def test_no_lookalike_html_or_untrusted_json():
    with pytest.raises(Problem):
        inf.parse_product(b"<html>product BTS134D is great</html>","BTS134D")
    with pytest.raises(Problem):
        inf.parse_product(b"<script type=\"application/ld+json\">{}</script>","BTS134D")
    with pytest.raises(Problem):
        inf.parse_product(b"<html>denied</html>"*(200_000),"BTS134D")


def test_mismatching_maker_never_queries_infineon():
    assert inf.eligible("BTS134D","") is True
    assert inf.eligible("BTS134D","Infineon") is True
    assert inf.eligible("IRF3205","International Rectifier") is True
    assert inf.eligible("BTS134D","Texas Instruments") is False
    assert inf.eligible("LM358","") is False


def test_multiple_variant_packages_are_not_assigned():
    profile=inf.parse_product(_fixture(),"BTS134D")
    profile["variants"].append({"mpn":"BTS134DB",
                                "properties":{"Package Name":"SOIC-8"}})
    result=inf.inspect_product(profile)
    assert result["family_datasheet"] is True
    assert "package" not in [entry["field"] for entry in result["suggestions"]]


def test_authorized_webgui_user_can_fetch_exact_bts134d(monkeypatch,tmp_path):
    monkeypatch.delenv("MAGAZYN_MOUSER_API_KEY",raising=False)
    downloaded=[]
    def provider(url, *, max_bytes, accept="application/pdf"):
        downloaded.append((url,accept))
        assert url=="https://www.infineon.com/part/BTS134D"
        assert accept=="text/html"
        return _fixture()
    monkeypatch.setattr(ds,"_fetch",provider)
    app=create_app(str(tmp_path/"warehouse.sqlite3"),secure_cookie=False)
    app.state.store.create_user("employee","secure-test-password-123","user")
    with TestClient(app) as client:
        assert client.get("/api/parts/datasheet/search",
                          params={"marking":"BTS134D"}).status_code==401
        login=client.post("/api/auth/login",json={
            "username":"employee","password":"secure-test-password-123"})
        headers={"X-CSRF-Token":login.json()["csrf"]}
        found=client.get("/api/parts/datasheet/search",
                         params={"marking":"BTS134D"})
        assert found.status_code==200,found.text
        candidates=found.json()["candidates"]
        assert len(candidates)==1,candidates
        assert candidates[0]["document_kind"]=="manufacturer_product"
        token=candidates[0]["token"]
        assert client.post("/api/parts/datasheet/analyze",
                           json={"token":token}).status_code==403
        selected=client.post("/api/parts/datasheet/analyze",
                             headers=headers,json={"token":token})
        assert selected.status_code==200,selected.text
        fields=selected.json()["suggestions"]
        assert {x["field"] for x in fields} >= {
            "manufacturer","primary_number","spec_current","package"}
        assert len(downloaded)==2
        assert client.get("/api/items",params={"kind":"part"}).json()==[]
        assert client.get("/api/history").json()==[]


def test_no_api_key_no_ti_source_but_infineon_source(monkeypatch):
    monkeypatch.delenv("MAGAZYN_MOUSER_API_KEY",raising=False)
    monkeypatch.setattr(ds,"_fetch", lambda *a,**kw: _fixture())
    entries=ds.DatasheetFinder().discover(2,"BTS134D")
    assert len(entries["candidates"])==1
    assert entries["candidates"][0]["source"].startswith("Infineon")
