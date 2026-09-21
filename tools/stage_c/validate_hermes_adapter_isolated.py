#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import httpx

from ai_bridge.providers.contracts import AgentTurnRequest
from ai_bridge.providers.hermes import HermesAdapter


PROD_HERMES_HOME = Path("/srv/ai-data/hermes")
HERMES_SOURCE = PROD_HERMES_HOME / "hermes-agent"
HERMES_PYTHON = HERMES_SOURCE / "venv" / "bin" / "python"
PROD_CONFIG = PROD_HERMES_HOME / "config.yaml"
PROD_ENV = PROD_HERMES_HOME / ".env"
AI_GATEWAY_URL = "http://127.0.0.1:11435"
HERMES_LLM_ROUTE = "http://127.0.0.1:11435/clients/hermes/v1"
MODEL = "qwen3.6:35b-hermes64k-gpu"
EXPECTED_REPLY = "STAGE_C_AGENT_OK"
EXPECTED_HERMES_COMMIT = "79445a496c86a19332ad786494b8384d2167e2d0"


class SmokeError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=None if cwd is None else str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _service_pid() -> int:
    result = _run(
        "systemctl",
        "--user",
        "show",
        "hermes-gateway.service",
        "-p",
        "MainPID",
        "--value",
    )
    if result.returncode != 0:
        raise SmokeError("Cannot read production hermes-gateway.service MainPID")
    try:
        pid = int(result.stdout.strip())
    except ValueError as exc:
        raise SmokeError("Invalid production Hermes MainPID") from exc
    if pid <= 0:
        raise SmokeError("Production Hermes gateway is not running")
    return pid


def _production_platform_states() -> dict[str, str]:
    path = PROD_HERMES_HOME / "gateway_state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SmokeError(f"Cannot read production Hermes gateway state: {path}") from exc
    if not isinstance(data, dict) or data.get("gateway_state") != "running":
        raise SmokeError("Production Hermes gateway_state is not running")
    platforms = data.get("platforms")
    if not isinstance(platforms, dict):
        return {}
    return {
        str(name): str(details.get("state") or "")
        for name, details in platforms.items()
        if isinstance(details, dict)
    }


def _gateway_status() -> dict:
    response = httpx.get(f"{AI_GATEWAY_URL}/status", timeout=5.0)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise SmokeError("AI Gateway /status returned invalid JSON")
    return data


def _scheduler_counts(status: dict) -> tuple[object, object, object]:
    leases = status.get("resource_leases")
    lease_count = leases.get("lease_count") if isinstance(leases, dict) else None
    return status.get("active_count"), status.get("queued_count"), lease_count


def _assert_scheduler_idle(*, where: str) -> None:
    status = _gateway_status()
    active, queued, leases = _scheduler_counts(status)
    if (active, queued, leases) != (0, 0, 0):
        raise SmokeError(
            f"AI Gateway is not idle {where}: "
            f"active={active!r} queued={queued!r} leases={leases!r}"
        )


