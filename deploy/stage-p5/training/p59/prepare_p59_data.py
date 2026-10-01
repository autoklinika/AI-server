#!/usr/bin/env python3
from __future__ import annotations
import ast, hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
DIR=ROOT/"deploy/stage-p5/training/p59"
RUNNER=ROOT/"deploy/stage-p5/benchmark/run_quality_benchmark_v1.py"
P58_TRAIN=ROOT/"deploy/stage-p5/training/p58/p58_curriculum_train.jsonl"
P58_DEV=ROOT/"deploy/stage-p5/training/p58/p58_dev_v1.jsonl"
P58_FINAL=ROOT/"deploy/stage-p5/training/p58/p58_final_v1.jsonl"
P57_FINAL=ROOT/"deploy/stage-p5/training/p57/p57_final_v1.jsonl"
P55=ROOT/"benchmarks/electronics_v3_quality_v1/cases.v1.jsonl"

P58_DEV_SHA="d3bb154b10ae43609585753273e45067bc53b5b0cbd31a2012d62a6d3dd663d9"
P58_FINAL_SHA="c6b3887accf6f3778be121011b15accb86339002c70c3e6dd50a6f524a9c420d"
P57_FINAL_SHA="5a09c4d53ff4f961402d57aaf03347d9f36bb5c10d1ecc7a7fc3243d6f987059"
P55_SHA="8ba6b0a767c4649949a399e38e276287cc3058d89e89fca86d44b3ddb1858fa5"

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def load(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
def system_prompt():
    tree=ast.parse(RUNNER.read_text())
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=="SYSTEM" for x in n.targets):
            return ast.literal_eval(n.value)
    raise RuntimeError("SYSTEM missing")

SYSTEM=system_prompt()

def answer(model,test,pred,abstain):
    return json.dumps({
      "diagnostic_model":model,
      "discriminating_measurement":test,
      "predicted_result":pred,
      "abstain":abstain
    },ensure_ascii=False,separators=(",",":"))

def train_record(rid,category,user,model,test,pred,abstain,role):
    return {
      "record_id":rid,"system":SYSTEM,"user":user,
      "assistant":answer(model,test,pred,abstain),
      "metadata":{"category":category,"training_eligible":True,
                  "p59_targeted":True,"curriculum_role":role}
    }

def eval_record(cid,category,prompt,model,test,pred,abstain):
    return {
      "schema_version":1,"case_id":cid,"category":category,
      "language":"pl","training_exclusion":True,"prompt":prompt,
      "reference":{"diagnostic_model":model,"discriminating_measurement":test,
                   "predicted_result":pred,"abstain":abstain}
    }
ZONES=("driver bramki","sekcja wejścia analogowego","lokalny regulator",
       "bufor wyjściowy","okolica złącza","obszar via pod układem")
TEMPS=(48,56,63,71,79,86)
RAILS=(1.8,2.5,3.3,5.0,8.0,12.0)
DWELLS=(9,14,21,29,38,49,61,74)
LOADS=(25,35,45,55,65,75,85,95)

