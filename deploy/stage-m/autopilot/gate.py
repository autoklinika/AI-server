#!/usr/bin/env python3
"""Stage M production gate: CRT projections with full L/0004 rollback."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import traceback
from urllib.error import HTTPError
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "stage_j_gate_base", ROOT / "deploy/stage-j/autopilot/gate.py"
)
j = importlib.util.module_from_spec(spec)
spec.loader.exec_module(j)
e = j.e

BASE = Path("/opt/ai-platform/releases/stage-l-96f0ec239464")
BASE_SHA = "96f0ec239464f728aca2a7cf374670c9cd9be210"
STATE = Path("/var/lib/ai-platform/stage-m")
BASE_REVISION = "0004_ers_core_persistence"
TARGET_REVISION = "0005_crt_projection"
CHECKS = (
    "platform_api", "observability", "knowledge", "wvc",
    "hermes_connected", "hermes_inference", "messaging_boundary",
    "matched_clients", "media_preflight", "health", "ers", "crt", "crt_ai_boundary",
)

# Rebase the proven Stage E/J runtime primitives onto the accepted Stage L release.
e.D6 = BASE
e.D6_SHA = BASE_SHA
e.STATE = STATE


def require(condition: bool) -> None:
    return e.require(condition)


def verify_release(path: Path, _stage=None):
    stamp = dict(
        line.split("=", 1)
        for line in (path / "RELEASE").read_text(encoding="utf-8").splitlines()
    )
    stage = stamp["stage"].lower()
    require(stage in ("l", "m"))
    return j._original_verify(path, stage)


e.verify_release = verify_release


def db_scalar(sql: str) -> str:
    return e.run([
        "runuser", "-u", "postgres", "--",
        "psql", "-X", "-d", "ai_bridge", "-Atqc", sql,
    ])


def schema_version() -> str:
    return db_scalar("SELECT version_num FROM alembic_version")


def crt_table_count() -> int:
    return int(db_scalar(
        "SELECT count(*) FROM pg_tables "
        "WHERE schemaname='public' AND tablename LIKE 'crt_%'"
    ))


def recent_pre_m_backup() -> str:
    root = Path("/mnt/AI_Platform/Knowledge/manifests/manual")
    require(root.is_dir())
    candidates = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)
    require(bool(candidates))
    for directory in candidates:
        try:
            manifest_path = directory / "manifest.json"
            complete = directory / "COMPLETE"
            if not manifest_path.is_file() or not complete.is_file():
                continue
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("status") != "COMPLETE":
                continue
            if manifest.get("postgres", {}).get("schema_version") != BASE_REVISION:
                continue
            age = time.time() - manifest_path.stat().st_mtime
            if age > 4 * 3600:
                continue
            backup_id = str(manifest["backup_id"])
            require(complete.read_text().strip() == backup_id)
            dump_meta = manifest["postgres"]["dump"]
            dump = Path("/mnt/AI_Platform") / str(dump_meta["path"])
            require(dump.is_file())
            require(dump.stat().st_size == int(dump_meta["bytes"]))
            with dump.open("rb") as stream:
                require(hashlib.file_digest(stream, "sha256").hexdigest() == dump_meta["sha256"])
            e.run(["pg_restore", "-l", dump], timeout=60)
            e.run(["python3", ROOT / "deploy/stage-k/verify_backup.py", directory], timeout=300)
            paired = Path("/mnt/AI_Platform/ERS/case-store/manifests/manual") / backup_id
            e.run(["python3", ROOT / "deploy/stage-k/verify_backup.py", paired], timeout=300)
            return backup_id
        except Exception:
            continue
    raise RuntimeError("fresh pre-M manual backup not found")


def recent_active_crt_backup() -> str:
    # Validate the complete shared dump and CRT metadata contract before rollback
    # or final acceptance; the paired ERS set is required by the DR validator.
    root = Path("/mnt/AI_Platform/Knowledge/manifests/manual")
    for directory in sorted(root.iterdir(), reverse=True):
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file() or time.time() - manifest_path.stat().st_mtime > 4 * 3600:
            continue
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("postgres", {}).get("schema_version") != TARGET_REVISION:
            continue
        require(set(manifest["postgres"]["crt"]["tables"]) == set(CRT_TABLES))
        e.run(["python3", ROOT / "deploy/stage-k/verify_backup.py", directory], timeout=300)
        paired = Path("/mnt/AI_Platform/ERS/case-store/manifests/manual") / manifest["backup_id"]
        e.run(["python3", ROOT / "deploy/stage-k/verify_backup.py", paired], timeout=300)
        return manifest["backup_id"]
    raise RuntimeError("fresh active CRT backup not found")


CRT_TABLES = ("crt_projects", "crt_sessions", "crt_session_artifacts", "crt_ers_links", "crt_ai_findings")


def checkpoint(candidate, baseline):
    path = STATE / baseline["source_sha"] / "crt-checkpoint.json"
    recent_active_crt_backup()
    sql = e.run(["runuser", "-u", "postgres", "--", "pg_dump", "--data-only",
                 "--column-inserts", "--no-owner", "--no-privileges", "-d", "ai_bridge",
                 *["--table=" + table for table in CRT_TABLES]], timeout=900)
    # Keep each quiesced checkpoint immutable; atomically advance the pointer.
    saved = path.with_name("crt-checkpoint-" + uuid4().hex + ".json")
    counts = {table: int(db_scalar("SELECT count(*) FROM " + table)) for table in CRT_TABLES}
    e.write_once(saved, {"sql": sql, "sha256": hashlib.sha256(sql.encode()).hexdigest(), "counts": counts})
    pointer = path.with_name(".crt-checkpoint-" + uuid4().hex)
    pointer.symlink_to(saved.name)
    os.replace(pointer, path)


def restore_checkpoint(baseline):
    path = STATE / baseline["source_sha"] / "crt-checkpoint.json"
    if not path.exists():
        return
    value = e.read(path)
    require(hashlib.sha256(value["sql"].encode()).hexdigest() == value["sha256"])
    require(set(value["counts"]) == set(CRT_TABLES))
    require(all(type(n) is int and n >= 0 for n in value["counts"].values()))
    e.run(["runuser", "-u", "postgres", "--", "psql", "-X", "-v", "ON_ERROR_STOP=1",
           "--single-transaction", "-d", "ai_bridge"], input=value["sql"], timeout=900)
    for table, count in value["counts"].items():
        require(int(db_scalar("SELECT count(*) FROM " + table)) == count)


def production_op(candidate: Path, action: str, timeout: int = 900) -> dict:
    helper = candidate / "services/ai-bridge/deploy/stage-m/production_ops.py"
    python = candidate / "services/ai-bridge/.venv/bin/python"
    require(helper.is_file() and python.is_file())
    name, uid, home = e.worktree_account()
    raw = e.run([
        "runuser", "-u", name, "--", "env",
        f"HOME={home}", f"XDG_RUNTIME_DIR=/run/user/{uid}",
        str(python), str(helper), action,
    ], timeout=timeout)
    value = json.loads(raw)
    require(value.get("status") == "PASS")
    return value


def candidate_identity(sha: str) -> Path:
    return Path("/opt/ai-platform/releases") / ("stage-m-" + sha[:12])


def verify_client_sources(candidate: Path) -> None:
    for source in e.CLIENTS.values():
        require(
            (candidate / "services/ai-bridge" / source).read_bytes()
            == (BASE / "services/ai-bridge" / source).read_bytes()
        )


def atomic_current(target: Path) -> None:
    temporary = e.CURRENT.with_name(".stage-m-current-" + uuid4().hex)
    temporary.symlink_to(target)
    os.replace(temporary, e.CURRENT)


def switch_with_schema(
    target: Path,
    candidate: Path,
    cfg: dict,
    baseline: dict,
) -> dict | None:
    require(e.CURRENT.resolve(strict=False) in (BASE, candidate))
    verify_release(BASE)
    verify_release(candidate)
    require(e.clients() == baseline["clients"])
    activating = target == candidate
    mutating = False
    healthy = False
    import_result = None
    try:
        e.quiesce(baseline, allow_gateway_unavailable=not activating)
        e.comfy_idle()
        require(e.run([
            "systemctl", "show", "ai-bridge-analysis.service",
            "-p", "ActiveState", "--value",
        ]) == "inactive")
        mutating = True
        e.run(["systemctl", "stop", "ai-gateway.service", "ai-bridge.service"])

        if activating:
            require(schema_version() == BASE_REVISION)
            require(crt_table_count() == 0)
            production_op(candidate, "upgrade")
            restore_checkpoint(baseline)
            import_result = {"status": "PASS", "checkpoint_restored": (STATE / baseline["source_sha"] / "crt-checkpoint.json").exists()}
            production_op(candidate, "verify-active")
            atomic_current(candidate)
        else:
            current_schema = schema_version()
            require(current_schema in (BASE_REVISION, TARGET_REVISION))
            if current_schema == TARGET_REVISION:
                checkpoint(candidate, baseline)
                production_op(candidate, "downgrade")
            production_op(candidate, "verify-inactive")
            atomic_current(BASE)

        e.run(["systemctl", "start", "ai-gateway.service", "ai-bridge.service"])
        for _ in range(45):
            try:
                e.runtime(target, cfg, baseline)
                healthy = True
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("runtime failed after Stage M switch")
    finally:
        if healthy or not mutating:
            e.resume_ingress(baseline)
    return import_result


def bridge_base() -> str:
    url = e.bridge_health_url()
    require(url.endswith("/health"))
    return url[:-7]


def ers_smoke(candidate, active):
    verified = production_op(candidate, "verify-active" if active else "verify-inactive")
    require(bool(verified["cases"]))
    for case in verified["cases"]:
        response = e.fetch(bridge_base() + "/api/v1/ecu-repair/cases/" + str(case["id"]))
        require(response["case"]["status"] == case["status"])
        require(len(response["events"]) == response["case"]["row_version"])
    return {"status": "PASS", "cases": len(verified["cases"])}


def crt_absent():
    require(schema_version() == BASE_REVISION and crt_table_count() == 0)
    try:
        e.fetch(bridge_base() + "/api/v1/crt/sessions")
    except HTTPError as error:
        require(error.code == 404)
        return {"status": "absent"}
    raise RuntimeError("Stage L unexpectedly exposes CRT API")


def crt_smoke():
    base = bridge_base() + "/api/v1/crt"
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    # Static output from the actual CRT exporter; no external checkout at runtime.
    fixture = json.loads((ROOT / "tests/fixtures/crt_platform_v1.json").read_text())
    manifest = fixture["manifest"]
    manifest_hash = digest(manifest)
    session = e.fetch(base + "/manifests", manifest)
    require(e.fetch(base + "/manifests", manifest)["id"] == session["id"])
    url = base + "/sessions/" + session["id"]
    require(e.fetch(url)["manifest_hash"] == manifest_hash)
    require(any(row["id"] == session["id"] for row in e.fetch(base + "/sessions?project_id=" + manifest["project_id"])))
    # Link an existing case; do not create a duplicate repair case.
    case_id = db_scalar("SELECT id FROM ers_cases ORDER BY id LIMIT 1")
    link = e.fetch(url + "/ers-links", {"case_id": case_id, "role": "gate_reference", "actor_id": "stage-m-gate"})
    require(link["active"])
    require(not e.fetch(url + "/ers-links/" + case_id + "/gate_reference/unlink", {"actor_id": "stage-m-gate"})["active"])
    context = fixture["context"]
    finding = e.fetch(url + "/findings", {"statement": "Synthetic advisory gate fixture",
        "provider": "gate-fixture", "model": "contract-v1", "context": context,
        "context_hash": digest(context), "actor_id": "stage-m-gate"})
    require(finding["status"] == "suggested")
    require(any(row["id"] == finding["id"] for row in e.fetch(url + "/findings")))
    for payload, suffix, code in (({**manifest, "schema_version": 999}, "/manifests", 422),
        ({**context, "question": "x" * 2049}, "/sessions/" + session["id"] + "/signal-hypothesis", 422)):
        try:
            e.fetch(base + suffix, payload)
        except HTTPError as error:
            require(error.code == code)
        else:
            raise RuntimeError("CRT boundary did not fail closed")
    generated = e.fetch(url + "/signal-hypothesis", context)
    require(generated["status"] == "suggested")
    require(all(isinstance(generated.get(key), str) and generated[key].strip()
                and generated[key] != "unknown" for key in ("provider", "model")))
    return {"status": "PASS", "ai_execution": "PASS", "session_id": session["id"],
            "provider": generated["provider"], "model": generated["model"]}


def smoke(phase: str, target: Path, candidate: Path, cfg: dict, baseline: dict, state: Path) -> None:
    e.runtime(target, cfg, baseline)
    before = [
        e.identity(unit)
        for unit in ("ai-gateway.service", "ai-bridge.service", "comfyui.service")
    ]
    challenge = uuid4().hex
    e.write_once(state / (phase + "-started.json"), {
        "challenge": challenge,
        "release_id": target.name,
    })

    timer_active = baseline["analysis_timer_active"] == "active"
    if timer_active:
        e.run(["systemctl", "stop", "ai-bridge-analysis.timer"])
    try:
        e.api_smoke(cfg)
        observability = j.observability_snapshot(cfg)
        knowledge = j.knowledge_smoke(cfg)
        ers = ers_smoke(candidate, target == candidate)
        crt = crt_smoke() if target == candidate else crt_absent()
        e.preflight_step("smoke_wvc", e.wvc_smoke)
        e.preflight_step("smoke_hermes_connected", e.hermes_state)
        e.preflight_step(
            "smoke_hermes_inference",
            lambda: e.hermes_oneshot_smoke(keep_ingress_paused=False),
        )
        e.preflight_step("smoke_messaging_boundary", j.messaging_boundary_smoke_with_retry)
        require(e.clients() == baseline["clients"])
        e.media_preflight()
        e.runtime(target, cfg, baseline)
        require(before == [
            e.identity(unit)
            for unit in ("ai-gateway.service", "ai-bridge.service", "comfyui.service")
        ])
    finally:
        if timer_active:
            e.run(["systemctl", "start", "ai-bridge-analysis.timer"])

    e.write_once(state / (phase + ".json"), {
        "schema_version": 1,
        "release_id": target.name,
        "challenge": challenge,
        "checks": {key: True for key in CHECKS},
        "observability": observability,
        "knowledge": knowledge,
        "ers": ers,
        "crt": crt,
        "time": int(time.time()),
        "services": before,
    })


def recoverable_smoke(
    canonical_phase: str,
    target: Path,
    candidate: Path,
    cfg: dict,
    baseline: dict,
    state: Path,
) -> None:
    completed = state / (canonical_phase + ".json")
    require(not completed.exists())
    phase = canonical_phase
    if (state / (canonical_phase + "-started.json")).exists():
        phase = canonical_phase + "-recovery-" + uuid4().hex
    smoke(phase, target, candidate, cfg, baseline, state)
    if phase != canonical_phase:
        evidence = dict(e.read(state / (phase + ".json")))
        evidence["recovered_from"] = phase
        e.write_once(completed, evidence)


def main(step: str) -> None:
    cfg = e.config()
    sha = e.git_run(["rev-parse", "HEAD"])
    candidate = candidate_identity(sha)
    state = STATE / sha

    if step == "00_preflight":
        e.preflight(cfg)
        require(schema_version() == BASE_REVISION)
        require(crt_table_count() == 0)
        recent_pre_m_backup()
        return

    require(os.geteuid() == 0)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / "executor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

        if step == "10_build_install":
            e.preflight(cfg)
            require(schema_version() == BASE_REVISION)
            require(crt_table_count() == 0)
            require(not state.exists() and not candidate.exists())
            require(not e.git_run(["status", "--porcelain"]))
            backup_id = recent_pre_m_backup()
            state.mkdir(mode=0o700)
            baseline = {
                "rollback": BASE.name,
                "rollback_sha": BASE_SHA,
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
                "rollback_checksums": e.digest(BASE / "metadata/SHA256SUMS"),
                "pre_m_backup_id": backup_id,
                "base_schema": BASE_REVISION,
            }
            require(baseline["hermes_active"] == "active")
            require(baseline["analysis_timer_active"] == "active")
            e.write_once(state / "baseline.json", baseline)
            e.run([
                "bash", ROOT / "deploy/stage-m/build_release.sh",
                candidate, candidate.name,
            ], timeout=1800, cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            require(verify_release(candidate)["source_git_sha"] == sha)
            verify_client_sources(candidate)
            e.runtime(BASE, cfg, baseline)
            e.write_once(state / "installed.json", {
                "candidate": candidate.name,
                "source_sha": sha,
                "checksums": e.digest(candidate / "metadata/SHA256SUMS"),
            })
            return

        baseline = e.read(state / "baseline.json")
        require(baseline["source_sha"] == sha)
        require(baseline["rollback_sha"] == BASE_SHA)
        require(baseline["candidate"] == candidate.name)
        require(baseline["rollback"] == BASE.name)
        require(e.digest(BASE / "metadata/SHA256SUMS") == baseline["rollback_checksums"])

        if step == "40_rollback":
            switch_with_schema(BASE, candidate, cfg, baseline)
            if not (state / "rollback.json").exists():
                e.write_once(state / "rollback.json", {
                    "release_id": BASE.name,
                    "schema": schema_version(),
                })
            return

        if step == "50_rollback_smoke":
            require((state / "rollback.json").is_file())
            recoverable_smoke("rollback-smoke", BASE, candidate, cfg, baseline, state)
            return

        installed = e.read(state / "installed.json")
        require(installed["source_sha"] == sha)
        require(e.digest(candidate / "metadata/SHA256SUMS") == installed["checksums"])

        if step in ("20_cutover", "60_reactivate"):
            if step == "60_reactivate":
                require((state / "rollback-smoke.json").is_file())
                require((state / "crt-checkpoint.json").is_file())
            else:
                require(not (state / "rollback.json").exists())
            require(not (state / (step + ".json")).exists())
            imported = switch_with_schema(candidate, candidate, cfg, baseline)
            require(imported is not None)
            e.write_once(state / (step + ".json"), {
                "release_id": candidate.name,
                "schema": schema_version(),
                "import": imported,
            })
            return

        if step in ("30_smoke", "70_reactivate_smoke"):
            phase, prior = {
                "30_smoke": ("candidate-smoke", "20_cutover"),
                "70_reactivate_smoke": ("final-smoke", "60_reactivate"),
            }[step]
            require((state / (prior + ".json")).is_file())
            recoverable_smoke(phase, candidate, candidate, cfg, baseline, state)
            return

        if step == "90_finalize":
            require(verify_release(candidate)["source_git_sha"] == sha)
            e.runtime(candidate, cfg, baseline)
            require(schema_version() == TARGET_REVISION)
            production_op(candidate, "verify-active")
            final_backup_id = recent_active_crt_backup()
            evidence = [
                e.read(state / (phase + ".json"))
                for phase in ("candidate-smoke", "rollback-smoke", "final-smoke")
            ]
            require([row["release_id"] for row in evidence] == [
                candidate.name, BASE.name, candidate.name,
            ])
            require(len({row["challenge"] for row in evidence}) == 3)
            require(all(set(row["checks"]) == set(CHECKS) for row in evidence))
            require(all(all(row["checks"].values()) for row in evidence))
            require(evidence[0]["ers"]["status"] == "PASS")
            require(evidence[1]["ers"]["status"] == "PASS")
            require(evidence[1]["crt"]["status"] == "absent")
            require(evidence[0]["crt"]["status"] == evidence[2]["crt"]["status"] == "PASS")
            require(evidence[2]["ers"]["status"] == "PASS")
            require(evidence[0]["knowledge"]["rag_citations"] >= 1)
            require(evidence[1]["knowledge"]["rag_citations"] >= 1)
            require(evidence[2]["knowledge"]["rag_citations"] >= 1)
            require(evidence[0]["time"] <= evidence[1]["time"] <= evidence[2]["time"])
            e.write_once(state / "complete.json", {
                "source_sha": sha,
                "candidate": candidate.name,
                "rollback": BASE.name,
                "base_schema": BASE_REVISION,
                "target_schema": TARGET_REVISION,
                "pre_m_backup_id": baseline["pre_m_backup_id"],
                "final_backup_id": final_backup_id,
                "rollback_cycle": "PASS",
                "checks": list(CHECKS),
                "time": int(time.time()),
            })
            return

        raise ValueError("unknown step")


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except BaseException as error:
        frames = [
            frame for frame in traceback.extract_tb(error.__traceback__)
            if str(ROOT / "deploy") in frame.filename
        ]
        location = "/".join(
            f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
            for frame in frames
        )
        print(
            f"GATE_FAIL={type(error).__name__} location={location}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print("PASS: Stage M " + sys.argv[1])
