"""Isolated Mouser adapter tests; no remote network, no real credentials."""
import tempfile
import unittest
from pathlib import Path

from magazyn.suppliers_dev.store import DevConfig
from magazyn.suppliers_dev.providers import SupplierEngine
from magazyn.suppliers_dev.mouser_enrich import (
    exact_parts, enrich_mouser, proposed_fields, product_attributes,
    verified_https_url,
)

BTS = {
    "ManufacturerPartNumber": "BTS134D",
    "MouserPartNumber": "726-BTS134D",
    "Manufacturer": "Infineon Technologies",
    "Category": "Układy scalone do przełączników zasilania",
    "Description": "SMART LOW SIDE POWER 42V 3.5A",
    "Availability": "Na stanie",
    "DataSheetUrl": "https://www.mouser.com/datasheet/2/196/BTS134D.pdf",
    "ProductDetailUrl": "https://www.mouser.pl/ProductDetail/Infineon/BTS134D",
    "ProductAttributes": [
        {"AttributeName": "Opakowanie", "AttributeValue": "Reel"},
        {"AttributeName": "Opakowanie", "AttributeValue": "Cut Tape"},
    ],
}
VARIANT = dict(BTS, ManufacturerPartNumber="BTS134DATMA1", MouserPartNumber="999-VARIANT")
RESPONSE = {"SearchResults": {"Parts": [BTS, VARIANT]}, "Errors": []}


class FakeTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("json_data")))
        return self.response


class MouserDevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "magazyn-hurtownie-webgui-dev-20261029"
        root.mkdir()
        self.store = DevConfig(root)
        self.store.save("mouser", enabled=True,
                        credentials={"api_key": "MOCK_ONLY_DO_NOT_USE"})
        self.transport = FakeTransport(RESPONSE)
        self.engine = SupplierEngine(
            self.store, live_allowed=True,
            live_providers={"tme", "mouser"}, transport=self.transport)

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_variant_only_and_pdf_link(self):
        reply = enrich_mouser(self.engine, "BTS134D")
        self.assertEqual(reply["status"], "ok")
        self.assertEqual(reply["mpn"], "BTS134D")
        self.assertEqual(reply["supplier_symbol"], "726-BTS134D")
        self.assertEqual(reply["manufacturer"], "Infineon Technologies")
        self.assertEqual(reply["availability"], "Na stanie")
        self.assertTrue(reply["manual_approval_required"])
        self.assertEqual(len(reply["documents"]), 1)
        self.assertEqual(reply["documents"][0]["type"], "DTE")
        self.assertTrue(reply["documents"][0]["url"].startswith("https://www.mouser.com/"))
        fields = {x["field"]: x["value"] for x in reply["suggestions"]}
        self.assertEqual(fields["designation"], "BTS134D")
        self.assertEqual(fields["primary_number"], "BTS134D")
        self.assertEqual(fields["manufacturer"], "Infineon Technologies")
        self.assertEqual(fields["category"], "Układy scalone")
        self.assertIn("SMART LOW SIDE", fields["parameters"])
        # Mouser provides only packaging attrs; don't invent electrical specs
        for field in ("spec_voltage", "spec_current", "spec_resistance", "package"):
            self.assertNotIn(field, fields)
        self.assertNotIn("MOCK_ONLY_DO_NOT_USE", str(reply))
        self.assertEqual(len(self.transport.calls), 1)

    def test_query_uses_only_search_api_and_mpn(self):
        enrich_mouser(self.engine, "BTS134D")
        method, url, body = self.transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("/api/v1/search/partnumber", url)
        self.assertEqual(body["SearchByPartRequest"]["mouserPartNumber"], "BTS134D")

    def test_ambiguous_identical_part_number_does_not_autofill(self):
        self.transport.response = {"SearchResults": {"Parts": [BTS, BTS]}}
        result = enrich_mouser(self.engine, "BTS134D")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["suggestions"], [])

    def test_no_exact_match_rejects_suffix(self):
        self.transport.response = {"SearchResults": {"Parts": [VARIANT]}}
        result = enrich_mouser(self.engine, "BTS134D")
        self.assertEqual(result["status"], "not_found")
        self.assertFalse(result["suggestions"])

    def test_offline_and_disabled_never_call_api(self):
        self.store.save("mouser", enabled=False)
        self.assertEqual(enrich_mouser(self.engine, "BTS134D")["status"], "disabled")
        self.store.save("mouser", enabled=True)
        block = SupplierEngine(self.store,live_allowed=True,live_providers={"tme"},
                               transport=self.transport)
        self.assertEqual(enrich_mouser(block, "BTS134D")["status"], "offline_dev")
        self.assertEqual(self.transport.calls, [])

    def test_untrusted_links_are_blocked(self):
        for url in ("http://www.mouser.com/a.pdf",
                    "https://localhost/file.pdf",
                    "https://192.0.2.1/a.pdf",
                    "https://evil@example.com/a.pdf",
                    "javascript:alert(1)",
                    "//www.mouser.com/a.pdf",
                    "https://www.mouser.com:8080/a.pdf"):
            self.assertEqual(verified_https_url(url), "", url)

    def test_conflicting_attributes_not_chosen(self):
        modified = dict(BTS, ProductAttributes=[
            {"AttributeName": "Package", "AttributeValue": "TO252"},
            {"AttributeName": "Package", "AttributeValue": "SOIC"}])
        fields={row["field"]:row["value"] for row in proposed_fields(
            "BTS134D",modified,product_attributes(modified))}
        self.assertNotIn("package",fields)

    def test_provider_errors_do_not_propose_data(self):
        with self.assertRaises(ValueError):
            exact_parts({"Errors": [{"Code": "InvalidKey"}]}, "BTS134D")
        with self.assertRaises(ValueError):
            exact_parts({"SearchResults": {"Parts": "INVALID"}}, "BTS134D")
        with self.assertRaises(ValueError):
            enrich_mouser(self.engine, "../bad/mpn")

if __name__ == "__main__":
    unittest.main(verbosity=2)
