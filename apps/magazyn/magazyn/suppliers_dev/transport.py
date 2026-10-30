"""HTTPS-only transport with a fixed host/path allowlist, bounded responses, no redirects."""
import json
import urllib.error
import urllib.parse
import urllib.request


class SupplierHTTPError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


ALLOWED = {
    ("api.mouser.com", "/api/v1/search/partnumber"),
    ("api.tme.eu", "/auth/token"),
    ("api.tme.eu", "/products"),
    ("api.tme.eu", "/products/data"),
    ("api.tme.eu", "/products/parameters"),
    ("api.tme.eu", "/products/files"),
    ("api.tme.eu", "/products/search"),
    ("api.digikey.com", "/v1/oauth2/token"),
    ("api.digikey.com", "/products/v4/search/keyword"),
    ("sandbox-api.digikey.com", "/v1/oauth2/token"),
    ("sandbox-api.digikey.com", "/products/v4/search/keyword"),
    ("api.element14.com", "/catalog/products"),
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SupplierHTTPError("Przekierowanie z API odrzucone.", status=code)


class Transport:
    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, method, url, *, headers=None, json_data=None, form_data=None):
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.fragment
                or (parsed.hostname, parsed.path) not in ALLOWED
                or method not in ("GET", "POST")):
            raise SupplierHTTPError("Niedozwolony adres API.")
        if json_data is not None and form_data is not None:
            raise SupplierHTTPError("Nie można łączyć rodzajów danych.")
        req_headers = {"Accept": "application/json", "User-Agent": "MagazynSuppliers-DEV/0.1"}
        req_headers.update(headers or {})
        payload = None
        if json_data is not None:
            payload = json.dumps(json_data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif form_data is not None:
            payload = urllib.parse.urlencode(form_data).encode("utf-8")
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as resp:
                blob = resp.read(1_048_577)
                if len(blob) > 1_048_576:
                    raise SupplierHTTPError("Odpowiedź API za duża.")
                return json.loads(blob)
        except urllib.error.HTTPError as exc:
            raise SupplierHTTPError(f"API HTTP {exc.code}", status=exc.code) from None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise SupplierHTTPError("Nie udało się pobrać poprawnej odpowiedzi API.") from None
