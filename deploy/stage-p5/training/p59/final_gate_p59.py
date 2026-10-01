#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

CORE=("diagnostic_model_pass_rate","measurement_pass_rate","prediction_pass_rate",
      "no_guessing_pass_rate","insufficient_data_abstention_rate",
      "overall_dimension_pass_rate")

def load(p):
    return json.loads(Path(p).read_text())

def loss(d):
    return float(d["token_weighted_loss"])

def deltas(parent,candidate):
    return {k:float(candidate[k])-float(parent[k]) for k in CORE}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--thermal-dev",required=True)
    ap.add_argument("--broad-dev",required=True)
    ap.add_argument("--final-quality",required=True)
    ap.add_argument("--p57-parent",required=True)
    ap.add_argument("--p57-candidate",required=True)
    ap.add_argument("--p55-parent",required=True)
    ap.add_argument("--p55-candidate",required=True)
    for v in ("v1","v2","v3","v4"):
        ap.add_argument(f"--parent-{v}",required=True)
        ap.add_argument(f"--candidate-{v}",required=True)
    ap.add_argument("--candidate",required=True)
    ap.add_argument("--run-id",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()

    thermal=load(a.thermal_dev)
    broad=load(a.broad_dev)
    final=load(a.final_quality)
    p57p=load(a.p57_parent)["metrics"]; p57c=load(a.p57_candidate)["metrics"]
    p55p=load(a.p55_parent)["metrics"]; p55c=load(a.p55_candidate)["metrics"]
    p57_delta=deltas(p57p,p57c); p55_delta=deltas(p55p,p55c)

    regress={}
    for v in ("v1","v2","v3","v4"):
        p=load(getattr(a,"parent_"+v)); c=load(getattr(a,"candidate_"+v))
        regress[v]=(loss(c)-loss(p))/loss(p)

    fm=final["metrics"]
    checks={
      "thermal_dev_gate":thermal.get("status")=="PASS",
      "broad_p58_dev_gate":broad.get("status")=="PASS",
      "sealed_final_gate":final.get("status")=="PASS",
      "final_parse_100":float(fm["final_parse_rate"])>=1.0,
      "final_diagnostic_90":float(fm["diagnostic_model_pass_rate"])>=0.90,
      "final_measurement_90":float(fm["measurement_pass_rate"])>=0.90,
      "final_prediction_90":float(fm["prediction_pass_rate"])>=0.90,
      "final_no_guessing_98":float(fm["no_guessing_pass_rate"])>=0.98,
      "final_abstention_100":float(fm["insufficient_data_abstention_rate"])>=1.0,
      "final_overall_90":float(fm["overall_dimension_pass_rate"])>=0.90,
      "regression_v1":regress["v1"]<=0.02,
      "regression_v2":regress["v2"]<=0.02,
      "regression_v3":regress["v3"]<=0.02,
      "regression_v4":regress["v4"]<=0.02,
      "p57_regression":all(x>=-0.02 for x in p57_delta.values()),
      "p55_regression":all(x>=-0.02 for x in p55_delta.values())
    }
    status="PASS" if all(checks.values()) else "FAIL"
    out={
      "status":status,"run_id":a.run_id,"candidate":a.candidate,
      "checks":checks,
      "thermal_dev_metrics":thermal["metrics"],
      "broad_dev_metrics":broad["metrics"],
      "final_metrics":fm,
      "final_category_metrics":final.get("category_metrics",{}),
      "relative_regression_vs_parent":regress,
      "p57_metric_delta":p57_delta,
      "p55_metric_delta":p55_delta,
      "stability_policy":{
        "independent_qualified_runs_required":2,
        "this_run_qualified":status=="PASS",
        "stable_release_ready":False
      }
    }
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    print("P59_FINAL_GATE="+status)
    if status!="PASS":
        raise SystemExit(1)

if __name__=="__main__":
    main()
