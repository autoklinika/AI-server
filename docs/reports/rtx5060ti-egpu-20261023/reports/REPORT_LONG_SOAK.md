# RTX 5060 Ti / TBGAA — Long SGEMM stability soak

**Verdict:** PASS
**Reason:** N/A
**Started UTC:** 2026-10-23T15:16:59.870905+00:00
**Finished UTC:** 2026-10-23T17:24:06.269237+00:00
**Boot ID:** 067e4fa7-1585-4f81-86fd-30cd6cc4e6ea

## Workload and acceptance
Warmup 300 s at SGEMM 2048²; ramp 120 s at SGEMM 4096²; 
sustained 7200 s at SGEMM 8192². No simultaneous high-VRAM load.
Factory board limit 180 W unchanged, stop at >=76°C / >181 W.
One supervised CUDA worker, no auto-restart, hardware/driver untouched.

- Sustained compute duration (s): 7200.001
- Total SGEMM operations: 432577
- Sustained samples (around 1 Hz): 7200
- Mean sustained power (W): 177.38
- Peak sustained power (W): 178.92
- Mean sustained temperature (°C): 65.76
- Peak sustained temperature (°C): 66.0
- Mean sustained utilization (%): 99.6
- Peak sustained utilization (%): 100.0
- Peak sustained VRAM (MiB): 918.0
- Hardware/software thermal throttle samples: 0
- SW power cap samples (normal at high load): 0
- Gen3 x4 maintained (each telemetry sample + sysfs checks): yes for logged samples
- Xid / AER: no errors in completed polls
- Post CUDA cleanup/idle (P8): {'temp_c': 44.0, 'power_w': 9.26, 'gpu_util_pct': 0.0, 'used_mib': 2.0, 'free_mib': 15941.0, 'sm_mhz': 180.0, 'mem_mhz': 405.0, 'pstate': 'P8', 'pcie_gen': 3, 'pcie_width': 4, 'clock_event_mask': '0x0000000000000400', 'sw_power_cap': 'Not Active', 'hw_thermal': 'Not Active', 'sw_thermal': 'Not Active'}
- Post RM status: IDLE / recovery_required=false / 0 jobs

## Warmup / clock behavior
- warmup: {"max_mem_mhz": 13801.0, "max_power_w": 175.3, "max_sm_mhz": 2797.0, "max_temp_c": 67.0, "max_util_pct": 99.0, "max_vram_mib": 198.0, "mean_mem_mhz": 13801.0, "mean_power_w": 172.9, "mean_sm_mhz": 2760.77, "mean_temp_c": 64.77, "mean_util_pct": 99.0, "min_mem_mhz": 13801.0, "min_power_w": 67.69, "min_sm_mhz": 2760.0, "min_temp_c": 50.0, "min_util_pct": 98.0, "samples": 300, "sw_power_cap_samples": 0, "thermal_throttle_samples": 0}
- ramp: {"max_mem_mhz": 13801.0, "max_power_w": 176.15, "max_sm_mhz": 2760.0, "max_temp_c": 67.0, "max_util_pct": 100.0, "max_vram_mib": 342.0, "mean_mem_mhz": 13801.0, "mean_power_w": 175.17, "mean_sm_mhz": 2756.47, "mean_temp_c": 65.89, "mean_util_pct": 99.99, "min_mem_mhz": 13801.0, "min_power_w": 172.34, "min_sm_mhz": 2752.0, "min_temp_c": 65.0, "min_util_pct": 99.0, "samples": 120, "sw_power_cap_samples": 0, "thermal_throttle_samples": 0}
- sustain: {"max_mem_mhz": 13801.0, "max_power_w": 178.92, "max_sm_mhz": 2805.0, "max_temp_c": 66.0, "max_util_pct": 100.0, "max_vram_mib": 918.0, "mean_mem_mhz": 13801.0, "mean_power_w": 177.38, "mean_sm_mhz": 2759.86, "mean_temp_c": 65.76, "mean_util_pct": 99.6, "min_mem_mhz": 13801.0, "min_power_w": 147.89, "min_sm_mhz": 2752.0, "min_temp_c": 58.0, "min_util_pct": 42.0, "samples": 7200, "sw_power_cap_samples": 0, "thermal_throttle_samples": 0}

## Worker stages
- {"compute_seconds": 300.001, "matrix_n": 2048, "numerical_check": 1142.984009, "requested_seconds": 300.0, "sgemm_ops": 292566, "stage": "warmup"}
- {"compute_seconds": 120.004, "matrix_n": 4096, "numerical_check": 2285.994629, "requested_seconds": 120.0, "sgemm_ops": 15672, "stage": "ramp"}
- {"compute_seconds": 7200.001, "matrix_n": 8192, "numerical_check": 4571.994629, "requested_seconds": 7200.0, "sgemm_ops": 124339, "stage": "sustain"}

## Evidence / caveats
- telemetry.csv: direct NVIDIA-SMI ~1s samples, flushed/fsync to NVMe
- events.jsonl: faults, phase changes, start/stop and watchdog decisions
- worker_state.json, worker_result.json, worker.log: CUDA heartbeat/work evidence
- result-long-soak.json: this verdict's structured data
- launcher.log: detached one-shot process output
- No reboot, driver reload, PCIe writes or power-limit changes.
- A passing test is a finite stability observation, not a lifetime guarantee.
- AER and Xid are monitored in the active boot; power is as reported by NVIDIA-SMI.