def thermal_case(block,kind):
    zone=ZONES[(block+kind)%len(ZONES)]
    temp=TEMPS[(2*block+kind)%len(TEMPS)]
    rail=RAILS[(block+2*kind)%len(RAILS)]
    dwell=DWELLS[block]
    load=LOADS[block]
    rid=f"P59-TRAIN-THM-{block:02d}-{kind}"
    if kind==0:
        user=f"Po osiągnięciu około {temp}°C i {dwell} s stabilizacji zanika funkcja w strefie {zone}. Komenda wejściowa pozostaje poprawna. Trzeba rozdzielić lokalne VDD, sam stopień i połączenie."
        model="usterka jest termicznie lokalna; nadal trzeba rozdzielić lokalne zasilanie, element aktywny i połączenie"
        test="podczas kontrolowanego heat/cool mierz jednocześnie lokalne VDD oraz wejście i wyjście badanego stopnia"
        pred="jeśli pierwsze zmienia się VDD, kierunek jest zasilaniowy; jeśli VDD i wejście są stabilne, a zmienia się wyjście, zawęź element lub jego połączenie"
    elif kind==1:
        user=f"W strefie „{zone}” selektywne chłodzenie natychmiast przywraca działanie przy {temp}°C i obciążeniu {load}%. Sam sygnał sterujący przed strefą nie zmienia się."
        model="lokalizacja termiczna jest wiarygodna, ale przyczyną może być lokalne zasilanie, aktywny stopień albo interconnect"
        test="rejestruj równolegle zasilanie strefy, sygnał przed stopniem i sygnał po stopniu podczas cyklu ogrzewanie-chłodzenie"
        pred="jeśli zmienia się zasilanie strefy, badaj regulator lub tor zasilania; jeśli zasilanie i wejście są stabilne, a wyjście reaguje, problem jest w stopniu lub interconnect"
    elif kind==2:
        user=f"Na gorąco około {temp}°C przy obciążeniu {load}% wejście drivera pozostaje poprawne, lecz amplituda wyjścia maleje. Lokalna szyna ma nominalnie {rail:g} V."
        model="problem jest za wejściem drivera i trzeba rozdzielić termiczny spadek VDD, sam driver oraz zwiększone obciążenie wyjścia"
        test="mierz równocześnie IN, lokalne VDD, OUT lub VGS oraz prąd obciążenia podczas przejścia przez temperaturę objawu"
        pred="jeśli VDD spada, badaj zasilanie; jeśli IN i VDD są stabilne, a rośnie prąd obciążenia przy spadku OUT, podejrzewaj downstream, w przeciwnym razie driver"
    elif kind==3:
        user=f"Tor analogowy K{block+1} zaczyna dryfować dopiero przy {temp}°C. Vref i sygnał wejściowy można mierzyć równocześnie z wyjściem."
        model="dryft termiczny może pochodzić z Vref, badanego stopnia analogowego albo jego połączenia, więc trzeba obserwować kolejność zmian"
        test="w czasie kontrolowanego nagrzewania rejestruj Vref, wejście i wyjście stopnia w tej samej osi czasu"
        pred="jeśli pierwsze dryfuje Vref, przyczyna jest referencyjna; jeśli Vref i wejście są stabilne, a dryfuje wyjście, zawęź stopień lub jego połączenie"
    elif kind==4:
        user=f"Po nagrzaniu {zone} do około {temp}°C przez {dwell} s pojawia się przerwa chwilowa. Docisk mechaniczny czasem zmienia objaw, ale nie jest to rozstrzygające."
        model="usterka może być połączeniem termomechanicznym albo elementem aktywnym w tej samej strefie; sam efekt docisku nie rozstrzyga"
        test="podczas heat/cool mierz czteroprzewodowy spadek na podejrzanym połączeniu oraz wejście i wyjście stopnia bez zmiany punktów sondowania"
        pred="jeśli skok spadku na połączeniu wyprzedza utratę funkcji, kierunek jest interconnect; jeśli spadek pozostaje stabilny, a zmienia się wyjście przy stabilnym wejściu, kierunek jest aktywny stopień"
    else:
        user=f"Lokalny regulator {rail:g} V działa na zimno, a po ogrzaniu do {temp}°C przy obciążeniu {load}% funkcja downstream zanika. Napięcie przed regulatorem jest dostępne do pomiaru."
        model="trzeba rozdzielić termiczną niewydolność regulatora od upstream oraz od przeciążenia downstream"
        test="podczas narastania temperatury rejestruj wejście regulatora, jego wyjście i prąd downstream"
        pred="jeśli spada wejście regulatora, problem jest upstream; jeśli wejście jest stabilne i wyjście spada przy prawidłowym prądzie, podejrzewaj regulator, a wzrost prądu wskazuje downstream"
    return train_record(rid,"thermal_intermittent",user,model,test,pred,False,"thermal_target")
