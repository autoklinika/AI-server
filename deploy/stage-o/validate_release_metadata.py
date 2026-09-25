#!/usr/bin/env python3
"""Stage O Control Center release metadata validator."""
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location(
    "stage_o_metadata_base",
    Path(__file__).parents[1] / "stage-d/validate_release_metadata.py",
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
base.VERSIONS = {
    **base.VERSIONS,
    "stage": "O",
    "phase": "O",
    "config_schema_version": "4",
    "migration_version": "crt-projection-v1",
    "platform_api_contract_version": "1",
    "observability_contract_version": "1",
    "knowledge_service_contract_version": "1",
    "ers_domain_contract_version": "1",
    "crt_domain_contract_version": "1",
    "control_center_contract_version": "1",
}

def validate(path: Path):
    result = base.validate(path)
    marker = path / "services/ai-bridge/src/ai_bridge/stage_m_enabled"
    if not marker.is_file() or marker.read_bytes() != b"":
        raise ValueError("Stage O must preserve Stage M composition")
    for service in ("ai-bridge", "ai-gateway"):
        static = path / f"services/{service}/src/ai_bridge/control_center/static"
        for name in ("index.html", "app.js", "styles.css", "manifest.webmanifest", "sw.js"):
            if not (static / name).is_file():
                raise ValueError(f"Control Center asset missing: {service}/{name}")
    javascript = (path / "services/ai-gateway/src/ai_bridge/control_center/static/app.js").read_text(encoding="utf-8")
    if 'const API_BASE = "/control/api/v1"' not in javascript:
        raise ValueError("Control Center Platform API boundary missing")
    lowered = javascript.lower()
    for forbidden in ("qdrant", "ollama", "postgres"):
        if forbidden in lowered:
            raise ValueError("Control Center bypasses Platform API")
    return result

if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]))
    except Exception:
        raise SystemExit("FAIL: Stage O metadata") from None
    print("Stage O metadata: PASS")
