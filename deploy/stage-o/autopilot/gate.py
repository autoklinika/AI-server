#!/usr/bin/env python3
"""Stage O production gate: runtime-only AI Control Center deployment."""
from __future__ import annotations

import fcntl
import importlib.util
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "stage_o_gate_base", ROOT / "deploy/stage-e/autopilot/gate.py"
)
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)

RELEASES = Path("/opt/ai-platform/releases")
INITIAL_BASE = RELEASES / "stage-m-8e6d21eff33d"
INITIAL_BASE_SHA = "8e6d21eff33de73d84fdfbff43b952dd34db838c"
STATE = Path("/var/lib/ai-platform/stage-o")
TARGET_REVISION = "0005_crt_projection"
CRT_TABLES = {
    "crt_projects",
    "crt_sessions",
    "crt_session_artifacts",
    "crt_ers_links",
    "crt_ai_findings",
}

_original_verify = e.verify_release
e.D6 = INITIAL_BASE
e.STATE = STATE


def require(condition: bool) -> None:
    e.require(condition)


def verify_release(path: Path):
    stamp = dict(
        line.split("=", 1)
        for line in (path / "RELEASE").read_text(encoding="utf-8").splitlines()
    )
    stage = stamp["stage"].lower()
    require(stage in ("m", "o"))
    return _original_verify(path, stage)


e.verify_release = lambda path, _stage=None: verify_release(path)


def accepted_stage_o(path: Path, stamp: dict | None = None) -> dict:
    stamp = stamp or verify_release(path)
    require(stamp["stage"] == "O")
    source_sha = stamp["source_git_sha"]
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha) is not None)
    require(path == candidate_identity(source_sha))
    evidence = e.read(STATE / source_sha / "accepted.json")
    require(evidence["status"] == "PASS")
    require(evidence["release_id"] == path.name)
    require(evidence["source_sha"] == source_sha)
    require(evidence["schema"] == TARGET_REVISION)
    require(evidence["control_center_contract_version"] == 1)
    return evidence


def active_rollback_baseline() -> tuple[Path, dict]:
    current = e.CURRENT.resolve(strict=True)
    stamp = verify_release(current)
    if current == INITIAL_BASE:
        require(stamp["stage"] == "M")
        require(stamp["source_git_sha"] == INITIAL_BASE_SHA)
    else:
        accepted_stage_o(current, stamp)
    e.D6 = current
    return current, stamp


def baseline_release(baseline: dict) -> tuple[Path, dict]:
    name = baseline["rollback"]
    require(re.fullmatch(r"stage-[mo]-[A-Za-z0-9_.-]+", name) is not None)
    rollback = (RELEASES / name).resolve(strict=True)
    require(rollback.parent == RELEASES)
    stamp = verify_release(rollback)
    require(stamp["source_git_sha"] == baseline["rollback_sha"])
    require(stamp["stage"] == baseline["rollback_stage"])
    if rollback == INITIAL_BASE:
        require(stamp["source_git_sha"] == INITIAL_BASE_SHA)
    else:
        accepted_stage_o(rollback, stamp)
    require(e.digest(rollback / "metadata/SHA256SUMS") == baseline["rollback_checksums"])
    e.D6 = rollback
    return rollback, stamp


def db_scalar(sql: str) -> str:
    return e.run([
        "runuser", "-u", "postgres", "--",
        "psql", "-X", "-d", "ai_bridge", "-Atqc", sql,
    ])


def schema_version() -> str:
    return db_scalar("SELECT version_num FROM alembic_version")


def crt_tables() -> set[str]:
    raw = db_scalar(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname='public' AND tablename LIKE 'crt_%' ORDER BY tablename"
    )
    return {line for line in raw.splitlines() if line}


def bridge_base() -> str:
    value = e.bridge_health_url()
    require(value.endswith("/health"))
    return value[:-7]


