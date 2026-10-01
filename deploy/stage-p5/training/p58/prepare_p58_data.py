#!/usr/bin/env python3
from __future__ import annotations
import ast,hashlib,json,random
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/p58"
RUNNER=ROOT/"deploy/stage-p5/benchmark/run_quality_benchmark_v1.py"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"
P57_FINAL=ROOT/"deploy/stage-p5/training/p57/p57_final_v1.jsonl"
P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"
P57_FINAL_SHA="5a09c4d53ff4f961402d57aaf03347d9f36bb5c10d1ecc7a7fc3243d6f987059"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def system_prompt():
    t=ast.parse(RUNNER.read_text())
    for n in t.body:
        if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=="SYSTEM" for x in n.targets):
            return ast.literal_eval(n.value)
    raise RuntimeError("SYSTEM missing")
SYSTEM=system_prompt()

def j(model,test,pred,abstain):
    return json.dumps({"diagnostic_model":model,"discriminating_measurement":test,
      "predicted_result":pred,"abstain":abstain},ensure_ascii=False,separators=(",",":"))

def tr(rid,cat,user,model,test,pred,abstain,difficulty,role):
    return {"record_id":rid,"system":SYSTEM,"user":user,"assistant":j(model,test,pred,abstain),
      "metadata":{"category":cat,"difficulty":difficulty,"curriculum_role":role,
      "training_eligible":True,"p58_curriculum":True}}

def ev(cid,cat,prompt,model,test,pred,abstain):
    return {"schema_version":1,"case_id":cid,"category":cat,"language":"pl","training_exclusion":True,
      "prompt":prompt,"reference":{"diagnostic_model":model,"discriminating_measurement":test,
      "predicted_result":pred,"abstain":abstain}}

def supply_train(block,variant):
    top=["buck 24→5 V","LDO 5→3.3 V","zasilanie 12 V przez high-side MOSFET","boost 5→12 V"][block%4]
    load=[0.35,0.55,0.85,1.2,1.55][block%5]; droop=[12,21,34,46,58][(block+variant)%5]
    if variant==0:
        u=f"Układ {top}: bez obciążenia napięcia są nominalne, przy {load:.2f} A wyjście spada o {droop}%. Wejście mierzone daleko od przetwornicy wygląda poprawnie. Jak rozdzielić impedancję upstream, stopień regulacji i obciążenie?"
    else:
        u=f"W torze {top} rail jest poprawny na jałowo, ale przy skoku do {load:.2f} A zapada się o {droop}%. Nie wiadomo czy traci napięcie lokalne wejście regulatora, sam regulator czy odbiornik."
    m="model usterki obejmuje trzy klasy: lokalny spadek na torze zasilania upstream, ograniczenie stopnia regulacji oraz nadmierne obciążenie downstream"
    t="zarejestruj równocześnie napięcie bezpośrednio na wejściu regulatora, jego wyjście oraz prąd lub spadek na elemencie szeregowym podczas skoku obciążenia"
    p="jeśli lokalne wejście regulatora spada, problem jest upstream; przy stabilnym wejściu i zapadzie wyjścia rozdziel regulator od downstream przez prąd/spadek szeregowym"
    return tr(f"P58-TRAIN-SUP-{block:02d}-{variant}", "schematic_symptom_measurements",u,m,t,p,False,block+1,"target")

def thermal_train(block):
    zone=["driver bramki","sekcja analogowa","stabilizator lokalny","złącze i pobliskie via"][block%4]
    temp=[52,59,66,73,81][block%5]
    u=f"Objaw występuje dopiero około {temp}°C. Selektywne chłodzenie obszaru '{zone}' natychmiast przywraca funkcję, ale nie wiadomo czy reaguje zasilanie, sam element czy połączenie. Jaki test i jakie rozgałęzienie wyniku?"
    m="usterka jest termicznie lokalna w wskazanej strefie, ale nadal trzeba rozdzielić lokalne zasilanie, element aktywny i połączenie"
    t="podczas kontrolowanego heat/cool mierz jednocześnie lokalne VDD, wejście i wyjście podejrzanego stopnia"
    p="jeśli pierwsze zmienia się VDD, badaj zasilanie; przy stabilnym VDD i wejściu zmiana wyjścia wskazuje element lub połączenie w tej strefie"
    return tr(f"P58-TRAIN-THM-{block:02d}","thermal_intermittent",u,m,t,p,False,block+1,"target")

