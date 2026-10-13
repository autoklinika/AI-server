# MODEL-01 — WinCLIP tiled + MiniCPM-V 4.7 1B CPU (2026-10-13)

Status: **Smoke MiniCPM=PASS; paired tiling B1 pilot=PASS; full B1=NOT COMPLETED**.

## Separate, pinned runtimes

- WinCLIP: venv `/srv/ai-data/evaluation/vision-pcb-envs/winclip-cpu-py311`; PyTorch CPU 2.10.0, Anomalib 2.7.0, OpenCLIP 2.24.0. Checkpoint ViT-B-16-plus-240/laion400m_e31 SHA256 `8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba`.
- MiniCPM-V 4.7 1B: venv `/srv/ai-data/evaluation/vision-pcb-envs/minicpm47-1b-cpu-py311`; Transformers 5.18.0, PyTorch CPU 2.10.0; official repo `openbmb/MiniCPM-V-4.7-1B`, pinned revision `984a89aafcd5160164f4f0d04b4be0f4eec03cb8`, Apache 2.0 model card; `model.safetensors` size 3 109 054 480 B SHA256 `8c4921ac83182c85190ad10c3aeb118d51e385d2d98ec13b88b514bbf6cac002` (HF LFS hash match).
- Storage exclusively on separate NVMe paths. No change in Ollama, Qwen3.8, GPU policy or adapter routing. `main` clean.

## MiniCPM real-image smoke

Source VisA PCB4; exactly 2 samples, both full 1358×1104 images.

| Sample | Actual label | Output summary | CPU generation wall-time |
|---|---|---|---|
| visa-pcb4-normal-0000 | normal | 'No visible damage; ... Cannot be determined if functional' | 14.17 s |
| visa-pcb4-anomaly-000 | burnt,scratch,dirt | Model described wear/corrosion around USB; did **not** identify all labeled defect classes | 14.32 s |

**Model pass means only inference successful, not defect detection accuracy.** Ground-truth labels were **not provided to the model**. Description of corrosion is not a verified defect class for this image. Trained expert must review it against the mask. Note possibility of visual hallucination and omitted burnt/scratch/dirt labels.

Image preprocessing: `downsample_mode=16x`, `max_slice_nums=4`, `enable_thinking=False`, model FP32 CPU two threads, `max_new_tokens=72`. Clock time excludes photograph acquisition. Model load 1.66 s (data cached). No logits-based calibrated anomaly score is available, hence **never insert confidence guessed from a textual answer into AUROC**.

### MiniCPM restrictions

1. VLM track must separately measure defect type, localization, ungrounded claims and abstention. Technical description != validated diagnosis.
2. Need a deterministic structured-output adapter or class log-probability extraction before joining common binary test. A self-reported confidence score cannot be treated as ground-truth probability.
3. Use fixed prompt and preprocessing across all test images, no leakage of VisA labels in prompts, cache images on NVMe.
4. High-resolution mode `downsample_mode=4x` should be evaluated against 16x with controlled input-cost before any selection.

## WinCLIP high-resolution tiled policy

Originals are >1300 px wide, while WinCLIP encodes 240×240. A whole-image score is computed separately. Tiled mode uses deterministic **640 px squares with 25% overlap**, original pixel coordinates, runs WinCLIP on each crop, then takes `max(global_score, *tile_scores)`.

**Crucial:** each policy needs its own normal-only calibration. Max-over-tiles often raises anomaly scores even on pristine boards, increasing false alarms. Do not compare raw scores or reuse global threshold for tiled.

Pilot is deliberately tiny: two normal + two anomaly examples per calibration, holdout and challenge (12 test images) from previous 56-case pilot. It is solely a preprocessing integration test, not a statistically meaningful B1.

Tile geometry is in `tile_policy.py`, with tests in `tests/test_tile_policy.py`. `winclip_compare_preprocessing.py` saves input GT, model outputs and tile-by-tile predictions on NVMe, not in Git. Scorer `benchmark.py` computes independent per-policy metrics, provided calibration file/hash is pinned.

## Remaining gates for *full* B1

- MODEL-01A: paired tiled experiment complete, masks/pixel-localization added separately, review false positives.
- MODEL-01B: full evaluation over all 4 cross-family folds; controlled job scheduling through Resource Manager, no overload or production deployment. CPU-only full runs may take hours.
- MODEL-01C: MiniCPM deterministic classification adapter, more samples and manual review.
- MODEL-01D: same dataset/prompt/preprocessing compatibility and licensing checks for other 5 candidates.
- Not a basis for automatic promotion into production.

## Paired tile result

Paired N=12 inference **PASS**, max aggregation and independent calibrations. N=4 evaluated in each test split; holdout PCB3 tiled recall 0.0 vs global 0.5; challenge PCB4 both recall 1.0 but false-positive rate 0.5. Details in `B1_WINCLIP_TILING_PILOT_2026-10-13.md`. No generalized advantage for tiling established.
