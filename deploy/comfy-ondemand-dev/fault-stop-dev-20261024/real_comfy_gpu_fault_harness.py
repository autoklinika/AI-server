#!/usr/bin/python3
"""One intentionally failed DEV stop phase after a successful real AMD VAE.

The *existing* on-demand DEV RM must keep its lease and recovery marker.
The maintenance supervisor must later stop the unique test unit and restore
production. Not an AMD kernel hang, GPU OOM or physically crashed worker.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys

OLD=Path("/srv/ai-data/staging/comfy-ondemand-maintenance-dev-20261023")
BASE=Path("/srv/ai-data/staging/comfy-ondemand-faults-dev-20261024")
SPEC=importlib.util.spec_from_file_location(
    "original_real_comfy_gpu_dev_harness",OLD/"real_comfy_gpu_rm_harness.py")
assert SPEC and SPEC.loader
engine=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=engine
SPEC.loader.exec_module(engine)

engine.BASE=BASE
engine.MARKER=BASE/"dev-residency.blocked"
engine.RESULT=BASE/"real-comfy-gpu-result.json"
assert not engine.MARKER.exists()
assert not engine.RESULT.exists()
triggered=[False]


async def intentional_stop_failure(self, token):
    assert not triggered[0], "only one injected failure per run"
    assert self.running(token), "managed systemd incarnation no longer trusted"
    assert engine.MARKER.is_file(), "failed to preserve RM recovery marker"
    self.events.append("stop_refused_by_dev_test")
    triggered[0]=True
    print("DEV_INJECTED_STOP_REFUSAL_AFTER_REAL_VAE",flush=True)
    raise RuntimeError("DEV simulated ComfyUI stop verification refused")


engine.FixedSystemdController.stop_and_verify=intentional_stop_failure

try:
    asyncio.run(engine.exercise())
except RuntimeError as exc:
    result=json.loads(engine.RESULT.read_text())
    if not triggered[0]:
        raise RuntimeError("DEV unexpected real GPU failure before selected injection") from exc
    if not isinstance(result.get("image"),dict):
        raise RuntimeError("No genuine VAE PNG proof before injected stop refusal") from exc
    if result.get("verdict")!="INCOMPLETE" or result.get("failure_class")!="RuntimeError":
        raise RuntimeError("Wrong fault record: RM did not abort as designed") from exc
    if not engine.MARKER.is_file() or result.get("recovery_marker_left") is not True:
        raise RuntimeError("RM recovery fence was cleared prematurely") from exc
    state=engine.unit_state()
    if state.get("ActiveState")!="active" or int(state.get("MainPID","0"))<2:
        raise RuntimeError("Transient worker did not remain for supervised rollback") from exc
    print("DEV_EXPECTED_STOP_FAULT_RM_FENCED_PASS",flush=True)
else:
    raise RuntimeError("DEV selected negative case unexpectedly completed normally")
