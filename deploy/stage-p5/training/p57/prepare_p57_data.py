#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json,random
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/p57"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
RUNNER=ROOT/"deploy/stage-p5/benchmark/run_quality_benchmark_v1.py"
P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def rows(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def system_prompt():
    t=ast.parse(RUNNER.read_text())
    for n in t.body:
        if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=="SYSTEM" for x in n.targets):
            return ast.literal_eval(n.value)
    raise RuntimeError("SYSTEM missing")
SYSTEM=system_prompt()

def ans(model,test,pred,abstain):
    return {"diagnostic_model":model,"discriminating_measurement":test,"predicted_result":pred,"abstain":abstain}
def case(cid,cat,prompt,model,test,pred,abstain):
    return {"schema_version":1,"case_id":cid,"category":cat,"language":"pl","training_exclusion":True,
      "prompt":prompt,"reference":ans(model,test,pred,abstain)}

def build_case(family,i,prefix):
    # Intentionally different wording/numbers from P5.5 and all training generators.
    if family==0:
        vin=[10,14,20,27][i%4]; rail=[3.0,4.0,6.0,9.0][(i//2)%4]; load=[0.42,0.68,0.92,1.18][(i//3)%4]
        p=f"Wejście przetwornicy utrzymuje {vin} V. Wyjście {rail:g} V jest poprawne bez obciążenia, lecz przy {load:.2f} A wyraźnie siada. Jaki jeden pomiar najlepiej rozdzieli źródło problemu?"
        return case(f"{prefix}-SUP-{i:02d}","schematic_symptom_measurements",p,
          "zapad może pochodzić z wejścia przetwornicy, samego stopnia mocy/dławika albo nadmiernego obciążenia downstream",
          "zarejestruj jednocześnie Vin przetwornicy, Vout i spadek na dławiku podczas skoku obciążenia",
          "jeśli Vin spada, szukaj upstream; jeśli Vin jest stabilne, a Vout spada, rozdziel stopień mocy/dławik od downstream po zachowaniu spadku na dławiku",False)
    if family==1:
        ref=[3.0,4.5][i%2]; good=[0.8,1.4,2.0,2.7][i%4]; bad=[0.1,0.4,ref-0.2,good*0.5][(i//2)%4]
        p=f"Dwa równoległe kanały mają wspólne Vref={ref:g} V. Na wejściu toru są zgodne, ale przed ADC dobry ma {good:g} V, a zły {bad:g} V. Jak wykorzystać kanał dobry?"
        return case(f"{prefix}-ANA-{i:02d}","good_bad_channels",p,
          "usterka jest lokalna w złym kanale między ostatnim zgodnym a pierwszym rozbieżnym węzłem",
          "porównaj oba kanały punkt po punkcie pod identycznym bodźcem od ostatniego zgodnego węzła do ADC",
          "pierwsza trwała rozbieżność lokalizuje uszkodzony stopień; zgodność aż do wejścia ADC przenosi podejrzenie dalej",False)
    if family==2:
        hz=[300,650,900,1400][i%4]; t=[57,64,71,79][(i//2)%4]; vg=[1.7,2.1,2.5,2.9][(i//3)%4]
        p=f"Sygnał PWM z MCU {hz} Hz pozostaje poprawny przy {t}°C, ale sygnał bramki spada do {vg:g} V i ma wolniejsze zbocza. Co mierzysz równolegle?"
        return case(f"{prefix}-WAV-{i:02d}","numeric_waveform",p,
          "usterka leży za MCU: w VDD drivera, samym driverze albo obciążeniu bramki",
          "mierz jednocześnie wejście drivera, jego VDD oraz VGS podczas kontrolowanej zmiany temperatury",
          "spadek VDD wskazuje zasilanie; stabilne wejście i VDD przy spadku VGS zawężają driver lub obciążenie bramki",False)
    if family==3:
        zone=["sekcja drivera","okolica stabilizatora","wzmacniacz analogowy","złącze sygnałowe"][i%4]; t=[56,63,70,78][(i//2)%4]
        p=f"Objaw pojawia się około {t}°C. Chłodzenie tylko strefy '{zone}' przywraca działanie, chłodzenie innych miejsc nie. Jak odróżnić element, połączenie i lokalne zasilanie?"
        return case(f"{prefix}-THM-{i:02d}","thermal_intermittent",p,
          "usterka termiczna jest lokalna w wskazanej strefie i może dotyczyć elementu, połączenia lub lokalnego zasilania",
          "wykonaj selektywne grzanie/chłodzenie małych punktów strefy z równoległym pomiarem wejścia, wyjścia i lokalnego zasilania",
          "jeśli pierwsze zmienia się zasilanie, badaj jego tor; przy stabilnym zasilaniu i wejściu zmiana wyjścia zawęża element lub połączenie",False)
    if family==4:
        rail=[2.5,3.6,6.5,11.0][i%4]; r=[0.7,1.4,2.6,5.2][(i//2)%4]; lim=[0.4,0.6,0.85,1.1][(i//3)%4]
        p=f"Szyna {rail:g} V ma po wyłączeniu około {r:g} Ω do masy i przy starcie wymusza limit prądu. Można bezpiecznie wstrzyknąć do {lim:g} A. Jak lokalizować bez zgadywania części?"
        return case(f"{prefix}-SHT-{i:02d}","pcb_short",p,
          "na szynie występuje zwarcie lub silne obciążenie upływowe w jednej z gałęzi",
          "wykonaj niskonapięciową iniekcję z limitem prądu, obserwując hotspot oraz gradient spadków napięcia w gałęziach",
          "hotspot lub największy gradient wskaże podejrzaną gałąź; brak lokalizacji oznacza potrzebę segmentacji szyny przed wskazaniem części",False)
    if family==5:
        node=["wyjściu bufora","za rezystorem szeregowym","drenie tranzystora","wejściu ADC"][i%4]
        g=[2.2,4.4,7.5,1.5][i%4]; b=[0.1,1.0,3.1,0.3][i%4]
        p=f"Dwa identyczne kanały mają wspólne zasilanie. Wcześniejsze węzły są zgodne; dopiero na {node} dobry ma {g:g} V, a zły {b:g} V. Co z tego wynika i jaki test następny?"
        return case(f"{prefix}-CMP-{i:02d}","good_bad_channel_comparison",p,
          "usterka jest lokalna w złym kanale pomiędzy ostatnim zgodnym i pierwszym różniącym się węzłem",
          "porównaj oba kanały na wejściu i wyjściu podejrzanego stopnia pod identycznym obciążeniem",
          "pierwsza trwała różnica powinna wystąpić w uszkodzonym stopniu, podczas gdy wspólne zasilanie pozostanie zgodne",False)
    unknown=[
      ("Sterownik sporadycznie resetuje się, ale nie ma logów ani przebiegów zasilania i RESET.","zmierz równocześnie główne szyny i RESET w chwili zdarzenia","dopiero kolejność zmian rozdzieli hipotezę zasilania od resetu/zegara"),
      ("Wyjście mocy pozostaje nieaktywne; nie wiadomo, czy dochodzi komenda ani czy driver ma zasilanie.","zmierz w jednym zdarzeniu komendę, VDD drivera i wyjście","brak komendy wskaże upstream, brak VDD zasilanie, a oba poprawne przy braku wyjścia zawężą driver/downstream"),
      ("Napięcie analogowe wygląda podejrzanie, ale brak wartości oczekiwanej, Vref i kanału referencyjnego.","ustal Vref i porównaj ten sam węzeł z pewnym kanałem lub egzemplarzem","dopiero różnica względem wiarygodnego odniesienia pozwoli uznać odczyt za usterkę"),
      ("Przebieg z oscyloskopu jest nieregularny, lecz brak skali czasu, amplitudy, punktu pomiaru i warunku obciążenia.","powtórz pomiar z kompletną konfiguracją oscyloskopu, poprawną masą i opisanym obciążeniem","pełny pomiar rozdzieli artefakt sondowania od rzeczywistej niestabilności")
    ]
    p,tst,pred=unknown[i%len(unknown)]
    return case(f"{prefix}-UNK-{i:02d}","insufficient_data",p,
      "dane są niewystarczające do odpowiedzialnego zawężenia modelu usterki; trzeba utrzymać kilka hipotez",
      tst,pred,True)

def build_eval(prefix,n_each,start_index=0):
    out=[]
    for f in range(7):
        for i in range(n_each):
            idx=start_index+i
            c=build_case(f,idx,prefix)
            c["prompt"]=f"Warunek pomiarowy W{1000+idx:04d}-{f+1}: "+c["prompt"]
            out.append(c)
    return out
def select_training():
    v41=rows(ROOT/"deploy/stage-p5/training/electronics_v4_1/contract_aligned_v41_train.jsonl")
    v42=rows(ROOT/"deploy/stage-p5/training/electronics_v4_2/targeted_v42_train.jsonl")
    v3=rows(ROOT/"deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_replay_train.jsonl")
    rng=random.Random(20261003)
    by41=defaultdict(list); by42=defaultdict(list)
    for r in v41: by41[r["metadata"]["category"]].append(r)
    for r in v42: by42[r["metadata"]["category"]].append(r)
    weak42=["schematic_symptom_measurements","good_bad_channels","numeric_waveform","thermal_intermittent","pcb_short","insufficient_data"]
    old41=["supply","analog","waveform","thermal","short","insufficient_data"]
    buckets=[]
    for c in weak42: buckets.append(rng.sample(by42[c],10))
    buckets.append(rng.sample(by42["borderline_sufficient"],8))
    for c in old41: buckets.append(rng.sample(by41[c],8))
    buckets.append(rng.sample(v3,28))
    # Round-robin source families prevents long same-skill runs.
    plan=[]; k=0
    while any(buckets):
        b=buckets[k%len(buckets)]
        if b: plan.append(b.pop())
        k+=1
    assert len(plan)==144
    for i,r in enumerate(plan,1):
        r=json.loads(json.dumps(r))
        r["record_id"]=f"P57-TRAIN-{i:04d}"
        r.setdefault("metadata",{})["p57_source_record_id"]=r.get("record_id")
        r["metadata"]["p57_training_plan"]=True
        plan[i-1]=r
    return plan

def regression_slice():
    paths=[
      ROOT/"deploy/stage-p5/training/electronics/electronics_foundation_holdout_v1.jsonl",
      ROOT/"deploy/stage-p5/training/electronics_v2/electronics_foundation_v2_holdout.jsonl",
      ROOT/"deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_holdout.jsonl",
      ROOT/"deploy/stage-p5/training/electronics_v4/discriminating_measurement_v4_holdout.jsonl"]
    out=[]
    for vi,p in enumerate(paths,1):
        rr=rows(p)
        # deterministic spread across each holdout
        idx=sorted(set([0,len(rr)//3,(2*len(rr))//3,len(rr)-1]))
        for j in idx:
            x=json.loads(json.dumps(rr[j])); x["record_id"]=f"P57-REG-v{vi}-{j:03d}"; out.append(x)
    return out

def write_jsonl(p,rr): p.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in rr))

def main():
    if sha(P55)!=P55_SHA: raise SystemExit("P57=BLOCKED legacy_p55_drift")
    train=select_training()
    dev=build_eval("P57-DEV",4,start_index=0)
    mini=[x for i,x in enumerate(dev) if i%2==0]
    final=build_eval("P57-FINAL",8,start_index=100)
    reg=regression_slice()
    p55txt=P55.read_text()
    # No exact prompt from the legacy benchmark may enter train/dev/final.
    for collection in (train,dev,final):
        for r in collection:
            text=r.get("user",r.get("prompt",""))
            if text and text in p55txt: raise SystemExit("P57=FAIL legacy_overlap")
    files={
      "train":DIR/"p57_balanced_train.jsonl","dev":DIR/"p57_dev_v1.jsonl",
      "mini_dev":DIR/"p57_mini_dev_v1.jsonl","final":DIR/"p57_final_v1.jsonl",
      "regression":DIR/"p57_regression_slice_v1.jsonl"}
    for k,rr in (("train",train),("dev",dev),("mini_dev",mini),("final",final),("regression",reg)): write_jsonl(files[k],rr)
    manifest={"schema_version":1,"pipeline_id":"P5.7-stable-training-v1",
      "parent_adapter":"electronics-v4.1-contract-r1-20261001",
      "legacy_p55_role":"regression_only","legacy_p55_sha256":P55_SHA,
      "train_records":len(train),"dev_records":len(dev),"mini_dev_records":len(mini),
      "final_records":len(final),"regression_slice_records":len(reg),
      "checkpoint_interval":8,"max_checkpoints":8,"early_stop_patience":2,
      "max_regression":0.02,
      "train_sha256":sha(files["train"]),"dev_sha256":sha(files["dev"]),
      "mini_dev_sha256":sha(files["mini_dev"]),"final_sha256":sha(files["final"]),
      "regression_sha256":sha(files["regression"]),
      "final_policy":"never used for training, checkpoint selection, threshold tuning, or early stopping"}
    (DIR/"p57_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("P57_DATA=PASS"); print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
