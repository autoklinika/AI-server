#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, statistics, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from peft import PeftModel
from transformers import AutoTokenizer
from streaming_bf16_loader import load_qwen_bf16

def build(tok,row,max_length):
    prompt=[{"role":"system","content":row["system"]},{"role":"user","content":row["user"]}]
    full=prompt+[{"role":"assistant","content":row["assistant"]}]
    ptxt=tok.apply_chat_template(prompt,tokenize=False,add_generation_prompt=True)
    ftxt=tok.apply_chat_template(full,tokenize=False,add_generation_prompt=False)
    pids=tok(ptxt,add_special_tokens=False)["input_ids"]
    enc=tok(ftxt,add_special_tokens=False,truncation=True,max_length=max_length)
    ids=enc["input_ids"]; labels=list(ids)
    labels[:min(len(pids),len(labels))]=[-100]*min(len(pids),len(labels))
    return (
      torch.tensor([ids],dtype=torch.long,device="cuda"),
      torch.ones((1,len(ids)),dtype=torch.long,device="cuda"),
      torch.tensor([labels],dtype=torch.long,device="cuda"),
      sum(x!=-100 for x in labels),
    )

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--model-dir",required=True)
    ap.add_argument("--dataset",required=True)
    ap.add_argument("--adapter-dir")
    ap.add_argument("--max-length",type=int,default=448)
    ap.add_argument("--output",required=True)
    args=ap.parse_args()
    rows=[json.loads(x) for x in Path(args.dataset).read_text().splitlines() if x.strip()]
    tok=AutoTokenizer.from_pretrained(args.model_dir,local_files_only=True)
    model,load_metrics=load_qwen_bf16(args.model_dir)
    if args.adapter_dir:
        model=PeftModel.from_pretrained(model,args.adapter_dir,is_trainable=False)
    model.eval()
    losses=[]; weighted=0.0; target_tokens=0
    t0=time.perf_counter()
    with torch.inference_mode():
        for i,row in enumerate(rows,1):
            ids,mask,labels,n=build(tok,row,args.max_length)
            out=model(input_ids=ids,attention_mask=mask,labels=labels)
            loss=float(out.loss.detach().cpu())
            losses.append(loss); weighted+=loss*n; target_tokens+=n
            print(json.dumps({"case":row["record_id"],"index":i,"loss":loss,"target_tokens":n}),flush=True)
    torch.cuda.synchronize()
    result={
      "status":"PASS","records":len(rows),
      "adapter_dir":args.adapter_dir,
      "mean_case_loss":sum(losses)/len(losses),
      "token_weighted_loss":weighted/target_tokens,
      "perplexity":math.exp(min(20,weighted/target_tokens)),
      "median_case_loss":statistics.median(losses),
      "target_tokens":target_tokens,
      "seconds":time.perf_counter()-t0,
      "model_load":load_metrics,
    }
    Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P5_2_ELECTRONICS_EVAL=PASS")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
