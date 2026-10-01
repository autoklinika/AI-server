#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p):
    return json.loads(Path(p).read_text())

def loss(d):
    return float(d["token_weighted_loss"])

def thermal_metrics(q):
    cat=q.get("category_metrics",{}).get("thermal_intermittent",{})
    return {
      "diagnostic":float(cat.get("diagnostic_model_pass_rate",0.0)),
      "measurement":float(cat.get("measurement_pass_rate",0.0)),
      "prediction":float(cat.get("prediction_pass_rate",0.0))
    }

def selection(q):
    m=q["metrics"]; t=thermal_metrics(q)
    return (0.15*t["diagnostic"] + 0.20*t["measurement"] +
            0.55*t["prediction"] + 0.10*float(m["no_guessing_pass_rate"]))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline-reg",required=True)
    ap.add_argument("--baseline-quality",required=True)
    ap.add_argument("--parent-checkpoint",required=True)
    ap.add_argument("--checkpoint-reg",required=True)
    ap.add_argument("--quality",required=True)
    ap.add_argument("--checkpoint",required=True)
    ap.add_argument("--index",type=int,required=True)
    ap.add_argument("--state",required=True)
    ap.add_argument("--max-regression",type=float,default=0.02)
    ap.add_argument("--patience",type=int,default=2)
    a=ap.parse_args()

    breg=load(a.baseline_reg); creg=load(a.checkpoint_reg)
    bq=load(a.baseline_quality); cq=load(a.quality)
    cm=cq["metrics"]; ct=thermal_metrics(cq)
    reg=(loss(creg)-loss(breg))/loss(breg)
    score=selection(cq)
    baseline_score=selection(bq)

    eligible=(reg<=a.max_regression and
              float(cm["final_parse_rate"])>=1.0 and
              float(cm["insufficient_data_abstention_rate"])>=1.0 and
              float(cm["no_guessing_pass_rate"])>=0.98 and
              ct["diagnostic"]>=0.80 and ct["measurement"]>=0.80)

    sp=Path(a.state)
    if sp.exists():
        state=load(sp)
    else:
        state={
          "baseline_score":baseline_score,
          "best_score":baseline_score,
          "best_checkpoint":a.parent_checkpoint,
          "best_index":0,
          "no_improve":0,
          "history":[]
        }

    improved=eligible and score>float(state["best_score"])+1e-9
    if improved:
        state["best_score"]=score
        state["best_checkpoint"]=a.checkpoint
        state["best_index"]=a.index
        state["no_improve"]=0
    else:
        state["no_improve"]=int(state.get("no_improve",0))+1

    item={
      "index":a.index,"checkpoint":a.checkpoint,
      "regression":reg,"eligible":eligible,
      "selection_score":score,"improved":improved,
      "thermal":ct,"metrics":cm
    }
    state["history"].append(item)

    stop=(reg>a.max_regression or state["no_improve"]>=a.patience)
    state["stop"]=stop
    state["stop_reason"]="regression" if reg>a.max_regression else ("patience" if stop else None)
    sp.write_text(json.dumps(state,indent=2,ensure_ascii=False,sort_keys=True)+"\n")

    print(json.dumps(item,ensure_ascii=False,sort_keys=True))
    print(f"P59_CHECKPOINT_ELIGIBLE={int(eligible)}")
    print(f"P59_CHECKPOINT_IMPROVED={int(improved)}")
    print(f"P59_STOP={int(stop)}")
    print(f"P59_BEST={state['best_checkpoint']}")
    print(f"P59_BEST_INDEX={state['best_index']}")

if __name__=="__main__":
    main()