ABSTAIN_CASES=(
 ("Objaw pojawia się tylko czasem po rozgrzaniu, ale nie ma żadnego pomiaru VDD, wejścia ani wyjścia z chwili zdarzenia.",
  "dane są niewystarczające do rozdzielenia lokalnego zasilania, elementu i połączenia",
  "zarejestruj jednocześnie VDD, wejście i wyjście w chwili wystąpienia objawu podczas kontrolowanego heat/cool",
  "dopiero sygnał, który zmieni się pierwszy, pozwoli zawęzić hipotezę"),
 ("Klient mówi tylko, że po schłodzeniu moduł wraca do pracy; brak lokalizacji termicznej i brak pomiarów z czasu awarii.",
  "sama zależność od temperatury nie wystarcza do lokalizacji przyczyny",
  "wykonaj selektywny heat/cool stref i rejestruj zasilania oraz krytyczne wejścia i wyjścia",
  "jeśli jedna strefa i jeden sygnał korelują z objawem, można dopiero zawężać tę gałąź"),
 ("Moduł resetuje się po nagrzaniu, ale nie zapisano przebiegu głównych szyn, RESET ani zegara w chwili resetu.",
  "brakuje danych potrzebnych do rozdzielenia brownoutu, toru resetu i problemu zegara",
  "zarejestruj równocześnie główne szyny, RESET i zegar podczas kontrolowanego cyklu temperaturowego",
  "pierwszy sygnał, który odchyli się przed resetem, wyznaczy właściwą gałąź diagnostyczną"),
 ("Kanał analogowy dryfuje na gorąco, ale brak jednoczesnego pomiaru Vref, wejścia i pewnego kanału referencyjnego.",
  "nie ma wystarczających danych, aby odróżnić dryft referencji od lokalnego toru analogowego",
  "zmierz Vref, wejście badanego kanału i pewny kanał referencyjny w tej samej osi czasu podczas heat/cool",
  "dopiero porównanie kolejności dryftu pokaże, czy problem jest wspólny czy lokalny"),
 ("Po nagrzaniu zrywa się komunikacja, lecz nie ma przebiegów magistrali ani pomiaru zasilania transceivera z chwili błędu.",
  "sam fakt utraty komunikacji nie rozdziela transceivera, zasilania i problemu po stronie sterownika",
  "rejestruj magistralę, lokalne VDD transceivera oraz sygnały logiczne TX/RX w chwili wystąpienia błędu",
  "pierwsza nieprawidłowość pozwoli rozdzielić zasilanie, warstwę fizyczną i sterowanie"),
 ("Wyjście mocy zanika po nagrzaniu, ale nie wiadomo czy w tej chwili obecna jest komenda wejściowa ani VDD drivera.",
  "bez komendy i lokalnego zasilania nie można zawęzić problemu do drivera lub downstream",
  "zmierz równocześnie komendę, VDD drivera i wyjście podczas termicznego odtworzenia objawu",
  "dopiero zestaw tych trzech sygnałów pozwoli wskazać etap, na którym pojawia się pierwsza nieprawidłowość"),
 ("Pobór prądu modułu rośnie na gorąco, ale nie ma pomiaru prądów gałęzi ani lokalizacji strefy, która reaguje na temperaturę.",
  "wzrost prądu całego modułu nie wystarcza do wskazania gałęzi lub elementu",
  "wykonaj selektywny heat/cool i porównaj prądy głównych gałęzi z lokalnymi spadkami napięcia",
  "gałąź, której prąd lub spadek zmieni się jako pierwszy razem z temperaturą, stanie się kandydatem do dalszej diagnostyki"),
 ("Po rozgrzaniu pojawia się błąd czujnika, ale nie ma wartości surowej, napięcia referencyjnego ani porównania z drugim kanałem.",
  "kod błędu bez danych surowych nie rozdziela czujnika, referencji i toru wejściowego",
  "zarejestruj wartość surową, Vref i drugi pewny kanał podczas kontrolowanego nagrzewania",
  "dopiero zgodność lub rozjazd tych sygnałów pozwoli rozdzielić źródło błędu")
)

def abstain_case(block):
    u,m,t,p=ABSTAIN_CASES[block%len(ABSTAIN_CASES)]
    return train_record(f"P59-TRAIN-ABST-{block:02d}","insufficient_data",
                        u,m,t,p,True,"abstention_replay")

