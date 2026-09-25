#!/usr/bin/env python3
"""Stage M CRT domain release metadata validator."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location(
    "stage_m_metadata_base",
    Path(__file__).parents[1] / "stage-d/validate_release_metadata.py",
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.VERSIONS = {
    **base.VERSIONS,
    "stage": "M",
    "phase": "M",
    "config_schema_version": "4",
    "migration_version": "crt-projection-v1",
    "platform_api_contract_version": "1",
    "observability_contract_version": "1",
    "knowledge_service_contract_version": "1",
    "ers_domain_contract_version": "1",
    "crt_domain_contract_version": "1",
}
def validate(path: Path):
    result = base.validate(path)
    marker = path / "services/ai-bridge/src/ai_bridge/stage_m_enabled"
    if not marker.is_file() or marker.read_bytes() != b"":
        raise ValueError("Stage M composition marker missing or invalid")
    return result

if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]))
    except Exception:
        raise SystemExit("FAIL: Stage M metadata") from None
    print("Stage M metadata: PASS")
