#!/usr/bin/env python3
from pathlib import Path
import argparse,json,math,re,urllib.request
ROOT=Path(__file__).resolve().parents[3]
REQ={"diagnostic_model","discriminating_measurement","predicted_result","abstain"}
FIELDS=("diagnostic_model","discriminating_measurement","predicted_result")

def norm(s): return re.sub(r"\s+"," ",str(s).lower()).strip()
def has(s,*terms): s=norm(s); return any(t in s for t in terms)
def all_groups(s,groups): return all(any(t in norm(s) for t in g) for g in groups)
def embed(texts):
    data=json.dumps({"model":"bge-m3","input":texts}).encode()
    req=urllib.request.Request("http://127.0.0.1:11434/api/embed",data=data,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=120) as r: return json.load(r)["embeddings"]
def cos(a,b):
    d=sum(x*y for x,y in zip(a,b)); na=math.sqrt(sum(x*x for x in a)); nb=math.sqrt(sum(y*y for y in b))
    return d/(na*nb) if na and nb else 0.0

def diagnostic_ok(cat,s,abst):
    if cat=="insufficient_data":
        return abst and all_groups(s,[("brak danych","niewystarcz","za mało danych","kilka hipotez"),("hipotez","niejednozn","zawę")])
    if cat in ("good_bad_channels","good_bad_channel_comparison"):
        return all_groups(s,[("kanał","gałę"),("lokal","między","rozbież","różni")])
    if cat=="schematic_symptom_measurements":
        return all_groups(s,[("zasil","regulator","dławik","obciąż"),("upstream","downstream","wejści","wyjści","tor")])
    if cat=="numeric_waveform":
        return all_groups(s,[("driver","bram","vgs"),("zasil","vdd","term","za mcu")])
    if cat=="thermal_intermittent":
        return all_groups(s,[("term","temper","ciep","chłod"),("lokal","obszar","element","połąc")])
    if cat=="pcb_short":
        return all_groups(s,[("zwar","upływ","obciąż"),("szyn","gałę","kondens","układ")])
    return False

def measurement_ok(cat,s):
    if cat=="insufficient_data":
        return has(s,"zmierz","pomiar","porówn","heat","cool","przebieg","scope","referenc")
    if cat in ("good_bad_channels","good_bad_channel_comparison"):
        return all_groups(s,[("porówn","good","dobr"),("punkt","węzeł","stopień","kanał")])
    if cat=="schematic_symptom_measurements":
        return all_groups(s,[("vin","wejści"),("vout","wyjści"),("obciąż","load","dławik")])
    if cat=="numeric_waveform":
        return all_groups(s,[("in","wejści"),("vdd","zasil"),("vgs","bram")])
    if cat=="thermal_intermittent":
        return all_groups(s,[("heat","cool","ogrz","chłod","temper"),("wejści","wyjści","zasil","vdd")])
    if cat=="pcb_short":
        return all_groups(s,[("iniekc","wstrzyk"),("hotspot","term","ipa"),("spad","gradient","mv")])
    return False

def prediction_ok(cat,s,abst):
    if cat=="insufficient_data":
        return abst and has(s,"dopiero","wynik","rozdziel","wskaż","zawę")
    if cat in ("good_bad_channels","good_bad_channel_comparison"):
        return all_groups(s,[("pierwsz","rozbież","różni"),("stopień","element","gałę","lokal")])
    if cat=="schematic_symptom_measurements":
        return all_groups(s,[("vin","wejści"),("vout","wyjści"),("upstream","regulator","downstream")])
    if cat=="numeric_waveform":
        return all_groups(s,[("vdd","zasil"),("vgs","bram","driver"),("in","wejści")])
    if cat=="thermal_intermittent":
        return all_groups(s,[("pierwsz","korel","temper"),("lokal","element","połąc","obszar")])
    if cat=="pcb_short":
        return all_groups(s,[("hotspot","gradient","spad"),("gałę","segment","lokal")])
    return False

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dataset",default=str(ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"))
    ap.add_argument("--results",required=True); ap.add_argument("--output",required=True); a=ap.parse_args()
    cases={r["case_id"]:r for r in (json.loads(x) for x in Path(a.dataset).read_text().splitlines() if x.strip())}
    results=[json.loads(x) for x in Path(a.results).read_text().splitlines() if x.strip()]
    details=[]; texts=[]; pairs=[]
    for r in results:
        c=cases[r["case_id"]]; p=r.get("parsed"); parse=isinstance(p,dict) and REQ.issubset(p or {})
        d={"case_id":r["case_id"],"category":c["category"],"parse_ok":parse}
        if parse:
            abst=bool(p["abstain"]); must=bool(c["reference"]["must_abstain"])
            hard=has(p["diagnostic_model"],"na pewno","jednoznacznie","z całą pewnością","definitywnie","wymień ")
            d["abstain_ok"]=abst==must
            d["no_guessing_pass"]=d["abstain_ok"] and not hard
            d["diagnostic_model_pass"]=diagnostic_ok(c["category"],p["diagnostic_model"],abst)
            d["measurement_pass"]=measurement_ok(c["category"],p["discriminating_measurement"])
            d["prediction_pass"]=prediction_ok(c["category"],p["predicted_result"],abst)
            for f in FIELDS:
                texts += [str(p[f]),str(c["reference"][f])]; pairs.append((len(details),f,len(texts)-2,len(texts)-1))
        details.append(d)
    embs=embed(texts) if texts else []
    for di,f,ia,ib in pairs: details[di][f+"_similarity"]=cos(embs[ia],embs[ib])
    def rate(k): return sum(bool(d.get(k)) for d in details)/len(details) if details else 0.0
    abst=[d for d in details if cases[d["case_id"]]["reference"]["must_abstain"]]
    metrics={"records":len(details),"parse_rate":rate("parse_ok"),"diagnostic_model_pass_rate":rate("diagnostic_model_pass"),
      "measurement_pass_rate":rate("measurement_pass"),"prediction_pass_rate":rate("prediction_pass"),
      "no_guessing_pass_rate":rate("no_guessing_pass"),
      "insufficient_data_abstention_rate":sum(bool(d.get("abstain_ok")) for d in abst)/len(abst) if abst else 0.0}
    metrics["overall_dimension_pass_rate"]=sum(sum(bool(d.get(k)) for k in ("diagnostic_model_pass","measurement_pass","prediction_pass","no_guessing_pass")) for d in details)/(4*len(details))
    gates={"parse_rate":1.0,"diagnostic_model_pass_rate":0.80,"measurement_pass_rate":0.85,"prediction_pass_rate":0.80,
      "no_guessing_pass_rate":0.95,"insufficient_data_abstention_rate":1.0,"overall_dimension_pass_rate":0.85}
    failed={k:{"actual":metrics[k],"required":v} for k,v in gates.items() if metrics[k]+1e-12<v}
    out={"status":"PASS" if not failed else "FAIL","scorer":"deterministic-v2","metrics":metrics,"gates":gates,"failed_gates":failed,"details":details}
    Path(a.output).write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps({"status":out["status"],"metrics":metrics,"failed_gates":failed},ensure_ascii=False))
    print("P5_5_QUALITY_GATE_V2="+out["status"])

if __name__=="__main__": main()
