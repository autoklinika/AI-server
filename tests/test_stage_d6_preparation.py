"""D.6 offline release checks and combined admission failure coverage."""
import importlib.util
from pathlib import Path
import re

import pytest

from ai_bridge.gateway.admission import binding
from ai_bridge.gateway.resource_leases import ResourceLeaseRegistry
from ai_bridge.gateway.scheduler import PriorityScheduler

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("d6metadata", ROOT / "deploy/stage-d/validate_release_metadata.py")
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)


@pytest.fixture
def candidate(tmp_path):
    # Exercise actual builder heredocs without bypassing its clean-source guard,
    # creating commits, installing dependencies, or calling production tools.
    builder = (ROOT / "deploy/stage-d/build_release.sh").read_text()
    for tag, target in (("MANIFEST", "metadata/release-manifest.yaml"), ("STAMP", "RELEASE")):
        content = re.search(r"<<" + tag + r"\n(.*?)\n" + tag, builder, re.S)[1]
        content = content.replace("$RELEASE_ID", "stage-d6-test").replace("$SOURCE_SHA", "a" * 40)
        path = tmp_path / target
        path.parent.mkdir(exist_ok=True)
        path.write_text(content + "\n")
    return tmp_path


def test_builder_emits_consistent_complete_candidate(candidate):
    metadata.validate(candidate)


@pytest.mark.parametrize("key", metadata.VERSIONS)
def test_stamp_rejects_missing_or_wrong_version(candidate, key):
    stamp = candidate / "RELEASE"
    stamp.write_text(re.sub(rf"^{key}=.*\n", "", stamp.read_text(), flags=re.M))
    with pytest.raises(ValueError):
        metadata.validate(candidate)


@pytest.mark.parametrize("change", [
    ("phase: D.6", "phase: D.0"),
    ("resource_manager: 2", "resource_manager: 1"),
    ("provider_registry: 1", "provider_registry: 2"),
    ("llm_provider: 1", "llm_provider: 2"),
    ("job_state: 1", "job_state: 1\n    job_state: 1"),
    ("source_git_sha: " + "a" * 40, "source_git_sha: " + "b" * 40),
])
def test_manifest_drift_is_rejected(candidate, change):
    path = candidate / "metadata/release-manifest.yaml"
    path.write_text(path.read_text().replace(*change))
    with pytest.raises(ValueError):
        metadata.validate(candidate)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("capacity", [1, 2, 4])
