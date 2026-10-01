#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4_1"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
RUNNER=ROOT/"deploy/stage-p5/benchmark/run_quality_benchmark_v1.py"
EXPECTED="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
REQ={"diagnostic_model","discriminating_measurement","predicted_result","abstain"}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def runner_system():
    tree=ast.parse(RUNNER.read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="SYSTEM" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("SYSTEM not found")

def main():
    train=load(DIR/"contract_aligned_v41_train.jsonl")
    hold=load(DIR/"contract_aligned_v41_holdout.jsonl")
    mixed=load(DIR/"contract_aligned_v41_replay_train.jsonl")
    m=json.loads((DIR/"contract_aligned_v41.manifest.json").read_text())
    parsed=[json.loads(r["assistant"]) for r in train+hold]
    checks={
      "p55_frozen":sha(P55)==EXPECTED,
      "system_exact":all(r["system"]==runner_system() for r in train+hold),
      "schema_exact":all(set(x)==REQ and isinstance(x["abstain"],bool) for x in parsed),
      "train_records":len(train)==144,
      "holdout_records":len(hold)==48,
      "mixed_records":len(mixed)==168,
      "abstain_true":sum(x["abstain"] for x in parsed[:len(train)])==24,
      "abstain_false":sum(not x["abstain"] for x in parsed[:len(train)])==120,
      "p55_excluded":all(r["user"] not in P55.read_text() for r in train+hold),
      "train_sha":m["train_sha256"]==sha(DIR/"contract_aligned_v41_train.jsonl"),
      "hold_sha":m["holdout_sha256"]==sha(DIR/"contract_aligned_v41_holdout.jsonl"),
      "mixed_sha":m["mixed_sha256"]==sha(DIR/"contract_aligned_v41_replay_train.jsonl"),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks},sort_keys=True))
    print("P5_6_1_READINESS="+status)
    if status!="PASS": raise SystemExit(1)

if __name__=="__main__": main()
