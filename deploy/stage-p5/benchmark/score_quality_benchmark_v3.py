#!/usr/bin/env python3
from pathlib import Path
import argparse,json,math,re,urllib.request

FIELDS=("diagnostic_model","discriminating_measurement","predicted_result")
ACTION_WORDS=("zmierz","mierz","porówn","rejestr","obserw","wykon","monitor","sprawd","wstrzy","ogrze","chłod","zadaj","test")
BRANCH_WORDS=("jeśli","gdy","wtedy","wskazuje","zawęża","potwierdza","wyklucza","przenosi","rozróż")
CERTAINTY=("na pewno","jednoznacznie winny","z całą pewnością","definitywnie","wymień ")

def norm(s): return re.sub(r"\s+"," ",str(s).lower()).strip()
def embed(texts):
    data=json.dumps({"model":"bge-m3","input":texts}).encode()
    req=urllib.request.Request("http://127.0.0.1:11434/api/embed",data=data,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=180) as r: return json.load(r)["embeddings"]
def cos(a,b):
    d=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return d/(na*nb) if na and nb else 0.0
def contains_any(s,words):
    s=norm(s); return any(w in s for w in words)
def tokenish_len(s): return len(re.findall(r"\w+",norm(s),re.UNICODE))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dataset",required=True); ap.add_argument("--results",required=True); ap.add_argument("--output",required=True)
    ap.add_argument("--diag-threshold",type=float,default=0.56); ap.add_argument("--measurement-threshold",type=float,default=0.55)
    ap.add_argument("--prediction-threshold",type=float,default=0.53); a=ap.parse_args()
    cases={r["case_id"]:r for r in (json.loads(x) for x in Path(a.dataset).read_text().splitlines() if x.strip())}
    results=[json.loads(x) for x in Path(a.results).read_text().splitlines() if x.strip()]
    details=[]; texts=[]; pairs=[]
    for r in results:
        c=cases[r["case_id"]]; p=r.get("parsed")
        d={"case_id":r["case_id"],"category":c["category"],"raw_parse_ok":bool(r.get("raw_parse_ok",p is not None)),
           "final_parse_ok":isinstance(p,dict),"repaired":bool(r.get("repaired",False))}
        if isinstance(p,dict):
            for f in FIELDS:
                texts += [str(p.get(f,"")),str(c["reference"][f])]
                pairs.append((len(details),f,len(texts)-2,len(texts)-1))
        details.append(d)
    embs=embed(texts) if texts else []
    for di,f,ia,ib in pairs: details[di][f+"_similarity"]=cos(embs[ia],embs[ib])
    for d,r in zip(details,results):
        c=cases[d["case_id"]]; p=r.get("parsed")
        if not isinstance(p,dict):
            for k in ("diagnostic_model_pass","measurement_pass","prediction_pass","no_guessing_pass","abstain_ok"): d[k]=False
            continue
        must=bool(c["reference"]["abstain"]); abst=bool(p.get("abstain"))
        ds=norm(p.get("diagnostic_model","")); ms=norm(p.get("discriminating_measurement","")); ps=norm(p.get("predicted_result",""))
        d["abstain_ok"]=abst==must
        d["no_guessing_pass"]=not contains_any(ds,CERTAINTY) and (not must or abst)
        d["diagnostic_model_pass"]=d.get("diagnostic_model_similarity",0)>=a.diag_threshold and tokenish_len(ds)>=4
        d["measurement_actionable"]=contains_any(ms,ACTION_WORDS) and tokenish_len(ms)>=4
        d["measurement_pass"]=d.get("discriminating_measurement_similarity",0)>=a.measurement_threshold and d["measurement_actionable"]
        if must:
            d["prediction_structured"]=abst and tokenish_len(ps)>=4
        else:
            d["prediction_structured"]=contains_any(ps,BRANCH_WORDS) and tokenish_len(ps)>=5
        d["prediction_pass"]=d.get("predicted_result_similarity",0)>=a.prediction_threshold and d["prediction_structured"]
    def rate(k): return sum(bool(x.get(k)) for x in details)/len(details) if details else 0.0
    abst_cases=[x for x in details if bool(cases[x["case_id"]]["reference"]["abstain"])]
    metrics={"records":len(details),"raw_parse_rate":rate("raw_parse_ok"),"final_parse_rate":rate("final_parse_ok"),
      "diagnostic_model_pass_rate":rate("diagnostic_model_pass"),"measurement_pass_rate":rate("measurement_pass"),
      "prediction_pass_rate":rate("prediction_pass"),"no_guessing_pass_rate":rate("no_guessing_pass"),
      "insufficient_data_abstention_rate":sum(bool(x.get("abstain_ok")) for x in abst_cases)/len(abst_cases) if abst_cases else 1.0}
    metrics["overall_dimension_pass_rate"]=sum(sum(bool(x.get(k)) for k in ("diagnostic_model_pass","measurement_pass","prediction_pass","no_guessing_pass")) for x in details)/(4*len(details)) if details else 0
    metrics["selection_score"]=0.25*metrics["diagnostic_model_pass_rate"]+0.30*metrics["measurement_pass_rate"]+0.30*metrics["prediction_pass_rate"]+0.15*metrics["no_guessing_pass_rate"]
    gates={"final_parse_rate":1.0,"diagnostic_model_pass_rate":0.90,"measurement_pass_rate":0.90,
      "prediction_pass_rate":0.90,"no_guessing_pass_rate":0.98,"insufficient_data_abstention_rate":1.0,
      "overall_dimension_pass_rate":0.90}
    failed={k:{"actual":metrics[k],"required":v} for k,v in gates.items() if metrics[k]+1e-12<v}
    out={"status":"PASS" if not failed else "FAIL","scorer":"semantic-structural-v3",
      "thresholds":{"diagnostic":a.diag_threshold,"measurement":a.measurement_threshold,"prediction":a.prediction_threshold},
      "metrics":metrics,"gates":gates,"failed_gates":failed,"details":details}
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"status":out["status"],"metrics":metrics,"failed_gates":failed},ensure_ascii=False))
    print("P57_QUALITY_V3="+out["status"])
if __name__=="__main__": main()
