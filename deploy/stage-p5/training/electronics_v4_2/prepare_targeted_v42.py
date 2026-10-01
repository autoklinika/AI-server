#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json,random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4_2"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
RUNNER=ROOT/"deploy/stage-p5/benchmark/run_quality_benchmark_v1.py"
EXPECTED_P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def runner_system():
    tree=ast.parse(RUNNER.read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="SYSTEM" for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("SYSTEM not found")
SYSTEM=runner_system()
def ans(model,test,pred,abstain):
    return json.dumps({"diagnostic_model":model,"discriminating_measurement":test,
      "predicted_result":pred,"abstain":abstain},ensure_ascii=False,separators=(",",":"))
def row(rid,prompt,model,test,pred,abstain,cat,split="train"):
    return {"record_id":rid,"system":SYSTEM,"user":prompt,"assistant":ans(model,test,pred,abstain),
      "metadata":{"schema_version":2,"language":"pl","category":cat,"split":split,
      "training_eligible":split=="train","contract":"p55-diagnostic-json-v1","p55_training_exclusion":True}}

def supply(i,split):
    vin=[9,12,18,24,28][i%5]; rail=[3.3,5,8,12][(i//2)%4]
    load=[0.3,0.5,0.75,1.0,1.35][(i//3)%5]; drop=[17,24,33,41,49][(i//4)%5]
    prompt=f"Na wejściu PCB jest stabilne {vin} V. Szyna {rail:g} V bez obciążenia jest poprawna, ale przy {load:.2f} A spada o {drop}%. Trzeba rozdzielić problem wejścia regulatora, regulatora/dławika i obciążenia downstream. Co mierzysz?"
    model="zapad pod obciążeniem może powstawać na wejściu regulatora, w regulatorze/dławiku albo przez nadmierne obciążenie downstream"
    test="zmierz równocześnie Vin regulatora, Vout regulatora i spadek napięcia na dławiku podczas kontrolowanego load-step"
    pred="jeśli Vin spada, winny jest upstream; jeśli Vin stabilne i Vout spada, zawęź regulator/dławik lub downstream według spadku na dławiku"
    return row(f"ELEC42-{split}-SUP-{i:03d}",prompt,model,test,pred,False,"schematic_symptom_measurements",split)

def analog(i,split):
    ref=[3.3,5][i%2]; good=[0.6,1.1,1.65,2.2,3.0,4.1][i%6]; bad=[0.05,0.2,ref-0.1,good*0.4][(i//2)%4]
    prompt=f"Dwa identyczne kanały mają wspólne zasilanie i Vref={ref:g} V. Dobry kanał daje {good:g} V, zły {bad:g} V na wejściu ADC, a punkt wejściowy obu kanałów jest zgodny. Jak znaleźć pierwszy uszkodzony stopień?"
    model="lokalna usterka leży między ostatnim zgodnym węzłem a pierwszym rozbieżnym węzłem złego kanału"
    test="porównaj dobry i zły kanał punkt po punkcie: rezystor, filtr, bufor i wejście ADC pod identycznym bodźcem"
    pred="pierwszy węzeł z trwałą różnicą lokalizuje uszkodzony stopień; zgodność aż do ADC przenosi podejrzenie na ADC lub dalej"
    return row(f"ELEC42-{split}-ANA-{i:03d}",prompt,model,test,pred,False,"good_bad_channels",split)

def waveform(i,split):
    hz=[250,500,800,1200,1800,2400][i%6]; duty=[20,35,50,65,80][(i//2)%5]; hot=[55,62,69,76,83][(i//3)%5]
    gate=[1.5,1.9,2.3,2.7,3.0][(i//4)%5]
    prompt=f"MCU PWM {hz} Hz/{duty}%/3.3 V pozostaje poprawny przy {hot}°C, ale VGS spada wtedy do {gate:g} V i zbocza zwalniają. Trzeba rozdzielić VDD drivera, driver i obciążenie bramki."
    model="usterka termiczna jest za MCU: zasilanie VDD drivera, sam driver albo nadmierne obciążenie toru bramki"
    test="mierz jednocześnie driver IN, VDD i VGS podczas przejścia zimny→gorący, przy tym samym obciążeniu"
    pred="jeśli VDD spada, problem jest w zasilaniu; jeśli IN i VDD są stabilne, a VGS spada, winny jest driver lub obciążenie bramki"
    return row(f"ELEC42-{split}-WAV-{i:03d}",prompt,model,test,pred,False,"numeric_waveform",split)
def thermal(i,split):
    zone=["driver","stabilizator","op-amp","złącze","rezystor mocy","obszar via/lut"][i%6]; temp=[54,59,64,70,76,82][(i//2)%6]
    prompt=f"Usterka pojawia się około {temp}°C. Chłodzenie strefy '{zone}' przywraca działanie, chłodzenie reszty PCB nie. Chcemy odróżnić element, połączenie i lokalne zasilanie bez zgadywania części."
    model="usterka termiczna jest lokalna w wskazanej strefie i może dotyczyć elementu, połączenia lut/via albo lokalnego zasilania"
    test="wykonaj selektywne heat/cool małych punktów strefy, mierząc równocześnie wejście, wyjście i lokalne VDD"
    pred="jeśli pierwszy zmienia się VDD, badaj zasilanie; jeśli VDD i wejście są stabilne, a wyjście reaguje, zawęź element lub połączenie w strefie"
    return row(f"ELEC42-{split}-THM-{i:03d}",prompt,model,test,pred,False,"thermal_intermittent",split)

def short(i,split):
    rail=[1.8,3.3,5,12][i%4]; ohm=[0.5,0.8,1.3,2.1,4.4,7.8][(i//2)%6]; lim=[0.3,0.5,0.7,1.0,1.3][(i//3)%5]
    prompt=f"Szyna {rail:g} V ma po wyłączeniu {ohm:g} Ω do masy i przy starcie wchodzi w limit prądu. Bezpieczna iniekcja jest do {lim:g} A. Jak lokalizujesz gałąź zwarcia?"
    model="szyna ma zwarcie lub silne upływowe obciążenie; źródłem może być kondensator, układ scalony albo dalsza gałąź"
    test="wykonaj niskonapięciową iniekcję z limitem prądu, szukając hotspotu i mierząc gradient spadków mV wzdłuż gałęzi"
    pred="jeśli pojawi się hotspot lub największy gradient mV, wskaże gałąź; jeśli nie, segmentuj szynę i powtórz pomiar zamiast zgadywać część"
    return row(f"ELEC42-{split}-SHT-{i:03d}",prompt,model,test,pred,False,"pcb_short",split)

UNKNOWN=[
("Urządzenie sporadycznie się resetuje; brak logów, pomiarów szyn i przebiegu RESET.",
 "zmierz jednocześnie główne szyny i RESET w momencie resetu",
 "jeśli szyna zanika przed RESET, podejrzewaj zasilanie; jeśli szyny są stabilne, dopiero RESET/zegar stają się kierunkiem"),
("Wyjście nie steruje obciążeniem; nie wiadomo, czy dociera komenda ani czy driver ma VDD.",
 "zmierz jednocześnie komendę wejściową, VDD drivera i OUT podczas żądania załączenia",
 "jeśli brak komendy, problem jest upstream; jeśli brak VDD, w zasilaniu; jeśli oba są poprawne i OUT brak, zawęź driver/downstream"),
("Po nagrzaniu układ przestaje działać, ale nie wykonano lokalnego heat/cool ani pomiaru wejścia, wyjścia i VDD.",
 "wykonaj lokalne heat/cool równolegle z pomiarem wejścia, wyjścia i VDD",
 "jeśli pierwszy zmienia się VDD, badaj zasilanie; jeśli VDD/wejście są stabilne, a wyjście reaguje, zawęź lokalny stopień"),
("Na linii analogowej jest napięcie, ale nie znamy wartości oczekiwanej, Vref ani poprawnego kanału referencyjnego.",
 "ustal Vref i porównaj ten sam węzeł z pewnym kanałem referencyjnym pod identycznym bodźcem",
 "jeśli odczyt różni się od referencji, lokalizuj tor; jeśli jest zgodny, sam pomiar nie potwierdza usterki"),
("Pobór prądu jest większy niż zwykle, ale brak wartości referencyjnej, rezystancji szyn i lokalizacji termicznej.",
 "zmierz rezystancje głównych szyn i porównaj pobór z pewnym egzemplarzem w identycznym stanie",
 "jeśli jedna szyna ma wyraźnie mniejszą rezystancję, badaj ją; jeśli nie, potrzebny jest kolejny test przed wskazaniem części"),
("Oscyloskop pokazuje nieregularny przebieg, ale brak skali czasu, amplitudy, punktu pomiarowego i stanu obciążenia.",
 "powtórz przebieg z pełną skalą czasu/amplitudy, poprawną masą sondy i opisanym obciążeniem",
 "jeśli kształt zależy od konfiguracji sondy, to artefakt; jeśli pozostaje, dopiero wtedy analizuj niestabilność układu")
]
def insufficient(i,split):
    prompt,test,pred=UNKNOWN[i%len(UNKNOWN)]
    model="dane są niewystarczające do odpowiedzialnego zawężenia modelu usterki; należy utrzymać kilka hipotez"
    return row(f"ELEC42-{split}-UNK-{i:03d}",prompt,model,test,pred,True,"insufficient_data",split)

def borderline(i,split):
    variants=[
      ("PWM z MCU jest poprawny także na gorąco; VDD drivera również stabilne, ale VGS spada wraz z temperaturą.",
       "usterka jest już zawężona do drivera lub obciążenia bramki, więc nie należy abstain",
       "porównaj VGS i prąd bramki zimny/gorący przy stabilnym IN i VDD",
       "jeśli VGS spada przy rosnącym prądzie bramki, podejrzewaj obciążenie; jeśli prąd nie rośnie, driver"),
      ("Dwa identyczne kanały są zgodne aż do wejścia bufora, a różnią się dopiero na jego wyjściu.",
       "usterka jest już lokalnie zawężona do bufora lub jego lokalnego obciążenia",
       "porównaj wejście, wyjście i lokalne zasilanie bufora obu kanałów pod identycznym bodźcem",
       "jeśli wejście i zasilanie są zgodne, a wyjście różne, zawęź bufor/obciążenie; różnica zasilania wskazuje supply"),
      ("Lokalne chłodzenie jednego małego obszaru przywraca funkcję, a chłodzenie reszty nie.",
       "jest już wiarygodna lokalizacja termiczna, więc można zawęzić model bez wskazywania konkretnej części",
       "wykonaj selektywne heat/cool punktów tej strefy z równoległym pomiarem IN/OUT/VDD",
       "pierwszy sygnał skorelowany z bodźcem rozdzieli element, połączenie i zasilanie")
    ]
    prompt,model,test,pred=variants[i%len(variants)]
    return row(f"ELEC42-{split}-BND-{i:03d}",prompt,model,test,pred,False,"borderline_sufficient",split)
def make(split):
    start=1000 if split=="train" else 9000
    n=28 if split=="train" else 8
    rows=[]
    for j in range(n):
        x=start+j*13
        rows += [supply(x,split),analog(x+1,split),waveform(x+2,split),thermal(x+3,split),short(x+4,split),insufficient(x+5,split)]
    b=24 if split=="train" else 9
    rows += [borderline(start+700+j,split) for j in range(b)]
    return rows

def replay():
    p=ROOT/"deploy/stage-p5/training/electronics_v4_1/contract_aligned_v41_replay_train.jsonl"
    rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    good=[r for r in rows if r.get("metadata",{}).get("category") in ("good_bad_channels","good_bad_channel_comparison")]
    general=[r for r in rows if r.get("metadata",{}).get("p561_replay")]
    rng=random.Random(20261002)
    chosen=rng.sample(good,min(18,len(good)))+rng.sample(general,min(18,len(general)))
    for i,r in enumerate(chosen,1):
        r=json.loads(json.dumps(r)); r["record_id"]=f"ELEC42-REPLAY-{i:03d}"
        r.setdefault("metadata",{})["p562_replay"]=True; chosen[i-1]=r
    return chosen

def main():
    if sha(P55)!=EXPECTED_P55_SHA: raise SystemExit("P5_6_2=BLOCKED p55_dataset_drift")
    train=make("train"); hold=make("holdout"); rep=replay()
    mixed=train+rep; random.Random(20261002).shuffle(mixed)
    tp=DIR/"targeted_v42_train.jsonl"; hp=DIR/"targeted_v42_holdout.jsonl"; mp=DIR/"targeted_v42_replay_train.jsonl"
    for p,rows in ((tp,train),(hp,hold),(mp,mixed)):
        p.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))
    p55=P55.read_text()
    if any(r["user"] in p55 for r in train+hold): raise SystemExit("P5_6_2=FAIL p55_overlap")
    parsed=[json.loads(r["assistant"]) for r in train]
    manifest={"schema_version":1,"dataset_id":"targeted-v4.2","train_records":len(train),"holdout_records":len(hold),
      "replay_records":len(rep),"mixed_records":len(mixed),"abstain_true_train":sum(x["abstain"] for x in parsed),
      "abstain_false_train":sum(not x["abstain"] for x in parsed),"p55_frozen_sha256":EXPECTED_P55_SHA,
      "p55_training_exclusion":True,"parent_adapter":"electronics-v4.1-contract-r1-20261001",
      "train_sha256":sha(tp),"holdout_sha256":sha(hp),"mixed_sha256":sha(mp),
      "focus":["discriminating_measurement","conditional_predicted_result","abstention_calibration"],
      "protected_skill":"good_bad_channel_comparison"}
    (DIR/"targeted_v42.manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("P5_6_2_DATASET=PASS"); print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
