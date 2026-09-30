#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--v2-base",required=True)
    ap.add_argument("--v2-tuned",required=True)
    ap.add_argument("--v1-reference",required=True)
    ap.add_argument("--v1-tuned",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--min-v2-relative-improvement",type=float,default=0.05)
    ap.add_argument("--max-v1-relative-regression",type=float,default=0.03)
    args=ap.parse_args()
    docs={k:json.loads(Path(v).read_text()) for k,v in {
        "v2_base":args.v2_base,"v2_tuned":args.v2_tuned,
        "v1_reference":args.v1_reference,"v1_tuned":args.v1_tuned}.items()}
    for k,d in docs.items():
        if d.get("status")!="PASS": raise SystemExit(f"P5_3_DUAL_HOLDOUT=FAIL status:{k}")
    vb=docs["v2_base"]["token_weighted_loss"]; vt=docs["v2_tuned"]["token_weighted_loss"]
    vr=docs["v1_reference"]["token_weighted_loss"]; v1t=docs["v1_tuned"]["token_weighted_loss"]
    v2_imp=(vb-vt)/vb
    v1_reg=(v1t-vr)/vr
    result={
        "v2_base_loss":vb,"v2_tuned_loss":vt,"v2_relative_improvement":v2_imp,
        "v1_reference_loss":vr,"v1_tuned_loss":v1t,"v1_relative_regression":v1_reg,
        "min_v2_relative_improvement":args.min_v2_relative_improvement,
        "max_v1_relative_regression":args.max_v1_relative_regression,
        "v2_gate_pass":v2_imp>=args.min_v2_relative_improvement,
        "v1_regression_gate_pass":v1_reg<=args.max_v1_relative_regression,
    }
    result["gate_pass"]=result["v2_gate_pass"] and result["v1_regression_gate_pass"]
    Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,sort_keys=True))
    if not result["gate_pass"]: raise SystemExit("P5_3_DUAL_HOLDOUT=FAIL")
    print("P5_3_DUAL_HOLDOUT=PASS")

if __name__=="__main__":
    main()
