#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p): return json.loads(Path(p).read_text())
def loss(d): return float(d["token_weighted_loss"])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--parent-v41",required=True); ap.add_argument("--tuned-v41",required=True)
    for v in ("v1","v2","v3","v4"):
        ap.add_argument(f"--parent-{v}",required=True); ap.add_argument(f"--tuned-{v}",required=True)
    ap.add_argument("--quality-v1",required=True); ap.add_argument("--quality-v2",required=True); ap.add_argument("--output",required=True)
    a=ap.parse_args()
    pb=load(a.parent_v41); tv=load(a.tuned_v41)
    improve=(loss(pb)-loss(tv))/loss(pb)
    regress={}
    for v in ("v1","v2","v3","v4"):
        p=load(getattr(a,"parent_"+v)); t=load(getattr(a,"tuned_"+v))
        regress[v]=(loss(t)-loss(p))/loss(p)
    q1=load(a.quality_v1); q2=load(a.quality_v2); m=q2["metrics"]
    checks={
      "v41_target_improvement": improve>=0.05,
      "v1_regression": regress["v1"]<=0.03,
      "v2_regression": regress["v2"]<=0.03,
      "v3_regression": regress["v3"]<=0.03,
      "v4_regression": regress["v4"]<=0.03,
      "p55_v2_parse": m["parse_rate"]>=1.0,
      "p55_v2_diagnostic": m["diagnostic_model_pass_rate"]>=0.80,
      "p55_v2_measurement": m["measurement_pass_rate"]>=0.85,
      "p55_v2_prediction": m["prediction_pass_rate"]>=0.80,
      "p55_v2_no_guessing": m["no_guessing_pass_rate"]>=0.95,
      "p55_v2_abstention": m["insufficient_data_abstention_rate"]>=1.0,
      "p55_v2_overall": m["overall_dimension_pass_rate"]>=0.85,
    }
    out={"status":"PASS" if all(checks.values()) else "FAIL","checks":checks,
      "v41_relative_improvement":improve,"relative_regression_vs_p56_r3":regress,
      "quality_v1_status":q1.get("status"),"quality_v1_metrics":q1.get("metrics"),
      "quality_v2_status":q2.get("status"),"quality_v2_metrics":m}
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps(out,ensure_ascii=False,sort_keys=True)); print("P5_6_1_FINAL_GATE="+out["status"])
    if out["status"]!="PASS": raise SystemExit(1)

if __name__=="__main__": main()
