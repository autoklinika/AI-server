The production host already runs the accepted Gateway overlay, fixed RADIO executor and ComfyUI startup ordering, while main still lacks those sources. This PR imports the exact production source inventory from vision-radio-5d9d267489609ccb: all 239 source/benchmark files match the accepted SHA256 manifest. It also retains the executor and rollback tooling, boot readiness drop-ins, regression tests and dated deployment/reboot evidence, and updates the stale README.

The import is based on main after the Stage K merge (#175). It contains none of the historical N1–N5, SHARED/Multi-GPU or experimental managed-worker stack in #174. Gateway RADIO remains disabled by default; the live host uses its explicit production setting. Merging this PR does not deploy or restart services.

Validation:
- Full CPU suite: 1463 passed, 9 skipped, 0 failed.
- Python, shell and JavaScript syntax: PASS.
- Release builds D/E/F/G/H/I/J/L/M/O: 10/10 PASS.
- SHA256 matches for all 239 deployed source/benchmark files.
- Existing production evidence: real Ollama → RADIO → ComfyUI → Ollama cycle after reboot PASS in 56.198 s; final RM IDLE, models unloaded, no matching GPU faults.

Scope remains the pinned RADIO calibration image. Arbitrary station images, long-duration stability and global GPU_REUSE_SAFE/N1 admission are not enabled. Historical one-time installers and manifests are retained as documented audit material; they are not re-run by this PR.

Evidence: docs/reports/COMFYUI_POST_REBOOT_ACCEPTANCE_2026-10-20_PL.md and docs/reports/REPOSITORY_CLEANUP_2026-10-20_PL.md.
