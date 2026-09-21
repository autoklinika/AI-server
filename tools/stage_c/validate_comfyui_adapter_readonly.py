#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from ai_bridge.providers.comfyui import ComfyUIAdapter, ComfyUIWorkflowPlan
from ai_bridge.providers.contracts import MediaGenerationRequest


COMFY_URL = "http://127.0.0.1:8188"
REQUIRED_RUNTIME_NODES = {
    "SaveVideo",
    "VAEDecodeTiled",
    "ImageScale",
    "LTXVImgToVideoInplace",
}


def _unused_resolver(_request: MediaGenerationRequest) -> ComfyUIWorkflowPlan:
    raise AssertionError("read-only validation must never resolve or submit a workflow")


def main() -> int:
    adapter = ComfyUIAdapter(
        base_url=COMFY_URL,
        workflow_resolver=_unused_resolver,
        profiles=("ltx23-stage30",),
        capabilities=("video-generation",),
    )

    health = adapter.health()
    if health.status != "ready":
        raise RuntimeError(f"media provider health is not ready: {health.detail}")

    descriptor = adapter.describe()
    if descriptor.provider_id != "comfyui-local":
        raise RuntimeError(f"unexpected provider id: {descriptor.provider_id}")
    if descriptor.provider_type != "media-generation":
        raise RuntimeError(f"unexpected provider type: {descriptor.provider_type}")

    info = adapter.object_info()
    missing = sorted(REQUIRED_RUNTIME_NODES - set(info))
    if missing:
        raise RuntimeError(
            "ComfyUI is reachable but Stage30 runtime nodes are missing: "
            + ", ".join(missing)
        )

    print(
        json.dumps(
            {
                "ok": True,
                "provider": descriptor.provider_id,
                "status": health.status,
                "profiles": list(descriptor.models),
                "capabilities": list(descriptor.capabilities),
                "required_nodes_present": sorted(REQUIRED_RUNTIME_NODES),
                "mutating_requests_sent": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("STAGE C.3 COMFYUI ADAPTER READ-ONLY VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
