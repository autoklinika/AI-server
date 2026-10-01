#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/p58"
def sha(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for c in iter(lambda:f.read(1024*1024),b""): h.update(c)
    return h.hexdigest()
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def main():
    m=json.loads((DIR/"p58_manifest.json").read_text())
    files={"train":DIR/"p58_curriculum_train.jsonl","dev":DIR/"p58_dev_v1.jsonl",
      "mini":DIR/"p58_mini_dev_v1.jsonl","final":DIR/"p58_final_v1.jsonl",
      "reg":DIR/"p58_p57final_regression.jsonl"}
    trn,dev,mini,fin,reg=(rows(files[k]) for k in ("train","dev","mini","final","reg"))
    ttext={r["user"] for r in trn}; dtext={r["prompt"] for r in dev}; ftext={r["prompt"] for r in fin}
    checks={
      "train_count":len(trn)==m["train_records"],"dev_count":len(dev)==m["dev_records"],
      "mini_count":len(mini)==m["mini_dev_records"],"final_count":len(fin)==m["final_records"],
      "train_sha":sha(files["train"])==m["train_sha256"],"dev_sha":sha(files["dev"])==m["dev_sha256"],
      "mini_sha":sha(files["mini"])==m["mini_dev_sha256"],"final_sha":sha(files["final"])==m["final_sha256"],
      "train_final_disjoint":not bool(ttext&ftext),"dev_final_disjoint":not bool(dtext&ftext),
      "mini_subset":all(r["case_id"] in {x["case_id"] for x in dev} for r in mini),
      "final_exclusion":all(r.get("training_exclusion") is True for r in fin),
      "p57_regression_count":len(reg)==56,
      "final_policy_locked":m["final_policy"].startswith("never used for training")
    }
    status="PASS" if all(checks.values()) else "FAIL"
    print(json.dumps({"status":status,"checks":checks},sort_keys=True)); print("P58_READINESS="+status)
    if status!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