def short_train(block):
    rail=[1.2,1.8,2.5,3.3,5.0][block%5]; ohm=[0.4,0.9,1.7,3.2,6.8][block%5]
    u=f"Po wyłączeniu szyna {rail:g} V ma około {ohm:g} Ω do masy. Źródło wchodzi w ograniczenie prądowe. Trzeba znaleźć gałąź zwarcia bez wskazywania części na podstawie samej temperatury."
    m="na szynie istnieje zwarcie lub silny upływ w jednej z gałęzi; regulator może być jedynie źródłem zasilającym uszkodzenie"
    t="wstrzyknij niskie bezpieczne napięcie z limitem prądu i porównaj hotspot z gradientem spadków mV, a gdy wynik jest niejednoznaczny segmentuj szynę"
    p="zgodny hotspot i gradient zawężają gałąź; brak zgodności oznacza segmentację szyny i ponowny pomiar zamiast zgadywania komponentu"
    return tr(f"P58-TRAIN-SHT-{block:02d}","pcb_short",u,m,t,p,False,block+1,"target")
def compare_train(block):
    stage=["filtr RC","bufor","rezystor szeregowy","wejście ADC"][block%4]
    u=f"Dwa równoległe kanały są zgodne aż do wejścia stopnia '{stage}', a różnią się dopiero na jego wyjściu. Wspólne zasilanie pozostaje prawidłowe. Co jest modelem usterki i jaki wynik pomiaru rozdziela hipotezy?"
    m="usterka jest lokalna w złym kanale między ostatnim zgodnym węzłem a pierwszym rozbieżnym węzłem"
    t="porównaj wejście, wyjście i lokalne zasilanie tego samego stopnia w obu kanałach pod identycznym bodźcem"
    p="jeśli wejścia i zasilania są zgodne, a wyjścia różne, zawęź sam stopień lub jego obciążenie; różnica już na wejściu przenosi podejrzenie upstream"
    return tr(f"P58-TRAIN-CMP-{block:02d}","good_bad_channel_comparison",u,m,t,p,False,block+1,"target")

TRUE_CASES=[
 ("Sterownik losowo resetuje się; nie ma logów, oscyloskopu na RESET ani nagrania szyn z chwili zdarzenia.",
  "dane nie pozwalają jeszcze odróżnić zasilania, resetu, zegara ani innej przyczyny zdarzenia",
  "zarejestruj jednocześnie główne szyny, RESET i zegar w chwili resetu",
  "jeśli pierwsza zanika szyna, badaj zasilanie; przy stabilnych szynach dopiero RESET/zegar stają się kierunkiem"),
 ("Wyjście mocy nie działa, ale nie wiadomo czy sterownik dostaje komendę i czy driver ma lokalne zasilanie.",
  "brakuje dwóch podstawowych obserwacji potrzebnych do zawężenia: komendy oraz zasilania drivera",
  "zmierz w tym samym żądaniu komendę wejściową, VDD drivera i wyjście",
  "brak komendy wskazuje upstream, brak VDD zasilanie, a oba poprawne przy braku wyjścia zawężają driver/downstream"),
 ("Na linii analogowej jest nietypowe napięcie, ale brak Vref, wartości oczekiwanej i pewnego kanału referencyjnego.",
  "sam poziom napięcia bez referencji nie pozwala rozstrzygnąć, czy jest poprawny czy uszkodzony",
  "ustal Vref i porównaj ten sam węzeł z pewnym kanałem lub egzemplarzem pod identycznym bodźcem",
  "dopiero odchylenie od wiarygodnej referencji uzasadnia zawężanie toru jako uszkodzonego"),
 ("Przebieg z oscyloskopu wygląda źle, lecz brak skali czasu, amplitudy, punktu pomiaru i warunku obciążenia.",
  "dane pomiarowe są niekompletne i nie odróżniają artefaktu sondowania od rzeczywistej niestabilności",
  "powtórz pomiar z pełną skalą czasu i amplitudy, poprawną masą sondy oraz opisanym obciążeniem",
  "jeśli anomalia znika po poprawnym sondowaniu, była artefaktem; jeśli pozostaje, dopiero wtedy analizuj układ")
]
FALSE_CASES=[
 ("PWM z MCU pozostaje poprawny na gorąco i lokalne VDD drivera także jest stabilne, ale VGS maleje wraz z temperaturą.",
  "dane już zawężają problem za MCU do drivera lub obciążenia bramki; nie trzeba abstainować",
  "porównaj VGS i prąd bramki zimny/gorący przy potwierdzonym stabilnym IN i VDD",
  "rosnący prąd bramki przy spadku VGS wskazuje obciążenie; bez wzrostu prądu bardziej prawdopodobny jest driver"),
 ("Dwa kanały są identyczne aż do wejścia bufora; tylko wyjście jednego kanału jest niepoprawne, a lokalne zasilanie obu jest takie samo.",
  "usterka jest już lokalnie zawężona do bufora lub jego obciążenia w jednym kanale",
  "porównaj wyjścia obu buforów pod tym samym obciążeniem i sprawdź prąd lub impedancję obciążenia złego kanału",
  "różne zachowanie przy tym samym obciążeniu wskazuje bufor; nietypowe obciążenie przenosi podejrzenie downstream"),
 ("Tylko jeden niewielki obszar reaguje na selektywne chłodzenie, podczas gdy reszta PCB nie zmienia zachowania.",
  "mamy wiarygodną lokalizację termiczną, choć nie konkretny komponent; można zawężać bez abstention",
  "podziel tę strefę na mniejsze punkty heat/cool i mierz równocześnie wejście, wyjście oraz lokalne zasilanie",
  "pierwszy punkt i pierwszy sygnał skorelowany z temperaturą rozdzielą element, połączenie i zasilanie"),
 ("Na szynie zwartej do masy iniekcja prądu pokazuje jednoznaczny gradient napięcia rosnący w stronę konkretnej gałęzi, bez pojedynczego hotspotu.",
  "dane wystarczają do zawężenia zwarcia do gałęzi mimo braku jednoznacznego komponentu",
  "odłącz lub odseparuj wskazaną gałąź i powtórz pomiar rezystancji oraz gradientu",
  "zanik niskiej rezystancji po izolacji potwierdzi gałąź; brak zmiany każe wrócić do dalszej segmentacji")
]

