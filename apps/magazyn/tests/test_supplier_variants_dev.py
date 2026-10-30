"""TJA1050T family-number regression; read-only, explicit variant selection."""
import secrets
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from magazyn.suppliers_dev.variants import find_variants,_related
from magazyn.server import create_app
from magazyn.store import Store

class FakeEngine:
    def __init__(self): self.calls=[]
    def search_one(self,supplier,query):
        self.calls.append((supplier,query))
        if supplier=="tme":
            return {"status":"ok","results":[
                {"mpn":"TJA1050T/CM,118","manufacturer":"NXP",
                 "supplier_sku":"TJA1050T/CM,118","description":"CAN transceiver"},
                {"mpn":"TJA1050T/CM","manufacturer":"NXP",
                 "supplier_sku":"TJA1050T/CM","description":"CAN transceiver"}]}
        return {"status":"ok","results":[
            {"mpn":"TJA1050T/N1,112","manufacturer":"NXP Semiconductors",
             "supplier_sku":"771-TJA1050TN1112","description":"CAN XCVR"},
            {"mpn":"TJA1050T/N1,118","manufacturer":"NXP Semiconductors",
             "supplier_sku":"771-TJA1050T/N1,118","description":"CAN XCVR"},
            {"mpn":"TJA1050TD","manufacturer":"NXP Semiconductors",
             "supplier_sku":"771-TJA1050TD","description":"CAN XCVR"},
            {"mpn":"TJA1050TUNGROUNDEDLONGOTHER","manufacturer":"Bad",
             "supplier_sku":"BAD","description":"nope"},
        ]}

class VariantsTests(unittest.TestCase):
    def test_tja1050t_returns_explicit_catalog_choices(self):
        engine=FakeEngine()
        found=find_variants(engine,"TJA1050T")
        self.assertEqual(found["status"],"variants_available")
        self.assertTrue(found["manual_selection_required"])
        codes=[r["mpn"] for r in found["variants"]]
        self.assertIn("TJA1050T/CM,118",codes)
        self.assertIn("TJA1050T/N1,112",codes)
        self.assertIn("TJA1050TD",codes)
        self.assertNotIn("TJA1050TUNGROUNDEDLONGOTHER",codes)
        self.assertEqual(engine.calls,[("tme","TJA1050T"),("mouser","TJA1050T")])
        self.assertEqual(len(found["variants"]),5)

    def test_no_silent_variant_choice(self):
        response=find_variants(FakeEngine(),"TJA1050T")
        self.assertNotIn("selected_mpn",response)
        self.assertNotIn("suggestions",response)
        self.assertNotIn("changes",response)
        self.assertTrue(_related("TJA1050T","TJA1050T/CM,118"))
        self.assertFalse(_related("TJA1050T","TJA1050"))
        self.assertFalse(_related("TJA1050T","BTS134D"))

    def test_readonly_worker_route_login_and_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Do not access the user's real supplier DB in tests.
            root=Path(tmp)/"magazyn-hurtownie-webgui-dev-20261029"
            root.mkdir()
            from magazyn.suppliers_dev.store import DevConfig
            cfg=DevConfig(root)
            path=str(Path(tmp)/"warehouse.sqlite3")
            store=Store(path)
            pw=secrets.token_urlsafe(25)
            store.create_user("variantuzytkownik",pw,"user")
            with patch("magazyn.server.SupplierDevConfig",return_value=cfg):
                app=create_app(path,secure_cookie=False)
            with TestClient(app) as client:
                def invoke(headers=None):
                    return client.post("/api/parts/suppliers/variants",
                        json={"query":"TJA1050T"},headers=headers or {})
                self.assertEqual(invoke().status_code,401)
                login=client.post("/api/auth/login",
                    json={"username":"variantuzytkownik","password":pw})
                self.assertEqual(login.status_code,200)
                self.assertEqual(invoke().status_code,403)
                csrf=login.json()["csrf"]
                before=store.statistics()["items"]
                with patch("magazyn.server.find_variants",
                           return_value=find_variants(FakeEngine(),"TJA1050T")) as mock:
                    result=invoke(headers={"X-CSRF-Token":csrf})
                self.assertEqual(result.status_code,200)
                self.assertTrue(result.json()["manual_selection_required"])
                self.assertEqual(len(result.json()["variants"]),5)
                mock.assert_called_once()
                self.assertEqual(store.statistics()["items"],before)

    def test_variant_suffix_comma_accepted_by_form_api_schema(self):
        from magazyn.server import SupplierEnrichmentQuery
        for mpn in ("TJA1050T/CM,118","TJA1050T/N1,112","TJA1050T/H/V,112"):
            self.assertEqual(SupplierEnrichmentQuery(query=mpn).query,mpn)

if __name__=="__main__":unittest.main()