def text_fetch(url: str) -> tuple[int, str, dict]:
    request = Request(url, headers={"Accept": "text/html,application/javascript,*/*"})
    with urlopen(request, timeout=20) as response:
        return (
            response.status,
            response.read().decode("utf-8", errors="replace"),
            {key.lower(): value for key, value in response.headers.items()},
        )


def preflight(cfg: dict) -> tuple[Path, dict]:
    rollback, stamp = active_rollback_baseline()
    require(schema_version() == TARGET_REVISION)
    require(crt_tables() == CRT_TABLES)
    e.preflight_runtime(cfg)
    for unit in ("ai-gateway.service", "ai-bridge.service", "ai-bridge-analysis.service"):
        require(
            e.run(["systemctl", "show", unit, "-p", "NeedDaemonReload", "--value"])
            == "no"
        )
    require(
        e.user_systemctl([
            "show", "hermes-gateway.service", "-p", "ActiveState", "--value"
        ])
        == "active"
    )
    e.hermes_state()
    e.media_preflight()
    return rollback, stamp


def candidate_identity(sha: str) -> Path:
    return Path("/opt/ai-platform/releases") / ("stage-o-" + sha[:12])


def verify_client_sources(candidate: Path, rollback: Path) -> None:
    for source in e.CLIENTS.values():
        require(
            (candidate / "services/ai-bridge" / source).read_bytes()
            == (rollback / "services/ai-bridge" / source).read_bytes()
        )


def atomic_current(target: Path) -> None:
    temporary = e.CURRENT.with_name(".stage-o-current-" + uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, e.CURRENT)


def switch(target: Path, candidate: Path, cfg: dict, baseline: dict) -> None:
    rollback, _stamp = baseline_release(baseline)
    require(e.CURRENT.resolve(strict=False) in (rollback, candidate))
    verify_release(candidate)
    require(e.clients() == baseline["clients"])
    require(schema_version() == TARGET_REVISION)
    require(crt_tables() == CRT_TABLES)

    mutating = False
    healthy = False
    try:
        e.quiesce(baseline, allow_gateway_unavailable=(target == rollback))
        e.comfy_idle()
        require(
            e.run([
                "systemctl", "show", "ai-bridge-analysis.service",
                "-p", "ActiveState", "--value",
            ])
            == "inactive"
        )
        mutating = True
        e.run(["systemctl", "stop", "ai-gateway.service", "ai-bridge.service"])
        atomic_current(target)
        e.run(["systemctl", "start", "ai-gateway.service", "ai-bridge.service"])
        for _ in range(45):
            try:
                e.runtime(target, cfg, baseline)
                require(schema_version() == TARGET_REVISION)
                require(crt_tables() == CRT_TABLES)
                healthy = True
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Stage O runtime failed after switch")
    finally:
        if healthy or not mutating:
            e.resume_ingress(baseline)


def control_center_absent() -> None:
    for url in (bridge_base() + "/control/", e.GATEWAY + "/control/"):
        try:
            text_fetch(url)
        except HTTPError as error:
            require(error.code == 404)
        else:
            raise RuntimeError("Control Center unexpectedly present in rollback baseline")


