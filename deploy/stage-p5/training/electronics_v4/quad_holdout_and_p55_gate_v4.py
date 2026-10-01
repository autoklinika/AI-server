#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
def load(p):
    d=json.loads(Path(p).read_text())
    if d.get("status") not in (None,"PASS","NEEDS_IMPROVEMENT"): raise ValueError(f"bad_status:{p}")
    return d
def loss(d): return float(d["token_weighted_loss"])
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--v4-base",required=True); ap.add_argument("--v4-tuned",required=True)
    ap.add_argument("--v3-ref",required=True); ap.add_argument("--v3-tuned",required=True)
    ap.add_argument("--v2-ref",required=True); ap.add_argument("--v2-tuned",required=True)
    ap.add_argument("--v1-ref",required=True); ap.add_argument("--v1-tuned",required=True)
    ap.add_argument("--p55-review",required=True); ap.add_argument("--output",required=True)
    a=ap.parse_args()
    v4b,v4t=load(a.v4_base),load(a.v4_tuned); v3r,v3t=load(a.v3_ref),load(a.v3_tuned)
    v2r,v2t=load(a.v2_ref),load(a.v2_tuned); v1r,v1t=load(a.v1_ref),load(a.v1_tuned)
    q=load(a.p55_review); m=q["dimension_rates"]
    imp=(loss(v4b)-loss(v4t))/loss(v4b)
    regs={"v3":(loss(v3t)-loss(v3r))/loss(v3r),"v2":(loss(v2t)-loss(v2r))/loss(v2r),"v1":(loss(v1t)-loss(v1r))/loss(v1r)}
    checks={
      "v4_target_improvement":imp>=0.05,
      "v3_regression":regs["v3"]<=0.03,"v2_regression":regs["v2"]<=0.03,"v1_regression":regs["v1"]<=0.03,
      "p55_diagnostic_model":m["diagnostic_model"]>=0.85,
      "p55_discriminating_measurement":m["discriminating_measurement"]>=0.85,
      "p55_predicted_result":m["predicted_result"]>=0.80,
      "p55_no_guessing":m["no_guessing"]>=0.95,
      "p55_overall":q["overall_weighted_rate"]>=0.85,
    }
    res={"status":"PASS" if all(checks.values()) else "FAIL","checks":checks,
         "v4_relative_improvement":imp,"relative_regression":regs,
         "p55_dimension_rates":m,"p55_overall":q["overall_weighted_rate"]}
    Path(a.output).write_text(json.dumps(res,indent=2,sort_keys=True)+"\n")
    print(json.dumps(res,sort_keys=True)); print("P5_6_FINAL_GATE="+res["status"])
if __name__=="__main__": main()
