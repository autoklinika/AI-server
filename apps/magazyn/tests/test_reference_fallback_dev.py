"""DEV manufacturer-reference fallback; no real API traffic or inventory writes."""
import base64
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from magazyn.part_reference_fallback import lookup_manufacturer_references
from magazyn.part_datasheets import DatasheetFinder, inspect_pdf
from magazyn.server import create_app
from magazyn.store import Store,Problem

OFFICIAL_TEXT=("The mosfet LM2309 SOT-23 of Leiditech electronic MOSFET "
               "can replace SQ2309ES-T1-GE3.")

class ManufacturerReferenceTests(unittest.TestCase):
    def test_lm2309y_unverified_candidate_never_autofills_electrical_specs(self):
        with patch("magazyn.part_reference_fallback._content",
                   return_value=OFFICIAL_TEXT) as fetch:
            result=lookup_manufacturer_references("LM2309Y")
        self.assertEqual(result["status"],"possible_reference")
        self.assertTrue(result["manual_approval_required"])
        self.assertEqual(len(result["candidates"]),1)
        candidate=result["candidates"][0]
        self.assertEqual(candidate["requested_mpn"],"LM2309Y")
        self.assertEqual(candidate["reference_mpn"],"LM2309")
        self.assertFalse(candidate["exact_mpn"])
        self.assertTrue(candidate["family_datasheet"])
        values={s["field"]:s for s in candidate["suggestions"]}
        self.assertEqual(values["manufacturer"]["value"],"Leiditech")
        self.assertEqual(values["category"]["value"],"Tranzystory i MOSFET-y")
        self.assertEqual(values["package"]["value"],"SOT-23")
        self.assertEqual(set(values),{"manufacturer","category","package"})
        self.assertTrue(all(x["confidence"]=="verify_variant" for x in values.values()))
        self.assertTrue(all(x["evidence"]=="mosfet LM2309 SOT-23" for x in values.values()))
        self.assertNotIn("primary_number",values)
        self.assertNotIn("designation",values)
        self.assertNotIn("spec_voltage",values)
        self.assertFalse(candidate["documents"])
        self.assertTrue(candidate["warnings"])
        fetch.assert_called_once()

    def test_exact_reference_is_eligible_for_reviewed_suggestions(self):
        with patch("magazyn.part_reference_fallback._content",
                   return_value=OFFICIAL_TEXT):
            result=lookup_manufacturer_references("LM2309")
        self.assertEqual(result["status"],"verified_reference")
        ref=result["candidates"][0]
        self.assertTrue(ref["exact_mpn"])
        self.assertFalse(ref["family_datasheet"])
        self.assertTrue(all(x["confidence"]=="document" for x in ref["suggestions"]))

    def test_non_matching_reference_returns_no_false_positive(self):
        for marking in ("LM2309YY","LMP2309Y","IRF3205","BTS134D"):
            with patch("magazyn.part_reference_fallback._content") as read:
                result=lookup_manufacturer_references(marking)
            self.assertEqual(result["status"],"not_found",marking)
            read.assert_not_called()
        with patch("magazyn.part_reference_fallback._content",
                   return_value="The mosfet LM2309A SOT-23"):
            self.assertEqual(lookup_manufacturer_references("LM2309Y")["status"],"not_found")

    def test_user_link_blocks_private_hosts_and_bad_docs(self):
        finder=DatasheetFinder()
        for url in ("http://www.leiditech.com/file.pdf",
                    "https://localhost/test.pdf",
                    "https://192.0.2.1/file.pdf",
                    "https://evil.example/file.pdf",
                    "https://www.leiditech.com.evil.example/file.pdf",
                    "https://www.mouser.com/foo.pdf",
                    "https://user:pass@www.leiditech.com/file.pdf"):
            with self.assertRaises(Problem,msg=url):
                finder.analyze_url("LM2309Y",url)
        with patch("magazyn.part_datasheets._fetch",
                   return_value=b"<html>not a PDF</html>"):
            with self.assertRaises(Problem):
                finder.analyze_url("LM2309Y","https://www.leiditech.com/notapdf")

    def test_document_must_include_exact_mpn_even_if_related(self):
        payload=b"%PDF-"+b"x"*140+b"%%EOF"
        with patch("magazyn.part_datasheets._pdf_text",
                   return_value=["Leiditech LM2309 P-channel SOT-23"]):
            with self.assertRaises(Problem) as error:
                inspect_pdf(payload,"LM2309Y")
            self.assertEqual(error.exception.status,422)
        with patch("magazyn.part_datasheets._pdf_text",
                   return_value=["Leiditech LM2309 P-channel SOT-23"]):
            result=inspect_pdf(payload,"LM2309")
            self.assertEqual(result["part_number"],"LM2309")

    def test_accepted_pdf_from_manufacturer_gets_domain_bound_identity(self):
        pdf=b"%PDF-"+b"x"*140+b"%%EOF"
        fake={"part_number":"LM2309Y","suggestions":[],
              "pdf_base64":base64.b64encode(pdf).decode()}
        finder=DatasheetFinder()
        with patch("magazyn.part_pdf_fetch.fetch_pdf",return_value=pdf) as fetch:
            with patch("magazyn.part_datasheets.inspect_pdf",return_value=fake) as parse:
                result=finder.analyze_url("LM2309Y","https://www.leiditech.com/file.pdf")
        self.assertEqual(result["source_kind"],"manufacturer_pdf")
        self.assertTrue(result["manual_approval_required"])
        self.assertEqual(parse.call_args.kwargs["manufacturer"],"Leiditech")
        self.assertEqual(parse.call_args.kwargs["source_url"],
                         "https://www.leiditech.com/file.pdf")
        fetch.assert_called_once()

    def test_ti_prefix_never_creates_fake_manufacturer_datasheet(self):
        # Previously any LM... code was treated as a TI datasheet candidate.
        finder=DatasheetFinder()
        with patch.object(finder,"_ti_pdf_available",return_value=False):
            result=finder.discover(42,"LM2309Y")
        self.assertEqual(result["candidates"],[])
        with patch.object(finder,"_ti_pdf_available",return_value=True):
            result=finder.discover(42,"LM358")
        self.assertEqual(len(result["candidates"]),1)
        self.assertEqual(result["candidates"][0]["source"],"Texas Instruments")

    def test_worker_api_auth_csrf_and_readonly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"magazyn-hurtownie-webgui-dev-20261029"
            root.mkdir()
            from magazyn.suppliers_dev.store import DevConfig
            cfg=DevConfig(root)
            path=str(Path(tmp)/"warehouse.sqlite3")
            store=Store(path)
            password=secrets.token_urlsafe(24)
            store.create_user("referenceemployee",password,"user")
            with patch("magazyn.server.SupplierDevConfig",return_value=cfg):
                app=create_app(path,secure_cookie=False)
            with TestClient(app) as client:
                def invoke(url,json_body,headers=None):
                    return client.post(url,json=json_body,headers=headers or {})
                self.assertEqual(invoke("/api/parts/reference/fallback",
                    {"query":"LM2309Y"}).status_code,401)
                auth=client.post("/api/auth/login",json={
                    "username":"referenceemployee","password":password})
                self.assertEqual(auth.status_code,200)
                self.assertEqual(invoke("/api/parts/reference/fallback",
                    {"query":"LM2309Y"}).status_code,403)
                csrf={"X-CSRF-Token":auth.json()["csrf"]}
                before=store.statistics()["items"]
                with patch("magazyn.part_reference_fallback._content",
                           return_value=OFFICIAL_TEXT):
                    response=invoke("/api/parts/reference/fallback",
                                    {"query":"LM2309Y"},csrf)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()["status"],"possible_reference")
                self.assertEqual(store.statistics()["items"],before)
                with patch.object(app.state.datasheet_finder,"analyze_url",
                           return_value={"part_number":"LM2309Y","suggestions":[]}):
                    response=invoke("/api/parts/datasheet/analyze-link",{
                        "marking":"LM2309Y",
                        "pdf_url":"https://www.leiditech.com/file.pdf"},csrf)
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(store.statistics()["items"],before)

if __name__=="__main__":unittest.main()