def control_center_smoke(*, require_operations: bool = True) -> dict:
    bridge = bridge_base()
    status, html, headers = text_fetch(bridge + "/control/")
    require(status == 200 and "AI Control Center" in html)
    require("frame-ancestors 'none'" in headers.get("content-security-policy", ""))

    status, javascript, _headers = text_fetch(bridge + "/control/assets/app.js")
    require(status == 200)
    require('const API_BASE = "/control/api/v1"' in javascript)
    lowered = javascript.lower()
    require(
        all(
            word not in lowered
            for word in ("qdrant", "ollama", "postgres", "localstorage")
        )
    )

    manifest = e.fetch(bridge + "/control/manifest.webmanifest")
    require(manifest["start_url"] == "/control/")
    require(manifest["display"] == "standalone")

    health = e.fetch(bridge + "/control/api/v1/health")
    require(health["readiness"] is True)
    if require_operations:
        operations = e.fetch(bridge + "/control/api/v1/operations")
        require(operations["release"]["stage"] == "O")
        require(isinstance(operations["storage"], list))
        require("backup" in operations)
    else:
        try:
            operations = e.fetch(bridge + "/control/api/v1/operations")
        except HTTPError as error:
            require(error.code in (403, 404))
        else:
            require(operations["release"]["stage"] == "O")
            require(isinstance(operations["storage"], list))
            require("backup" in operations)
    apps = e.fetch(bridge + "/control/api/v1/apps")["apps"]
    app_ids = [item["id"] for item in apps]
    require(app_ids[:3] == ["knowledge", "benchmarks", "ers"])
    if require_operations:
        require(app_ids == ["knowledge", "benchmarks", "ers", "observability", "system-map", "incidents"])
        traces = e.fetch(bridge + "/control/api/v1/traces")
        require(traces["retention"]["persistent"] is False)
        require(traces["retention"]["limit"] == 256)
        system_map = e.fetch(bridge + "/control/api/v1/system-map")
        require(system_map["retention"]["trace_sample_limit"] == 64)
        require(any(node["id"] == "platform-api" for node in system_map["nodes"]))
        incidents = e.fetch(bridge + "/control/api/v1/incidents")
        require(incidents["retention"]["source"] == "flight-recorder")
        agents = e.fetch(bridge + "/control/api/v1/agents")
        require(isinstance(agents["agents"], list))
        require(agents["retention"]["raw_logs_exposed"] is False)
        logs = e.fetch(bridge + "/control/api/v1/logs")
        require(isinstance(logs["logs"], list))
        require(logs["retention"]["raw_logs_exposed"] is False)
        require(logs["retention"]["limit"] == 256)
    else:
        require(app_ids in (
            ["knowledge", "benchmarks", "ers"],
            ["knowledge", "benchmarks", "ers", "observability"],
            ["knowledge", "benchmarks", "ers", "observability", "system-map"],
            ["knowledge", "benchmarks", "ers", "observability", "system-map", "incidents"],
        ))

    search = e.fetch(
        bridge + "/control/api/v1/knowledge/search",
        {
            "schema_version": 1,
            "query": "0 281 007 439",
            "mode": "exact",
            "context": {"domain": "ecu-repair"},
            "limit": 1,
        },
    )
    require(search["results"])

    try:
        e.fetch(
            bridge + "/control/api/v1/ai",
            {"messages": [{"role": "user", "content": "must be blocked"}]},
        )
    except HTTPError as error:
        require(error.code == 403)
    else:
        raise RuntimeError("Control Center exposed arbitrary Platform AI endpoint")

    status, gateway_html, _headers = text_fetch(e.GATEWAY + "/control/")
    require(status == 200 and "AI Control Center" in gateway_html)
    return {
        "status": "PASS",
        "apps": [item["id"] for item in apps],
        "knowledge_results": len(search["results"]),
    }


def platform_smoke(active: bool, *, require_observability: bool = False) -> None:
    base = e.GATEWAY + "/api/v1"
    require(e.fetch(base + "/health")["readiness"] is True)
    if active:
        apps = e.fetch(base + "/apps")["apps"]
        app_ids = [item["id"] for item in apps]
        require(app_ids[:3] == ["knowledge", "benchmarks", "ers"])
        if require_observability:
            require(app_ids == ["knowledge", "benchmarks", "ers", "observability", "system-map", "incidents"])
            traces = e.fetch(base + "/traces")
            require(traces["retention"]["limit"] == 256)
            system_map = e.fetch(base + "/system-map")
            require(system_map["retention"]["trace_sample_limit"] == 64)
            incidents = e.fetch(base + "/incidents")
            require(incidents["retention"]["source"] == "flight-recorder")
            agents = e.fetch(base + "/agents")
            require(isinstance(agents["agents"], list))
            require(agents["retention"]["raw_logs_exposed"] is False)
            logs = e.fetch(base + "/logs")
            require(isinstance(logs["logs"], list))
            require(logs["retention"]["raw_logs_exposed"] is False)
            require(logs["retention"]["limit"] == 256)
        else:
            require(app_ids in (
                ["knowledge", "benchmarks", "ers"],
                ["knowledge", "benchmarks", "ers", "observability"],
                ["knowledge", "benchmarks", "ers", "observability", "system-map"],
                ["knowledge", "benchmarks", "ers", "observability", "system-map", "incidents"],
            ))
    else:
        try:
            e.fetch(base + "/apps")
        except HTTPError as error:
            require(error.code == 404)
        else:
            raise RuntimeError("Stage M baseline unexpectedly exposes app registry")