def abstain_pair(block,true_case):
    arr=TRUE_CASES if true_case else FALSE_CASES
    u,m,t,p=arr[block%len(arr)]
    return tr(f"P58-TRAIN-{'ABT' if true_case else 'ABF'}-{block:02d}",
      "insufficient_data" if true_case else "borderline_sufficient",u,m,t,p,true_case,block+1,"calibration")

def replay_train(block):
    # Protect a skill that was perfect on P57-FINAL using independent older replay data.
    v3=load(ROOT/"deploy/stage-p5/training/electronics_v3/electronics_foundation_v3_replay_train.jsonl")
    pool=[x for x in v3 if x.get("metadata",{}).get("category") in ("gate_driver_uvlo","brownout_waveform_signature","comparative_channel_diagnosis","pcb_voltage_drop_tracing")]
    r=json.loads(json.dumps(pool[block%len(pool)]))
    r["record_id"]=f"P58-TRAIN-REPLAY-{block:02d}"
    r.setdefault("metadata",{})["p58_curriculum"]=True
    r["metadata"]["curriculum_role"]="replay"
    return r

def training_curriculum():
    out=[]
    for b in range(10):
        out.extend([supply_train(b,0),supply_train(b,1),thermal_train(b),short_train(b),
                    compare_train(b),abstain_pair(b,True),abstain_pair(b,False),replay_train(b)])
    return out
