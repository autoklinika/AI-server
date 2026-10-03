#!/usr/bin/env python3
"""Fail-closed WVC dataset contract; protected frozen baseline remains evaluation-only."""
from __future__ import annotations
import hashlib
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path
from curriculum import CATEGORIES, render
from prepare_wvc_specialization_v1 import HERE, FILES, QUALITY, PROTECTED_EVAL, build, read, sha

NEAR_THRESHOLD=.90
SMOKE_LEAK_THRESHOLD=.58
PROTECTED_QUESTION_THRESHOLD=.48

def require(value,message):
    if not value: raise ValueError(message)

def normalize(text):
    return " ".join(re.findall(r"\w+",text.casefold()))

def shingles(text,n=5):
    words=normalize(text).split()
    return {tuple(words[i:i+n]) for i in range(max(0,len(words)-n+1))}

def similarity(a,b):
    return len(a & b)/max(1,len(a | b))

def guard_target(row):
    target=row["assistant"]
    require("OBSERWACJA:" in target,"observation section missing")
    require("HIPOTEZY:" in target,"hypotheses section missing")
    require("NIE WYNIKA:" in target,"non-conclusion missing")
    require("NAJLEPSZE NASTĘPNE SPRAWDZENIE:" in target,"next check missing")
    require("JEŚLI A:" in target and "JEŚLI B:" in target,"conditional branches missing")
    require("BRAKI/PEWNOŚĆ:" in target,"missing-data boundary missing")
    require(not re.search(r"\b(?:wymień|wymienić należy|winny jest|uszkodzony jest)\b",target,re.I),
            "parts-cannon conclusion")
    require(not re.search(r"\b(?:na pewno|jednoznacznie dowodzi|z całą pewnością)\b",target,re.I),
            "overconfident conclusion")

def validate_spec(row):
    s=row["spec"]
    for field in ("focus","check","branch_a","branch_b","missing","non_conclusion"):
        require(isinstance(s.get(field),str) and len(s[field])>20,"missing "+field)
    hs=s.get("hypotheses",[])
    require(2<=len(hs)<=4 and len(set(hs))==len(hs),"hypotheses")
    require(1<=int(s.get("variant",0))<=6,"variant")
    require("Telemetria JSON:" in row["user"],"telemetry context missing")
    require(row["metadata"].get("source_kind")=="project_owned_contract_grounded_synthetic","source kind")
    require(row["metadata"].get("training_eligible") is True and row["metadata"].get("split")=="train","training boundary")
    from curriculum import PROFILES
    require(row["assistant"]==render(PROFILES[row["metadata"]["category"]],s["variant"]),"target/spec drift")
    guard_target(row)

def protected_guard(new):
    if not PROTECTED_EVAL.is_file():
        return {"available":False,"max_question_similarity":None,"closest":None}
    frozen=json.loads(PROTECTED_EVAL.read_text(encoding="utf-8"))
    max_sim=0.0; closest=None
    for case in frozen["cases"]:
        q=shingles(case["question"])
        for row in new:
            for field in ("user","assistant"):
                sim=similarity(q,shingles(row[field]))
                if sim>max_sim:
                    max_sim=sim; closest=[case["id"],row["record_id"],field]
                require(sim<PROTECTED_QUESTION_THRESHOLD,
                        f"protected WVC question leakage: {case['id']} / {row['record_id']} / {field}: {sim:.3f}")
    return {"available":True,"corpus_sha256":sha(PROTECTED_EVAL),
            "max_question_similarity":round(max_sim,6),"closest":closest}