def smoke(
    phase: str,
    target: Path,
    candidate: Path,
    cfg: dict,
    baseline: dict,
    state: Path,
) -> None:
    e.runtime(target, cfg, baseline)
    require(schema_version() == TARGET_REVISION)
    require(crt_tables() == CRT_TABLES)
    active = target == candidate
    has_control_center = active or baseline["rollback_stage"] == "O"
    platform_smoke(has_control_center, require_observability=active)
    evidence = (
        control_center_smoke(require_operations=active)
        if has_control_center
        else {"status": "ABSENT"}
    )
    if not has_control_center:
        control_center_absent()
    e.hermes_state()
    e.media_preflight()
    e.write_once(
        state / (phase + ".json"),
        {
            "release_id": target.name,
            "schema": schema_version(),
            "control_center": evidence,
            "time": int(time.time()),
        },
    )


def recover_active_unaccepted_candidate(cfg: dict) -> None:
    """Rollback a prior Stage O candidate whose smoke failed before acceptance."""
    active = e.CURRENT.resolve(strict=True)
    require(active.name.startswith("stage-o-"))
    stamp = verify_release(active)
    source_sha = stamp["source_git_sha"]
    require(re.fullmatch(r"[0-9a-f]{40}", source_sha) is not None)

    prior_state = STATE / source_sha
    baseline = e.read(prior_state / "baseline.json")
    installed = e.read(prior_state / "installed.json")
    rollback, _rollback_stamp = baseline_release(baseline)
    require(baseline["source_sha"] == source_sha)
    require(baseline["candidate"] == active.name)
    require(baseline["schema"] == TARGET_REVISION)
    require(installed["source_sha"] == source_sha)
    require(installed["candidate"] == active.name)
    require((prior_state / "20_cutover.json").is_file())
    require(not (prior_state / "accepted.json").exists())
    require(
        e.digest(active / "metadata/SHA256SUMS") == installed["checksums"]
    )

    switch(rollback, active, cfg, baseline)
    rollback_evidence = prior_state / "rollback.json"
    if not rollback_evidence.exists():
        e.write_once(
            rollback_evidence,
            {"release_id": rollback.name, "recovery": True},
        )
    print("STAGE_O_RECOVERY_ROLLBACK=PASS")


