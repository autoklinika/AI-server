# P3 router baseline v1 — 2026-09-28

These are authoritative CPU router baselines produced from a clean AI-server
worktree.

Reproducibility identity:

- AI-server commit: 31ccb42855a06539785469dbe8dfdc1f2af7cc46
- ERS commit: 81909b30ef18ca2053bd7496d6faeb814d4e9866
- golden dataset SHA-256:
  1f829de1eacdd8e19905e28f2d086161f94fd93c691bee586d6171976d0f8edf
- Python: 3.14.4
- Torch: 2.14.0+cpu
- GLiNER2: 2.0.0
- GLiNER2 base.py SHA-256:
  791814c58c3674f0b546c67d90ab5013bf645e5eda29d25e9fd17fa100aaa061

All GLiNER model revisions are pinned in each run artifact.


## Configurations

- small: fastino/gliner2.5-small-v1, joint route/tool heads, threshold 0.5.
- multi: fastino/GLiNER2.5-multi-Decide, separate described heads, threshold 0.5.
- decide: fastino/GLiNER2.5-Decide, separate described heads, threshold 0.5.
- majority: always knowledge_rag + knowledge.search; class-imbalance floor only.

Head configuration was selected on the dev split only. Holdout and challenge
were not used for calibration.

## Key result

340M Decide has the strongest routing quality in this baseline, but none of the
tested zero-shot/calibrated models has acceptable tool-selection quality yet.

Therefore these results justify router-specific calibration/training work, but
do not authorize a production router change.