def _wait_scheduler_idle(timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last = None
    while time.monotonic() < deadline:
        last = _gateway_status()
        if _scheduler_counts(last) == (0, 0, 0):
            return
        time.sleep(0.25)
    active, queued, leases = _scheduler_counts(last or {})
    raise SmokeError(
        "AI Gateway did not return idle after isolated smoke: "
        f"active={active!r} queued={queued!r} leases={leases!r}"
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _minimal_config() -> dict:
    return {
        "model": {
            "default": MODEL,
            "provider": "custom",
            "base_url": HERMES_LLM_ROUTE,
            "api_key": "stage-c-local-no-secret",
            "api_mode": "chat_completions",
            "context_length": 65536,
        },
        "toolsets": [],
        "platform_toolsets": {
            "api_server": [],
        },
        "mcp_servers": {},
        "agent": {
            "max_turns": 1,
            "reasoning_effort": "none",
            "tool_use_enforcement": False,
            "execution_guidance": False,
            "intent_ack_continuation": False,
            "task_completion_guidance": False,
            "parallel_tool_call_guidance": False,
            "environment_probe": False,
            "coding_context": "off",
        },
        "memory": {
            "memory_enabled": False,
            "user_profile_enabled": False,
        },
        "auxiliary": {
            "title_generation": {
                "enabled": False,
            }
        },
    }


def _isolated_env(home: Path, port: int, api_key: str) -> dict[str, str]:
    keep = (
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
    )
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.update(
        {
            "HERMES_HOME": str(home),
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "127.0.0.1",
            "API_SERVER_PORT": str(port),
            "API_SERVER_KEY": api_key,
            "PYTHONUNBUFFERED": "1",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        }
    )
    return env


def _write_isolated_home(home: Path) -> None:
    home.mkdir(mode=0o700, parents=True, exist_ok=False)
    (home / "config.yaml").write_text(
        json.dumps(_minimal_config(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (home / "config.yaml").chmod(0o600)
    (home / ".no-bundled-skills").write_text("stage-c isolated smoke\n", encoding="utf-8")


def _wait_http_ready(proc: subprocess.Popen, base_url: str, api_key: str, log_path: Path) -> None:
    deadline = time.monotonic() + 90.0
    headers = {"Authorization": f"Bearer {api_key}"}
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SmokeError(
                "Isolated Hermes exited before becoming ready:\n"
                + _redacted_log_tail(log_path, api_key)
            )
        try:
            response = httpx.get(f"{base_url}/health", headers=headers, timeout=2.0)
            if response.is_success:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise SmokeError(
        f"Isolated Hermes did not become ready: {last_error}\n"
        + _redacted_log_tail(log_path, api_key)
    )


def _redacted_log_tail(path: Path, api_key: str, lines: int = 80) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "<log unavailable>"
    tail = "\n".join(text.splitlines()[-lines:])
    return tail.replace(api_key, "<redacted>")


def _enabled_concrete_tools(base_url: str, api_key: str) -> list[tuple[str, list[str]]]:
    response = httpx.get(
        f"{base_url}/v1/toolsets",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict) or data.get("platform") != "api_server":
        raise SmokeError("Isolated Hermes /v1/toolsets returned unexpected payload")
    rows = data.get("data")
    if not isinstance(rows, list):
        raise SmokeError("Isolated Hermes /v1/toolsets data is not a list")
    result: list[tuple[str, list[str]]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("enabled") is not True:
            continue
        tools = row.get("tools")
        concrete = [str(item) for item in tools] if isinstance(tools, list) else []
        if concrete:
            result.append((str(row.get("name") or ""), concrete))
    return result


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _assert_port_closed(port: int) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.2)
    raise SmokeError(f"Isolated Hermes port {port} is still accepting connections")


def _verify_source_commit() -> None:
    result = _run("git", "-C", str(HERMES_SOURCE), "rev-parse", "HEAD")
    if result.returncode != 0:
        raise SmokeError("Cannot resolve Hermes source commit")
    actual = result.stdout.strip()
    if actual != EXPECTED_HERMES_COMMIT:
        raise SmokeError(
            f"Unexpected Hermes source commit: {actual}; expected {EXPECTED_HERMES_COMMIT}"
        )


def main() -> int:
    print("===== STAGE C.2 ISOLATED HERMES ADAPTER E2E =====")
    for path in (HERMES_SOURCE, HERMES_PYTHON, PROD_CONFIG, PROD_ENV):
        if not path.exists():
            raise SmokeError(f"Required production artifact is missing: {path}")

    _verify_source_commit()
    prod_pid_before = _service_pid()
    prod_platforms_before = _production_platform_states()
    config_hash_before = _sha256(PROD_CONFIG)
    env_hash_before = _sha256(PROD_ENV)
    _assert_scheduler_idle(where="before isolated smoke")

    port = _free_loopback_port()
    api_key = secrets.token_hex(32)
    base_url = f"http://127.0.0.1:{port}"
    root = Path(
        tempfile.mkdtemp(
            prefix="stage-c-hermes-smoke-",
            dir="/tmp",
        )
    )
    # mkdtemp created the directory; recreate through our guarded writer.
    root.rmdir()
    log_path = root.with_suffix(".log")
    proc = None

    try:
        _write_isolated_home(root)
        env = _isolated_env(root, port, api_key)

        print("production Hermes PID:", prod_pid_before)
        print("isolated HERMES_HOME:", root)
        print("isolated API:", base_url)
        print("isolated API key: <redacted>")
        print("model route:", HERMES_LLM_ROUTE)

        log_stream = log_path.open("w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [
                    str(HERMES_PYTHON),
                    "-m",
                    "hermes_cli.main",
                    "gateway",
                    "run",
                    "--force",
                ],
                cwd=str(HERMES_SOURCE),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        finally:
            log_stream.close()

        _wait_http_ready(proc, base_url, api_key, log_path)
        print("PASS: isolated Hermes API ready")

        enabled = _enabled_concrete_tools(base_url, api_key)
        if enabled:
            details = "; ".join(
                f"{name}=[{', '.join(tools)}]" for name, tools in enabled
            )
            raise SmokeError(
                "Isolated api_server unexpectedly exposes tools; no agent turn executed: "
                + details
            )
        print("PASS: isolated api_server has zero enabled concrete tools")

        adapter = HermesAdapter(
            base_url=base_url,
            api_key=api_key,
            model_name="hermes-agent",
            timeout_seconds=300.0,
        )
        if adapter.health().status != "ready":
            raise SmokeError("HermesAdapter health is not ready against isolated API")

        request_id = f"req-{uuid4().hex}"
        session_id = f"stage-c-isolated-{uuid4().hex}"
        result = adapter.run_turn(
            AgentTurnRequest(
                request_id=request_id,
                session_id=session_id,
                message=(
                    "To jest izolowany test kontraktu Stage C bez narzędzi. "
                    f"Odpowiedz dokładnie: {EXPECTED_REPLY}"
                ),
                context={"domain": "shared", "purpose": "stage-c-isolated-smoke"},
                capability="reasoning",
            )
        )

        if result.request_id != request_id:
            raise SmokeError("HermesAdapter changed request_id")
        if result.session_id != session_id:
            raise SmokeError(
                f"HermesAdapter changed explicit session_id: {result.session_id!r}"
            )
        if result.provider != "hermes-local":
            raise SmokeError(f"Unexpected AgentProvider id: {result.provider!r}")
        if EXPECTED_REPLY not in result.content:
            raise SmokeError(
                "Isolated Hermes turn did not return expected marker: "
                f"{result.content[:240]!r}"
            )

        print("PASS: HermesAdapter -> isolated Hermes -> AI Gateway -> Qwen")
        print("provider:", result.provider)
        print("model:", result.model)
        print("response marker:", EXPECTED_REPLY)
        print(
            "usage:",
            {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            },
        )
        _wait_scheduler_idle()
        print("PASS: AI Gateway returned to active=0 queued=0 leases=0")
    finally:
        if proc is not None:
            _stop_process(proc)
        _assert_port_closed(port)
        shutil.rmtree(root, ignore_errors=True)
        try:
            log_path.unlink()
        except FileNotFoundError:
            pass

    prod_pid_after = _service_pid()
    prod_platforms_after = _production_platform_states()
    if prod_pid_after != prod_pid_before:
        raise SmokeError(
            f"Production Hermes PID changed: before={prod_pid_before} after={prod_pid_after}"
        )
    if _sha256(PROD_CONFIG) != config_hash_before:
        raise SmokeError("Production Hermes config.yaml changed during isolated smoke")
    if _sha256(PROD_ENV) != env_hash_before:
        raise SmokeError("Production Hermes .env changed during isolated smoke")
    if prod_platforms_after != prod_platforms_before:
        raise SmokeError(
            "Production Hermes platform states changed during isolated smoke: "
            f"before={prod_platforms_before} after={prod_platforms_after}"
        )

    print("PASS: production Hermes PID unchanged")
    print("PASS: production Hermes config/.env unchanged")
    print("PASS: production Hermes platform states unchanged")
    print("STAGE C.2 ISOLATED HERMES ADAPTER E2E: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SmokeError, httpx.HTTPError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
