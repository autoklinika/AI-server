"""Scanned-document regression and mismatch guard (CPU-only, DEV).

Generated synthetic datasheets contain no real customer or manufacturer data.
"""
import base64
import tempfile
import secrets
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from magazyn.part_datasheets import _pdf_text, DatasheetFinder, inspect_pdf
from magazyn.part_pdf_ocr import available
from magazyn.store import Problem, Store
from magazyn.server import create_app
from magazyn.suppliers_dev.store import DevConfig

HERE=Path(__file__).resolve().parent/"fixtures"


class ScannedPDFTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(available(),"Portable local CPU Tesseract is required for this host")
        self.lm358=(HERE/"ocr-scanned-LM358.pdf").read_bytes()
        self.lm2309=(HERE/"ocr-scanned-LM2309.pdf").read_bytes()

    def test_image_only_pdf_uses_local_ocr_without_inventing_specs(self):
        pages=_pdf_text(self.lm358)
        self.assertEqual(pages.ocr_pages,(1,))
        self.assertIn("LM358",pages[0])
        result=DatasheetFinder().analyze_upload(
            "LM358",base64.b64encode(self.lm358).decode())
        self.assertEqual(result["part_number"],"LM358")
        self.assertEqual(result["extraction_mode"],"ocr")
        self.assertEqual(result["ocr_pages"],[1])
        self.assertNotIn("pdf_base64",result)
        self.assertTrue(result["document_already_selected"])
        self.assertTrue(result["manual_approval_required"])
        proposals={r["field"]:r for r in result["suggestions"]}
        self.assertEqual(proposals["primary_number"]["value"],"LM358")
        self.assertEqual(proposals["package"]["value"],"SOIC-8")
        self.assertEqual(proposals["spec_temperature"]["value"],"-40 to +85 C")
        self.assertTrue(all(r["confidence"]=="verify_variant"
                            for r in result["suggestions"]))
        self.assertTrue(any("OCR" in w for w in result["warnings"]))

    def test_ocr_recognized_but_mpn_differs_is_not_unreadable(self):
        result=DatasheetFinder().analyze_upload(
            "LM2309Y",base64.b64encode(self.lm2309).decode())
        self.assertEqual(result["status"],"needs_identification")
        self.assertTrue(result["pdf_readable"])
        self.assertEqual(result["candidate_numbers"],["LM2309"])
        self.assertEqual(result["extraction_mode"],"ocr")
        self.assertEqual(result["suggestions"],[])
        self.assertNotIn("pdf_base64",result)
        self.assertTrue(result["document_already_selected"])
        with self.assertRaises(Problem):
            inspect_pdf(self.lm2309,"LM2309Y")  # Link remains strict.

    def test_scanned_upload_is_read_only_and_session_protected(self):
        with tempfile.TemporaryDirectory(prefix="warehouse-ocr-dev-") as tmp:
            sdir=Path(tmp)/"magazyn-hurtownie-webgui-dev-20261029"
            sdir.mkdir()
            cfg=DevConfig(sdir)
            db=Path(tmp)/"warehouse.sqlite3"
            store=Store(str(db))
            pw=secrets.token_urlsafe(25)
            store.create_user("pdfocrworker",pw,"user")
            with patch("magazyn.server.SupplierDevConfig",return_value=cfg):
                app=create_app(str(db),secure_cookie=False)
            with TestClient(app) as client:
                body={"marking":"LM358",
                      "pdf_base64":base64.b64encode(self.lm358).decode()}
                self.assertEqual(client.post(
                    "/api/parts/datasheet/analyze-upload",
                    json=body).status_code,401)
                login=client.post("/api/auth/login",json={
                    "username":"pdfocrworker","password":pw})
                self.assertEqual(login.status_code,200)
                self.assertEqual(client.post(
                    "/api/parts/datasheet/analyze-upload",
                    json=body).status_code,403)
                before=store.statistics()["items"]
                resp=client.post("/api/parts/datasheet/analyze-upload",
                    json=body,headers={"X-CSRF-Token":login.json()["csrf"]})
                self.assertEqual(resp.status_code,200,resp.text[:200])
                self.assertEqual(resp.json()["extraction_mode"],"ocr")
                self.assertEqual(store.statistics()["items"],before)


if __name__=="__main__":
    unittest.main(verbosity=2)