def replay_case(block):
    rows=load(P58_TRAIN)
    keep=[r for r in rows if r.get("metadata",{}).get("category") in
          ("numeric_waveform","pcb_short","schematic_symptom_measurements",
           "good_bad_channel_comparison","borderline_sufficient")]
    r=json.loads(json.dumps(keep[block%len(keep)]))
    r["record_id"]=f"P59-TRAIN-REPLAY-{block:02d}"
    r.setdefault("metadata",{})["p59_targeted"]=True
    r["metadata"]["curriculum_role"]="broad_replay"
    return r

def training_rows():
    out=[]
    for block in range(8):
        for kind in range(6):
            out.append(thermal_case(block,kind))
        out.append(abstain_case(block))
        out.append(replay_case(block))
    return out
def thermal_eval(i,prefix,offset):
    kind=i%6
    idx=offset+i
    zone=ZONES[(i*3+1)%len(ZONES)]
    temp=(51,59,68,76,83,88)[i%6]
    rail=(2.0,3.0,3.6,5.2,9.0,12.5)[i%6]
    if kind==0:
        prompt=f"Próba T{idx}: usterka pojawia się przy {temp}°C w strefie {zone}. Sygnał przed stopniem pozostaje poprawny. Jak rozdzielisz VDD, stopień i połączenie?"
        model="usterka jest termicznie lokalna, ale nadal trzeba rozdzielić lokalne zasilanie, aktywny stopień oraz połączenie"
        test="rejestruj równolegle lokalne VDD oraz wejście i wyjście stopnia podczas kontrolowanego ogrzewania i chłodzenia"
        pred="jeśli pierwsze odchyla się VDD, badaj zasilanie; jeśli VDD i wejście są stabilne, a odchyla się wyjście, zawęź stopień lub połączenie"
    elif kind==1:
        prompt=f"Próba T{idx}: selektywne chłodzenie {zone} przy {temp}°C przywraca działanie, lecz upstream nie reaguje na temperaturę."
        model="źródło objawu leży lokalnie w chłodzonej strefie, ale może dotyczyć jej zasilania, elementu lub interconnect"
        test="podczas powtarzalnego heat/cool obserwuj zasilanie strefy oraz sygnały przed i po podejrzanym stopniu"
        pred="jeśli zasilanie zmienia się razem z objawem, kierunek jest zasilaniowy; przy stabilnym zasilaniu i wejściu zmiana wyjścia wskazuje stopień lub interconnect"
    elif kind==2:
        prompt=f"Próba T{idx}: wejście drivera jest poprawne również na gorąco, ale wyjście słabnie przy {temp}°C; lokalne VDD nominalnie {rail:g} V."
        model="należy rozdzielić termiczny problem VDD drivera, samego drivera i obciążenia wyjściowego"
        test="mierz IN, VDD, OUT lub VGS oraz prąd obciążenia w tym samym przebiegu temperaturowym"
        pred="jeśli VDD spada, problem jest w zasilaniu; jeśli IN i VDD są stabilne, wzrost prądu przy spadku OUT wskazuje downstream, a brak wzrostu bardziej driver"
    elif kind==3:
        prompt=f"Próba T{idx}: wyjście analogowe dryfuje po nagrzaniu do {temp}°C, a Vref i wejście są dostępne równocześnie."
        model="dryft może wynikać z referencji, lokalnego stopnia analogowego albo jego połączenia"
        test="zapisuj Vref, wejście i wyjście stopnia równocześnie podczas narastania oraz opadania temperatury"
        pred="jeśli Vref dryfuje jako pierwsze, badaj referencję; jeśli Vref i wejście są stabilne, a dryfuje wyjście, zawęź lokalny stopień lub połączenie"
    elif kind==4:
        prompt=f"Próba T{idx}: po nagrzaniu {zone} do {temp}°C występuje chwilowa przerwa; delikatny docisk czasem zmienia objaw."
        model="trzeba rozdzielić połączenie termomechaniczne od elementu aktywnego w tej samej strefie"
        test="podczas heat/cool rejestruj spadek na podejrzanym połączeniu oraz wejście i wyjście stopnia bez przemieszczania sond"
        pred="jeśli skok spadku na połączeniu pojawia się przed utratą funkcji, kierunek jest interconnect; jeśli połączenie jest stabilne, a zmienia się wyjście przy stabilnym wejściu, kierunek jest aktywny stopień"
    else:
        prompt=f"Próba T{idx}: lokalny regulator {rail:g} V traci funkcję downstream dopiero przy {temp}°C; jego wejście i prąd obciążenia można mierzyć."
        model="należy rozdzielić upstream, termiczną niewydolność regulatora i przeciążenie downstream"
        test="rejestruj jednocześnie wejście regulatora, wyjście i prąd downstream podczas przechodzenia przez temperaturę objawu"
        pred="jeśli spada wejście, problem jest upstream; jeśli wejście jest stabilne i wyjście spada bez wzrostu prądu, podejrzewaj regulator, a wzrost prądu wskazuje downstream"
    return eval_record(f"{prefix}-THM-{idx}","thermal_intermittent",
                       prompt,model,test,pred,False)

