"""TME enrichment contract tests: isolated fixtures, no real API, no production."""
import tempfile
import unittest
from pathlib import Path

from magazyn.suppliers_dev.store import DevConfig
from magazyn.suppliers_dev.providers import SupplierEngine
from magazyn.suppliers_dev.tme_enrich import (
    enrich_tme, document_link, suggestions_for_product, match_symbol,
    technical_parameters, technical_documents, response_elements
)


PRODUCT = {
    "symbol": "BTS134D",
    "manufacturer_symbols": ["BTS134D"],
    "manufacturer": {"id": 47, "name": "INFINEON TECHNOLOGIES"},
    "category": {"name": "Power switches - układy scalone"},
    "description": "IC: power switch; low-side; 3,5A; SMD; TO252-3",
}
PARAMETERS = [
    ("Producent", "INFINEON TECHNOLOGIES"),
    ("Typ układu scalonego", "power switch"),
    ("Rodzaj układu scalonego", "low-side"),
    ("Prąd wyjściowy", "3,5A"),
    ("Liczba kanałów", "1"),
    ("Rodzaj wyjścia", "N-Channel"),
    ("Montaż", "SMD"),
    ("Obudowa", "TO252-3"),
    ("Rezystancja w stanie przewodzenia", "35mΩ"),
    ("Technologia", "HITFET®"),
    ("Napięcie wyjściowe", "42V"),
]
PARAM_RESPONSE = {"status": "OK", "data": {"elements": [{
    "symbol": "BTS134D", "parameters": {"elements": [
        {"id": i, "name": n, "values": [{"id": i, "value": v}]}
        for i, (n, v) in enumerate(PARAMETERS)
    ]}
}]}}
DOC_RESPONSE = {"status": "OK", "data": {"elements": [{
    "symbol": "BTS134D", "documents": {"elements": [{
        "url": "//www.tme.eu/Document/example/BTS134D.pdf",
        "file_name": "BTS134D.pdf",
        "type": "DTE", "language": "EN", "size": 276988
    }]}
}]}}
PRODUCT_RESPONSE = {"status": "OK", "data": {"elements": [PRODUCT]}}


class FakeTransport:
    def __init__(self, replies=None, raise_for=None):
        self.replies = list(replies or [])
        self.calls = []
        self.raise_for = raise_for

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if self.raise_for and self.raise_for in url:
            raise ValueError("Simulated TME payload problem")
        if "/auth/token" in url:
            return {"access_token": "FAKE_BEARER", "expires_in": 300}
        if self.replies:
            return self.replies.pop(0)
        raise AssertionError("Unexpected remote call in mock test")


class TmeEnrichmentDevTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "magazyn-hurtownie-webgui-dev-20261029"
        self.root.mkdir(mode=0o700)
        self.store = DevConfig(self.root)
        self.store.save("tme", enabled=True, credentials={
            "client_token": "MOCK_APP_TOKEN", "app_secret": "MOCK_APP_SECRET"})
        self.store.save("mouser", enabled=False)

    def tearDown(self):
        self.tmp.cleanup()

    def engine(self, responses=None):
        transport = FakeTransport(responses)
        engine = SupplierEngine(self.store, live_allowed=True,
                                live_providers={"tme"}, transport=transport)
        return engine, transport

    def test_bts134d_realistic_response(self):
        engine, transport = self.engine([PRODUCT_RESPONSE, PARAM_RESPONSE, DOC_RESPONSE])
        answer = enrich_tme(engine, "BTS134D")
        self.assertEqual(answer["status"], "ok")
        self.assertEqual(answer["manufacturer"], "INFINEON TECHNOLOGIES")
        self.assertEqual(answer["supplier_symbol"], "BTS134D")
        self.assertEqual(len(answer["technical_parameters"]), 11)
        self.assertEqual(len(answer["documents"]), 1)
        self.assertTrue(answer["documents"][0]["url"].startswith("https://www.tme.eu/"))
        self.assertEqual(answer["documents"][0]["filename"], "BTS134D.pdf")
        fields = {x["field"]: x["value"] for x in answer["suggestions"]}
        self.assertEqual(fields["primary_number"], "BTS134D")
        self.assertEqual(fields["category"], "Układy scalone")
        self.assertEqual(fields["package"], "TO252-3")
        self.assertEqual(fields["spec_current"], "3,5A")
        self.assertEqual(fields["spec_voltage"], "42V")
        self.assertEqual(fields["spec_resistance"], "35mΩ")
        self.assertIn("HITFET", fields["parameters"])
        self.assertEqual(answer["source_kind"], "supplier_catalog")
        self.assertTrue(answer["manual_approval_required"])
        self.assertNotIn("MOCK_APP_SECRET", str(answer))
        self.assertEqual(len(transport.calls), 4)
        self.assertTrue(all("https://api.tme.eu/" in url for _, url in transport.calls))

    def test_disabled_does_not_access_external_api(self):
        self.store.save("tme", enabled=False)
        engine, transport = self.engine()
        self.assertEqual(enrich_tme(engine, "BTS134D")["status"], "disabled")
        self.assertEqual(transport.calls, [])

    def test_offline_does_not_call_tme(self):
        transport = FakeTransport()
        engine = SupplierEngine(self.store, live_allowed=False, transport=transport)
        self.assertEqual(enrich_tme(engine, "BTS134D")["status"], "offline_dev")
        self.assertEqual(transport.calls, [])

    def test_non_exact_or_multiple_product_will_not_enrich(self):
        product = dict(PRODUCT)
        product["manufacturer_symbols"] = ["BTS134DX"]
        engine, transport = self.engine([{"status": "OK", "data": {"elements": [product]}}])
        self.assertEqual(enrich_tme(engine, "BTS134D")["status"], "not_found")
        self.assertEqual(len(transport.calls), 2)
        engine, transport = self.engine([{"status": "OK", "data": {"elements": [PRODUCT, PRODUCT]}}])
        self.assertEqual(enrich_tme(engine, "BTS134D")["status"], "ambiguous")
        self.assertEqual(len(transport.calls), 2)

    def test_documents_mismatch_does_not_leak_foreign_document(self):
        changed = dict(DOC_RESPONSE)
        changed = {"status": "OK", "data": {"elements": [{
            "symbol": "NOT_BTS134D", "documents": {
                "elements": [{"url": "//www.tme.eu/a.pdf", "type": "DTE"}]}}]}}
        engine, _ = self.engine([PRODUCT_RESPONSE, PARAM_RESPONSE, changed])
        answer = enrich_tme(engine, "BTS134D")
        self.assertEqual(answer["status"], "ok")
        self.assertEqual(answer["documents"], [])
        self.assertTrue(any("dokument" in w.lower() for w in answer["warnings"]))

    def test_document_url_is_strictly_allowlisted(self):
        for value in (
            "http://www.tme.eu/Document/bts.pdf",
            "https://evil.example/bts.pdf",
            "//www.tme.eu.evil.example/bts.pdf",
            "javascript:alert(1)",
            "https://user:pass@www.tme.eu/doc.pdf",
            "//192.0.2.10/doc.pdf",
            "/only-local.pdf",
        ):
            self.assertEqual(document_link(value), "")
        self.assertEqual(document_link("//www.tme.eu/file.pdf"),
                         "https://www.tme.eu/file.pdf")

    def test_extra_fields_not_fabricated(self):
        fields = {s["field"]:s["value"] for s in suggestions_for_product(
            "BTS134D", PRODUCT,
            [{"name": "Liczba kanałów", "value": "1"}])}
        self.assertEqual(fields["parameters"], "Liczba kanałów: 1")
        self.assertNotIn("spec_voltage", fields)
        self.assertNotIn("package", fields)

    def test_invalid_status_and_mpn_rejected(self):
        with self.assertRaises(ValueError):
            response_elements({"status": "ERR", "data": {"elements": []}})
        with self.assertRaises(ValueError):
            enrich_tme(self.engine()[0], "../etc/passwd")
        self.assertEqual(match_symbol([PRODUCT], "BTS134D"), [PRODUCT])


if __name__ == "__main__":
    unittest.main(verbosity=2)
