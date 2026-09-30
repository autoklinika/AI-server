#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/electronics_v4"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
EXPECTED_P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
SYSTEM=(
 "Diagnostyka PCB: oddziel fakty od hipotez. Nie powtarzaj znanego pomiaru. Wybierz test, którego możliwe wyniki "
 "najlepiej rozdzielają hipotezy. Nie zgaduj części. Format: ZNANE; HIP; BRAK; TEST; ODRZUĆ; WYNIK."
)

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def norm(s): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9ąćęłńóśźż]+"," ",s.lower())).strip()
def case_supply(i):
    vin=[12,24][i%2]; rail=[5.0,3.3][(i//2)%2]; load=[0.45,0.7,0.95,1.2,1.5][i%5]; drop=[22,31,38,44,52][(i//5)%5]
    text=f"SUP-{i+1:03d}: wejście PCB {vin}V stabilne; {rail:g}V bez obciążenia OK, przy {load:.2f}A spada {drop}%. A: zmierz znów Vout. B: mierz temperaturę MCU. C: przy load-step mierz Vin/Vout regulatora i spadek na dławiku. "
    ans="ZNANE: wejście stabilne, Vout siada pod obciążeniem. HIP: tor wejściowy / regulator / downstream. BRAK: gdzie zaczyna się zapad. TEST:C. ODRZUĆ:A powtarza objaw; B słabo rozdziela. WYNIK: Vin spada=>upstream; Vin stabilne, Vout spada=>regulator/downstream."
    return text,ans
def case_analog(i):
    ref=[3.3,5.0][i%2]; sig=[0.7,1.2,1.8,2.4,3.1,4.0][i%6]; bad=[0.05,0.2,ref-0.1,ref-0.35][(i//3)%4]
    text=f"ANA-{i+1:03d}: dobry kanał daje {sig:g}V do ADC; zły ma poprawne wejście, zasilania i Vref={ref:g}V, lecz pin ADC={bad:g}V. A: sprawdź znów Vref. B: wymień ADC. C: porównaj dobry/zły kanał węzeł po węźle przez R/filtr/bufor do ADC. "
    ans="ZNANE: wejście i zasilania są dobre, błąd jest dalej w torze. HIP: R/filtr / bufor / clamp-leakage ADC. BRAK: pierwszy różny węzeł. TEST:C. ODRZUĆ:A znane; B zgaduje część. WYNIK: pierwszy punkt rozbieżności lokalizuje stopień."
    return text,ans
def case_wave(i):
    hz=[250,500,800,1000,1500,2000][i%6]; duty=[25,35,45,55,65,75][(i//2)%6]; gate=[1.8,2.2,2.8,3.2,3.8,4.2][(i//4)%6]
    text=f"WAV-{i+1:03d}: PWM MCU {hz}Hz/{duty}%/3.3V stabilny; po nagrzaniu VGS za driverem spada do {gate:g}V i zbocza zwalniają. A: mierz znów PWM MCU. B: wymień MOSFET. C: podczas grzania mierz razem wejście drivera, VDD i VGS. "
    ans="ZNANE: PWM MCU dobry, degradacja jest za nim i termiczna. HIP: VDD drivera / driver / gate load. BRAK: czy najpierw psuje się VDD czy wyjście. TEST:C. ODRZUĆ:A znane; B zgaduje. WYNIK: VDD spada=>zasilanie; VDD+wejście stabilne, VGS spada=>driver/gate."
    return text,ans
def case_thermal(i):
    part=["stabilizatora","drivera","op-ampa","złącza","rezystora mocy","przelotki/lutu"][i%6]; temp=[58,63,68,72,77,82][(i//3)%6]
    text=f"THM-{i+1:03d}: usterka od {temp}°C; chłodzenie okolicy {part} przywraca pracę, reszty PCB nie. A: powtórz samo chłodzenie. B: reflow. C: selektywnie grzej punkty tej strefy i mierz równocześnie wejście/wyjście/zasilanie stopnia. "
    ans="ZNANE: strefa termiczna już wskazana. HIP: element / lut-via-złącze / sąsiad. BRAK: pierwszy zmienny punkt elektryczny. TEST:C. ODRZUĆ:A powtarza znaną korelację; B niszczy dowód. WYNIK: pierwszy sygnał skorelowany z bodźcem lokalizuje winny stopień/połączenie."
    return text,ans
def case_short(i):
    rail=[3.3,5.0,12.0][i%3]; ohm=[0.7,1.1,1.8,2.6,4.3,7.5][(i//2)%6]; lim=[0.5,0.7,0.9,1.1,1.3,1.5][(i//4)%6]
    text=f"SHT-{i+1:03d}: szyna {rail:g}V ma {ohm:g}Ω do GND i start wchodzi w limit; bezpieczna iniekcja do {lim:g}A. A: zmierz znów rezystancję. B: wymień regulator. C: niskie V + limit prądu; mapuj hotspot i spadki mV po gałęziach. "
    ans="ZNANE: silne obciążenie szyny potwierdzone. HIP: MLCC / IC / gałąź downstream. BRAK: droga prądu zwarciowego. TEST:C. ODRZUĆ:A powtarza objaw; B zgaduje. WYNIK: hotspot lub gradient mV wskazuje gałąź; bez hotspotu segmentuj."
    return text,ans
def case_unknown(i):
    variants=[
      ("sporadyczne resety; brak logów i pomiaru zasilania/reset","mierz razem zasilanie i RESET podczas zdarzenia","zapad przed resetem=>power; stabilna szyna=>reset/clock/logika"),
      ("wyjście nie działa; nie wiadomo czy jest komenda i VDD drivera","mierz komendę, VDD i wyjście drivera w jednym zdarzeniu","brak komendy=>upstream; brak VDD=>zasilanie; oba dobre=>driver/downstream"),
      ("linia analogowa ma napięcie, lecz brak wartości oczekiwanej i punktu odniesienia","ustal referencję i porównaj z dobrym kanałem","dopiero różnica względem wzorca rozdzieli hipotezy"),
      ("nieregularny przebieg bez skali czasu, amplitudy, punktu i obciążenia","powtórz akwizycję z pełną skalą, punktem, masą sondy i obciążeniem","pełny przebieg rozdzieli artefakt od usterki"),
      ("usterka po nagrzaniu bez lokalizacji termicznej i pomiaru sygnałów","pobudzaj strefy termicznie, monitorując krytyczne wejście/wyjście/zasilanie","pierwszy sygnał skorelowany ze strefą zawęzi usterkę"),
    ]
    symptom,test,pred=variants[i%len(variants)]
    text=f"UNK-{i+1:03d}: {symptom}. A: wskaż od razu element. B: {test}. C: powtórz objaw bez nowych danych. "
    ans=f"ZNANE: danych za mało na część. HIP: kilka przyczyn. BRAK: test rozdzielający. TEST:B. ODRZUĆ:A zgaduje; C nic nie wnosi. WYNIK: {pred}. DECYZJA: wstrzymaj wskazanie elementu do wyniku testu."
    return text,ans
BUILDERS=[case_supply,case_analog,case_wave,case_thermal,case_short,case_unknown]

def packed_row(i):
    cases=[]; answers=[]
    for b in BUILDERS:
        q,a=b(i); cases.append(q); answers.append(a)
    user="Rozwiąż 6 niezależnych przypadków. W każdym wybierz jeden test A-D o największej wartości rozdzielającej; nie powtarzaj pomiaru, którego wynik jest już znany.\n" + "\n".join(cases)
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
