#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/p57"

def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
    return h.hexdigest()
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]

def main():
    m=json.loads((DIR/"p57_manifest.json").read_text())
    files={"train":DIR/"p57_balanced_train.jsonl","dev":DIR/"p57_dev_v1.jsonl","mini_dev":DIR/"p57_mini_dev_v1.jsonl",
           "final":DIR/"p57_final_v1.jsonl","regression":DIR/"p57_regression_slice_v1.jsonl"}
    train,dev,mini,final,reg=(rows(files[k]) for k in ("train","dev","mini_dev","final","regression"))
    train_text={r.get("user","") for r in train}
    dev_text={r.get("prompt","") for r in dev}
    final_text={r.get("prompt","") for r in final}
    checks={
      "train_count":len(train)==m["train_records"],"dev_count":len(dev)==m["dev_records"],
      "mini_count":len(mini)==m["mini_dev_records"],"final_count":len(final)==m["final_records"],
      "reg_count":len(reg)==m["regression_slice_records"],
      "train_sha":sha(files["train"])==m["train_sha256"],"dev_sha":sha(files["dev"])==m["dev_sha256"],
      "mini_sha":sha(files["mini_dev"])==m["mini_dev_sha256"],"final_sha":sha(files["final"])==m["final_sha256"],
      "reg_sha":sha(files["regression"])==m["regression_sha256"],
      "train_final_disjoint":not bool(train_text & final_text),"dev_final_disjoint":not bool(dev_text & final_text),
      "mini_is_dev_subset":all(r["case_id"] in {x["case_id"] for x in dev} for r in mini),
      "final_training_exclusion":all(r.get("training_exclusion") is True for r in final),
      "final_policy_locked":m.get("final_policy","").startswith("never used for training")
    }
    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks},sort_keys=True)); print("P57_READINESS="+status)
    if status!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