# DEV and FINAL deliberately use separate wording families from TRAIN.
def eval_case(fam,i,prefix,final=False):
    tag=(200 if final else 20)+i
    if fam==0:
        source=["bezpiecznik i ścieżka wejściowa","high-side switch","złącze zasilania","dławik wejściowy"][i%4]
        rail=[2.8,4.2,7.0,10.0][i%4]; load=[0.48,0.72,1.05,1.42][(i//2)%4]
        prompt=f"Przy obciążeniu {load:.2f} A szyna {rail:g} V zapada się, choć napięcie mierzone przed sekcją '{source}' jest stabilne. Jak jednym zestawem obserwacji rozdzielisz stratę przed regulatorem, regulator i downstream?"
        return ev(f"{prefix}-SUP-{tag}","schematic_symptom_measurements",prompt,
          "trzeba rozdzielić lokalny spadek toru zasilania przed regulatorem, niewydolność regulatora oraz przeciążenie downstream",
          "rejestruj równocześnie napięcie bezpośrednio na wejściu regulatora, wyjście i prąd albo spadek na elemencie szeregowym podczas obciążenia",
          "spadek lokalnego wejścia oznacza upstream; stabilne wejście z zapadem wyjścia wymaga rozdzielenia regulatora i downstream na podstawie prądu/spadku szeregowym",False)
    if fam==1:
        node=["wyjściu wzmacniacza","za filtracją","na wejściu multipleksera","na pinie ADC"][i%4]
        prompt=f"Tor A i B są identyczne aż do poprzedniego węzła. Dopiero na {node} kanał B odbiega, przy wspólnym poprawnym Vref i zasilaniu. Jaki jest właściwy model usterki?"
        return ev(f"{prefix}-ANA-{tag}","good_bad_channels",prompt,
          "usterka jest lokalna w kanale B między ostatnim zgodnym a pierwszym rozbieżnym węzłem",
          "porównaj oba kanały na wejściu i wyjściu podejrzanego stopnia pod tym samym sygnałem oraz obciążeniem",
          "jeśli wejścia są zgodne, a wyjścia różne, zawęź ten stopień lub jego obciążenie; różnica na wejściu przenosi podejrzenie upstream",False)
    if fam==2:
        freq=[420,780,1250,2100][i%4]; hot=[58,67,74,84][i%4]
        prompt=f"Przy {hot}°C PWM {freq} Hz z MCU pozostaje poprawny, lecz sygnał gate traci amplitudę i zbocza zwalniają. Jak rozdzielić driver, jego zasilanie i obciążenie bramki?"
        return ev(f"{prefix}-WAV-{tag}","numeric_waveform",prompt,
          "usterka jest za MCU i obejmuje VDD drivera, sam driver albo obciążenie bramki",
          "mierz jednocześnie wejście drivera, lokalne VDD, VGS i w razie potrzeby prąd bramki podczas przejścia przez temperaturę objawu",
          "spadek VDD wskazuje zasilanie; stabilne IN/VDD ze spadkiem VGS zawężają driver lub obciążenie bramki",False)
    if fam==3:
        zone=["okolica układu drivera","sekcja wejścia analogowego","mały obszar przy złączu","lokalny regulator"][i%4]
        prompt=f"Usterka występuje tylko po nagrzaniu, a selektywne chłodzenie '{zone}' ją usuwa. Jak zaplanować pomiar, który nie pomyli zasilania z elementem lub połączeniem?"
        return ev(f"{prefix}-THM-{tag}","thermal_intermittent",prompt,
          "usterka jest termicznie lokalna, ale może dotyczyć lokalnego zasilania, elementu aktywnego albo połączenia",
          "przy kontrolowanym heat/cool obserwuj równocześnie lokalne VDD oraz wejście i wyjście stopnia",
          "jeśli pierwsze zmienia się VDD, badaj zasilanie; przy stabilnym VDD i wejściu zmiana wyjścia wskazuje element lub połączenie",False)
    if fam==4:
        rail=[1.5,2.0,3.6,5.5][i%4]
        prompt=f"Szyna {rail:g} V ma niską rezystancję do masy i zasilacz ogranicza prąd. Termika nie pokazuje jednoznacznego punktu. Co robisz, aby lokalizować gałąź?"
        return ev(f"{prefix}-SHT-{tag}","pcb_short",prompt,
          "na szynie jest zwarcie lub silny upływ w jednej z gałęzi, a brak hotspotu nie identyfikuje jeszcze komponentu",
          "wstrzyknij bezpieczne niskie napięcie z limitem prądu, mapuj gradient mV i segmentuj szynę, jeśli gradient nie daje jednej gałęzi",
          "spójny gradient zawęża gałąź; brak jednoznacznego kierunku wymaga segmentacji i ponownego pomiaru zamiast wskazywania części",False)
    if fam==5:
        prompt=f"Dwa bliźniacze kanały mają wspólne zasilanie. Węzły do punktu N{tag} są zgodne, pierwszy rozjazd pojawia się dopiero na wyjściu kolejnego stopnia. Jak wykorzystujesz tę informację?"
        return ev(f"{prefix}-CMP-{tag}","good_bad_channel_comparison",prompt,
          "pierwszy rozbieżny węzeł lokalizuje usterkę do stopnia między ostatnim zgodnym i pierwszym różnym punktem",
          "porównaj oba kanały na wejściu, wyjściu i lokalnym zasilaniu tego stopnia przy identycznym bodźcu",
          "zgodne wejścia i zasilania przy różnym wyjściu wskazują ten stopień lub jego obciążenie; różne wejścia przenoszą problem upstream",False)
    # Alternate true/false abstention with wording not used in TRAIN.
    if i%2==0:
        prompt=["Objaw pojawia się sporadycznie, ale nie ma żadnego pomiaru z chwili zdarzenia ani pewnego punktu odniesienia.",
                "Nie działa wyjście, ale nie sprawdzono ani komendy wejściowej, ani zasilania stopnia wykonawczego."][i%2]
        return ev(f"{prefix}-UNK-{tag}","insufficient_data",prompt,
          "dane są niewystarczające do odpowiedzialnego zawężenia przyczyny i trzeba zachować kilka hipotez",
          "najpierw zarejestruj brakujące sygnały wejściowe i zasilania dokładnie w chwili wystąpienia objawu",
          "dopiero kolejność i miejsce pierwszej nieprawidłowości pozwolą rozdzielić hipotezy",True)
    prompt="Sygnał sterujący i lokalne zasilanie stopnia są potwierdzone jako poprawne w chwili objawu, ale jego wyjście jest błędne. Czy danych jest dość do zawężenia?"
    return ev(f"{prefix}-UNK-{tag}","borderline_sufficient",prompt,
      "dane wystarczają do zawężenia usterki do badanego stopnia lub jego bezpośredniego obciążenia",
      "porównaj wyjście stopnia pod znanym obciążeniem oraz impedancję lub prąd bezpośredniego downstream",
      "jeśli wyjście pozostaje błędne przy poprawnym obciążeniu, zawęź stopień; nietypowe obciążenie przenosi podejrzenie downstream",False)

def make_eval(prefix,n_each,final=False):
    out=[]
    base=8000 if final else 4000
    for f in range(7):
        for i in range(n_each):
            c=eval_case(f,i,prefix,final)
            c["prompt"]=f"Warunek testowy T{base+f*100+i:04d}: "+c["prompt"]
            out.append(c)
    return out

def regression_slice():
    # P57-FINAL is now revealed and may only be used as regression, never for selection.
    return load(P57_FINAL)

def writej(p,rows): p.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in rows))

