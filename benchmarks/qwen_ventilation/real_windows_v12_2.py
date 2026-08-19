from __future__ import annotations

"""Read-only archived-real-window validation for v12.2.

Reuses the proven v12.1 database/report plumbing and replaces only the
environmental model contract. The generated report is renamed to v12.2.
"""

from pathlib import Path

import real_windows_v12_1 as base

from ai_bridge.adapters.ventilation.analysis_v12_2 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    EnvironmentalDecisionV122,
    build_environment_packet_from_compact,
    build_environment_prompt_from_compact,
    render_result,
    resolve_final_decision,
)


base.ANALYSIS_THINK = ANALYSIS_THINK
base.PROMPT_VERSION = PROMPT_VERSION
base.EnvironmentalDecisionV121 = EnvironmentalDecisionV122
base.build_environment_packet_from_compact = build_environment_packet_from_compact
base.build_environment_prompt_from_compact = build_environment_prompt_from_compact
base.render_result = render_result
base.resolve_final_decision = resolve_final_decision


def main() -> int:
    before = set(base.RESULTS_DIR.glob("real_windows_v12_1_*.json"))
    rc = base.main()
    after = set(base.RESULTS_DIR.glob("real_windows_v12_1_*.json"))
    created = sorted(after - before, key=lambda path: path.stat().st_mtime)
    if created:
        old_path = created[-1]
        new_name = old_path.name.replace("real_windows_v12_1_", "real_windows_v12_2_", 1)
        new_path = Path(old_path.parent) / new_name
        old_path.replace(new_path)
        print(f"Report v12.2: {new_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
