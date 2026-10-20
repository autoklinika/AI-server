#!/usr/bin/env python3
"""Reproducible minimal Gateway-only patch on accepted stage-o source.

No production write. Fail closed if the accepted baseline changes.
"""
from pathlib import Path
from shutil import copytree, copy2, rmtree
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SRC = Path("/opt/ai-platform/current/services/ai-gateway/src/ai_bridge")
DEV = ROOT / "src/ai_bridge/gateway"
CAND = ROOT / "candidate/src/ai_bridge"
EXPECTED = {
    "app.py": "4501a344e0769337e8d14f57457c83fe840cd837e989197ab415861a371d4214",
    "resource_leases.py": "ee6569d2fbbe75b7ebfa78f73e4fe34efef76a62b343f56611bccf6f1b758a0b",
    "residency.py": "15c7d4ee863588918dd620625fe29348dd41d692b68814cdcfa51d4f3eba3a90",
}
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def change(s, a, b):
    if s.count(a) != 1:
        raise RuntimeError("unknown accepted source / anchor drift: " + a[:55])
    return s.replace(a, b)

assert Path("/opt/ai-platform/current").resolve() == Path("/opt/ai-platform/releases/stage-o-28e3ea214660")
for file, expected in EXPECTED.items():
    assert sha(SRC / "gateway" / file) == expected, "production file changed: " + file

if CAND.exists():
    raise RuntimeError("refusing to rewrite existing staged candidate")
CAND.parent.mkdir(parents=True, exist_ok=True)
copytree(SRC, CAND, ignore=lambda p, n: {"__pycache__"} & set(n))

p = CAND / "gateway/app.py"
s = p.read_text()
s = change(s, "from .jobs import JobLifecycle, JobMetadata\n",
              "from .jobs import JobLifecycle, JobMetadata\nfrom .engine_state import resource_manager_snapshot\n")
s = change(s, "from .residency import GPUResidency, ResidencyError\n",
              "from .residency import GPUResidency, ResidencyError\nfrom .engine_lifecycle import EngineLifecycleError, lifecycle_for\n")
s = change(s,
'''        async def finish(state: JobLifecycle) -> None:
            if lease_id:''',
'''        async def finish(state: JobLifecycle) -> None:
            await lifecycle_for(workload.provider).release(resource_leases.residency)
            if lease_id:''')
s = change(s,
'''        state = JobLifecycle.COMPLETED
        if not _requests_stream(body):''',
'''        # Uncertain preparation retains the scheduler ticket and prevents
        # another dispatch. Only supervised recovery may clear DIRTY.
        try:
            adapter = lifecycle_for(workload.provider)
            await adapter.prepare(resource_leases.residency)
        except BaseException:
            scheduler.admission_blocked = True
            resource_leases.residency.state = "blocked"
            try:
                resource_leases.residency._dirty()
            except OSError:
                pass  # retained ticket and in-memory fence still block
            raise

        state = JobLifecycle.COMPLETED
        if not _requests_stream(body):''')
s = change(s,
'''        snapshot = await scheduler.snapshot()
        accelerator_state = accelerator_state_snapshot(
            accelerator_registry, resource_leases.residency.snapshot()
        )
        return {
            "status": "ok" if ollama == "ok" and not scheduler.admission_blocked else "degraded",
            "gpu_residency": resource_leases.residency.snapshot(),''',
'''        snapshot = await scheduler.snapshot()
        residency = resource_leases.residency.snapshot()
        accelerator_state = accelerator_state_snapshot(
            accelerator_registry, residency
        )
        return {
            "status": "ok" if ollama == "ok" and not scheduler.admission_blocked else "degraded",
            "gpu_residency": residency,
            "resource_manager": resource_manager_snapshot(snapshot, residency),''')
s = change(s,
'''        snapshot["gpu_residency"] = resource_leases.residency.snapshot()
        snapshot["accelerators"]''',
'''        snapshot["gpu_residency"] = resource_leases.residency.snapshot()
        snapshot["resource_manager"] = resource_manager_snapshot(
            snapshot, snapshot["gpu_residency"]
        )
        snapshot["accelerators"]''')
s = change(s,
'''            # Only the existing external media executor is supported. Embedding
            # execution still enters through scheduled HTTP.
            if body["provider"] != "comfyui-local":
                raise ValueError()''',
'''            # Both the internal fixed adapter allowlist and the existing
            # provider/node/capability registry must allow the external use.
            lifecycle_for(body["provider"], external=True)''')
s = change(s,
'''        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="invalid external workload")''',
'''        except (ValueError, TypeError, EngineLifecycleError):
            raise HTTPException(status_code=400, detail="invalid external workload")''')
p.write_text(s)

p = CAND / "gateway/resource_leases.py"
s = p.read_text()
s = change(s, "from .admission import WorkloadBinding, external_workload\n",
              "from .admission import WorkloadBinding, external_workload\nfrom .engine_lifecycle import EngineLifecycleError, lifecycle_for\n")
s = change(s,
'''            if workload.provider != "comfyui-local":
                raise ResourceLeaseNotAllowed("external execution requires ComfyUI")''',
'''            try:
                adapter = lifecycle_for(workload.provider, external=True)
            except EngineLifecycleError as exc:
                raise ResourceLeaseNotAllowed(str(exc)) from exc''')
s = change(s,
'''        try:
            if self.residency:
                await self.residency.enter_media()
        except BaseException:''',
'''        try:
            await adapter.prepare(self.residency)
        except BaseException:''')
s = change(s,
'''                    or (self.residency and self.residency.state != "media")):
                return None
            return rec.external_workload''',
'''                    or rec.external_workload is None):
                return None
            adapter = lifecycle_for(rec.external_workload.provider, external=True)
            return rec.external_workload if adapter.verify_active(self.residency) else None''')
s = change(s,
'''        try:
            if self.residency:
                await self.residency.leave_media()
        except BaseException:''',
'''        try:
            adapter = lifecycle_for(rec.external_workload.provider, external=True)
            await adapter.release(self.residency)
        except BaseException:''')
p.write_text(s)
for name in ("engine_state.py", "engine_lifecycle.py"):
    copy2(DEV / name, CAND / "gateway" / name)
assert sha(CAND / "gateway/residency.py") == EXPECTED["residency.py"]
assert sha(CAND / "gateway/scheduler.py") == sha(SRC / "gateway/scheduler.py")
assert sha(CAND / "settings.py") == sha(SRC / "settings.py")
copytree(SRC.parents[1] / "benchmarks", ROOT / "candidate/benchmarks")
for name in ("app.py", "resource_leases.py", "engine_state.py", "engine_lifecycle.py"):
    print(name, sha(CAND / "gateway" / name))
# Freeze content hashes for the privileged installer and remove Python caches.
for cache in (ROOT / "candidate").rglob("__pycache__"):
    if cache.is_dir():
        rmtree(cache)
files = {}
for category in ("src", "benchmarks"):
    for path in ((ROOT / "candidate") / category).rglob("*"):
        if path.is_file():
            if path.is_symlink():
                raise RuntimeError("candidate symlink")
            files[path.relative_to(ROOT / "candidate").as_posix()] = sha(path)
import json
(ROOT / "RM_GATEWAY_CANDIDATE_SHA256.json").write_text(
    json.dumps(files, indent=2, sort_keys=True) + "\n")
print("CANDIDATE_MANIFEST_FILES=", len(files))
print("CANDIDATE_BACKPORT=BUILT_ACCEPTED_STAGE_O_BASE")
