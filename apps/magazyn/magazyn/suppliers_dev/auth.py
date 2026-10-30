"""Unified provider authorization mechanisms. Never print or persist access tokens."""
import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode
from .transport import SupplierHTTPError


class AuthorizationError(Exception):
    """Sanitized failure; do not include credentials or remote response bodies."""


@dataclass
class Token:
    access: str
    expires: float
    refresh: str = ""


class OAuthManager:
    """Shared OAuth2 client_credentials, refresh and authorization_code (PKCE)."""

    TOKEN_URLS = {
        "tme": "https://api.tme.eu/auth/token",
        "digikey": "https://api.digikey.com/v1/oauth2/token",
    }

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._tokens = {}
        self._pending = {}

    def clear(self, provider=None):
        if provider is None:
            self._tokens.clear()
            self._pending.clear()
        else:
            self._tokens.pop(provider, None)
            self._pending = {k: v for k, v in self._pending.items() if v["provider"] != provider}

    def _store_token(self, provider, answer):
        if not isinstance(answer, dict) or not isinstance(answer.get("access_token"), str):
            raise AuthorizationError("Token API: niepoprawna odpowiedź.")
        token = Token(
            answer["access_token"],
            self.clock() + max(1, int(answer.get("expires_in", 300))) - 30,
            str(answer.get("refresh_token") or ""),
        )
        self._tokens[provider] = token
        return token.access

    def _token_request(self, provider, creds, grant, transport, **extra):
        if provider == "tme":
            ident, secret = creds.get("client_token"), creds.get("app_secret")
            if not ident or not secret:
                raise AuthorizationError("TME: brak tokenu i sekretu aplikacji.")
            basic = base64.b64encode((ident + ":" + secret).encode()).decode()
            return transport.request(
                "POST", self.TOKEN_URLS["tme"],
                headers={"Authorization": "Basic " + basic},
                form_data={"grant_type": grant, **extra},
            )
        if provider == "digikey":
            ident, secret = creds.get("client_id"), creds.get("client_secret")
            if not ident or not secret:
                raise AuthorizationError("DigiKey: brak client_id i client_secret.")
            return transport.request(
                "POST", self.TOKEN_URLS["digikey"],
                form_data={"client_id": ident, "client_secret": secret,
                           "grant_type": grant, **extra},
            )
        raise AuthorizationError("Nieobsługiwany dostawca OAuth2.")

    def get_access_token(self, provider, creds, transport):
        cached = self._tokens.get(provider)
        if cached and self.clock() < cached.expires:
            return cached.access
        if cached and cached.refresh:
            try:
                return self._store_token(provider, self._token_request(
                    provider, creds, "refresh_token", transport, refresh_token=cached.refresh))
            except (AuthorizationError, SupplierHTTPError, ValueError):
                # Refresh can be revoked; fall back to client credentials.
                pass
        return self._store_token(provider, self._token_request(
            provider, creds, "client_credentials", transport))

    def begin_authorization_code(self, provider, client_id, redirect_uri, *, use_pkce=True):
        """Scaffold for delegated account access; not enabled in DEV WebGUI by default.

        Requires a registered HTTPS redirect URI. The real 3-legged flow must
        be tested with the supplier before enabling it for end users.
        """
        if provider != "digikey" or not client_id or not redirect_uri.startswith("https://"):
            raise AuthorizationError("Authorization code wymaga DigiKey i HTTPS callback.")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        params = {"response_type": "code", "client_id": client_id,
                  "redirect_uri": redirect_uri, "state": state}
        if use_pkce:
            digest = hashlib.sha256(verifier.encode()).digest()
            params["code_challenge"] = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            params["code_challenge_method"] = "S256"
        self._pending[state] = {
            "provider": provider, "redirect_uri": redirect_uri, "verifier": verifier,
            "pkce": use_pkce, "expiry": self.clock() + 180,
        }
        return "https://api.digikey.com/v1/oauth2/authorize?" + urlencode(params), state

    def finish_authorization_code(self, provider, state, code, creds, transport):
        pending = self._pending.pop(state, None)
        if (not pending or pending["provider"] != provider
                or self.clock() > pending["expiry"] or not code):
            raise AuthorizationError("OAuth callback: nieważny stan lub kod.")
        extra = {"code": code, "redirect_uri": pending["redirect_uri"]}
        if pending["pkce"]:
            extra["code_verifier"] = pending["verifier"]
        return self._store_token(provider, self._token_request(
            provider, creds, "authorization_code", transport, **extra))


def farnell_contract_signature(secret, operation, timestamp=None):
    """HMAC-SHA1 -> Base64 per element14 contract-pricing legacy specification."""
    allowed = {"searchByKeyword", "searchByPremierFarnellPartNumber",
               "searchByManufacturerPartNumber"}
    if operation not in allowed or not secret:
        raise AuthorizationError("Niedozwolona operacja HMAC lub brak sekretu.")
    if timestamp is None:
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"
    payload = (operation + timestamp).encode("utf-8")
    signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha1).digest()
    ).decode("ascii")
    return timestamp, signature
