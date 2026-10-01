#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p): return json.loads(Path(p).read_text())
def loss(d): return float(d["token_weighted_loss"])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dev-quality",required=True); ap.add_argument("--final-quality",required=True)
    ap.add_argument("--legacy-parent",required=True); ap.add_argument("--legacy-candidate",required=True)
    for v in ("v1","v2","v3","v4"):
        ap.add_argument(f"--parent-{v}",required=True); ap.add_argument(f"--candidate-{v}",required=True)
    ap.add_argument("--candidate",required=True); ap.add_argument("--run-id",required=True); ap.add_argument("--output",required=True)
    a=ap.parse_args()
    dev=load(a.dev_quality); final=load(a.final_quality); lp=load(a.legacy_parent); lc=load(a.legacy_candidate)
    dm=dev["metrics"]; fm=final["metrics"]; lpm=lp["metrics"]; lcm=lc["metrics"]
    regress={}
    for v in ("v1","v2","v3","v4"):
        p=load(getattr(a,"parent_"+v)); c=load(getattr(a,"candidate_"+v))
        regress[v]=(loss(c)-loss(p))/loss(p)
    legacy_keys=("diagnostic_model_pass_rate","measurement_pass_rate","prediction_pass_rate",
                 "no_guessing_pass_rate","insufficient_data_abstention_rate","overall_dimension_pass_rate")
    legacy_delta={k:lcm[k]-lpm[k] for k in legacy_keys}
    checks={
      "dev_gate":dev.get("status")=="PASS",
      "final_gate":final.get("status")=="PASS",
      "final_parse_100":fm["final_parse_rate"]>=1.0,
      "final_abstention_100":fm["insufficient_data_abstention_rate"]>=1.0,
      "final_no_guessing_98":fm["no_guessing_pass_rate"]>=0.98,
      "final_diagnostic_90":fm["diagnostic_model_pass_rate"]>=0.90,
      "final_measurement_90":fm["measurement_pass_rate"]>=0.90,
      "final_prediction_90":fm["prediction_pass_rate"]>=0.90,
      "final_overall_90":fm["overall_dimension_pass_rate"]>=0.90,
      "regression_v1":regress["v1"]<=0.02,"regression_v2":regress["v2"]<=0.02,
      "regression_v3":regress["v3"]<=0.02,"regression_v4":regress["v4"]<=0.02,
      "legacy_regression":all(v>=-0.02 for v in legacy_delta.values())
    }
    status="PASS" if all(checks.values()) else "FAIL"
    out={"status":status,"run_id":a.run_id,"candidate":a.candidate,"checks":checks,
         "dev_metrics":dm,"final_metrics":fm,"relative_regression_vs_parent":regress,
         "legacy_regression_delta":legacy_delta,
         "stability_policy":{"independent_qualified_runs_required":2,
                             "this_run_qualified":status=="PASS",
                             "stable_release_ready":False}}
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    print("P57_FINAL_GATE="+status)
    if status!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
