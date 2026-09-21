#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import quote
from uuid import uuid4

import httpx

from ai_bridge.providers.contracts import AgentTurnRequest
from ai_bridge.providers.hermes import HermesAdapter


HERMES_HOME = Path("/srv/ai-data/hermes")
HERMES_ENV = HERMES_HOME / ".env"
HERMES_CONFIG = HERMES_HOME / "config.yaml"
HERMES_STATE = HERMES_HOME / "gateway_state.json"
HERMES_URL = "http://127.0.0.1:8642"
AI_GATEWAY_URL = "http://127.0.0.1:11435"
EXPECTED_HERMES_LLM_ROUTE = "http://127.0.0.1:11435/clients/hermes/v1"
EXPECTED_REPLY = "STAGE_C_AGENT_OK"


class SmokeError(RuntimeError):
    pass


def _read_private_env_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SmokeError(f"Cannot read private Hermes env: {path}") from exc

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != key:
            continue
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]
        if not value:
            raise SmokeError(f"{key} exists but is empty in {path}")
        return value

    raise SmokeError(f"{key} is not present in {path}")


def _service_active(*args: str) -> bool:
    completed = subprocess.run(
        ["systemctl", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "active"


def _gateway_status() -> dict:
    response = httpx.get(f"{AI_GATEWAY_URL}/status", timeout=5.0)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise SmokeError("AI Gateway /status returned invalid JSON")
    return data


def _assert_scheduler_idle(status: dict, *, where: str) -> None:
    leases = status.get("resource_leases")
    lease_count = leases.get("lease_count") if isinstance(leases, dict) else None
    active = status.get("active_count")
    queued = status.get("queued_count")
    if active != 0 or queued != 0 or lease_count != 0:
        raise SmokeError(
            f"AI Gateway is not idle {where}: "
            f"active={active!r} queued={queued!r} leases={lease_count!r}"
        )


def _wait_scheduler_idle(timeout_seconds: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        last = _gateway_status()
        leases = last.get("resource_leases")
        lease_count = leases.get("lease_count") if isinstance(leases, dict) else None
        if (
            last.get("active_count") == 0
            and last.get("queued_count") == 0
            and lease_count == 0
        ):
            return last
        time.sleep(0.25)
    _assert_scheduler_idle(last, where="after smoke")
    return last


def _enabled_api_toolsets(api_key: str) -> list[dict]:
    response = httpx.get(
        f"{HERMES_URL}/v1/toolsets",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("platform") != "api_server":
        raise SmokeError("Hermes /v1/toolsets returned an unexpected payload")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise SmokeError("Hermes /v1/toolsets data is not a list")
    enabled: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("enabled") is not True:
            continue
        tools = row.get("tools")
        concrete = [str(tool) for tool in tools] if isinstance(tools, list) else []
        enabled.append(
            {
                "name": str(row.get("name") or ""),
                "tools": concrete,
            }
        )
    return enabled


def _assert_real_turn_safe(api_key: str) -> None:
    enabled = _enabled_api_toolsets(api_key)
    toolsets_with_tools = [row for row in enabled if row["tools"]]
    if not toolsets_with_tools:
        print("PASS: api_server exposes no enabled concrete tools for this smoke")
        return

    print("SAFE STOP: real agent turn was NOT executed.")
    print("Enabled api_server toolsets:")
    for row in toolsets_with_tools:
        print(f"  - {row['name']}: {', '.join(row['tools'])}")
    raise SmokeError(
        "Real Hermes smoke refused because request-scoped tool disabling is not "
        "available on this API boundary. Use an isolated no-tools Hermes profile "
        "for the E2E turn."
    )


def _assert_hermes_runtime_ready() -> None:
    if not _service_active("--user", "is-active", "hermes-gateway.service"):
        raise SmokeError("hermes-gateway.service is not active")
    if not _service_active("is-active", "ai-gateway.service"):
        raise SmokeError("ai-gateway.service is not active")

    try:
        state = json.loads(HERMES_STATE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SmokeError(f"Cannot read Hermes gateway state: {HERMES_STATE}") from exc
    if not isinstance(state, dict):
        raise SmokeError("Hermes gateway state is not an object")

    platforms = state.get("platforms")
    api_state = (
        (platforms.get("api_server") or {}).get("state")
        if isinstance(platforms, dict)
        else None
    )
    if state.get("gateway_state") != "running" or api_state != "connected":
        raise SmokeError(
            "Hermes gateway/API server is not ready: "
            f"gateway={state.get('gateway_state')!r} api_server={api_state!r}"
        )

    try:
        config_text = HERMES_CONFIG.read_text(encoding="utf-8")
    except OSError as exc:
        raise SmokeError(f"Cannot read Hermes config: {HERMES_CONFIG}") from exc
    if EXPECTED_HERMES_LLM_ROUTE not in config_text:
        raise SmokeError(
            "Hermes is not configured through the expected AI Gateway namespace"
        )


def _delete_test_session(api_key: str, session_id: str) -> bool:
    response = httpx.delete(
        f"{HERMES_URL}/api/sessions/{quote(session_id, safe='')}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    if response.status_code == 404:
        return True
    response.raise_for_status()
    data = response.json()
    return (
        isinstance(data, dict)
        and data.get("object") == "hermes.session.deleted"
        and data.get("id") == session_id
        and data.get("deleted") is True
    )


def main() -> int:
    print("===== STAGE C HERMES ADAPTER REAL SMOKE =====")
    print("Secret source:", HERMES_ENV)
    print("API_SERVER_KEY value: <redacted>")

    _assert_hermes_runtime_ready()
    _assert_scheduler_idle(_gateway_status(), where="before smoke")
    print("PASS: Hermes + AI Gateway ready; scheduler idle")

    api_key = _read_private_env_value(HERMES_ENV, "API_SERVER_KEY")
    _assert_real_turn_safe(api_key)

    adapter = HermesAdapter(
        base_url=HERMES_URL,
        api_key=api_key,
        model_name="hermes-agent",
        timeout_seconds=300.0,
    )

    health = adapter.health()
    if health.status != "ready":
        raise SmokeError(f"HermesAdapter health is not ready: {health}")
    descriptor = adapter.describe()
    if descriptor.provider_id != "hermes-local" or descriptor.provider_type != "agent":
        raise SmokeError(f"Unexpected Hermes descriptor: {descriptor}")
    print("PASS: HermesAdapter health/describe")

    session_id = f"stage-c-smoke-{uuid4().hex}"
    request_id = f"req-{uuid4().hex}"
    cleanup_ok = False
    run = None
    try:
        run = adapter.run_turn(
            AgentTurnRequest(
                request_id=request_id,
                session_id=session_id,
                message=(
                    "To jest techniczny test kontraktu Stage C. "
                    "Nie używaj żadnych narzędzi. Nie wyjaśniaj. "
                    f"Odpowiedz dokładnie tekstem: {EXPECTED_REPLY}"
                ),
                context={"domain": "shared", "purpose": "stage-c-smoke"},
                capability="reasoning",
            )
        )
        if run.request_id != request_id:
            raise SmokeError("HermesAdapter changed request_id")
        if run.session_id != session_id:
            raise SmokeError(
                f"HermesAdapter changed explicit session_id: {run.session_id!r}"
            )
        if run.provider != "hermes-local":
            raise SmokeError(f"Unexpected provider: {run.provider!r}")
        if EXPECTED_REPLY not in run.content:
            raise SmokeError(
                "Real Hermes turn completed but did not return the expected marker; "
                f"response={run.content[:200]!r}"
            )
        print("PASS: HermesAdapter -> Hermes API -> agent turn")
        print("provider:", run.provider)
        print("model:", run.model)
        print("response marker:", EXPECTED_REPLY)
        print(
            "usage:",
            {
                "input_tokens": run.usage.input_tokens,
                "output_tokens": run.usage.output_tokens,
            },
        )
    finally:
        try:
            cleanup_ok = _delete_test_session(api_key, session_id)
        finally:
            _wait_scheduler_idle()

    if not cleanup_ok:
        raise SmokeError(f"Could not verify deletion of test session {session_id}")

    print("PASS: test Hermes session removed")
    print("PASS: AI Gateway returned to active=0 queued=0 leases=0")
    print("STAGE C.2 REAL HERMES ADAPTER SMOKE: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeError, httpx.HTTPError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