async def test_idle_llm_workers_ttl_dispatch_priority_fifo_and_cancel(capacity, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("ai_bridge.gateway.resource_leases.monotonic", lambda: now[0])
    scheduler = PriorityScheduler(max_concurrency=capacity)
    leases = ResourceLeaseRegistry(scheduler, ttl_seconds=10)
    from ai_bridge.gateway.admission import external_workload
    from ai_bridge.gateway.jobs import JobMetadata
    metadata = JobMetadata(workload=external_workload(scheduler.registry, "llm"))
    owners = [await leases.create(priority=50, source="llm", metadata=metadata) for _ in range(capacity)]
    queued = [await leases.create(priority=p, source="test", metadata=metadata) for p in [200, 10, 50, 10, 100]]
    cancelled = queued.pop(2)
    await leases.release(cancelled["lease_id"])
    now[0] = 10
    assert await leases.reap_expired() == 0  # strict TTL boundary
    for item in queued:
        await leases.heartbeat(item["lease_id"])
    now[0] = 11
    assert await leases.reap_expired() == capacity
    ordered = sorted(queued, key=lambda item: (item["priority"], item["job_id"]))
    for index, item in enumerate(ordered):
        snap = await scheduler.snapshot()
        assert snap["active_count"] <= capacity
        assert {job["job_id"] for job in snap["active"]} == {
            expected["job_id"] for expected in ordered[index:index + capacity]}
        assert (await leases.describe(item["lease_id"]))["state"] == "active"
        await leases.release(item["lease_id"])
    snap = await scheduler.snapshot()
    assert snap["active_count"] == snap["queued_count"] == 0
    assert (await leases.snapshot())["lease_count"] == 0
    assert sum(job["state"] == "expired" for job in snap["recent_jobs"]) == capacity
    assert sum(job["state"] == "cancelled" for job in snap["recent_jobs"]) == 1


def load_tool(name, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "deploy/stage-d"))
    spec = importlib.util.spec_from_file_location(name, ROOT / f"deploy/stage-d/{name}.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def checksums(root):
    import hashlib
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    (root / "metadata/SHA256SUMS").write_text("".join(
        hashlib.sha256(p.read_bytes()).hexdigest() + "  ./" + str(p.relative_to(root)) + "\n" for p in files))


@pytest.mark.parametrize("failure", [None, "tampered", "missing", "same", "escape"])
def test_rollback_artifact_guard(candidate, tmp_path, monkeypatch, failure):
    import shutil
    tool = load_tool("validate_rollback_readiness", monkeypatch)
    for service in ("ai-bridge", "ai-gateway"):
        (candidate / "services" / service / "src/ai_bridge").mkdir(parents=True)
    # Copy outside candidate so neither checksum set accidentally includes the other.
    rollback = tmp_path.parent / (tmp_path.name + "-rollback")
    shutil.copytree(candidate, rollback)
    (rollback / "RELEASE").write_text("stage=D\nphase=D.0\n")
    checksums(candidate)
    checksums(rollback)
    if failure == "tampered":
        (rollback / "RELEASE").write_text("stage=C\n")
    elif failure == "missing":
        (rollback / "metadata/SHA256SUMS").write_text("")
    elif failure == "same":
        rollback = candidate
    elif failure == "escape":
        (rollback / "metadata/SHA256SUMS").write_text("0" * 64 + "  ../outside\n")
    if failure:
        with pytest.raises(ValueError):
            tool.verify_pair(candidate, rollback)
    else:
        tool.verify_pair(candidate, rollback)


def test_observer_never_emits_raw_content(monkeypatch):
    tool = load_tool("observe_validation", monkeypatch)
    payloads = {"health": {"status": "ok"}, "status": {
        "active_count": 1, "queued_count": 2, "resource_leases": {"lease_count": 1},
        "source": "private prompt", "recent_jobs": [{"prompt": "private prompt"}]},
        "queue": {"queue_running": ["private prompt"], "queue_pending": []}}
    result = tool.snapshot(lambda url: payloads[url.rsplit("/", 1)[-1]])
    assert result == dict(gateway_healthy=True, active=1, queued=2, leases=1,
                          comfy_running=1, comfy_pending=0)
    payloads["status"].pop("active_count")
    with pytest.raises(ValueError):
        tool.snapshot(lambda url: payloads[url.rsplit("/", 1)[-1]])


@pytest.mark.anyio
async def test_gateway_restart_has_no_resume_and_rejects_old_lease():
    from ai_bridge.gateway.resource_leases import ResourceLeaseNotFound
    first = ResourceLeaseRegistry(PriorityScheduler())
    old = await first.create(priority=50, source="test")
    restarted_scheduler = PriorityScheduler()
    restarted = ResourceLeaseRegistry(restarted_scheduler)
    with pytest.raises(ResourceLeaseNotFound):
        await restarted.begin_use(old["lease_id"])
    new = await restarted.create(priority=50, source="test")
    assert new["job"]["job_id"] != old["job"]["job_id"]
    assert new["job"]["request_id"] != old["job"]["request_id"]
    assert not (await restarted_scheduler.snapshot())["recent_jobs"]
    await restarted.release(new["lease_id"])


def test_runtime_validators_inline_python_compiles():
    for name in ("validate_wvc_gateway_runtime.sh", "validate_media_runtime.sh"):
        source = (ROOT / "deploy/stage-d" / name).read_text()
        snippets = re.findall(r"<<'PY'\n(.*?)\nPY", source, re.S)
        assert snippets
        for snippet in snippets:
            compile(snippet, name, "exec")


@pytest.mark.parametrize("domain", ["wvc", "shared", None])
def test_wvc_smoke_checks_v2_metadata_without_live_requests(monkeypatch, domain, capsys):
    import io
    import json
    import sys
    import urllib.request
    source = (ROOT / "deploy/stage-d/validate_wvc_gateway_runtime.sh").read_text()
    snippet = next(code for code in re.findall(r"<<'PY'\n(.*?)\nPY", source, re.S)
                   if 'v2_job_id = ' in code)
    seen = []

    class Response(io.BytesIO):
        headers = {"X-AI-Gateway-Priority": "10", "X-AI-Gateway-Job-Id": "1",
                   "X-AI-Gateway-Wait-Ms": "0", "X-AI-Job-Id": "job-id",
                   "X-AI-Request-Id": "request-id"}

    def urlopen(request, timeout):
        if isinstance(request, urllib.request.Request):
            seen.append(request.full_url)
            body = {"done": True, "prompt_eval_count": 10, "message": {"content": "private response"}}
        else:
            body = {"recent_jobs": [{"job_id": "job-id", "request_id": "request-id",
                    "domain": domain, "capability": "reasoning", "state": "completed",
                    "priority_class": "infrastructure", "assigned_provider": "ollama-local",
                    "assigned_node": "ai-node-01"}]}
        return Response(json.dumps(body).encode())

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", ["validation", "http://127.0.0.1:11435", "test-model"])
    if domain == "wvc":
        exec(compile(snippet, "wvc-smoke", "exec"), {})
    else:
        with pytest.raises(SystemExit, match="unexpected D.6 WVC job metadata"):
            exec(compile(snippet, "wvc-smoke", "exec"), {})
    assert seen == ["http://127.0.0.1:11435/clients/ventilation/api/chat"]
    assert "private response" not in capsys.readouterr().out
