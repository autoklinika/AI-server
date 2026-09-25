from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STEPS = (
    "00_preflight.sh",
    "10_build_install.sh",
    "20_cutover.sh",
    "30_smoke.sh",
    "40_rollback.sh",
    "50_rollback_smoke.sh",
    "60_reactivate.sh",
    "70_reactivate_smoke.sh",
    "90_finalize.sh",
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage_l_release_contract_is_explicit():
    wrapper = (ROOT / "deploy/stage-l/build_release.sh").read_text()
    assert "RELEASE_STAGE=L" in wrapper
    assert "RELEASE_MIGRATION=ers-domain-v1" in wrapper
    assert "RELEASE_OBSERVABILITY_CONTRACT=1" in wrapper
    assert "RELEASE_KNOWLEDGE_CONTRACT=1" in wrapper
    assert "RELEASE_ERS_CONTRACT=1" in wrapper

    builder = (ROOT / "deploy/runtime/build_release.sh").read_text()
    assert '[[ "$STAGE" =~ ^[GHIJL]$ ]]' in builder
    assert 'ERS_CONTRACT="${RELEASE_ERS_CONTRACT:-}"' in builder
    assert 'ers_domain: $ERS_CONTRACT' in builder
    assert "ers_domain_contract_version" in builder

    validator = load_module(
        "stage_l_metadata_test",
        ROOT / "deploy/stage-l/validate_release_metadata.py",
    )
    assert validator.base.VERSIONS["stage"] == "L"
    assert validator.base.VERSIONS["phase"] == "L"
    assert validator.base.VERSIONS["migration_version"] == "ers-domain-v1"
    assert validator.base.VERSIONS["ers_domain_contract_version"] == "1"
    assert validator.base.VERSIONS["knowledge_service_contract_version"] == "1"


def test_stage_l_has_complete_reversible_production_step_contract():
    autopilot = ROOT / "deploy/stage-l/autopilot"
    for name in STEPS:
        path = autopilot / name
        assert path.is_file(), name
        text = path.read_text()
        assert "gate.py" in text
        assert "set -euo pipefail" in text

    gate = (autopilot / "gate.py").read_text()
    assert 'BASE = Path("/opt/ai-platform/releases/stage-j-3b456a56343a")' in gate
    assert 'BASE_REVISION = "0003_knowledge_canonical"' in gate
    assert 'TARGET_REVISION = "0004_ers_core_persistence"' in gate
    assert "recent_pre_l_backup()" in gate
    assert "recent_active_ers_backup()" in gate
    assert "switch_with_schema(BASE, candidate, cfg, baseline)" in gate
    assert 'production_op(candidate, "downgrade")' in gate
    assert 'production_op(candidate, "upgrade")' in gate
    assert 'production_op(candidate, "import"' in gate
    assert 'production_op(candidate, "verify-active")' in gate
    assert 'evidence[1]["ers"]["status"] == "absent"' in gate
    assert '"rollback_cycle": "PASS"' in gate


def test_stage_l_production_ops_do_not_accept_database_url_as_cli_input():
    text = (ROOT / "deploy/stage-l/production_ops.py").read_text()
    assert 'ENV_FILE = Path("/etc/ai-bridge/ai-bridge.env")' in text
    assert "--database-url" not in text
    assert "AI_BRIDGE_DATABASE_URL" in text
    assert 'choices=("upgrade", "downgrade", "import", "verify-active", "verify-inactive")' in text
    assert 'TARGET_REVISION = "0004_ers_core_persistence"' in text
    assert 'BASE_REVISION = "0003_knowledge_canonical"' in text
    assert "FileObjectStore(OBJECT_ROOT)" in text
    assert "source_revision()" in text


def test_ci_builds_stage_l_candidate():
    workflow = (ROOT / ".github/workflows/ai-gateway-tests.yml").read_text()
    assert "Validate Stage L release build" in workflow
    assert "deploy/stage-l/build_release.sh" in workflow
    assert '"stage-l-${GITHUB_SHA::12}"' in workflow


def test_default_bridge_composition_exposes_ers_only_in_new_source():
    app_source = (ROOT / "src/ai_bridge/api/app.py").read_text()
    assert "from ai_bridge.domains.ers.adapter import ERSAdapter" in app_source
    assert "(WVCAdapter(), ERSAdapter()) if domains is None" in app_source
