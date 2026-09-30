# P5 AMDGPU/MES diagnostics

These tools run only diagnostics. They do not change drivers, BIOS, kernel arguments,
IOMMU, memory carve-out, production releases or checkpoints. They never resume P5.6.
The 42 P5.5 cases and all existing adapters are unused. Qwen mode creates a disposable
rank-8 LoRA in memory, uses random token IDs and lr=0, and saves no model or adapter.

## Files

- `mes_stability.py audit`: kernel history, version, firmware/package, sysfs and container audit.
- `mes_stability.py run`: one isolated Docker workload, journal cursor guard and telemetry.
- `workload.py`: BF16 matrix/backward, pinned transfer correctness and allocation churn;
  alternatively the real Qwen BF16 loader and model forward/backward with synthetic tokens.
- `matrix.py`: sequential experiments with a maintenance-priority external resource reservation.
  Requires an idle platform; unloads idle Ollama residency, waits for physical GPU release,
  and restores it on a clean exit. It does not stop/restart services. On a kernel fault it
  retains its reservation with heartbeat (`HOLD_FAULT`) rather than reload an inference model.
- `gate.py`: offline evidence gate; no training/deployment action even on PASS.
- `tests/test_mes_stability.py`: classification, preflight, monitor-loss containment and gate tests.

## Execution

Use the committed diagnostic worktree and a new output directory for each run.
Evidence belongs on `/srv/ai-data/training/p5/diagnostics`, not in Git. Containers are
retained after exit for inspection and are not automatically removed.

```bash
python3 tools/mes_stability/mes_stability.py audit --boots 6 --output /srv/ai-data/training/p5/diagnostics/new-audit
python3 -m unittest discover -s tests -p test_mes_stability.py -v
python3 tools/mes_stability/matrix.py --seconds 60 --resident-gib 2 --output /srv/ai-data/training/p5/diagnostics/new-smoke
python3 tools/mes_stability/matrix.py --seconds 120 --resident-gib 56 --output /srv/ai-data/training/p5/diagnostics/new-memory-screen
```

Do not run these example commands concurrently. `matrix.py` must remain alive to maintain
its reservation. An execution-session disconnect is not permission to relaunch a second
matrix: inspect the process, Docker state, `progress.json` and `containment.json` first.
Do not terminate a `HOLD_FAULT` coordinator simply to free admission on a tainted boot.
Recovery decisions require the operator; reboot/reset/driver changes are never automatic.

## Controlled variables

| Variant | Override relative to A | Purpose |
|---|---|---|
| A | none | Current image/device/cgroup/IPC baseline |
| B | `HSA_USE_SVM=0` | ROCR thunk SVM API path; does not turn off IOMMU or kernel HMM globally |
| C | `HSA_ENABLE_SDMA=0` | HIP copy path via compute blit rather than SDMA |
| D | both | Factor interaction, only after B and C individually initialize correctly |
| E | `PYTORCH_ALLOC_CONF=backend:native,expandable_segments:True` | Optional allocator/churn hypothesis; first verify actual support in workload log |

The launcher starts a fresh container/process for every variant, pins the image ID resolved
from the local image, and records inherited image environment plus all effective HSA/HIP/ROCm/
PyTorch variables. The existing image contains no HSA/allocator overrides. No software upgrades.
SDMA disable is not a guarantee that every driver/kernel DMA operation is disabled.
The 56 GiB synthetic residency is physical allocation/touch, not a full-model stability gate.

## Fail-fast contract and limits

Kernel messages are followed from a journal cursor captured before container creation.
The first new MES error (including WAIT_REG_MEM, before ring-full), KFD/GPUVM fault,
GPU reset, IOMMU fault, OOM, soft/hard lockup or SVM workqueue warning aborts the run.
The follower is checked every 100 ms between bounded operations (Docker inspection can take
up to 3 seconds); this is not a real-time response guarantee. Kill is bounded to 5 seconds.
Failure to kill is `FAIL_CONTAINMENT`, never PASS. The final journal tail is checked after
teardown. Monitoring loss, missing required telemetry, low host memory, >=90 C GPU sensor,
deadline overrun, nonfinite arithmetic or failed transfer verification fail closed.

Previously tainted boots are blocked. A completed workload does not rehabilitate such a boot.
New variants are never launched after a failed run. No injection of a real kernel fault is
used for watchdog testing; unit tests simulate the journal and Docker boundary.
Temperatures are null/empty if unavailable. Historical lack of a temperature trace cannot
exclude a thermal cause. Counts are log messages, not unique independent crashes.

## Stability gate

1. Same committed code, image ID, kernel, profile and variant across at least 3 distinct,
   non-overlapping process runs. Each must last >=3600 seconds **after model loading**.
   Raise the duration if a later full P5.6 duration estimate exceeds one hour.
2. Real Qwen BF16 forward/backward + LoRA/Adam execution using synthetic tokens, lengths
   396/900/960/887/399. No benchmark data, trained parent adapter or partial checkpoint.
3. Zero new kernel faults/warnings, successful process exit and observed container teardown.
4. Representative GPU memory footprint >=52 GiB, host MemAvailable >=8 GiB, no new failed
   system units, GPU allocations released. Review latency/CPU/memory-pressure traces too;
   `host_regression_free` covers these automated checks, not every host service's semantics.
5. Run offline gate on the three result files. This is a repeatability gate, not proof of
   indefinite reliability or full equivalence to real training data/kernel distributions.

```bash
python3 tools/mes_stability/matrix.py --variants B --profile qwen --seconds 3600 --repeats 3 --output /srv/ai-data/training/p5/diagnostics/new-B-gate
python3 tools/mes_stability/gate.py /srv/ai-data/training/p5/diagnostics/new-B-gate/B-{1,2,3}/result.json
```

B is an experiment, not an accepted configuration. Do not promote any environment change
or resume P5.6 until evidence passes and the actual intended training configuration is reviewed.

## Audit limitations

Reading live MES microcode versions in debugfs may require operator-granted privileged
read access. The audit does not elevate or expose a reset/recovery interface. On-disk firmware
hashes and package versions must not be presented as proof of the running firmware revision.
A missing distro source endpoint is recorded as a verification gap, not inferred patch absence.
