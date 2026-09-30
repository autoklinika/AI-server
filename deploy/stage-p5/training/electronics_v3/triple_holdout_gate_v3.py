#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p):
    d=json.loads(Path(p).read_text())
    if d.get("status")!="PASS": raise ValueError(f"eval_not_pass:{p}")
    return d

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--v3-base",required=True); ap.add_argument("--v3-tuned",required=True)
    ap.add_argument("--v2-reference",required=True); ap.add_argument("--v2-tuned",required=True)
    ap.add_argument("--v1-reference",required=True); ap.add_argument("--v1-tuned",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--min-v3-relative-improvement",type=float,default=0.05)
    ap.add_argument("--max-v2-relative-regression",type=float,default=0.03)
    ap.add_argument("--max-v1-relative-regression",type=float,default=0.03)
    a=ap.parse_args()
    v3b,v3t=load(a.v3_base),load(a.v3_tuned)
    v2r,v2t=load(a.v2_reference),load(a.v2_tuned)
    v1r,v1t=load(a.v1_reference),load(a.v1_tuned)
    l=lambda d:float(d["token_weighted_loss"])
    v3imp=(l(v3b)-l(v3t))/l(v3b)
    v2reg=(l(v2t)-l(v2r))/l(v2r)
    v1reg=(l(v1t)-l(v1r))/l(v1r)
    res={
      "v3_base_loss":l(v3b),"v3_tuned_loss":l(v3t),"v3_relative_improvement":v3imp,
      "v2_reference_loss":l(v2r),"v2_tuned_loss":l(v2t),"v2_relative_regression":v2reg,
      "v1_reference_loss":l(v1r),"v1_tuned_loss":l(v1t),"v1_relative_regression":v1reg,
      "v3_gate_pass":v3imp>=a.min_v3_relative_improvement,
      "v2_regression_gate_pass":v2reg<=a.max_v2_relative_regression,
      "v1_regression_gate_pass":v1reg<=a.max_v1_relative_regression,
      "min_v3_relative_improvement":a.min_v3_relative_improvement,
      "max_v2_relative_regression":a.max_v2_relative_regression,
      "max_v1_relative_regression":a.max_v1_relative_regression,
    }
    res["gate_pass"]=res["v3_gate_pass"] and res["v2_regression_gate_pass"] and res["v1_regression_gate_pass"]
    Path(a.output).write_text(json.dumps(res,indent=2,sort_keys=True)+"\n")
    print(json.dumps(res,sort_keys=True))
    if not res["gate_pass"]: raise SystemExit("P5_4_TRIPLE_HOLDOUT=FAIL")
    print("P5_4_TRIPLE_HOLDOUT=PASS")
if __name__=="__main__": main()
