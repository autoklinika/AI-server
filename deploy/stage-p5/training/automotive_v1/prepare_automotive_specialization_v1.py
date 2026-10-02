#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FIXTURE = ROOT / "deploy/stage-p5/training/fixtures/automotive_curriculum_v2.jsonl"
DK_DEFAULT = Path("/home/harrypotter/EcuRepairService/sources/automotive-semiconductor-corpus-v0/DIAGNOSTIC_KNOWLEDGE.jsonl")
DK_PATH = Path(os.environ.get("P5_ERS_DIAGNOSTIC_KNOWLEDGE", str(DK_DEFAULT)))
OUT_NEW = HERE / "automotive_specialization_v1_train.jsonl"
OUT_REPLAY = HERE / "automotive_specialization_v1_replay_train.jsonl"
MANIFEST = HERE / "automotive_specialization_v1.manifest.json"
REPLAY_MANIFEST = HERE / "automotive_specialization_v1_replay.manifest.json"
SEED = 20261002
REPLAY_TARGETS = {
    ROOT / "deploy/stage-p5/training/electronics/electronics_foundation_train_v1.jsonl": 20,
    ROOT / "deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_train.jsonl": 20,
    ROOT / "deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_train.jsonl": 21,
}
SYSTEM = (
    "Jesteś technicznym asystentem diagnostyki ECU i elektroniki automotive. "
    "Oddzielaj fakty od hipotez, nie zgaduj części do wymiany, wybieraj pomiar "
    "rozdzielający i jawnie zatrzymuj wnioskowanie przy niewystarczających danych. "
    "Odpowiadaj po polsku: FAKTY; WYKLUCZONE; HIPOTEZY; TEST ROZDZIELAJĄCY; "
    "OCZEKIWANE WYNIKI; INTERPRETACJA; NASTĘPNY KROK; PEWNOŚĆ."
)
ALLOWED_DK = ("topic", "subtopic", "generalizable_pattern", "diagnostic_use", "source_id")

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())

def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def write_jsonl(path: Path, rows: list[dict]) -> None:
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")

