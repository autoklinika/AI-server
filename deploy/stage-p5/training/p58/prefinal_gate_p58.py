#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p): return json.loads(Path(p).read_text())
def loss(d): return float(d["token_weighted_loss"])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dev-quality",required=True)
    ap.add_argument("--p57-parent",required=True); ap.add_argument("--p57-candidate",required=True)
    ap.add_argument("--p55-parent",required=True); ap.add_argument("--p55-candidate",required=True)
    for v in ("v1","v2","v3","v4"):
        ap.add_argument(f"--parent-{v}",required=True); ap.add_argument(f"--candidate-{v}",required=True)
    ap.add_argument("--candidate",required=True); ap.add_argument("--output",required=True)
    a=ap.parse_args()
    dev=load(a.dev_quality)
    p57p=load(a.p57_parent)["metrics"]; p57c=load(a.p57_candidate)["metrics"]
    p55p=load(a.p55_parent)["metrics"]; p55c=load(a.p55_candidate)["metrics"]
    keys=("diagnostic_model_pass_rate","measurement_pass_rate","prediction_pass_rate",
          "no_guessing_pass_rate","insufficient_data_abstention_rate","overall_dimension_pass_rate")
    p57_delta={k:p57c[k]-p57p[k] for k in keys}
    p55_delta={k:p55c[k]-p55p[k] for k in keys}
    regress={}
    for v in ("v1","v2","v3","v4"):
        p=load(getattr(a,"parent_"+v)); c=load(getattr(a,"candidate_"+v))
        regress[v]=(loss(c)-loss(p))/loss(p)
    checks={
      "dev_gate":dev.get("status")=="PASS",
      "regression_v1":regress["v1"]<=0.02,"regression_v2":regress["v2"]<=0.02,
      "regression_v3":regress["v3"]<=0.02,"regression_v4":regress["v4"]<=0.02,
      "p57_final_regression":all(x>=-0.02 for x in p57_delta.values()),
      "p55_regression":all(x>=-0.02 for x in p55_delta.values())
    }
    status="PASS" if all(checks.values()) else "FAIL"
    out={"status":status,"candidate":a.candidate,"checks":checks,"dev_metrics":dev["metrics"],
         "relative_regression_vs_parent":regress,"p57_final_metric_delta":p57_delta,"p55_metric_delta":p55_delta,
         "final_open_allowed":status=="PASS"}
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps(out,ensure_ascii=False,sort_keys=True)); print("P58_PREFINAL_GATE="+status)
    if status!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
