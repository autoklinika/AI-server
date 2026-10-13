#!/usr/bin/env python3
"""CPU-only, fixed-output cross-UID Vision handshake verifier; NO GPU imports."""
from __future__ import annotations

import json
import os
from pathlib import Path

OUT=Path("/srv/ai-data/evaluation/vision-rm-service/crossuid-cpu-result.json")
if os.geteuid()!=994:
    raise SystemExit("CPU worker must run under ai-vision")
if OUT.exists():
    raise SystemExit("refuse to overwrite previous evidence")
if any(k.startswith("VISION_RM_EXECUTOR_TOKEN") for k in os.environ):
    raise SystemExit("control credential leaked to model process")
assert not os.access("/etc/ai-platform/vision-rm/executor.token",os.R_OK,effective_ids=True)
OUT.write_text(json.dumps({"status":"cpu_only", "worker_uid":os.geteuid(),
                           "rm_control_credential_absent":True,
                           "gpu_imports":False})+"\n")
print("VISION_CROSS_UID_CPU_WORKER=PASS",flush=True)
