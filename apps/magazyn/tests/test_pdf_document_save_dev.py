"""DEV-only isolated end-to-end test of 'Add element' + PDF attachment."""
import base64
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from magazyn.server import create_app
from magazyn.store import Store
from magazyn.suppliers_dev.store import DevConfig
from test_pdf_sources_improved_dev import make_text_pdf


class PDFSaveDevTests(unittest.TestCase):
    def test_selected_pdf_is_stored_only_after_explicit_inventory_create(self):
        pdf=make_text_pdf([
            "LM358 Low-Power Operational Amplifier",
            "Document tests metadata"
        ])
        with tempfile.TemporaryDirectory(prefix="magazyn-pdf-save-") as root:
            db=str(Path(root)/"inventory.sqlite3")
            cfgroot=Path(root)/"magazyn-hurtownie-webgui-dev-20261029"
            cfgroot.mkdir()
            cfg=DevConfig(cfgroot)
            store=Store(db)
            password=secrets.token_urlsafe(23)
            store.create_user("pdfadminqa",password,"admin")
            with patch("magazyn.server.SupplierDevConfig",return_value=cfg):
                app=create_app(db,secure_cookie=False)
            with TestClient(app) as client:
                identity=client.post("/api/auth/login",json={
                    "username":"pdfadminqa","password":password})
                self.assertEqual(identity.status_code,200)
                csrf={"X-CSRF-Token":identity.json()["csrf"]}
                before=store.statistics()["items"]
                # Analysis by itself cannot create a catalog item or a file row.
                answer=client.post("/api/parts/datasheet/analyze-upload",
                    headers=csrf,json={
                        "marking":"LM358","pdf_base64":base64.b64encode(pdf).decode()})
                self.assertEqual(answer.status_code,200,answer.text[:300])
                self.assertTrue(answer.json()["document_already_selected"])
                self.assertNotIn("pdf_base64",answer.json())
                self.assertEqual(store.statistics()["items"],before)

                created=client.post("/api/items/receive",headers=csrf,json={
                    "kind":"part","designation":"LM358","primary_number":"LM358",
                    "manufacturer":"Texas Instruments","category":"Układy scalone",
                    "quantity":1,"new_location_code":"PDF-TEST-A1",
                    "product_state":"na","technical_state":"na","specs":{},
                })
                self.assertEqual(created.status_code,201,created.text[:500])
                item_id=created.json()["id"]
                self.assertTrue(item_id>0)
                self.assertEqual(store.statistics()["items"],before+1)
                docs=client.get(f"/api/items/{item_id}/documents")
                self.assertEqual(docs.status_code,200)
                self.assertFalse(docs.json())

                attached=client.post(f"/api/items/{item_id}/documents",
                    headers=csrf,json={
                        "filename":"LM358-manufacturer-datasheet.pdf",
                        "doc_type":"datasheet",
                        "content_base64":base64.b64encode(pdf).decode(),
                    })
                self.assertEqual(attached.status_code,201,attached.text[:300])
                found=client.get(f"/api/items/{item_id}/documents")
                self.assertEqual(found.status_code,200)
                self.assertEqual(len(found.json()),1)
                doc_id=attached.json()["id"]
                restored=client.get(f"/api/items/{item_id}/documents/{doc_id}")
                self.assertEqual(restored.status_code,200)
                self.assertEqual(restored.content,pdf)
                self.assertIn("application/pdf",restored.headers["content-type"])
                self.assertEqual(store.statistics()["items"],before+1)

if __name__=="__main__":
    unittest.main()
