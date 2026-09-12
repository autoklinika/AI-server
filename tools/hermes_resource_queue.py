#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

GATEWAY_DEFAULT = "http://127.0.0.1:11435"
QUEUE_NOTICE_AFTER_DEFAULT = 0.75
POLL_SECONDS_DEFAULT = 0.35
HEARTBEAT_SECONDS_DEFAULT = 10.0
NOTIFIABLE_PLATFORMS = frozenset({"telegram", "discord"})


class ResourceQueueError(RuntimeError):
    pass


def should_manage_base_url(base_url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(base_url or ""))
        return (
            parsed.scheme in {"http", "https"}
            and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
            and parsed.port == 11435
        )
    except Exception:
        return False


def _gateway() -> str:
    raw = os.environ.get("HERMES_RESOURCE_GATEWAY_URL", GATEWAY_DEFAULT).strip().rstrip("/")
    if not should_manage_base_url(raw):
        raise ResourceQueueError(
            "Global Resource Manager musi działać na lokalnym AI Gateway :11435."
        )
    return raw


def _json(method: str, path: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        _gateway() + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ResourceQueueError(
            f"Resource Manager HTTP {exc.code}: {body[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ResourceQueueError(
            f"Resource Manager niedostępny: {getattr(exc, 'reason', exc)}"
        ) from exc
    value = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(value, dict):
        raise ResourceQueueError("Resource Manager zwrócił niepoprawny format.")
    return value


def _hermes_bin() -> str:
    configured = os.environ.get("HERMES_CLI_BIN", "").strip()
    candidates = [
        configured,
        shutil.which("hermes") or "",
        "/srv/ai-data/hermes/hermes-agent/venv/bin/hermes",
        "/srv/ai-data/hermes/hermes-agent/venv/bin/hermes-agent",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise ResourceQueueError(
        "Nie znaleziono lokalnego CLI Hermesa do komunikatu statusowego."
    )


def _notification_platform(target: str | None) -> str | None:
    if not target:
        return None
    platform, separator, destination = str(target).partition(":")
    platform = platform.strip().lower()
    if not separator or not destination.strip() or platform not in NOTIFIABLE_PLATFORMS:
        return None
    return platform


def _notify(target: str | None, message: str | None) -> None:
    platform = _notification_platform(target)
    if platform is None or not message:
        return
    process = subprocess.run(
        [_hermes_bin(), "send", "--to", str(target), str(message)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
        check=False,
    )
    if process.returncode != 0:
        raise ResourceQueueError(
            f"Nie udało się wysłać statusu kolejki przez {platform}."
        )


def _notify_best_effort(target: str | None, message: str | None) -> bool:
    """Status kolejki nie może zatrzymać właściwego zadania użytkownika."""
    platform = _notification_platform(target)
    if platform is None or not message:
        return False
    try:
        _notify(target, message)
        return True
    except Exception as exc:
        print(
            f"WARN: {platform} queue status delivery failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return False


def _float_env(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


@dataclass
class ResourceLease:
    lease_id: str
    job_id: int
    source: str
    target: str | None
    _stop: threading.Event
    _thread: threading.Thread | None = None
    _released: bool = False

    def start_heartbeat(self) -> None:
        interval = _float_env(
            "HERMES_RESOURCE_HEARTBEAT_SECONDS",
            HEARTBEAT_SECONDS_DEFAULT,
            2.0,
            30.0,
        )

        def run() -> None:
            while not self._stop.wait(interval):
                try:
                    _json(
                        "POST",
                        f"/resource/leases/{self.lease_id}/heartbeat",
                        timeout=5,
                    )
                except Exception:
                    self._stop.set()
                    return

        self._thread = threading.Thread(
            target=run,
            name=f"resource-lease-{self.job_id}",
            daemon=True,
        )
        self._thread.start()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._stop.set()
        try:
            _json("DELETE", f"/resource/leases/{self.lease_id}", timeout=5)
        except Exception:
            pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)


def acquire_resource(
    *,
    target: str | None,
    source: str,
    priority: int = 50,
    queue_message: str | None = None,
    start_message: str | None = None,
) -> ResourceLease:
    created = _json(
        "POST",
        "/resource/leases",
        {"source": source, "priority": int(priority)},
        timeout=5,
    )
    lease_id = str(created.get("lease_id") or "")
    job_id = int(created.get("job_id") or 0)
    if not lease_id or job_id <= 0:
        raise ResourceQueueError(
            "Resource Manager nie zwrócił identyfikatora zadania."
        )

    handle = ResourceLease(
        lease_id=lease_id,
        job_id=job_id,
        source=source,
        target=target,
        _stop=threading.Event(),
    )
    handle.start_heartbeat()

    state = str(created.get("state") or "")
    queued_notice_attempted = False
    queued_notice_sent = False
    started = time.monotonic()
    notice_after = _float_env(
        "HERMES_RESOURCE_QUEUE_NOTICE_AFTER",
        QUEUE_NOTICE_AFTER_DEFAULT,
        0.0,
        5.0,
    )
    poll = _float_env(
        "HERMES_RESOURCE_POLL_SECONDS",
        POLL_SECONDS_DEFAULT,
        0.1,
        2.0,
    )

    try:
        while state != "active":
            if state != "queued":
                raise ResourceQueueError(
                    f"Niepoprawny stan Resource Managera: {state or '<pusty>'}"
                )
            if (
                not queued_notice_attempted
                and time.monotonic() - started >= notice_after
            ):
                queued_notice_attempted = True
                queued_notice_sent = _notify_best_effort(target, queue_message)

            time.sleep(poll)
            status = _json(
                "GET",
                f"/resource/leases/{lease_id}",
                timeout=5,
            )
            state = str(status.get("state") or "")

        if queued_notice_sent:
            _notify_best_effort(target, start_message)
        return handle
    except Exception:
        handle.release()
        raise


def lease_headers_from_env(*, release_after: bool = False) -> dict[str, str]:
    lease_id = os.environ.get("HERMES_RESOURCE_LEASE_ID", "").strip()
    if not lease_id:
        return {}
    headers = {"X-AI-Resource-Lease": lease_id}
    if release_after:
        headers["X-AI-Resource-Lease-Release"] = "1"
    return headers