def insufficient_eval(i,prefix,offset):
    idx=offset+i
    prompt=f"Próba T{idx}: wiadomo tylko, że objaw zależy od temperatury; brak równoczesnych pomiarów zasilania, wejścia i wyjścia w chwili awarii."
    return eval_record(f"{prefix}-UNK-{idx}","insufficient_data",prompt,
      "dane są niewystarczające do rozdzielenia hipotez termicznych",
      "zarejestruj równocześnie lokalne zasilanie, wejście i wyjście podczas kontrolowanego heat/cool",
      "dopiero kolejność pierwszej zmiany pozwoli rozdzielić zasilanie, stopień i połączenie",True)

def dev_rows():
    thermal=[thermal_eval(i,"P59-DEV",5000) for i in range(24)]
    unknown=[insufficient_eval(i,"P59-DEV",5900) for i in range(4)]
    return thermal+unknown

def mini_rows(dev):
    thermal=[r for r in dev if r["category"]=="thermal_intermittent"][::2]
    unknown=[r for r in dev if r["category"]=="insufficient_data"][::2]
    return thermal+unknown
def writej(path,rows):
    path.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))

def main():
    locks=((P58_DEV,P58_DEV_SHA,"p58_dev"),(P58_FINAL,P58_FINAL_SHA,"p58_final"),
           (P57_FINAL,P57_FINAL_SHA,"p57_final"),(P55,P55_SHA,"p55"))
    for path,expected,name in locks:
        if sha(path)!=expected:
            raise SystemExit(f"P59=BLOCKED {name}_drift")

    train=training_rows(); dev=dev_rows(); mini=mini_rows(dev)
    old_prompts={r.get("prompt","") for p in (P58_DEV,P58_FINAL,P57_FINAL,P55) for r in load(p)}
    if any(r["user"] in old_prompts for r in train):
        raise SystemExit("P59=FAIL training_overlap_revealed_or_final")
    t={r["user"] for r in train}; d={r["prompt"] for r in dev}
    if t & d:
        raise SystemExit("P59=FAIL train_dev_overlap")

    files={"train":DIR/"p59_thermal_train.jsonl",
           "dev":DIR/"p59_thermal_dev_v1.jsonl",
           "mini":DIR/"p59_thermal_mini_dev_v1.jsonl"}
    writej(files["train"],train); writej(files["dev"],dev); writej(files["mini"],mini)
    manifest={
      "schema_version":1,"pipeline_id":"P5.9-thermal-causal-v1",
      "parent_adapter":"/srv/ai-data/training/p5/checkpoints/p58-p58-seed1-20261001/step-008",
      "train_records":len(train),"dev_records":len(dev),"mini_dev_records":len(mini),
      "thermal_train_records":sum(r["metadata"]["category"]=="thermal_intermittent" for r in train),
      "checkpoint_interval":8,"max_checkpoints":4,"early_stop_patience":2,
      "lr":0.0000003,
      "selection_focus":"thermal predicted_result first; preserve diagnostic/measurement/no_guessing",
      "p58_dev_role":"revealed regression and prefinal gate only",
      "p58_final_role":"sealed final; never used for training, selection, threshold tuning, or early stopping",
      "p58_final_sha256":P58_FINAL_SHA,
      "train_sha256":sha(files["train"]),"dev_sha256":sha(files["dev"]),
      "mini_dev_sha256":sha(files["mini"])
    }
    (DIR/"p59_manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print("P59_DATA=PASS")
    print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
