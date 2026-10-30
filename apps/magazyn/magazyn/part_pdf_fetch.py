"""Safe PDF retrieval from an exact allowlisted manufacturer domain.

Allows at most 3 HTTPS redirects **within the same manufacturer domain**.
Never follows a redirect to arbitrary/CDN/private domains. Data only in memory;
no PDF cache or arbitrary URL proxy.
"""
from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .store import Problem


def domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def manufacturer_domain(url: str, manufacturer_hosts: dict[str, str], validate_url):
    try:
        validate_url(url)
        host=(urlsplit(url).hostname or "").lower().rstrip(".")
        matches=[d for d in manufacturer_hosts if domain_matches(host,d)]
        if len(matches)!=1:
            raise ValueError("Ambiguous or untrusted PDF producer")
        return matches[0]
    except (ValueError, TypeError):
        raise Problem(422,"Podaj bezpośredni link HTTPS do PDF producenta (obsługiwanego przez Magazyn).")


class SameManufacturerRedirect(HTTPRedirectHandler):
    def __init__(self,root,manufacturer_hosts,validate_url):
        super().__init__()
        self.root=root
        self.manufacturer_hosts=manufacturer_hosts
        self.validate_url=validate_url
        self.hops=0

    def redirect_request(self,req,fp,code,msg,headers,newurl):
        self.hops+=1
        final=urljoin(req.full_url,newurl)
        if self.hops>3:
            raise Problem(422,"Za dużo przekierowań dokumentacji. Pobierz PDF i dodaj z dysku.")
        domain=manufacturer_domain(final,self.manufacturer_hosts,self.validate_url)
        if domain!=self.root:
            raise Problem(422,"PDF przekierowuje poza domenę producenta. Pobierz go ręcznie i dodaj z dysku.")
        return super().redirect_request(req,fp,code,msg,headers,final)


def fetch_pdf(url: str, max_bytes: int, manufacturer_hosts: dict[str,str],
              validate_url):
    root=manufacturer_domain(url,manufacturer_hosts,validate_url)
    client=build_opener(SameManufacturerRedirect(root,manufacturer_hosts,validate_url))
    request=Request(url,headers={
        "User-Agent":"Mozilla/5.0 (compatible; MagazynV1-DatasheetDEV/1.0)",
        "Accept":"application/pdf,application/octet-stream;q=0.8,*/*;q=0.2",
    })
    try:
        with client.open(request,timeout=14) as response:
            raw_size=response.headers.get("Content-Length")
            if raw_size:
                try:
                    if int(raw_size)>max_bytes:
                        raise Problem(413,"Karta PDF przekracza limit 8 MB. Pobierz mniejszą wersję.")
                except ValueError:
                    pass
            data=response.read(max_bytes+1)
            if len(data)>max_bytes:
                raise Problem(413,"Karta PDF przekracza limit 8 MB.")
    except Problem:
        raise
    except HTTPError as exc:
        if exc.code in (404,410):
            raise Problem(422,"Nie znaleziono PDF pod tym adresem (404/410). Sprawdź link.")
        if exc.code in (401,403):
            raise Problem(422,"Serwer producenta blokuje automatyczny odczyt. Pobierz PDF i wybierz go z dysku.")
        raise Problem(503,"Dokumentacja producenta chwilowo niedostępna.")
    except (URLError,OSError,TimeoutError):
        raise Problem(503,"Nie udało się pobrać PDF. Sprawdź link lub wybierz plik z dysku.")

    if not (len(data)>=128 and data.startswith(b"%PDF-") and b"%%EOF" in data[-2048:]):
        raise Problem(422,"Link nie prowadzi do poprawnego pliku PDF. Wybierz bezpośredni PDF lub wczytaj go z dysku.")
    return data
