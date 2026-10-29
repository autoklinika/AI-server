"""Bounded, opt-in ECU OCR residency on the existing RTX Ollama service.

A global RM LLM lease is required BEFORE any RTX model load or inference.
The current RM does not independently arbitrate RTX VRAM: we additionally
check physical free VRAM and the RTX Ollama resident model count and fail closed.
No new service, scheduler, SQL table, or direct client GPU access is introduced.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import subprocess
import threading
import time
import zlib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import ecu_ai
from .store import Problem

RM_URL = "http://127.0.0.1:11435"
RTX_URL = "http://127.0.0.1:11436"
MODEL = "qwen3-vl:8b-instruct"
REQUIRED_FREE_MIB = 8300  # observed 7046 MiB peak + operating reserve
IDLE_SECONDS = 120
_HTTP_MAX_RESPONSE = 100_000


class Busy(RuntimeError):
    pass


def _json(method: str, url: str, payload: dict | None = None, *, timeout: int = 6) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method=method,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            data = response.read(_HTTP_MAX_RESPONSE + 1)
            if len(data) > _HTTP_MAX_RESPONSE:
                raise RuntimeError("Oversized response")
            return json.loads(data) if data else {}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError("Internal AI service unavailable") from exc


def _gpu() -> tuple[int, int]:
    try:
        check = subprocess.run(
            ["nvidia-smi", "-i", "0", "--query-gpu=name,memory.free,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        lines = check.stdout.strip().splitlines()
        if len(lines) != 1:
            raise ValueError("Unexpected GPU enumeration")
        name, free, total = [x.strip() for x in lines[0].split(",", 2)]
        if "RTX 5060 Ti" not in name:
            raise ValueError("Unexpected GPU")
        return int(free), int(total)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        raise Busy("Nie można bezpiecznie sprawdzić pamięci RTX; użyj OCR.") from exc


def _warmup_png() -> str:
    # Valid 96x32 RGB PNG using only stdlib; warms the VLM image encoder.
    def chunk(name: bytes, value: bytes) -> bytes:
        return (struct.pack(">I", len(value)) + name + value +
                struct.pack(">I", zlib.crc32(name + value) & 0xffffffff))
    rows = []
    for y in range(32):
        pixels = bytearray()
        for x in range(96):
            shade = 20 if (8 <= y <= 13 or 20 <= y <= 24) and 8 < x < 86 else 255
            pixels.extend((shade, shade, shade))
        rows.append(b"\x00" + bytes(pixels))
    raw = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", 96, 32, 8, 2, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(b"".join(rows))) +
           chunk(b"IEND", b""))
    return base64.b64encode(raw).decode("ascii")


class RtxSession:
    def __init__(self, *, idle_seconds: int = IDLE_SECONDS):
        self._lock = threading.RLock()
        self._idle_seconds = idle_seconds
        self._owner: int | None = None
        self._sid = ""
        self._phase = "off"
        self._progress = 0
        self._message = "AI wyłączone. Aparat korzysta z OCR telefonu."
        self._lease = ""
        self._deadline = 0.0
        self._free_mib: int | None = None
        self._own_model = False
        self._shutdown = threading.Event()

    def _update(self, sid: str, phase: str, progress: int, message: str) -> bool:
        with self._lock:
            if self._sid != sid or self._phase in ("closing", "off"):
                return False
            self._phase, self._progress, self._message = phase, progress, message
            return True

    def status(self, user_id: int) -> dict:
        with self._lock:
            if self._owner is not None and self._owner != user_id:
                return {
                    "enabled": True, "phase": "busy", "ready": False,
                    "progress": 0, "session_id": "",
                    "message": "Tryb AI jest używany przez innego pracownika. Aparat: OCR telefonu.",
                    "expires_in": 0,
                }
            return {
                "enabled": True,
                "phase": self._phase,
                "ready": self._phase == "ready" and time.monotonic() < self._deadline,
                "progress": self._progress,
                "session_id": self._sid if self._owner == user_id else "",
                "message": self._message,
                "expires_in": max(0, int(self._deadline - time.monotonic()))
                              if self._phase == "ready" else 0,
                "free_mib": self._free_mib,
            }

    def activate(self, user_id: int) -> dict:
        with self._lock:
            if self._owner is not None and self._owner != user_id:
                raise Problem(409, "RTX jest aktualnie zajęty przez innego użytkownika. Aparat: OCR.")
            if self._phase in ("checking", "reserving", "loading", "warming", "scanning", "closing"):
                return self.status(user_id)
            if self._phase == "ready":
                # Do not overwrite a still-owned RM lease while watchdog retires it.
                return self.status(user_id)
            self._sid = secrets.token_urlsafe(22)
            self._owner = user_id
            self._phase, self._progress = "checking", 5
            self._message = "Sprawdzanie Resource Managera i dostępnej pamięci RTX…"
            self._lease = ""
            self._deadline = 0
            self._own_model = False
            self._free_mib = None
            self._shutdown = threading.Event()
            sid = self._sid
        threading.Thread(target=self._prepare, args=(sid,), daemon=True,
                         name="magazyn-ecu-rtx-prepare").start()
        return self.status(user_id)

    def _preflight(self) -> tuple[bool, int]:
        rm = _json("GET", RM_URL + "/status")
        if (rm.get("admission_blocked") or rm.get("gpu_residency", {}).get("state") != "llm"
                or rm.get("active_count") or rm.get("queued_count")):
            raise Busy("Resource Manager jest zajęty; aparat użyje OCR telefonu.")
        free, _total = _gpu()
        resident = _json("GET", RTX_URL + "/api/ps").get("models", [])
        if not isinstance(resident, list):
            raise Busy("Nie można sprawdzić modeli na RTX.")
        names = [str(m.get("name", "")) for m in resident]
        already_loaded = MODEL in names
        if not already_loaded and len(names) >= 2:
            raise Busy("RTX ma już dwa załadowane modele. Aparat użyje OCR.")
        threshold = 650 if already_loaded else REQUIRED_FREE_MIB
        if free < threshold:
            raise Busy(
                f"Za mało wolnej pamięci RTX ({free} MiB; wymagane {threshold} MiB). Aparat użyje OCR."
            )
        return already_loaded, free

    def _prepare(self, sid: str) -> None:
        lease = ""
        try:
            _loaded, free = self._preflight()
            with self._lock:
                if self._sid != sid: return
                self._free_mib = free
            self._update(sid, "reserving", 30, "Rezerwacja zasobów przez Resource Manager…")
            reserved = _json("POST", RM_URL + "/resource/leases", {
                "source": "magazyn-ecu-rtx-on-demand",
                "priority_class": "background",
                "workload": "llm",
            })
            lease = str(reserved.get("lease_id") or "")
            if not lease:
                raise Busy("Nie uzyskano rezerwacji RM. Aparat użyje OCR.")
            if reserved.get("state") != "active":
                raise Busy("Resource Manager ma zajęte zasoby. Aparat użyje OCR.")
            with self._lock:
                if self._sid != sid:
                    _json("DELETE", RM_URL + "/resource/leases/" + lease)
                    return
                self._lease = lease
            # Re-check AFTER RM admission. VRAM can change while RM is granting.
            already_loaded, free = self._preflight_after_lease()
            with self._lock:
                self._free_mib = free
                self._own_model = not already_loaded
            threading.Thread(target=self._keepalive, args=(sid, lease), daemon=True,
                             name="magazyn-ecu-rtx-rm-keepalive").start()
            self._update(sid, "loading", 55, "Ładowanie Qwen3-VL 8B do pamięci RTX…")
            # Empty-prompt generate loads the model without entering image inference.
            # The separate vision request below truly warms its image encoder.
            _json("POST", RTX_URL + "/api/generate", {
                "model": MODEL, "prompt": "", "stream": False, "keep_alive": "3m",
            }, timeout=80)
            payload = {
                "model": MODEL, "stream": False, "think": False,
                "keep_alive": "3m",
                "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 32},
                "messages": [{
                    "role": "user",
                    "content": "Read any visible text, without guessing.",
                    "images": [_warmup_png()],
                }],
            }
            self._update(sid, "warming", 85, "Rozgrzewanie modelu i enkodera obrazu…")
            warm = _json("POST", RTX_URL + "/api/chat", payload, timeout=110)
            if not isinstance(warm.get("message"), dict):
                raise RuntimeError("Model warmup failed")
            current = _json("GET", RTX_URL + "/api/ps")
            if MODEL not in [m.get("name") for m in current.get("models", [])]:
                raise RuntimeError("Model not resident after warmup")
            with self._lock:
                if self._sid != sid: return
                self._phase, self._progress = "ready", 100
                self._message = "AI gotowe na RTX. Zrób zdjęcie etykiety ECU."
                self._deadline = time.monotonic() + self._idle_seconds
        except Busy as exc:
            self._stop(sid, "busy", str(exc))
        except Exception:
            self._stop(sid, "error", "Nie udało się przygotować RTX. Aparat korzysta z OCR.")
        finally:
            if lease:
                with self._lock:
                    owned = self._sid == sid and self._lease == lease
                if not owned:
                    try: _json("DELETE", RM_URL + "/resource/leases/" + lease)
                    except RuntimeError: pass

    def _preflight_after_lease(self) -> tuple[bool, int]:
        free, _total = _gpu()
        resident = _json("GET", RTX_URL + "/api/ps").get("models", [])
        if not isinstance(resident, list): raise Busy("Brak stanu modeli na RTX.")
        names = [str(m.get("name", "")) for m in resident]
        loaded = MODEL in names
        if not loaded and len(names) >= 2:
            raise Busy("RTX ma już dwa aktywne modele. Aparat: OCR.")
        threshold = 650 if loaded else REQUIRED_FREE_MIB
        if free < threshold:
            raise Busy(f"Za mało wolnej VRAM ({free} MiB). Aparat: OCR.")
        return loaded, free

    def _keepalive(self, sid: str, lease: str) -> None:
        fails = 0
        while not self._shutdown.wait(6):
            with self._lock:
                if sid != self._sid or lease != self._lease: return
                phase, deadline = self._phase, self._deadline
                if phase in ("closing", "off", "error", "busy"): return
            if phase == "ready" and time.monotonic() > deadline:
                self._stop(sid, "off", "Sesja AI wygasła; aparat korzysta z OCR.")
                return
            try:
                _json("POST", RM_URL + "/resource/leases/" + lease + "/heartbeat", {})
                fails = 0
            except RuntimeError:
                fails += 1
                if fails >= 2:
                    with self._lock:
                        if self._phase == "scanning":
                            # Avoid unloading an active inference. Scan will fail
                            # closed on its next check and the RM reaper can recover.
                            continue
                    self._stop(sid, "error", "Utracono rezerwację RM. Aparat: OCR.")
                    return

    def scan(self, user_id: int, session_id: str, photo_base64: str,
             local_text: str, barcodes: list[str]) -> dict:
        ecu_ai._image_bytes(photo_base64)
        with self._lock:
            if not (self._owner == user_id and self._sid == session_id and
                    self._phase == "ready" and time.monotonic() < self._deadline
                    and bool(self._lease)):
                raise Problem(409, "AI nie jest gotowe; użyj OCR lub włącz AI ponownie.")
            self._phase = "scanning"
            self._message = "Analizowanie zdjęcia na RTX…"
        try:
            resident = _json("GET", RTX_URL + "/api/ps")
            if MODEL not in [m.get("name") for m in resident.get("models", [])]:
                raise RuntimeError("Model was evicted")
            answer = _json("POST", RTX_URL + "/api/chat", {
                "model": MODEL, "stream": False, "think": False,
                "keep_alive": "3m",
                "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 850},
                "messages": [{
                    "role": "user", "content": ecu_ai._OCR_PROMPT,
                    "images": [photo_base64],
                }],
            }, timeout=110)
            transcript = answer.get("message", {}).get("content", "")
            if not isinstance(transcript, str) or not transcript.strip():
                raise RuntimeError("No model text")
            result = ecu_ai.analyze_transcripts(transcript, local_text, barcodes)
            result["gpu"] = "RTX 5060 Ti"
            with self._lock:
                if self._sid != session_id or self._phase != "scanning":
                    raise RuntimeError("AI session changed")
                self._phase = "ready"
                self._deadline = time.monotonic() + self._idle_seconds
                self._message = "AI gotowe na RTX. Możesz skanować kolejną etykietę."
            return result
        except Exception as exc:
            self._stop(session_id, "error",
                       "Błąd analizy na RTX. Aparat korzysta z OCR telefonu.")
            raise Problem(503, "AI jest chwilowo niedostępne; użyj OCR telefonu") from exc

    def deactivate(self, user_id: int, session_id: str) -> dict:
        with self._lock:
            if self._owner != user_id or self._sid != session_id:
                raise Problem(409, "Nieprawidłowa sesja AI.")
            if self._phase in ("checking", "reserving", "loading", "warming", "scanning"):
                raise Problem(409, "Trwa przygotowanie lub analiza. Spróbuj ponownie po zakończeniu.")
        self._stop(session_id, "off", "AI wyłączone. Aparat korzysta z OCR telefonu.")
        return self.status(user_id)

    def _stop(self, sid: str, final_phase: str, message: str) -> None:
        with self._lock:
            if sid != self._sid or self._phase == "closing": return
            self._phase = "closing"
            lease, own_model = self._lease, self._own_model
            self._lease = ""
            self._deadline = 0
            self._shutdown.set()
        if lease:
            if own_model:
                try:
                    _json("POST", RTX_URL + "/api/generate",
                          {"model": MODEL, "prompt": "", "keep_alive": 0,
                           "stream": False}, timeout=15)
                except RuntimeError:
                    pass
            try: _json("DELETE", RM_URL + "/resource/leases/" + lease)
            except RuntimeError: pass
        with self._lock:
            if sid == self._sid:
                self._phase, self._progress, self._message = final_phase, 0, message
                self._owner = None
                self._sid = ""
                self._free_mib = None
                self._own_model = False
