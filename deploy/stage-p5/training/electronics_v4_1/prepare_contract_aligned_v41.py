#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4_1"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
EXPECTED_P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
SYSTEM='''Jesteś diagnostą elektroniki. Używaj wyłącznie danych przypadku. Nie zgaduj konkretnej części bez pomiaru rozdzielającego. Zwróć WYŁĄCZNIE jeden krótki poprawny JSON, bez markdownu i bez dodatkowego tekstu: {"diagnostic_model":"maks. 25 słów: fizyczny model usterki lub ograniczony zestaw hipotez","discriminating_measurement":"maks. 25 słów: jeden test o największej wartości rozdzielającej","predicted_result":"maks. 30 słów: przewidywany wynik i jak rozdzieli hipotezy","abstain":true|false}. `abstain=true` tylko gdy dane są zbyt słabe, by odpowiedzialnie zawęzić model usterki; sam fakt, że trzeba wykonać pomiar rozdzielający, NIE oznacza abstain. Nie podawaj chain-of-thought.'''

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def answer(model,test,pred,abstain=False):
    return json.dumps({"diagnostic_model":model,"discriminating_measurement":test,
      "predicted_result":pred,"abstain":abstain},ensure_ascii=False,separators=(",",":"))

def supply(i):
    vin=[9,12,18,24,28][i%5]; rail=[3.3,5.0,8.0][(i//2)%3]
    load=[0.35,0.55,0.8,1.1,1.4][(i//3)%5]; drop=[18,27,36,43,51][(i//4)%5]
    prompt=f"Zasilanie PCB {vin} V jest stabilne. Szyna {rail:g} V bez obciążenia jest poprawna, lecz przy {load:.2f} A spada o {drop}%. Jak zawęzić usterkę jednym pomiarem?"
    model="usterka leży w torze zasilania pod obciążeniem: wejście regulatora, sam regulator/dławik albo nadmierne obciążenie za nim"
    test="zmierz jednocześnie Vin regulatora, Vout i spadek na dławiku podczas kontrolowanego skoku obciążenia"
    pred="Vin spada: problem upstream; Vin stabilne i Vout spada: regulator/dławik lub downstream, co rozdzieli dalszy test"
    return prompt,answer(model,test,pred,False),"supply"

def analog(i):
    ref=[3.3,5.0][i%2]; good=[0.6,1.1,1.65,2.2,2.8,4.1][i%6]
    bad=[0.05,0.25,ref-0.15,good*0.45][(i//3)%4]
    node=["wejściu ADC","wyjściu bufora","za filtrem RC","wyjściu wzmacniacza"][i%4]
    prompt=f"Dwa identyczne kanały mają wspólne zasilanie i Vref={ref:g} V. Dobry ma {good:g} V, zły {bad:g} V na {node}; wcześniejszy punkt jest zgodny. Co mierzyć dalej?"
    model="lokalna usterka złego kanału między ostatnim zgodnym a pierwszym rozbieżnym węzłem, nie wspólne zasilanie"
    test="porównaj oba kanały punkt po punkcie pod tym samym obciążeniem, zaczynając od ostatniego zgodnego węzła"
    pred="pierwsza trwała rozbieżność wskaże uszkodzony stopień; zgodność kolejnego węzła przesunie podejrzenie dalej w torze"
    return prompt,answer(model,test,pred,False),"analog"
def waveform(i):
    hz=[200,400,750,1200,1800,2500][i%6]; duty=[20,35,50,65,80][(i//2)%5]
    gate=[1.6,2.0,2.4,2.9,3.4][(i//4)%5]; temp=[52,61,69,77][(i//5)%4]
    prompt=f"MCU generuje PWM {hz} Hz, {duty}% i 3.3 V poprawnie także przy {temp}°C, ale wtedy VGS spada do {gate:g} V i zbocza zwalniają. Jaki model i test?"
    model="usterka termiczna jest za MCU: zasilanie drivera, sam driver albo nadmierne obciążenie bramki"
    test="rejestruj równocześnie driver IN, VDD i VGS podczas kontrolowanego wzrostu temperatury"
    pred="VDD spada: zasilanie drivera; IN i VDD stabilne przy spadku VGS: driver lub obciążenie bramki"
    return prompt,answer(model,test,pred,False),"waveform"

def thermal(i):
    part=["driver","stabilizator","op-amp","złącze","rezystor mocy","obszar via"][i%6]
    temp=[55,60,66,72,79,84][(i//3)%6]
    prompt=f"Usterka pojawia się przy około {temp}°C. Schłodzenie obszaru '{part}' przywraca działanie, chłodzenie reszty PCB nie. Nie znamy jeszcze konkretnego elementu. Co dalej?"
    model="usterka termiczna jest lokalna w wskazanym obszarze: element, połączenie lutowane/via lub jego lokalne zasilanie"
    test="selektywnie ogrzewaj małe punkty obszaru i jednocześnie mierz wejście, wyjście oraz lokalne zasilanie"
    pred="pierwszy punkt i sygnał skorelowany z temperaturą zawęzi winny element lub połączenie; brak korelacji rozszerzy obszar"
    return prompt,answer(model,test,pred,False),"thermal"

def short(i):
    rail=[1.8,3.3,5.0,12.0][i%4]; ohm=[0.6,1.0,1.7,2.9,5.6,8.2][(i//2)%6]
    lim=[0.35,0.5,0.7,0.9,1.2][(i//4)%5]
    prompt=f"Po wyłączeniu zasilania szyna {rail:g} V ma {ohm:g} Ω do masy, a przy starcie zasilacz wpada w limit. Bezpieczna iniekcja jest ograniczona do {lim:g} A. Jaki test wykonać?"
    model="szyna ma zwarcie lub silne upływowe obciążenie; winny może być kondensator, układ scalony albo dalsza gałąź"
    test="wykonaj niskonapięciową iniekcję z limitem prądu, obserwując hotspot i równolegle gradient spadków napięcia po gałęziach"
    pred="hotspot lub największy gradient wskaże gałąź; brak lokalizacji oznacza segmentację szyny zamiast zgadywania części"
    return prompt,answer(model,test,pred,False),"short"

def insufficient(i):
    variants=[
      ("Urządzenie sporadycznie się resetuje; brak logów, przebiegu RESET i pomiarów szyn.",
       "zmierz jednocześnie główne szyny i RESET w momencie zdarzenia",
       "dopiero kolejność zaniku szyny i RESET rozdzieli hipotezy zasilania od resetu/zegara"),
      ("Wyjście nie steruje obciążeniem; nie wiadomo, czy dociera komenda ani czy driver ma VDD.",
       "zmierz jednocześnie komendę wejściową, VDD drivera i jego wyjście podczas żądania załączenia",
       "brak komendy wskaże upstream, brak VDD zasilanie, a oba poprawne z brakiem OUT zawężą driver/downstream"),
      ("Na linii analogowej zmierzono napięcie, ale nie znamy wartości oczekiwanej, Vref ani źródła sygnału.",
       "ustal Vref i porównaj ten sam węzeł z pewnym kanałem referencyjnym pod identycznym warunkiem",
       "dopiero różnica względem poprawnego odniesienia pozwoli uznać odczyt za usterkę i wskazać kierunek"),
      ("Oscyloskop pokazuje nieregularny przebieg, lecz brak skali czasu, amplitudy, punktu pomiarowego i stanu obciążenia.",
       "powtórz pomiar z pełną skalą czasu i amplitudy, poprawną masą sondy oraz opisanym obciążeniem",
       "kompletny przebieg rozdzieli artefakt pomiarowy od rzeczywistej niestabilności układu"),
      ("Układ przestaje działać po nagrzaniu, ale nie wykonano lokalnego grzania/chłodzenia ani pomiarów krytycznych sygnałów.",
       "wykonaj lokalne heat/cool równolegle z pomiarem wejścia, wyjścia i lokalnego zasilania",
       "dopiero pierwszy sygnał skorelowany z temperaturą pozwoli zawęzić strefę bez wskazywania części"),
      ("Pobór prądu jest większy niż zwykle, lecz brak wartości referencyjnej, rezystancji szyn i termowizji.",
       "zmierz rezystancje głównych szyn do masy i porównaj pobór z pewnym egzemplarzem przy tym samym stanie",
       "dopiero odchylenie konkretnej szyny rozdzieli normalne obciążenie od zwarcia lub nadmiernego poboru")
    ]
    prompt,test,pred=variants[i%len(variants)]
    model="dane są niewystarczające do odpowiedzialnego zawężenia modelu usterki; należy utrzymać kilka hipotez"
    return prompt,answer(model,test,pred,True),"insufficient_data"

BUILDERS=[supply,analog,waveform,thermal,short,insufficient]
def make_rows(split,count_per_family,start):
    rows=[]
    for fi,builder in enumerate(BUILDERS):
      for j in range(count_per_family):
        idx=start + j*7 + fi*101
        prompt,assistant,category=builder(idx)
        rows.append({"record_id":f"ELEC41-{split.upper()}-{fi+1}-{j+1:03d}",
          "system":SYSTEM,"user":prompt,"assistant":assistant,
          "metadata":{"schema_version":1,"language":"pl","category":category,
            "training_eligible":split=="train","split":split,
            "contract":"p55-diagnostic-json-v1","p55_training_exclusion":True}})
    return rows

def replay_rows():
    src=ROOT/"deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_replay_train.jsonl"
    rows=[json.loads(x) for x in src.read_text().splitlines() if x.strip()]
    rng=random.Random(20261001)
    chosen=rng.sample(rows,min(24,len(rows)))
    for i,r in enumerate(chosen,1):
      r=json.loads(json.dumps(r))
      r["record_id"]=f"ELEC41-REPLAY-{i:03d}"
      r.setdefault("metadata",{})["p561_replay"]=True
      chosen[i-1]=r
    return chosen

def main():
    if sha(P55)!=EXPECTED_P55_SHA: raise SystemExit("P5_6_1=BLOCKED p55_dataset_drift")
    train=make_rows("train",24,1000)
    hold=make_rows("holdout",8,9000)
    replay=replay_rows()
    rng=random.Random(20261001); mixed=train+replay; rng.shuffle(mixed)
    tp=DIR/"contract_aligned_v41_train.jsonl"
    hp=DIR/"contract_aligned_v41_holdout.jsonl"
    rp=DIR/"contract_aligned_v41_replay_train.jsonl"
    for path,rows in ((tp,train),(hp,hold),(rp,mixed)):
      path.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))
    p55_text=P55.read_text()
    if any(r["user"] in p55_text for r in train+hold): raise SystemExit("P5_6_1=FAIL p55_prompt_overlap")
    manifest={"schema_version":1,"dataset_id":"contract-aligned-v4.1",
      "system_contract_sha256":hashlib.sha256(SYSTEM.encode()).hexdigest(),
      "train_records":len(train),"holdout_records":len(hold),"replay_records":len(replay),
      "mixed_records":len(mixed),"abstain_true_train":sum('"abstain":true' in r["assistant"] for r in train),
      "abstain_false_train":sum('"abstain":false' in r["assistant"] for r in train),
      "p55_frozen_sha256":EXPECTED_P55_SHA,"p55_training_exclusion":True,
      "train_sha256":sha(tp),"holdout_sha256":sha(hp),"mixed_sha256":sha(rp),
      "parent_adapter":"electronics-v4-measurement-r3-20261001",
      "principle":"one case = one production-contract JSON; explicit calibrated abstention; v3 replay"}
    (DIR/"contract_aligned_v41.manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("P5_6_1_DATASET=PASS"); print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))

if __name__=="__main__": main()