def validate_rows(new,combined,smoke):
    require((len(new),len(combined),len(smoke))==(96,160,12),"row counts")
    require(Counter(r["metadata"]["category"] for r in new)==Counter({c:6 for c in CATEGORIES}),"category balance")
    require(len({r["record_id"] for r in combined+smoke})==172,"duplicate IDs")
    require({r["record_id"] for r in new}==
            {r["record_id"] for r in combined if r["metadata"].get("p513_origin")=="new"},"new rows missing")
    require(all(r["metadata"].get("split")=="train" and r["metadata"].get("training_eligible",True) for r in combined),
            "non-train leakage")
    require(all(r["metadata"].get("split")=="smoke" and r["metadata"].get("training_eligible") is False for r in smoke),
            "smoke eligibility")
    require(Counter(r["metadata"]["p513_origin"] for r in combined)==
            Counter(new=96,automotive=32,electronics_v1=10,electronics_v2=11,electronics_v3=11),
            "replay composition")
    for row in new: validate_spec(row)
    for field in ("user","assistant"):
        values=[normalize(r[field]) for r in combined if field in r]
        require(len(values)==len(set(values)),"exact duplicate "+field)
    max_near=0.0; closest=None
    for field in ("user","assistant"):
        ss=[shingles(r[field]) for r in new]
        for i,j in combinations(range(len(new)),2):
            sim=similarity(ss[i],ss[j])
            if sim>max_near:
                max_near=sim; closest=[new[i]["record_id"],new[j]["record_id"],field]
            require(sim<NEAR_THRESHOLD,
                    f"near duplicate {field}: {new[i]['record_id']} / {new[j]['record_id']}: {sim:.3f}")
    max_smoke=0.0; smoke_pair=None
    for s in smoke:
        require(len(s["user"])>100,"too-easy smoke prompt")
        require(set(s["expected"])=={"must_include","must_not_include"},"smoke expectation schema")
        for r in new:
            sim=similarity(shingles(s["user"]),shingles(r["user"]))
            if sim>max_smoke:
                max_smoke=sim; smoke_pair=[s["record_id"],r["record_id"]]
            require(sim<SMOKE_LEAK_THRESHOLD,"smoke-vs-train leakage")
    protected=protected_guard(new)
    return {
        "status":"PASS",
        "new_records":96,
        "replay_records":64,
        "combined_records":160,
        "smoke_records":12,
        "replay_fraction":.40,
        "category_balance":{c:6 for c in CATEGORIES},
        "max_near_similarity":round(max_near,6),
        "closest_pair":closest,
        "near_threshold":NEAR_THRESHOLD,
        "max_smoke_train_similarity":round(max_smoke,6),
        "smoke_closest_pair":smoke_pair,
        "smoke_leak_threshold":SMOKE_LEAK_THRESHOLD,
        "protected_eval_guard":protected,
        "quality_acceptance":QUALITY,
    }

def validate():
    new,combined,smoke=[read(HERE/f) for f in FILES]
    report=validate_rows(new,combined,smoke)
    expected=build()
    require((new,combined,smoke)==expected[:3],"deterministic authoring/replay provenance mismatch")
    m=json.loads((HERE/"wvc_specialization_v1.manifest.json").read_text(encoding="utf-8"))
    require(m["files"]=={f:sha(HERE/f) for f in FILES},"dataset SHA mismatch")
    require(m["sources"]==expected[3],"replay source SHA/selection mismatch")
    require(m["authoring_sha256"]=={f:sha(HERE/f) for f in ("curriculum.py","smoke_cases.py")},"authoring SHA mismatch")
    require(m["quality_acceptance"]==QUALITY and m["protected_eval_material_used"] is False,"quality boundary")
    current_protected=report["protected_eval_guard"]
    recorded_protected=m["validation"]["protected_eval_guard"]
    if current_protected["available"]:
        require(recorded_protected==current_protected,"protected eval validation drift")
        require(m["protected_eval"].get("sha256")==current_protected["corpus_sha256"],"protected eval corpus changed")
    else:
        # The training container deliberately does not mount evaluation data.
        # Freeze the host-side leakage gate by dataset/authoring hashes and the
        # recorded immutable corpus identity rather than exposing holdout content.
        require(recorded_protected.get("available") is True,"protected eval gate was never executed")
        require(recorded_protected.get("corpus_sha256")==m["protected_eval"].get("sha256"),"protected eval identity drift")
        require(recorded_protected.get("max_question_similarity") is not None,"protected eval leakage evidence missing")
        report["protected_eval_guard"]=recorded_protected
    require(m["validation"]==report,"validation manifest drift")
    return report

if __name__=="__main__":
    print(json.dumps(validate(),ensure_ascii=False,sort_keys=True))
    print("P5_13_WVC_READINESS=PASS")
