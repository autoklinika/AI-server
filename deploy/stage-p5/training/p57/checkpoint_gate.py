#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

def load(p): return json.loads(Path(p).read_text())
def loss(d): return float(d["token_weighted_loss"])

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline-reg",required=True); ap.add_argument("--checkpoint-reg",required=True)
    ap.add_argument("--quality",required=True); ap.add_argument("--checkpoint",required=True)
    ap.add_argument("--index",type=int,required=True); ap.add_argument("--state",required=True)
    ap.add_argument("--max-regression",type=float,default=0.02); ap.add_argument("--patience",type=int,default=2)
    a=ap.parse_args()
    b=load(a.baseline_reg); r=load(a.checkpoint_reg); q=load(a.quality); m=q["metrics"]
    reg=(loss(r)-loss(b))/loss(b)
    eligible=(reg<=a.max_regression and m["final_parse_rate"]>=1.0 and
              m["insufficient_data_abstention_rate"]>=1.0 and m["no_guessing_pass_rate"]>=0.95)
    score=float(m["selection_score"])
    sp=Path(a.state)
    state=load(sp) if sp.exists() else {"best_score":-1.0,"best_checkpoint":None,"best_index":None,"no_improve":0,"history":[]}
    improved=eligible and score>state["best_score"]+1e-9
    if improved:
        state["best_score"]=score; state["best_checkpoint"]=a.checkpoint; state["best_index"]=a.index; state["no_improve"]=0
    else:
        state["no_improve"]=int(state.get("no_improve",0))+1
    item={"index":a.index,"checkpoint":a.checkpoint,"regression":reg,"eligible":eligible,"score":score,
          "improved":improved,"metrics":m}
    state["history"].append(item)
    stop=(reg>a.max_regression) or (state["best_checkpoint"] is not None and state["no_improve"]>=a.patience)
    state["stop"]=stop; state["stop_reason"]="regression" if reg>a.max_regression else ("patience" if stop else None)
    sp.write_text(json.dumps(state,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps(item,ensure_ascii=False,sort_keys=True))
    print(f"P57_CHECKPOINT_ELIGIBLE={int(eligible)}")
    print(f"P57_CHECKPOINT_IMPROVED={int(improved)}")
    print(f"P57_STOP={int(stop)}")
    print(f"P57_BEST={state['best_checkpoint'] or ''}")
if __name__=="__main__": main()
