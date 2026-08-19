from __future__ import annotations

"""Read-only archived real-window validation for ventilation prompt v11.6.

The v11.5 runner owns the database/query/report plumbing. This wrapper replaces
only the active analysis profile so the same six archived windows are compared
under v11.6 without writing to ventilation_analysis_runs.
"""

from pathlib import Path

import real_windows_v11_5 as base

from ai_bridge.adapters.ventilation.analysis_profile_v11_6 import (
    ANALYSIS_THINK,
    PROMPT_VERSION,
    build_compact_analysis_packet,
    build_ventilation_prompt,
)


base.ANALYSIS_THINK = ANALYSIS_THINK
base.PROMPT_VERSION = PROMPT_VERSION
base.build_compact_analysis_packet = build_compact_analysis_packet
base.build_ventilation_prompt = build_ventilation_prompt


def main() -> int:
    before = set(base.RESULTS_DIR.glob("real_windows_v11_5_*.json"))
    rc = base.main()
    after = set(base.RESULTS_DIR.glob("real_windows_v11_5_*.json"))
    created = sorted(after - before, key=lambda path: path.stat().st_mtime)
    if created:
        old_path = created[-1]
        new_name = old_path.name.replace("real_windows_v11_5_", "real_windows_v11_6_", 1)
        new_path = Path(old_path.parent) / new_name
        old_path.replace(new_path)
        print(f"Report v11.6: {new_path}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