def load_examples():
    spec = importlib.util.spec_from_file_location("p511_knowledge_examples", HERE / "knowledge_examples.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    examples = list(module.EXAMPLES)
    if len(examples) != 28:
        raise RuntimeError(f"expected 28 authored knowledge scenarios, got {len(examples)}")
    return examples

def make_dk_rows() -> list[dict]:
    raw = read_jsonl(DK_PATH)
    examples = load_examples()
    if len(raw) != len(examples):
        raise RuntimeError(f"DK/example count mismatch: {len(raw)} != {len(examples)}")
    rows = []
    for idx, (record, example) in enumerate(zip(raw, examples), 1):
        meta = {key: record.get(key) for key in ALLOWED_DK}
        if any(not meta[key] for key in ALLOWED_DK):
            raise RuntimeError(f"missing permitted DK metadata in row {idx}")
        user, hypothesis, test, outcomes = example
        assistant = (
            f"FAKTY: {user}\n"
            "WYKLUCZONE: Na podstawie samego opisu niczego nie wolno jeszcze wykluczyć pomiarem.\n"
            f"HIPOTEZY: {hypothesis}\n"
            f"TEST ROZDZIELAJĄCY: {test}\n"
            f"OCZEKIWANE WYNIKI: {outcomes}\n"
            "INTERPRETACJA: Wniosek wybiera się dopiero po wyniku testu i porównaniu z hipotezą konkurencyjną.\n"
            "NASTĘPNY KROK: Wykonaj bezpieczny pomiar, zapisz warunki testu i dopiero wtedy zawężaj przyczynę.\n"
            "PEWNOŚĆ: Wysoka co do procedury; przyczyna pozostaje warunkowa do czasu pomiaru."
        )
        rows.append({
            "record_id": f"P511-DK-{idx:04d}",
            "system": SYSTEM,
            "user": user,
            "assistant": assistant,
            "metadata": {
                "schema_version": 1,
                "language": "pl",
                "category": str(meta["topic"]),
                "subtopic": str(meta["subtopic"]),
                "training_eligible": True,
                "split": "train",
                "source_kind": "project_owned_paraphrase_from_curated_diagnostic_knowledge",
                "source_policy": "diagnostic_use_plus_generalizable_pattern_only_no_source_fact_copy",
                "source_id": str(meta["source_id"]),
                "diagnostic_use": str(meta["diagnostic_use"]),
                "generalizable_pattern": str(meta["generalizable_pattern"]),
                "curriculum": "automotive-specialization-v1",
            },
        })
    return rows

def select_diverse(rows: list[dict], count: int) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        meta = row.get("metadata", {})
        if meta.get("split") != "train" or not meta.get("training_eligible", False):
            raise RuntimeError("replay source contains non-train/non-eligible row")
        groups[str(meta.get("category", "uncategorized"))].append(row)
    for values in groups.values():
        values.sort(key=lambda r: r["record_id"])
    selected = []
    categories = sorted(groups)
    round_idx = 0
    while len(selected) < count:
        progressed = False
        for category in categories:
            values = groups[category]
            if round_idx < len(values):
                selected.append(values[round_idx])
                progressed = True
                if len(selected) == count:
                    break
        if not progressed:
            raise RuntimeError("not enough replay rows")
        round_idx += 1
    return selected

def main() -> int:
    base_rows = read_jsonl(FIXTURE)
    if len(base_rows) != 155:
        raise RuntimeError(f"expected 155 curriculum rows, got {len(base_rows)}")
    if any(not r.get("metadata", {}).get("training_eligible") for r in base_rows):
        raise RuntimeError("automotive curriculum contains non-training row")
    dk_rows = make_dk_rows()
    new_rows = []
    for row in base_rows:
        copied = json.loads(json.dumps(row))
        copied.setdefault("metadata", {})["p511_origin"] = "automotive_curriculum_v2"
        copied["metadata"]["split"] = "train"
        new_rows.append(copied)
    new_rows.extend(dk_rows)
    if len(new_rows) != 183:
        raise RuntimeError(f"new curriculum must have 183 rows, got {len(new_rows)}")
    write_jsonl(OUT_NEW, new_rows)

    replay_rows = []
    replay_counts = {}
    replay_categories = {}
    for path, target in REPLAY_TARGETS.items():
        source = read_jsonl(path)
        chosen = select_diverse(source, target)
        replay_counts[path.name] = len(chosen)
        replay_categories[path.name] = sorted({r["metadata"]["category"] for r in chosen})
        for row in chosen:
            copied = json.loads(json.dumps(row))
            copied.setdefault("metadata", {})["p511_origin"] = path.name
            copied["metadata"]["p511_replay"] = True
            replay_rows.append(copied)
    if len(replay_rows) != 61:
        raise RuntimeError(f"replay must have 61 rows, got {len(replay_rows)}")

    combined = new_rows + replay_rows
    rng = random.Random(SEED)
    rng.shuffle(combined)
    if len(combined) != 244:
        raise RuntimeError(f"combined dataset must have 244 rows, got {len(combined)}")
    write_jsonl(OUT_REPLAY, combined)

    manifest = {
        "schema_version": 1,
        "dataset_id": "automotive-specialization-v1",
        "status": "TRAINING_DATA_READY_NO_QUALITY_ACCEPTANCE",
        "new_records": len(new_rows),
        "automotive_curriculum_v2_records": len(base_rows),
        "diagnostic_knowledge_paraphrase_records": len(dk_rows),
        "records": len(new_rows),
        "dataset_sha256": sha256_file(OUT_NEW),
        "source_fixture_sha256": sha256_file(FIXTURE),
        "diagnostic_knowledge_input_sha256": sha256_file(DK_PATH),
        "knowledge_fields_used": list(ALLOWED_DK),
        "source_fact_used": False,
        "protected_eval_material_used": False,
        "quality_acceptance": "PENDING_FUTURE_INDEPENDENT_EVALUATION",
    }
    replay_manifest = {
        "schema_version": 1,
        "dataset_id": "automotive-specialization-v1-replay",
        "status": "TRAINING_DATA_READY_NO_QUALITY_ACCEPTANCE",
        "new_records": len(new_rows),
        "replay_records": len(replay_rows),
        "records": len(combined),
        "replay_fraction": len(replay_rows) / len(combined),
        "trainer_shuffle_seed": SEED,
        "dataset_sha256": sha256_file(OUT_REPLAY),
        "new_dataset_sha256": sha256_file(OUT_NEW),
        "replay_sources": replay_counts,
        "replay_categories": replay_categories,
        "optimizer_steps": 64,
        "microsteps": 244,
        "gradient_groups": {"size_3": 12, "size_4": 52},
        "parent_adapter": "/srv/ai-data/training/p5/adapters/electronics-foundation-v3/current",
        "lora_r": 8,
        "learning_rate": 2e-5,
        "max_length": 640,
        "stability_profile": {"HSA_USE_SVM": "0"},
        "protected_eval_material_used": False,
        "quality_acceptance": "PENDING_FUTURE_INDEPENDENT_EVALUATION",
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPLAY_MANIFEST.write_text(json.dumps(replay_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("P5_11_AUTOMOTIVE_DATASET_GATE=PASS")
    print(json.dumps({
        "new_records": len(new_rows),
        "replay_records": len(replay_rows),
        "combined_records": len(combined),
        "replay_fraction": len(replay_rows) / len(combined),
        "dataset_sha256": replay_manifest["dataset_sha256"],
        "categories": len(Counter(r["metadata"].get("category") for r in new_rows)),
    }, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
