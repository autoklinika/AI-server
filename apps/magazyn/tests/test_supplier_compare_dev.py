"""TME/Mouser quote comparison contract: offline mocks; no live API keys or orders."""
import unittest
from urllib.parse import urlsplit

from magazyn.suppliers_dev.quote_compare import compare, _quantity, _money
from magazyn.suppliers_dev.providers import SupplierEngine
from magazyn.suppliers_dev.transport import SupplierHTTPError

class Config:
    def __init__(self,enabled=True):
        self.enabled=enabled
    def internal(self,supplier):
        return {"enabled":self.enabled,"creds":({"client_token":"TEST","app_secret":"TEST"}
                   if supplier=="tme" else {"api_key":"SECRET_TEST_DO_NOT_LOG"})}

class OAuth:
    def get_access_token(self,*args):
        return "FAKE_TOKEN"

class FakeTransport:
    def __init__(self,bad_tme=False,no_stock=False):
        self.calls=[]
        self.bad_tme=bad_tme
        self.no_stock=no_stock
    def request(self,method,url,**kwargs):
        parsed=urlsplit(url)
        self.calls.append((parsed.hostname,parsed.path,method))
        if parsed.path=="/products/data":
            if self.bad_tme: raise SupplierHTTPError("SECRET_TEST_DO_NOT_LOG",503)
            product={"symbol":"BTS134D-TME","prices":{"currency":"PLN","type":"GROSS",
                 "elements":[{"amount":1,"price":3.20},{"amount":10,"price":2.90}]}}
            if not self.no_stock: product["stock_quantity"]=158
            return {"status":"OK","data":{"elements":[product]}}
        if parsed.path=="/api/v1/search/partnumber":
            p={"ManufacturerPartNumber":"BTS134D","Manufacturer":"Infineon",
               "Description":"Smart high-side switch","MouserPartNumber":"123-BTS134D",
               "ProductDetailUrl":"https://www.mouser.com/ProductDetail/Infineon/BTS134D",
               "Availability":"38 In Stock","AvailabilityInStock":"38",
               "PriceBreaks":[{"Quantity":1,"Price":"$2.10","Currency":"USD"},
                              {"Quantity":100,"Price":"$1.52","Currency":"USD"}]}
            variant={**p,"ManufacturerPartNumber":"BTS134D-A",
                     "MouserPartNumber":"123-BTS134D-A"}
            return {"SearchResults":{"Parts":[p,variant]},"Errors":[]}
        raise AssertionError("Unexpected API path "+parsed.path)

class FakeEngine:
    _valid_query=staticmethod(SupplierEngine._valid_query)
    live_allowed=True
    live_providers=frozenset({"tme","mouser"})
    def __init__(self,transport=None,config=None):
        self.store=config or Config()
        self.oauth=OAuth()
        self.transport=transport or FakeTransport()
    def search_one(self,supplier,query):
        if supplier=="tme":
            return {"supplier":"tme","status":"ok","results":[{
                "supplier":"tme","mpn":"BTS134D","manufacturer":"Infineon",
                "description":"Power switch","supplier_sku":"BTS134D-TME",
                "product_url":"","availability":"",
                "exact_mpn":True}]}
        raise AssertionError("Unexpected supplier")

class CompareTests(unittest.TestCase):
    def test_prices_stock_variants_and_currency_unconverted(self):
        engine=FakeEngine()
        resp=compare(engine,"BTS134D")
        a,b=resp["sources"]
        self.assertEqual((a["status"],b["status"]),("ok","ok"))
        self.assertEqual(a["results"][0]["stock_quantity"],158)
        self.assertEqual(a["results"][0]["link_kind"],"catalog_search")
        self.assertEqual(a["results"][0]["product_url"],
                         "https://www.tme.eu/pl/katalog/?search=BTS134D-TME")
        self.assertTrue(b["results"][0]["product_url"].startswith("https://www.mouser.com/"))
        self.assertEqual(a["results"][0]["price_breaks"][0],{"quantity":1,"price":"3.2"})
        self.assertEqual(a["results"][0]["currency"],"PLN")
        self.assertEqual(a["results"][0]["price_type"],"GROSS")
        self.assertEqual(b["results"][0]["stock_quantity"],38)
        self.assertEqual(b["results"][0]["price_breaks"][1]["price"],"$1.52")
        self.assertEqual(b["results"][0]["currency"],"USD")
        self.assertEqual(len(b["results"]),2)
        self.assertTrue(b["results"][0]["exact_mpn"])
        self.assertFalse(b["results"][1]["exact_mpn"])
        self.assertEqual(engine.transport.calls[0][1],"/products/data")
        self.assertEqual(engine.transport.calls[1][1],"/api/v1/search/partnumber")
        self.assertNotIn("SECRET_TEST_DO_NOT_LOG",str(resp))
    def test_missing_stock_is_null_not_zero(self):
        result=compare(FakeEngine(transport=FakeTransport(no_stock=True)),"BTS134D")
        self.assertIsNone(result["sources"][0]["results"][0]["stock_quantity"])
        self.assertIsNone(_quantity("In Stock"))
        self.assertEqual(_quantity(0),0)
    def test_tme_price_failure_preserves_catalog_result_without_fictitious_price(self):
        r=compare(FakeEngine(transport=FakeTransport(bad_tme=True)),"BTS134D")
        first=r["sources"][0]
        self.assertEqual(first["status"],"partial")
        self.assertIsNone(first["results"][0]["stock_quantity"])
        self.assertEqual(first["results"][0]["price_breaks"],[])
        self.assertNotIn("SECRET_TEST_DO_NOT_LOG",str(r))
        self.assertEqual(r["sources"][1]["status"],"ok")
    def test_disabled_sources_do_not_call_api(self):
        engine=FakeEngine(config=Config(enabled=False))
        r=compare(engine,"BTS134D")
        self.assertEqual([s["status"] for s in r["sources"]],["disabled","disabled"])
        self.assertFalse(engine.transport.calls)
    def test_offline_sources_do_not_call_api(self):
        engine=FakeEngine()
        engine.live_allowed=False
        r=compare(engine,"BTS134D")
        self.assertEqual([s["status"] for s in r["sources"]],["offline_dev","offline_dev"])
        self.assertFalse(engine.transport.calls)
    def test_input_validation_and_money_guard(self):
        with self.assertRaises(Exception):compare(FakeEngine(),"B")
        self.assertEqual(_money("<img onerror=x>"),"")
        self.assertIsNone(_quantity("-1"))
        self.assertEqual(_quantity("1,200"),1200)

if __name__=="__main__":
    unittest.main()