def main(step: str) -> None:
    cfg = e.config()
    sha = e.git_run(["rev-parse", "HEAD"])
    require(re.fullmatch(r"[0-9a-f]{40}", sha) is not None)
    candidate = candidate_identity(sha)
    state = STATE / sha

    require(os.geteuid() == 0)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "executor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        current = e.CURRENT.resolve(strict=False)
        if (
            step == "40_rollback"
            and current != INITIAL_BASE
            and current != candidate
            and current.name.startswith("stage-o-")
        ):
            recover_active_unaccepted_candidate(cfg)
            return

        if step == "00_preflight":
            preflight(cfg)
            return

        if step == "10_build_install":
            rollback, rollback_stamp = preflight(cfg)
            require(not state.exists() and not candidate.exists())
            require(not e.git_run(["status", "--porcelain"]))
            state.mkdir(mode=0o700)
            baseline = {
                "rollback": rollback.name,
                "rollback_sha": rollback_stamp["source_git_sha"],
                "rollback_stage": rollback_stamp["stage"],
                "candidate": candidate.name,
                "source_sha": sha,
                "clients": e.clients(),
                "comfy": e.identity("comfyui.service"),
                "hermes_active": e.user_systemctl([
                    "show", "hermes-gateway.service", "-p", "ActiveState", "--value"
                ]),
                "analysis_timer_active": e.run([
                    "systemctl", "show", "ai-bridge-analysis.timer",
                    "-p", "ActiveState", "--value",
                ]),
                "rollback_checksums": e.digest(rollback / "metadata/SHA256SUMS"),
                "schema": schema_version(),
            }
            require(baseline["schema"] == TARGET_REVISION)
            e.write_once(state / "baseline.json", baseline)
            e.run(
                [
                    "bash",
                    ROOT / "deploy/stage-o/build_release.sh",
                    candidate,
                    candidate.name,
                ],
                timeout=1800,
                cwd=ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            stamp = verify_release(candidate)
            require(stamp["source_git_sha"] == sha)
            require(stamp["control_center_contract_version"] == "1")
            verify_client_sources(candidate, rollback)
            e.runtime(rollback, cfg, baseline)
            e.write_once(
                state / "installed.json",
                {
                    "candidate": candidate.name,
                    "source_sha": sha,
                    "checksums": e.digest(candidate / "metadata/SHA256SUMS"),
                },
            )
            return

        baseline = e.read(state / "baseline.json")
        require(baseline["source_sha"] == sha)
        require(baseline["schema"] == TARGET_REVISION)
        rollback, _rollback_stamp = baseline_release(baseline)

        installed = e.read(state / "installed.json")
        require(installed["source_sha"] == sha)
        require(
            e.digest(candidate / "metadata/SHA256SUMS") == installed["checksums"]
        )

        if step == "20_cutover":
            require(not (state / "20_cutover.json").exists())
            switch(candidate, candidate, cfg, baseline)
            e.write_once(
                state / "20_cutover.json",
                {"release_id": candidate.name},
            )
            return

        if step == "30_smoke":
            require((state / "20_cutover.json").is_file())
            smoke("candidate-smoke", candidate, candidate, cfg, baseline, state)
            return

        if step == "40_rollback":
            require((state / "20_cutover.json").is_file())
            switch(rollback, candidate, cfg, baseline)
            e.write_once(state / "rollback.json", {"release_id": rollback.name})
            return

        if step == "50_rollback_smoke":
            require((state / "rollback.json").is_file())
            smoke("rollback-smoke", rollback, candidate, cfg, baseline, state)
            return

        if step == "60_reactivate":
            require((state / "rollback-smoke.json").is_file())
            switch(candidate, candidate, cfg, baseline)
            e.write_once(
                state / "reactivate.json",
                {"release_id": candidate.name},
            )
            return

        if step == "70_reactivate_smoke":
            require((state / "reactivate.json").is_file())
            smoke("final-smoke", candidate, candidate, cfg, baseline, state)
            return

        if step == "90_finalize":
            require((state / "final-smoke.json").is_file())
            require(e.CURRENT.resolve(strict=True) == candidate)
            require(schema_version() == TARGET_REVISION)
            require(crt_tables() == CRT_TABLES)
            e.runtime(candidate, cfg, baseline)
            accepted = {
                "status": "PASS",
                "release_id": candidate.name,
                "source_sha": sha,
                "schema": TARGET_REVISION,
                "control_center_contract_version": 1,
                "time": int(time.time()),
            }
            if not (state / "accepted.json").exists():
                e.write_once(state / "accepted.json", accepted)
            print("STAGE_O_PRODUCTION_GATE=PASS")
            return

        raise RuntimeError("unknown Stage O step")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except BaseException:
        print("STAGE_O_GATE=FAIL", file=sys.stderr)
        raise
