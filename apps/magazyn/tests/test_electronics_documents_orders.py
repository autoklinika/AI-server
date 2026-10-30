"""Electronics-specific fields, authenticated technical documents and order status.

All tests use synthetic SQLite; no real inventory, YubiKey, Telegram or NAS writes.
"""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from magazyn import backup
from magazyn.store import Store
from test_magazyn import scenario, auth, post, ecu, operation


PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0"*40


def sample_part(**extras):
    values = {
        "kind":"part","designation":"IRF3205 TEST","primary_number":"IRF3205TEST",
        "category":"Tranzystory i MOSFET-y","manufacturer":"Infineon",
        "package":"TO-220","parameters":"RDS 8 mOhm",
        "specs":{"voltage":"55 V","current":"110 A","power":"80 W",
                 "resistance":"8 mΩ","interface":"N-MOSFET"},
        "location_id":1,"quantity":3,"notes":"Tylko syntetyczny test",
    }
    values.update(extras)
    return values


def create_part(client, headers, **changes):
    result=post(client,"/api/items/receive",sample_part(**changes),headers)
    assert result.status_code == 201, result.text
    return result.json()["id"]


def doc_payload(filename="datasheet.pdf", doc_type="datasheet", data=PDF):
    return {"filename":filename,"doc_type":doc_type,
            "content_base64":base64.b64encode(data).decode("ascii")}


def test_electronic_fields_search_edit_and_separation_from_ecu(scenario):
    c,s,admin,worker=scenario
    heads=auth(c)
    s.add_location("A1")
    item=create_part(c,heads)
    record=c.get(f"/api/items/{item}").json()
    assert record["kind"]=="part"
    assert record["specs"]["voltage"]=="55 V"
    assert record["specs"]["resistance"]=="8 mΩ"
    assert record["package"]=="TO-220"
    assert record["total"]==3
    assert record["balances"][0]["product_state"]=="na"
    assert c.get("/api/items",params={"q":"110A"}).json()[0]["id"]==item
    assert c.get("/api/items",params={"q":"N-MOSFET"}).json()[0]["id"]==item
    similar=c.get("/api/items/similar",params={
        "kind":"part","primary_number":"IRF3205TEST","category":"Tranzystory i MOSFET-y",
        "package":"TO-220","parameters":"RDS 8 mOhm",
        "specs_json":json.dumps(sample_part()["specs"]),
    })
    assert similar.status_code==200 and similar.json()[0]["same_variant"]
    diff=c.get("/api/items/similar",params={
        "kind":"part","primary_number":"IRF3205TEST","category":"Tranzystory i MOSFET-y",
        "package":"TO-220","parameters":"RDS 8 mOhm",
        "specs_json":json.dumps({"voltage":"24 V"}),
    })
    assert diff.status_code==200 and not diff.json()[0]["same_variant"]

    worker_h=auth(c,"worker1","second-test-password-456")
    assert c.patch(f"/api/items/{item}",json={"specs":{"voltage":"12 V"}},headers=worker_h).status_code==403
    heads=auth(c)
    edit=c.patch(f"/api/items/{item}",json={"specs":{"voltage":"60 V","power":"100 W"},
                                            "package":"D2PAK"},headers=heads)
    assert edit.status_code==200,edit.text
    updated=c.get(f"/api/items/{item}").json()
    assert updated["specs"]["voltage"]=="60 V"
    assert updated["package"]=="D2PAK"
    assert updated["total"]==3
    assert len(c.get("/api/history").json())==1
    before=s.statistics()["units"]
    ecu_item=s.add_item(ecu(),{"id":admin,"username":"admin1","role":"admin"})
    assert c.patch(f"/api/items/{ecu_item}",json={"specs":{"voltage":"100 V"}},headers=heads).status_code==422
    assert c.get(f"/api/items/{ecu_item}").json().get("specs") is None
    assert c.post("/api/items",json={"kind":"ecu","brand":"MAN","designation":"ECU2",
                  "specs":{"current":"1A"}},headers=heads).status_code==422
    assert s.statistics()["units"]==before


