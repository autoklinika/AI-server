#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
EXPECTED_P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
SYSTEM=("Diagnostyka PCB: fakty != hipotezy. Nie powtarzaj znanego pomiaru; wybierz test o największym information gain. "
"Nie zgaduj części. Format: ZNANE; HIP; BRAK; TEST; ODRZUĆ; WYNIK.")

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(s): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9ąćęłńóśźż]+"," ",s.lower())).strip()
def case_supply(i):
    vin=[12,24][i%2]; rail=[5.0,3.3][(i//2)%2]; load=[0.45,0.7,0.95,1.2,1.5][i%5]; drop=[22,31,38,44,52][(i//5)%5]
    text=f"SUP{i+1:03d}: VinPCB={vin}V OK; Vout={rail:g}V idle OK, -{drop}%@{load:.2f}A. A Vout znów; B T_MCU; C Vin/Vout regulatora + ΔV dławika przy load-step."
    ans="ZNANE VinPCB OK,Vout droop; HIP upstream/reg/downstream; BRAK miejsce zapadu; TEST C; ODRZUĆ A=znane,B=niski gain; WYNIK Vinreg↓=>upstream, Vinreg= i Vout↓=>reg/downstream."
    return text,ans
def case_analog(i):
    ref=[3.3,5.0][i%2]; sig=[0.7,1.2,1.8,2.4,3.1,4.0][i%6]; bad=[0.05,0.2,ref-0.1,ref-0.35][(i//3)%4]
    text=f"ANA{i+1:03d}: good ADC={sig:g}V; bad: wejście OK, supplies/Vref={ref:g}V OK, ADC={bad:g}V. A Vref znów; B wymień ADC; C good/bad: R→filtr→bufor→ADC."
    ans="ZNANE wejście,Vref OK; HIP R/filtr-bufor-clamp ADC; BRAK pierwszy różny węzeł; TEST C; ODRZUĆ A=znane,B=zgadywanie; WYNIK pierwsza rozbieżność lokalizuje stopień."
    return text,ans
def case_wave(i):
    hz=[250,500,800,1000,1500,2000][i%6]; duty=[25,35,45,55,65,75][(i//2)%6]; gate=[1.8,2.2,2.8,3.2,3.8,4.2][(i//4)%6]
    text=f"WAV{i+1:03d}: MCU PWM {hz}Hz/{duty}%/3.3V OK hot; hot VGS={gate:g}V i slow edges. A PWM znów; B wymień FET; C driver IN,VDD,VGS równocześnie vs T."
    ans="ZNANE PWM OK, błąd za MCU i termiczny; HIP VDD/driver/gate-load; BRAK co psuje się pierwsze; TEST C; ODRZUĆ A=znane,B=zgadywanie; WYNIK VDD↓=>supply, VDD+IN= i VGS↓=>driver/gate."
    return text,ans
def case_thermal(i):
    part=["stabilizator","driver","op-amp","złącze","R-mocy","via/lut"][i%6]; temp=[58,63,68,72,77,82][(i//3)%6]
    text=f"THM{i+1:03d}: fail@{temp}°C; cool({part})=fix, cool(rest)=no. A cool same znów; B reflow; C selektywnie heat punkty + mierz IN/OUT/VDD."
    ans="ZNANE strefa termiczna; HIP element/lut-via/sąsiad; BRAK pierwszy zmienny punkt; TEST C; ODRZUĆ A=znane,B=niszczy dowód; WYNIK pierwszy sygnał skorelowany z bodźcem lokalizuje."
    return text,ans
def case_short(i):
    rail=[3.3,5.0,12.0][i%3]; ohm=[0.7,1.1,1.8,2.6,4.3,7.5][(i//2)%6]; lim=[0.5,0.7,0.9,1.1,1.3,1.5][(i//4)%6]
    text=f"SHT{i+1:03d}: rail={rail:g}V, Rgnd={ohm:g}Ω, startup=ILIM, safe inject≤{lim:g}A. A R znów; B wymień regulator; C low-V inject + hotspot + mapa ΔmV gałęzi."
    ans="ZNANE rail silnie obciążona; HIP MLCC/IC/downstream; BRAK droga prądu; TEST C; ODRZUĆ A=znane,B=zgadywanie; WYNIK hotspot/gradient mV=>gałąź; brak=>segmentacja."
    return text,ans
def case_unknown(i):
    variants=[
      ("resety; brak logów,Vrail,RESET","Vrail+RESET podczas eventu","Vrail↓ przed RESET=>power; Vrail==>reset/clock"),
      ("output dead; brak info o command,VDD drivera","command+VDD+OUT w jednym evencie","command-=>upstream; VDD-=>supply; oba+ i OUT-=>driver/downstream"),
      ("analog ma V; brak expected/reference","ustal reference + compare good channel","dopiero różnica do wzorca rozdziela"),
      ("wave nieregularny; brak timebase,amp,node,load","powtórz scope z pełną skalą,node,GND,load","pełny waveform rozdziela artefakt/usterkę"),
      ("fail hot; brak thermal localization i sygnałów","lokalne heat/cool + krytyczne IN/OUT/VDD","pierwszy skorelowany sygnał zawęża strefę"),
    ]
    symptom,test,pred=variants[i%len(variants)]
    text=f"UNK{i+1:03d}: {symptom}. A wskaż część; B {test}; C powtórz objaw."
    ans=f"ZNANE za mało danych; HIP wiele; BRAK test rozdzielający; TEST B; ODRZUĆ A=zgadywanie,C=0 info; WYNIK {pred}; DECYZJA wstrzymaj część do testu."
    return text,ans
BUILDERS=[case_supply,case_analog,case_wave,case_thermal,case_short,case_unknown]

def packed_row(i):
    cases=[]; answers=[]
    for b in BUILDERS:
        q,a=b(i); cases.append(q); answers.append(a)
    user="6 niezależnych przypadków; wybierz test o największym information gain, nie powtarzaj znanego pomiaru.\n"+"\n".join(cases)
    assistant="\n".join(f"{j+1}. {a}" for j,a in enumerate(answers))
    return {"record_id":f"ELEC4-TRAIN-{i+1:04d}","system":SYSTEM,"user":user,"assistant":assistant,
      "metadata":{"schema_version":4,"language":"pl","category":"discriminating_measurement_contrastive_pack","training_eligible":True,"split":"train","microcases":6,"curriculum":"electronics-foundation-v4","parent_adapter":"electronics-foundation-v3/current"}}

def holdout_row(family,i):
    q,a=BUILDERS[family](50+i)
    return {"record_id":f"ELEC4-HOLD-{family+1}-{i+1:02d}","system":SYSTEM,
      "user":"Wybierz pomiar rozdzielający i uzasadnij, dlaczego nie należy powtarzać znanych już pomiarów. "+q,
      "assistant":a,"metadata":{"schema_version":4,"language":"pl","category":["supply","analog","waveform","thermal","short","insufficient"][family],"training_eligible":False,"split":"holdout","microcases":1,"curriculum":"electronics-foundation-v4"}}

def main():
    if sha(P55)!=EXPECTED_P55_SHA: raise SystemExit("P5_6=BLOCKED p55_dataset_drift")
    train=[packed_row(i) for i in range(50)]
    hold=[holdout_row(f,i) for f in range(6) for i in range(6)]
    p55=[json.loads(x) for x in P55.read_text().splitlines() if x.strip()]
    p55n={norm(json.dumps(x,ensure_ascii=False)) for x in p55}
    allrows=train+hold
    texts=[norm(r["user"]+" "+r["assistant"]) for r in allrows]
    if len(texts)!=len(set(texts)): raise SystemExit("P5_6=FAIL duplicate_rows")
    if any(t in p55n for t in texts): raise SystemExit("P5_6=FAIL p55_exact_overlap")
    tp=DIR/"discriminating_measurement_v4_train.jsonl"; hp=DIR/"discriminating_measurement_v4_holdout.jsonl"
    tp.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in train))
    hp.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in hold))
    manifest={"schema_version":1,"dataset_id":"discriminating-measurement-v4","target_microcases":300,"train_records":50,
      "holdout_records":36,"families":6,"p55_frozen_sha256":EXPECTED_P55_SHA,"p55_training_exclusion":True,
      "train_sha256":sha(tp),"holdout_sha256":sha(hp),"parent_adapter":"electronics-foundation-v3/current",
      "principle":"known facts -> competing hypotheses -> missing information -> highest-information test -> predicted branch result"}
    (DIR/"discriminating_measurement_v4.manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("P5_6_TARGET_DATASET=PASS"); print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
