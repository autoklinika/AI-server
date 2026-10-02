#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
NEW = HERE / "automotive_specialization_v1_train.jsonl"
REPLAY = HERE / "automotive_specialization_v1_replay_train.jsonl"
MANIFEST = HERE / "automotive_specialization_v1.manifest.json"
REPLAY_MANIFEST = HERE / "automotive_specialization_v1_replay.manifest.json"

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

def contains_key(value, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(contains_key(v, forbidden) for v in value.values())
    if isinstance(value, list):
        return any(contains_key(v, forbidden) for v in value)
    return False

def validate() -> dict:
    new_rows = rows(NEW)
    replay_rows = rows(REPLAY)
    manifest = json.loads(MANIFEST.read_text())
    replay_manifest = json.loads(REPLAY_MANIFEST.read_text())

    if len(new_rows) != 183 or len(replay_rows) != 244:
        raise ValueError("record count mismatch")
    if len({r["record_id"] for r in new_rows}) != 183:
        raise ValueError("duplicate new record_id")
    if len({r["record_id"] for r in replay_rows}) != 244:
        raise ValueError("duplicate replay record_id")
    if any(not r.get("metadata", {}).get("training_eligible") for r in replay_rows):
        raise ValueError("non-training row in combined dataset")
    if any(r.get("metadata", {}).get("split") != "train" for r in replay_rows):
        raise ValueError("non-train split in combined dataset")
    if any(contains_key(r, "source_fact") for r in new_rows):
        raise ValueError("source_fact leaked into generated training rows")

    replay_count = sum(bool(r.get("metadata", {}).get("p511_replay")) for r in replay_rows)
    dk_count = sum(r.get("record_id", "").startswith("P511-DK-") for r in new_rows)
    base_count = sum(r.get("metadata", {}).get("p511_origin") == "automotive_curriculum_v2" for r in new_rows)
    if (replay_count, dk_count, base_count) != (61, 28, 155):
        raise ValueError(f"composition mismatch replay={replay_count} dk={dk_count} base={base_count}")
    if abs(replay_count / len(replay_rows) - 0.25) > 1e-12:
        raise ValueError("replay fraction is not exactly 25%")

    replay_origins = Counter(
        r.get("metadata", {}).get("p511_origin")
        for r in replay_rows if r.get("metadata", {}).get("p511_replay")
    )
    expected_origins = {
        "electronics_foundation_train_v1.jsonl": 20,
        "electronics_foundation_v2_train.jsonl": 20,
        "electronics_foundation_v3_train.jsonl": 21,
    }
    if dict(replay_origins) != expected_origins:
        raise ValueError(f"replay source mismatch: {dict(replay_origins)}")
    if any(word in origin.lower() for origin in replay_origins for word in ("holdout", "golden", "final", "eval", "test")):
        raise ValueError("protected/evaluation-like source name found in replay")

    for row in replay_rows:
        if not all(isinstance(row.get(k), str) and row[k].strip() for k in ("system", "user", "assistant", "record_id")):
            raise ValueError("invalid conversation row")
        if row.get("metadata", {}).get("language") != "pl":
            raise ValueError("non-Polish training row")

    if manifest.get("dataset_sha256") != sha256_file(NEW):
        raise ValueError("new dataset hash mismatch")
    if replay_manifest.get("dataset_sha256") != sha256_file(REPLAY):
        raise ValueError("replay dataset hash mismatch")
    if replay_manifest.get("new_dataset_sha256") != sha256_file(NEW):
        raise ValueError("new dataset binding mismatch")
    if replay_manifest.get("records") != 244 or replay_manifest.get("microsteps") != 244:
        raise ValueError("replay manifest record/microstep mismatch")
    if replay_manifest.get("optimizer_steps") != 64:
        raise ValueError("optimizer step contract mismatch")
    if replay_manifest.get("gradient_groups") != {"size_3": 12, "size_4": 52}:
        raise ValueError("gradient accumulation contract mismatch")
    if replay_manifest.get("replay_fraction") != 0.25:
        raise ValueError("manifest replay fraction mismatch")
    if replay_manifest.get("lora_r") != 8 or replay_manifest.get("learning_rate") != 2e-5:
        raise ValueError("training hyperparameter contract mismatch")
    if replay_manifest.get("stability_profile") != {"HSA_USE_SVM": "0"}:
        raise ValueError("stability profile mismatch")
    if manifest.get("source_fact_used") is not False:
        raise ValueError("source_fact policy changed")
    if manifest.get("protected_eval_material_used") is not False or replay_manifest.get("protected_eval_material_used") is not False:
        raise ValueError("protected evaluation material policy changed")
    if "PENDING_FUTURE_INDEPENDENT_EVALUATION" not in {
        manifest.get("quality_acceptance"), replay_manifest.get("quality_acceptance")
    }:
        raise ValueError("future quality acceptance boundary missing")

    categories = Counter(r["metadata"].get("category") for r in new_rows)
    return {
        "status": "PASS",
        "new_records": len(new_rows),
        "replay_records": replay_count,
        "combined_records": len(replay_rows),
        "replay_fraction": replay_count / len(replay_rows),
        "diagnostic_knowledge_records": dk_count,
        "categories": len(categories),
        "dataset_sha256": replay_manifest["dataset_sha256"],
        "quality_acceptance": "PENDING_FUTURE_INDEPENDENT_EVALUATION",
    }

def main() -> int:
    result = validate()
    print("P5_11_AUTOMOTIVE_READINESS=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