def test_docs_auth_upload_download_reject_invalid_and_delete(scenario):
    c,s,admin,worker=scenario
    heads=auth(c);s.add_location("A1")
    item=create_part(c,heads)
    endpoint=f"/api/items/{item}/documents"
    assert c.get("/api/items/99999/documents").status_code==404
    assert c.post(endpoint,json=doc_payload()).status_code==403
    saved=c.post(endpoint,json=doc_payload(),headers=heads)
    assert saved.status_code==201,saved.text
    number=saved.json()["id"]
    docs=c.get(endpoint).json()
    assert len(docs)==1 and docs[0]["filename"]=="datasheet.pdf"
    assert "content" not in docs[0]
    assert docs[0]["bytes"]==len(PDF)
    assert "sha256" in docs[0]
    dl=c.get(endpoint+f"/{number}")
    assert dl.status_code==200 and dl.content==PDF
    assert dl.headers["content-type"].startswith("application/pdf")
    assert "attachment" in dl.headers["content-disposition"].lower()
    assert dl.headers["x-content-type-options"]=="nosniff"
    assert c.post(endpoint,json=doc_payload(),headers=heads).status_code==409
    assert c.post(endpoint,json=doc_payload("../../../secret.pdf"),headers=heads).status_code==422
    assert c.post(endpoint,json=doc_payload("not-pdf.pdf",data=b"<html>malware</html>"),headers=heads).status_code==422
    assert c.post(endpoint,json=doc_payload("tool.svg"),headers=heads).status_code==422
    assert c.post(endpoint,json={**doc_payload(),"content_base64":"NOT VALID @@"},headers=heads).status_code==422
    assert c.post(endpoint,json=doc_payload("diagram.png","schematic",PNG),headers=heads).status_code==201
    assert c.get(f"/api/items/{item}").json()["documents"]
    worker_h=auth(c,"worker1","second-test-password-456")
    assert c.get(endpoint+f"/{number}").status_code==200
    assert c.delete(endpoint+f"/{number}",headers=worker_h).status_code==403
    assert c.post(endpoint,json=doc_payload("worker.pdf"),headers=worker_h).status_code==201
    heads=auth(c)
    assert c.delete(endpoint+f"/{number}",headers=heads).status_code==200
    assert c.get(endpoint+f"/{number}").status_code==404


def test_docs_are_part_of_encrypted_sqlite_backup_and_restored(tmp_path,scenario):
    c,s,admin,worker=scenario
    h=auth(c);s.add_location("A1")
    item=create_part(c,h)
    added=c.post(f"/api/items/{item}/documents",
                 json=doc_payload("layout.pdf","schematic"),headers=h)
    assert added.status_code==201,added.text
    c.put(f"/api/items/{item}/order-status",json={
        "status":"ordered","quantity":7,"note":"Syntetyczne zamówienie"},headers=h)
    key=backup.init_key(tmp_path/"private-key"/"aes.key")
    spool=tmp_path/"spool"
    archives=backup.create_local(s.path,spool,key)
    enc=Path(archives[0]).read_bytes()
    assert PDF not in enc and b"Syntetyczne zam" not in enc
    restored_path=tmp_path/"restored"/"magazyn.sqlite3"
    assert backup.restore_archive(archives[0],restored_path,key)["status"]=="PASS"
    recovered=Store(str(restored_path))
    assert recovered.read_document(item,added.json()["id"])["content"]==PDF
    assert recovered.item(item)["specs"]["voltage"]=="55 V"
    assert recovered.get_order_status(item)["quantity"]==7
    assert recovered.item(item)["total"]==3


def test_ordered_status_and_reorder_list_do_not_change_stock(scenario):
    c,s,admin,worker=scenario
    h=auth(c);s.add_location("A1")
    item=create_part(c,h,quantity=2)
    assert c.put(f"/api/items/{item}/minimum",
                 json={"minimum":5},headers=h).status_code==200
    before=s.item(item)["total"]
    events=len(s.history())
    rows=c.get("/api/low-stock").json()
    assert rows[0]["order_status"]=="none"
    assert rows[0]["ordered_quantity"]==0
    assert c.put(f"/api/items/{item}/order-status",json={"status":"ordered","quantity":0},
                 headers=h).status_code==422
    assert c.put(f"/api/items/{item}/order-status",json={"status":"ordered","quantity":8,
                 "note":"zamówienie do dostawcy"},headers=h).status_code==200
    rows=c.get("/api/low-stock").json()
    assert rows[0]["order_status"]=="ordered" and rows[0]["ordered_quantity"]==8
    assert c.get(f"/api/items/{item}/order-status").json()["note"]=="zamówienie do dostawcy"
    assert s.item(item)["total"]==before
    assert len(s.history())==events
    hw=auth(c,"worker1","second-test-password-456")
    assert c.put(f"/api/items/{item}/order-status",json={"status":"none","quantity":0},
                 headers=hw).status_code==403
    assert c.get(f"/api/items/{item}/order-status").status_code==200
    h=auth(c)
    assert c.put(f"/api/items/{item}/order-status",json={"status":"none","quantity":0},
                 headers=h).status_code==200
    assert c.get("/api/low-stock").json()[0]["order_status"]=="none"


