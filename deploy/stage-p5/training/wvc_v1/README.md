# WVC advisory v1

Standalone LoRA curriculum for Workshop Ventilation Control on Qwen3.8 27B.

- No parent adapter is loaded.
- No electronics, ECU, PCB or automotive training records are permitted.
- CURRENT examples preserve the production v12.2 environmental-decision contract.
- FUTURE examples use a separate explicit task and are not connected to production.
- Production WVC communication remains unchanged.
- Dataset gates enforce domain contamination, CURRENT schema and family split leakage.
- Training uses the audited buffered BF16 checkpoint, LoRA rank 8 and HSA_USE_SVM=0.
- The runner does not merge weights, update a runtime tag or promote the adapter.

The host runner is `run.sh`. It requires a completed clean-base `baseline.json`,
a free GPU, passing unit/dataset gates and an active Resource Manager lease.
