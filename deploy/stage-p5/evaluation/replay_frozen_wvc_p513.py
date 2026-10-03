#!/usr/bin/env python3
"""Replay immutable WVC cases on P5.11 and P5.13; never modifies the frozen bundle."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.request

EXPECTED_CORPUS_SHA="ae70251542d5d69ebac94d83b995238ea869e7e0282d62ed19d2f7501573e22a"
OPTIONS={"temperature":0,"seed":20261003,"num_ctx":65536,"num_predict":1024}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def encoded(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()

def prompt(case):
    origin=("Archiwalne dane rzeczywiste." if case["data_origin"]=="real_archived"
            else "Hipotetyczny przykład zgodny z kontraktem; nie opisuje rzeczywistej instalacji.")
    return (
        "Jesteś doradcą technika wentylacji WVC. Analiza ma charakter doradczy.\n"+origin+
        "\nOddziel obserwacje od hipotez, wskaż najbardziej rozstrzygające następne sprawdzenie, "
        "niepewność, brakujące dane i praktyczne znaczenie. Odpowiedz naturalnie i zwięźle, maksymalnie 220 słów; "
        "nie powtarzaj tych samych bloków ani list.\n"+case["question"]+
        "\nKontekst telemetryczny JSON:\n"+encoded(case["context"]).decode()
    )

def api(base,path,body=None,timeout=900):
    req=urllib.request.Request(
        base+path,
        data=None if body is None else encoded(body),
        headers={"Content-Type":"application/json"},
    )
    started=time.perf_counter()
    with urllib.request.urlopen(req,timeout=timeout) as response:
        data=response.read()
    return json.loads(data),time.perf_counter()-started

def kernel_counts():
    text=subprocess.run(["journalctl","-k","-b","--no-pager"],capture_output=True,text=True,check=False).stdout
    pats={
        "MES failed":r"MES.*failed",
        "GPU reset":r"GPU reset",
        "ring timeout":r"ring.*timeout",
        "GPUVM fault":r"GPUVM.*fault|GPU VM.*fault",
        "device wedged":r"device.*wedged",
    }
    return {k:len(re.findall(v,text,re.I)) for k,v in pats.items()}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--candidate",required=True)
    ap.add_argument("--freeze",type=Path,default=Path("/srv/ai-data/evaluation/wvc-baseline/ollama-0.32.14-p511-vs-p512-20261003"))
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--url",default="http://127.0.0.1:11434")
    args=ap.parse_args()
    corpus_raw=(args.freeze/"corpus.json").read_bytes()
    if digest(corpus_raw)!=EXPECTED_CORPUS_SHA:
        raise RuntimeError("frozen WVC corpus identity mismatch")
    if args.out.exists():
        raise RuntimeError("output already exists")
    args.out.mkdir(parents=True)
    corpus=json.loads(corpus_raw)
    models=["qwen3.8:27b-p4-64k-gpu-p511",args.candidate]
    version,_=api(args.url,"/api/version")
    tags,_=api(args.url,"/api/tags")
    identities={}
    for model in models:
        item=next((x for x in tags["models"] if x.get("name")==model or x.get("model")==model),None)
        if not item: raise RuntimeError("missing model: "+model)
        identities[model]={"digest":item.get("digest"),"size":item.get("size")}
    before=kernel_counts()
    results=[]; responses={c["id"]:{} for c in corpus["cases"]}
    for model in models:
        for case in corpus["cases"]:
            body={"model":model,"prompt":prompt(case),"think":False,"stream":False,
                  "keep_alive":"30m","options":OPTIONS}
            parsed,seconds=api(args.url,"/api/generate",body)
            answer=parsed.get("response","")
            if parsed.get("done") is not True or parsed.get("done_reason")!="stop" or not isinstance(answer,str) or not answer.strip():
                raise RuntimeError("incomplete replay: "+model+" "+case["id"])
            lines=[x.strip() for x in answer.splitlines() if len(x.strip())>=18]
            reps=sum(n-1 for n in Counter(lines).values())
            record={"case_id":case["id"],"model":model,"seconds":seconds,
                    "eval_count":parsed.get("eval_count"),"response_sha256":digest(answer.encode()),
                    "repeated_nontrivial_lines":reps,"response":answer}
            results.append(record); responses[case["id"]][model]=answer
            (args.out/f"{case['id']}-{models.index(model)}.json").write_bytes(encoded(record))
    after=kernel_counts()
    review=[{
        "case_id":c["id"],"question":c["question"],"dimensions":c["dimensions"],
        "P511":responses[c["id"]][models[0]],"P513":responses[c["id"]][models[1]],
        "manual_review":{"validity_gate":None,"command_vs_execution":None,"temporal_order":None,
                         "causal_restraint":None,"evidence_hierarchy":None,"missing_signals":None,
                         "domain_boundary":None,"repetition":None,"notes":""},
    } for c in corpus["cases"]]
    payload={"schema_version":1,"stage":"P5.13","created_at":datetime.now(timezone.utc).isoformat(),
             "frozen_corpus_sha256":EXPECTED_CORPUS_SHA,"source_freeze":str(args.freeze),
             "ollama_api_version":version,"models":identities,"options":OPTIONS,
             "gpu_error_counts_before":before,"gpu_error_counts_after":after,
             "gpu_error_delta":{k:after[k]-before[k] for k in before},
             "mechanical_error_count":0,"semantic_authority":"manual review","results":results}
    (args.out/"results.json").write_bytes(encoded(payload))
    (args.out/"manual-review.json").write_text(json.dumps(review,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    checks={str(p.relative_to(args.out)):digest(p.read_bytes()) for p in sorted(args.out.rglob("*")) if p.is_file()}
    (args.out/"SHA256SUMS.json").write_bytes(encoded(checks))
    print(json.dumps({"status":"PASS","cases":len(corpus["cases"]),"generations":len(results),
                      "gpu_error_delta":payload["gpu_error_delta"],"out":str(args.out)},sort_keys=True))

if __name__=="__main__":
    main()
