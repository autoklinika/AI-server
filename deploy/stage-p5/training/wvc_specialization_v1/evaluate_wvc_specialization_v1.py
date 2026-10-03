#!/usr/bin/env python3
"""Two-model WVC smoke. Mechanical + auditable keyword telemetry; human/frozen review stays authoritative."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path
from prepare_wvc_specialization_v1 import HERE, QUALITY, read, sha

def normalized(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD",text.casefold().replace("ł","l"))
        if not unicodedata.combining(c)
    )

def has(text: str, needle: str) -> bool:
    return normalized(needle) in normalized(text)

def repetition(text: str) -> int:
    lines=[re.sub(r"\s+"," ",x.strip()) for x in text.splitlines() if len(x.strip())>=18]
    seen=set(); repeated=0
    for line in lines:
        key=normalized(line)
        if key in seen: repeated+=1
        seen.add(key)
    return repeated

def score(text: str,row: dict) -> dict:
    must=row["expected"]["must_include"]
    must_not=row["expected"]["must_not_include"]
    included={x:has(text,x) for x in must}
    forbidden={x:has(text,x) for x in must_not}
    return {
        "must_include":included,
        "must_include_recall":sum(included.values())/len(included) if included else 1.0,
        "must_not_triggered":forbidden,
        "must_not_pass":not any(forbidden.values()),
        "repeated_nontrivial_lines":repetition(text),
        "quality_acceptance":"PENDING_WVC_BASELINE_REVIEW",
    }

def api(url: str,path: str,body=None,timeout=600):
    raw=None if body is None else json.dumps(body,ensure_ascii=False).encode()
    req=urllib.request.Request(url+path,data=raw,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return json.load(response)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--models",nargs=2,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--url",default="http://127.0.0.1:11434")
    args=ap.parse_args()
    if args.models[0]==args.models[1]: ap.error("two distinct model names required")
    from validate_wvc_specialization_v1 import validate
    validate()
    rows=read(HERE/"wvc_specialization_v1_smoke.jsonl")
    version=api(args.url,"/api/version")
    tags=api(args.url,"/api/tags").get("models",[])
    identities={}
    for model in args.models:
        item=next((x for x in tags if x.get("name")==model or x.get("model")==model),None)
        if item is None: raise RuntimeError("missing model identity: "+model)
        identities[model]={"digest":item.get("digest"),"size":item.get("size")}
    results=[]
    for model in args.models:
        for row in rows:
            body={
                "model":model,
                "system":row["system"],
                "prompt":row["user"],
                "stream":False,
                "think":False,
                "keep_alive":"30m",
                "options":{"temperature":0,"seed":20261003,"num_ctx":4096,"num_predict":512},
            }
            started=time.perf_counter()
            raw=api(args.url,"/api/generate",body)
            seconds=time.perf_counter()-started
            if raw.get("done") is not True or not raw.get("response","").strip():
                raise RuntimeError("incomplete smoke response: "+model+" "+row["record_id"])
            text=raw["response"]
            results.append({
                "model":model,
                "record_id":row["record_id"],
                "response":text,
                "response_sha256":hashlib.sha256(text.encode()).hexdigest(),
                "done_reason":raw.get("done_reason"),
                "seconds":seconds,
                "eval_count":raw.get("eval_count"),
                "score":score(text,row),
            })
    payload={
        "schema_version":1,
        "stage":"P5.13",
        "adapter_id":"wvc-specialization-v1",
        "ollama_api_version":version,
        "models":identities,
        "smoke_sha256":sha(HERE/"wvc_specialization_v1_smoke.jsonl"),
        "quality_acceptance":QUALITY,
        "semantic_authority":"frozen WVC baseline + manual review",
        "results":results,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
