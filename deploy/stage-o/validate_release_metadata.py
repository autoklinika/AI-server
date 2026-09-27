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
STAGE_O_VERSIONS = {
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
    "technical_conversation_contract_version": "1",
}
LEGACY_STAGE_O_VERSIONS = {
    key: value
    for key, value in STAGE_O_VERSIONS.items()
    if key != "technical_conversation_contract_version"
}
base.VERSIONS = dict(STAGE_O_VERSIONS)


def _validate_with_versions(path: Path, versions: dict[str, str]):
    previous = base.VERSIONS
    base.VERSIONS = dict(versions)
    try:
        result = base.validate(path)
    finally:
        base.VERSIONS = previous
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


def validate(path: Path):
    return _validate_with_versions(path, STAGE_O_VERSIONS)


def validate_rollback_compatible(path: Path):
    stamp = dict(
        line.split("=", 1)
        for line in (path / "RELEASE").read_text(encoding="utf-8").splitlines()
    )
    manifest = base.manifest_scalars(
        (path / "metadata/release-manifest.yaml").read_text(encoding="utf-8")
    )
    stamp_value = stamp.get("technical_conversation_contract_version")
    manifest_value = manifest.get(
        ("release", "contract_versions", "technical_conversation")
    )
    if stamp_value is None and manifest_value is None:
        return _validate_with_versions(path, LEGACY_STAGE_O_VERSIONS)
    if stamp_value == "1" and manifest_value == "1":
        return validate(path)
    raise ValueError("technical conversation contract mismatch")


if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]))
    except Exception:
        raise SystemExit("FAIL: Stage O metadata") from None
    print("Stage O metadata: PASS")
