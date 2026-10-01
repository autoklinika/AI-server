#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4_2"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
RUNNER=ROOT/"deploy/stage-p5/benchmark/run_quality_benchmark_v1.py"
EXPECTED="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
REQ={"diagnostic_model","discriminating_measurement","predicted_result","abstain"}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p): return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def system():
    tree=ast.parse(RUNNER.read_text())
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="SYSTEM" for t in n.targets):
            return ast.literal_eval(n.value)
    raise RuntimeError

def main():
    train=load(DIR/"targeted_v42_train.jsonl"); hold=load(DIR/"targeted_v42_holdout.jsonl"); mixed=load(DIR/"targeted_v42_replay_train.jsonl")
    m=json.loads((DIR/"targeted_v42.manifest.json").read_text())
    p55=P55.read_text(); parsed=[json.loads(r["assistant"]) for r in train+hold]
    cats=collections.Counter(r["metadata"]["category"] for r in train)
    checks={
      "p55_frozen":sha(P55)==EXPECTED,
      "system_exact":all(r["system"]==system() for r in train+hold),
      "schema_exact":all(set(x)==REQ and isinstance(x["abstain"],bool) for x in parsed),
      "p55_excluded":all(r["user"] not in p55 for r in train+hold),
      "train_records":len(train)==192,"holdout_records":len(hold)==57,"mixed_records":len(mixed)==210,
      "abstain_true":sum(x["abstain"] for x in parsed[:len(train)])==28,
      "abstain_false":sum(not x["abstain"] for x in parsed[:len(train)])==164,
      "supply_present":cats["schematic_symptom_measurements"]==28,
      "wave_present":cats["numeric_waveform"]==28,"thermal_present":cats["thermal_intermittent"]==28,
      "short_present":cats["pcb_short"]==28,"unknown_present":cats["insufficient_data"]==28,
      "borderline_present":cats["borderline_sufficient"]==24,
      "train_sha":m["train_sha256"]==sha(DIR/"targeted_v42_train.jsonl"),
      "hold_sha":m["holdout_sha256"]==sha(DIR/"targeted_v42_holdout.jsonl"),
      "mixed_sha":m["mixed_sha256"]==sha(DIR/"targeted_v42_replay_train.jsonl"),
    }
    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks,"categories":cats},default=dict,sort_keys=True))
    print("P5_6_2_READINESS="+status)
    if status!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
