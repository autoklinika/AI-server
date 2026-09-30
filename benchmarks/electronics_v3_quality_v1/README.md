# P5.5 Electronics v3 qualitative benchmark

Purpose: evaluate `Qwen3.8-27B + electronics-foundation-v3/current` on new diagnostic problems using the production-style sequence **physical fault model -> discriminating measurement -> predicted result -> no guessing**.

The 42 cases are `training_exclusion=true` and contain no OEM pinouts, controller numbers or calibration data. OEM-specific facts remain a Knowledge/RAG responsibility.

Families: supply/schematic symptoms, analog paths, numeric oscilloscope waveforms, thermal intermittents, PCB shorts, good-vs-bad channels, and insufficient-evidence cases.

Validation rejects exact/near-copy overlap with electronics v1/v2/v3 train/holdout material. Generation uses the P5 bounded BF16 loader and the standalone LoRA adapter; it never merges LoRA weights into the Qwen base.

Scoring uses BGE-M3 only as a transparent semantic pre-scorer for the three generated text fields; abstention/no-guessing is checked structurally. The per-case outputs and similarities remain reviewable, so the benchmark does not hide its evidence behind a single aggregate score.
