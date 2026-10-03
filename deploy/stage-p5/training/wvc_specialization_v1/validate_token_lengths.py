#!/usr/bin/env python3
"""CPU-only exact Qwen3.8 chat-template validation for P5.13 WVC."""
import argparse
import json
from pathlib import Path
from prepare_wvc_specialization_v1 import HERE, QUALITY, read, sha

def check(model_dir):
    from transformers import AutoTokenizer
    from validate_wvc_specialization_v1 import validate
    validate()
    tok=AutoTokenizer.from_pretrained(str(model_dir),local_files_only=True)
    lengths=[]
    for row in read(HERE/"wvc_specialization_v1_replay_train.jsonl"):
        prompt=[{"role":"system","content":row["system"]},{"role":"user","content":row["user"]}]
        full=prompt+[{"role":"assistant","content":row["assistant"]}]
        pids=tok(tok.apply_chat_template(
            prompt,tokenize=False,add_generation_prompt=True,enable_thinking=False
        ),add_special_tokens=False)["input_ids"]
        fids=tok(tok.apply_chat_template(
            full,tokenize=False,add_generation_prompt=False,enable_thinking=False
        ),add_special_tokens=False)["input_ids"]
        if not 0 < len(pids) < len(fids) <= 768:
            raise ValueError("token contract: "+row["record_id"]+f" full={len(fids)}")
        if fids[:len(pids)] != pids:
            raise ValueError("chat template prompt/target prefix mismatch: "+row["record_id"])
        lengths.append({
            "record_id":row["record_id"],
            "full_tokens":len(fids),
            "target_tokens":len(fids)-len(pids),
        })
    return {
        "stage":"P5.13",
        "adapter_id":"wvc-specialization-v1",
        "status":"PASS",
        "records":len(lengths),
        "max_length":768,
        "truncated_records":0,
        "dataset_sha256":sha(HERE/"wvc_specialization_v1_replay_train.jsonl"),
        "tokenizer_sha256":sha(model_dir/"tokenizer.json"),
        "tokenizer_config_sha256":sha(model_dir/"tokenizer_config.json"),
        "max_tokens":max(r["full_tokens"] for r in lengths),
        "max_target_tokens":max(r["target_tokens"] for r in lengths),
        "quality_acceptance":QUALITY,
        "lengths":lengths,
    }

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--model-dir",type=Path,required=True)
    ap.add_argument("--output",type=Path,default=HERE/"token_validation.json")
    args=ap.parse_args()
    result=check(args.model_dir)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="lengths"},sort_keys=True))
