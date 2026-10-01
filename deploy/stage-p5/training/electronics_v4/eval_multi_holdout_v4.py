#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,statistics,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from peft import PeftModel
from transformers import AutoTokenizer
from streaming_bf16_loader import load_qwen_bf16
def build(tok,row,maxlen):
    prompt=[{"role":"system","content":row["system"]},{"role":"user","content":row["user"]}]
    full=prompt+[{"role":"assistant","content":row["assistant"]}]
    p=tok.apply_chat_template(prompt,tokenize=False,add_generation_prompt=True)
    f=tok.apply_chat_template(full,tokenize=False,add_generation_prompt=False)
    pids=tok(p,add_special_tokens=False)["input_ids"]; enc=tok(f,add_special_tokens=False,truncation=True,max_length=maxlen)
    ids=enc["input_ids"]; lab=list(ids); lab[:min(len(pids),len(lab))]=[-100]*min(len(pids),len(lab))
    return torch.tensor([ids],device="cuda"),torch.ones((1,len(ids)),dtype=torch.long,device="cuda"),torch.tensor([lab],device="cuda"),sum(x!=-100 for x in lab)
def evaluate(model,tok,path,maxlen):
    rows=[json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    ls=[]; weighted=0.; nt=0; t0=time.perf_counter()
    with torch.inference_mode():
      for row in rows:
        ids,mask,labels,n=build(tok,row,maxlen); v=float(model(input_ids=ids,attention_mask=mask,labels=labels).loss.detach().cpu())
        ls.append(v); weighted+=v*n; nt+=n
    torch.cuda.synchronize()
    return {"status":"PASS","records":len(rows),"mean_case_loss":sum(ls)/len(ls),"token_weighted_loss":weighted/nt,
            "perplexity":math.exp(min(20,weighted/nt)),"median_case_loss":statistics.median(ls),"target_tokens":nt,"seconds":time.perf_counter()-t0}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--model-dir",required=True); ap.add_argument("--adapter-dir",required=True)
    ap.add_argument("--dataset",action="append",required=True,help="NAME=PATH"); ap.add_argument("--output-dir",required=True); ap.add_argument("--max-length",type=int,default=960)
    a=ap.parse_args(); tok=AutoTokenizer.from_pretrained(a.model_dir,local_files_only=True); model,load=load_qwen_bf16(a.model_dir)
    model=PeftModel.from_pretrained(model,a.adapter_dir,is_trainable=False); model.eval(); out=Path(a.output_dir); out.mkdir(parents=True,exist_ok=True)
    for spec in a.dataset:
      name,path=spec.split("=",1); r=evaluate(model,tok,path,a.max_length); r["adapter_dir"]=a.adapter_dir; r["model_load"]=load
      (out/f"{name}.json").write_text(json.dumps(r,indent=2,sort_keys=True)+"\n"); print(name,json.dumps(r,sort_keys=True),flush=True)
    print("P5_6_MULTI_HOLDOUT_EVAL=PASS")
if __name__=="__main__": main()