def test_additive_v2_migration_retains_rows_and_document_cascade(tmp_path,scenario):
    c,s,admin,worker=scenario
    h=auth(c);s.add_location("A1")
    item=create_part(c,h)
    document=c.post(f"/api/items/{item}/documents",
                    json=doc_payload(),headers=h).json()
    with s.connect(write=True) as con:
        con.execute("PRAGMA user_version=2")
    reused=Store(s.path)
    with reused.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0]==3
        assert con.execute("PRAGMA foreign_key_check").fetchall()==[]
        assert con.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    assert reused.item(item)["total"]==3
    assert reused.read_document(item,document["id"])["content"]==PDF
    assert c.delete(f"/api/items/{item}",headers=h).status_code==200
    with reused.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM item_documents WHERE item_id=?",(item,)).fetchone()[0]==0
        assert con.execute("SELECT COUNT(*) FROM electronic_specs WHERE item_id=?",(item,)).fetchone()[0]==0


def test_document_max_count_enforced_and_html_ui_separate(scenario):
    c,s,admin,worker=scenario
    h=auth(c);s.add_location("A1")
    item=create_part(c,h)
    for n in range(6):
        result=c.post(f"/api/items/{item}/documents",
                      json=doc_payload(f"datasheet-{n}.pdf"),headers=h)
        assert result.status_code==201,result.text
    assert c.post(f"/api/items/{item}/documents",
                  json=doc_payload("seventh.pdf"),headers=h).status_code==409
    page=c.get("/").text
    assert 'id="part-dialog"' in page
    assert 'id="item-dialog"' in page
    assert 'id="part-edit-form"' in page
    assert 'id="part-doc-upload"' in page
    assert 'id="order-status-form"' in page
    assert 'id="show-add-part"' in page
    assert '/static/electronics.js' in page
    script=c.get("/static/electronics.js").text
    assert "sendElectronicDocument" in script
    assert '"ordered"' in script and "spec_voltage" in page


def test_migrates_actual_v2_table_layout_without_touching_quantities(tmp_path):
    from magazyn.store import SCHEMA
    db=tmp_path/"legacy_v2.sqlite3"
    prior_schema=SCHEMA.split("CREATE TABLE IF NOT EXISTS electronic_specs",1)[0]
    assert "PRAGMA user_version=3" not in prior_schema
    con=sqlite3.connect(db)
    try:
        con.executescript(prior_schema+"PRAGMA user_version=2;")
        con.execute("INSERT INTO items(kind,designation,primary_number,created_at,updated_at) "
                    "VALUES('part','LEGACY-IC','LEGACY123','2026-10-01','2026-10-01')")
        con.execute("INSERT INTO locations(code) VALUES('LEGACY-A1')")
        con.execute("INSERT INTO balances(item_id,location_id,product_state,technical_state,quantity) "
                    "VALUES(1,1,'na','na',17)")
        con.commit()
        assert con.execute("PRAGMA user_version").fetchone()[0]==2
        assert con.execute("SELECT name FROM sqlite_master WHERE name='item_documents'").fetchone() is None
    finally:
        con.close()
    updated=Store(str(db))
    assert updated.item(1)["total"]==17
    assert updated.item(1)["specs"]["voltage"]==""
    assert updated.item(1)["documents"]==[]
    assert updated.get_order_status(1)["status"]=="none"
    with updated.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0]==3
        assert con.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall()==[]


def test_document_upload_streamed_limit_is_enforced_and_ecu_docs_are_rejected(scenario):
    c,s,admin,worker=scenario
    h=auth(c)
    s.add_location("A1")
    item=create_part(c,h)
    ecu_id=s.add_item(ecu(),{"id":admin,"username":"admin1","role":"admin"})
    wrong=c.post(f"/api/items/{ecu_id}/documents",
                 json=doc_payload(),headers=h)
    assert wrong.status_code==422
    assert not s.list_documents(item)
    excessive=b'{"filename":"large.pdf","doc_type":"datasheet","content_base64":"'+(
        b"A"*(12*1024*1024))+b'"}'
    rejected=c.post(f"/api/items/{item}/documents",content=excessive,
                    headers={**h,"Content-Type":"application/json"})
    assert rejected.status_code==413,rejected.text[:100]
    assert s.list_documents(item)==[]
