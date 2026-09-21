"""External executor guard; lease ownership/heartbeats remain with the worker."""
from contextlib import contextmanager
import os
import re
from urllib.parse import urlparse

import httpx


class MediaAdmissionError(RuntimeError):
    pass


@contextmanager
def media_admission(capability: str):
    lease_id = os.environ.get("HERMES_RESOURCE_LEASE_ID", "")
    gateway = os.environ.get("HERMES_RESOURCE_GATEWAY_URL", "http://127.0.0.1:11435").rstrip("/")
    try:
        parsed = urlparse(gateway)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                 and parsed.port == 11435 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and parsed.path in {"", "/"})
    except ValueError:
        valid = False
    if not valid or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", lease_id):
        raise MediaAdmissionError("active local resource lease required")
    path = f"/resource/leases/{lease_id}/uses"
    with httpx.Client(base_url=gateway, timeout=5, trust_env=False) as client:
        try:
            response = client.post(path, json={"provider": "comfyui-local", "capability": capability})
            response.raise_for_status()
            use_id = response.json()["use_id"]
            if not isinstance(use_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", use_id):
                raise ValueError()
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise MediaAdmissionError("media admission unavailable") from exc
        try:
            yield
        finally:
            # Failed cleanup leaves the phase owned by the lease until explicit
            # release/TTL. Never silently run another provider without admission.
            try:
                client.delete(f"{path}/{use_id}").raise_for_status()
            except httpx.HTTPError:
                pass