def main():
    if sha(P55)!=P55_SHA: raise SystemExit("P58=BLOCKED p55_drift")
    if sha(P57_FINAL)!=P57_FINAL_SHA: raise SystemExit("P58=BLOCKED p57_final_drift")
    train=training_curriculum()
    dev=make_eval("P58-DEV",6,False)
    mini=[r for idx,r in enumerate(dev) if idx%3==0]
    final=make_eval("P58-FINAL",10,True)
    reg=regression_slice()
    # Hard exclusion of old revealed benchmarks from new training and new FINAL.
    old_text={x.get("prompt","") for x in load(P57_FINAL)} | {x.get("prompt","") for x in load(P55)}
    for r in train:
        if r["user"] in old_text: raise SystemExit("P58=FAIL train_overlap_old_benchmark")
    final_text={r["prompt"] for r in final}; dev_text={r["prompt"] for r in dev}; train_text={r["user"] for r in train}
    if final_text & dev_text or final_text & train_text: raise SystemExit("P58=FAIL final_overlap")
    files={"train":DIR/"p58_curriculum_train.jsonl","dev":DIR/"p58_dev_v1.jsonl","mini":DIR/"p58_mini_dev_v1.jsonl",
           "final":DIR/"p58_final_v1.jsonl","reg":DIR/"p58_p57final_regression.jsonl"}
    for k,rr in (("train",train),("dev",dev),("mini",mini),("final",final),("reg",reg)): writej(files[k],rr)
    manifest={"schema_version":1,"pipeline_id":"P5.8-competency-curriculum-v1",
      "parent_adapter":"/srv/ai-data/training/p5/checkpoints/p57-p57-seed1b-20261001/step-008",
      "train_records":len(train),"dev_records":len(dev),"mini_dev_records":len(mini),"final_records":len(final),
      "revealed_p57_final_role":"regression_only","revealed_p57_final_sha256":P57_FINAL_SHA,
      "legacy_p55_role":"regression_only","legacy_p55_sha256":P55_SHA,
      "checkpoint_interval":8,"max_checkpoints":10,"early_stop_patience":2,
      "focus":["supply causal localization","thermal conditional prediction","pcb short localization",
               "good-bad conditional prediction","abstention calibration"],
      "protected":["numeric_waveform","v1-v4 foundation"],
      "train_sha256":sha(files["train"]),"dev_sha256":sha(files["dev"]),
      "mini_dev_sha256":sha(files["mini"]),"final_sha256":sha(files["final"]),
      "final_policy":"never used for training, checkpoint selection, threshold tuning, or early stopping"}
    (DIR/"p58_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("P58_DATA=PASS"); print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
