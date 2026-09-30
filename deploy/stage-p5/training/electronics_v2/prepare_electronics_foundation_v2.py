#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
V1_DIR = ROOT / "deploy/stage-p5/training/electronics"
SYSTEM=(
 "Jesteś inżynierem elektroniki uczącym rozumowania od pierwszych zasad. "
 "Nie zgaduj części ani numerów układów. Oddziel dane od założeń, nazwij model fizyczny, "
 "wyprowadź konsekwencje i wskaż pomiar rozdzielający. Odpowiadaj: "
 "DANE; MODEL/PRAWO; WNIOSKOWANIE; POMIAR/KONTROLA; ODPOWIEDŹ; PEWNOŚĆ."
)

TRAIN=[
("ac_impedance","Kondensator i rezystor tworzą obciążenie AC; napięcie i prąd nie są w fazie.","Impedancja zespolona zależy od częstotliwości: Z_R=R, Z_C=1/(jωC), Z_L=jωL.","Trzeba policzyć moduł i fazę impedancji, a nie stosować tylko rezystancję DC.","Zmierz amplitudę i przesunięcie fazowe napięcia oraz prądu przy kilku częstotliwościach.","W AC o zachowaniu decyduje impedancja i faza, nie sama rezystancja omowa."),
("rlc_resonance","W szeregowym RLC prąd gwałtownie rośnie przy jednej częstotliwości.","Rezonans występuje w pobliżu f0=1/(2π√LC), gdy reaktancje L i C się znoszą.","W rezonansie impedancję ogranicza głównie R, a napięcia na L/C mogą być większe od napięcia źródła.","Przemiataj częstotliwość i mierz prąd oraz fazę; porównaj z obliczonym f0.","Pik prądu i zmiana fazy w pobliżu f0 są naturalnym skutkiem rezonansu."),
("q_factor","Obwód rezonansowy ma bardzo wąski pik odpowiedzi.","Dobroć Q opisuje stosunek energii magazynowanej do traconej i wiąże się z szerokością pasma.","Mniejsze straty dają większe Q, węższy rezonans i większą wrażliwość na tolerancje.","Zmierz f0 i szerokość pasma przy -3 dB, potem oszacuj Q=f0/BW.","Wąski pik nie musi oznaczać niestabilności; może wynikać z wysokiej dobroci."),
("capacitive_coupling","Szybki sygnał na jednej ścieżce pojawia się jako krótki impuls na sąsiedniej.","Prąd pojemnościowy i=C·dv/dt; sprzężenie rośnie z pojemnością wzajemną i szybkością zbocza.","Krótki glitch może pochodzić ze sprzężenia pojemnościowego mimo braku połączenia DC.","Porównaj glitch z dv/dt agresora, zwiększ odstęp lub dodaj ekran/zmień impedancję ofiary.","Korelacja z szybkim zboczem wskazuje sprzężenie pojemnościowe, nie zwarcie DC."),
("inductive_coupling","Pętla sygnałowa zbiera zakłócenie podczas przełączania dużego prądu obok.","Indukowane napięcie zależy od wzajemnej indukcyjności i di/dt.","Duża powierzchnia pętli i szybka zmiana prądu zwiększają zakłócenie magnetyczne.","Zmniejsz pętlę, zmień orientację lub odległość i obserwuj zmianę amplitudy zakłócenia.","Zmiana zakłócenia wraz z geometrią pętli wskazuje sprzężenie indukcyjne."),
("transformer_ratio","Transformator daje inne napięcie wtórne niż oczekiwane z samego przełożenia.","Idealnie V2/V1=N2/N1, ale rzeczywisty wynik zależy od obciążenia, rezystancji uzwojeń i strumienia.","Najpierw rozdziel błąd przełożenia od spadków pod obciążeniem i nasycenia rdzenia.","Zmierz napięcia bez obciążenia i pod znanym obciążeniem oraz prąd pierwotny.","Poprawne napięcie jałowe z zapadem pod obciążeniem wskazuje straty/impedancję, nie złe przełożenie."),
("transformer_saturation","Prąd pierwotny transformatora rośnie gwałtownie po zwiększeniu czasu impulsu.","Strumień zależy od całki napięcia w czasie; przekroczenie zdolności rdzenia prowadzi do nasycenia i spadku indukcyjności.","Po nasyceniu prąd rośnie szybko mimo niewielkiej zmiany sterowania.","Mierz prąd pierwotny i napięcie przy zmianie duty/czasu impulsu; szukaj załamania nachylenia prądu.","Gwałtowny wzrost prądu po określonym volt-seconds jest charakterystyczny dla nasycenia."),
("optocoupler_ctr","Optoizolator działa przy małym prądzie LED, ale zawodzi przy temperaturze lub większym obciążeniu wyjścia.","CTR=Ic/If ma rozrzut i zależy od prądu, temperatury oraz starzenia.","Układ może działać nominalnie, ale nie mieć zapasu prądowego na wyjściu fototranzystora.","Zmierz If, Ic i napięcie kolektora w najgorszej temperaturze i przy wymaganym pull-up.","Trzeba projektować z minimalnym gwarantowanym CTR i zapasem, nie z typową wartością."),
("zener_shunt","Prosty stabilizator z diodą Zenera daje poprawne napięcie bez obciążenia, ale spada pod obciążeniem.","Rezystor szeregowy musi dostarczyć sumę prądu Zenera i obciążenia; Zener stabilizuje tylko przy wystarczającym Iz.","Gdy obciążenie zabiera prąd, Zener może wypaść z obszaru stabilizacji.","Zmierz prąd przez rezystor, prąd obciążenia i oszacuj pozostały prąd Zenera.","Spadek napięcia przy obciążeniu często oznacza za mały zapas prądu, nie uszkodzoną Zenerkę."),
("constant_current_source","Źródło prądowe utrzymuje prąd tylko w części zakresu napięcia obciążenia.","Każde źródło prądowe ma wymagany compliance voltage i ograniczenia mocy.","Po wyjściu poza zakres napięciowy element regulacyjny nie może utrzymać zadanej wartości prądu.","Zmieniaj napięcie obciążenia i obserwuj prąd oraz napięcie na elemencie regulacyjnym.","Stały prąd jest możliwy tylko w zakresie compliance i SOA."),
("current_mirror","Dwa tranzystory lustra prądowego nie dają identycznych prądów.","Proste lustro zależy od dopasowania VBE, temperatury, β i efektu Early'ego.","Różnica prądów może być naturalnym błędem topologii lub wynikiem gradientu temperatury.","Zmierz VBE obu tranzystorów, napięcia kolektorów i temperaturę; wyrównaj warunki.","Lustro nie jest idealnym kopiowaniem; wymaga zgodnych warunków i zapasu napięcia."),
("mosfet_gate_charge","MOSFET ma poprawne napięcie bramki, ale przełącza zbyt wolno przy dużym obciążeniu.","Driver musi dostarczyć ładunek Qg; czas przełączenia zależy od dostępnego prądu gate.","Sama amplituda VGS nie mówi, jak szybko driver ładuje pojemności bramki.","Zmierz przebieg VGS, prąd drivera lub spadek na gate resistor i czas zbocza.","Za wolne przełączanie może wynikać z niedostatecznego prądu bramki mimo poprawnego końcowego VGS."),
("miller_plateau","Na przebiegu VGS widać płaski odcinek podczas zmiany VDS.","Ładunek Millera Cgd jest pobierany podczas zmiany napięcia drain, co tworzy plateau bramki.","Długość plateau zależy od prądu drivera, Qgd i szybkości zmiany VDS.","Mierz VGS i VDS jednocześnie; porównaj czas plateau z prądem bramki.","Plateau Millera jest normalną częścią przełączania MOSFET-a i wpływa na straty dynamiczne."),
("switching_losses","MOSFET ma małe Rds(on), ale silnie grzeje się przy wysokiej częstotliwości PWM.","Straty obejmują przewodzenie oraz energię nakładania się VDS i ID podczas przejść.","Przy wysokiej częstotliwości straty przełączania mogą dominować nad I²R.","Zmierz VDS i ID w czasie przejść, oszacuj energię na cykl i pomnóż przez częstotliwość.","Niskie Rds(on) nie gwarantuje małych strat, jeśli przełączanie jest wolne lub częste."),
("snubber_rc","Na nodzie przełączającym występuje silne ringing po każdym zboczu.","Pasożytnicze L i C tworzą rezonans; snubber RC może tłumić energię oscylacji.","Trzeba najpierw zidentyfikować częstotliwość i źródło rezonansu, a nie dobierać RC losowo.","Zmierz częstotliwość ringingu krótką sondą, zmień C testowo i obserwuj zmianę częstotliwości/tłumienia.","Skuteczny snubber ogranicza ringing kosztem dodatkowych strat."),
("rcd_clamp","Element mocy ma przepięcie związane z energią indukcyjności rozproszenia.","RCD clamp przechwytuje energię do kondensatora i rozprasza ją przez rezystor.","Napięcie clamp zależy od energii impulsu, C, R i częstotliwości powtarzania.","Mierz szczyt napięcia, temperaturę rezystora i napięcie kondensatora clamp.","Clamp musi ograniczać pik i jednocześnie bezpiecznie rozpraszać średnią energię."),
("mosfet_soa","MOSFET przeżywa krótkie impulsy, ale uszkadza się przy wolnym przejściu liniowym.","SOA ogranicza jednoczesne napięcie, prąd i czas trwania; Rds(on) nie opisuje pracy liniowej.","Duże VDS i ID przez dłuższy czas mogą przekroczyć lokalną temperaturę struktury.","Nanieś punkt VDS-ID-czas na SOA lub oszacuj energię i temperaturę impulsową.","Dobór MOSFET-a do pracy liniowej wymaga SOA, nie tylko prądu znamionowego."),
("thermal_resistance","Układ ma znaną moc strat, ale temperatura obudowy wydaje się zbyt wysoka.","Przybliżenie ΔT=P·θ opisuje przepływ cieplny dla określonej ścieżki i warunków.","Trzeba rozróżnić θJA, θJC i wpływ PCB/radiatora; temperatura otoczenia jest punktem odniesienia.","Zmierz moc, temperaturę obudowy/PCB i warunki chłodzenia; porównaj z oczekiwanym ΔT.","Temperatura wynika z mocy i całkowitej rezystancji cieplnej ścieżki."),
("thermal_runaway","Prąd elementu rośnie wraz z temperaturą i nagrzewanie przyspiesza.","Dodatnie sprzężenie cieplne występuje, gdy wzrost temperatury zwiększa moc strat.","Stabilność wymaga ujemnego sprzężenia lub ograniczenia prądu/temperatury.","Podgrzewaj kontrolowanie i rejestruj prąd, napięcie oraz temperaturę, zatrzymując test przed przekroczeniem limitu.","Przyspieszający wzrost prądu z temperaturą wskazuje ryzyko runaway."),
("inrush_current","Duży kondensator wejściowy powoduje krótki bardzo duży prąd przy podłączeniu zasilania.","I=C·dv/dt, a energia 1/2CV² musi zostać dostarczona podczas ładowania.","Mała impedancja źródła i szybkie zbocze napięcia dają duży inrush.","Mierz prąd i napięcie wejściowe w czasie; porównaj z precharge/NTC/soft-start.","Ograniczenie szybkości ładowania lub rezystancji wstępnej zmniejsza inrush."),
("efuse_current_limit","Elektroniczny bezpiecznik obniża napięcie wyjściowe przy przeciążeniu zamiast natychmiast się wyłączyć.","eFuse może stosować current-limit, foldback lub retry; zachowanie zależy od trybu ochrony.","Spadek Vout może być kontrolowaną ochroną, nie awarią regulatora.","Mierz Iout, Vout i czas; sprawdź czy prąd zatrzymuje się na stałym limicie lub maleje w foldback.","Kształt ograniczenia prądu pozwala rozpoznać tryb ochrony."),
("reverse_polarity_mosfet","MOSFET ochrony odwrotnej polaryzacji ma mały spadek w poprawnym kierunku, ale blokuje odwrotne zasilanie.","Po odpowiednim sterowaniu MOSFET zachowuje się jak idealna dioda o małym spadku, a body diode ustala warunki startowe.","Trzeba analizować orientację body diode i VGS dla obu polaryzacji.","Zmierz VGS, VDS i prąd dla poprawnej oraz odwrotnej polaryzacji przy ograniczeniu prądowym.","Poprawne działanie ochrony wynika z orientacji MOSFET-a i sterowania bramki."),
("logic_thresholds","Wyjście 3,3 V steruje wejście 5 V, które czasem interpretuje stan błędnie.","Poziomy logiczne muszą spełniać gwarantowane VIH/VIL, a nie tylko wyglądać na HIGH/LOW.","Margines napięcia może być zbyt mały przy tolerancjach, temperaturze lub szumie.","Zmierz poziomy na pinie odbiornika i porównaj z gwarantowanymi progami oraz marginesem szumu.","Zgodność napięcia nominalnego nie wystarcza; liczą się gwarantowane progi logiczne."),
("level_shifter","Dwukierunkowy translator poziomów działa w jedną stronę, ale nie w drugą.","Topologia level-shiftera musi pasować do typu wyjść, kierunku i napięć pull-up.","Układ dla open-drain zachowuje się inaczej niż translator push-pull.","Sprawdź typ nadajników, pull-up po obu stronach i przebiegi podczas transmisji w obu kierunkach.","Najpierw dopasuj topologię translatora do elektrycznego typu interfejsu."),
("adc_sample_hold","ADC z wejściem o dużej rezystancji źródła zaniża wynik przy szybkim próbkowaniu.","Kondensator sample-and-hold musi naładować się przez impedancję źródła w czasie akwizycji.","Za duże Rsource lub za krótki acquisition time powodują niepełne ustalenie napięcia.","Zwiększ czas akwizycji, zmniejsz Rsource lub dodaj bufor i porównaj wynik.","Błąd może pochodzić z dynamiki wejścia ADC, mimo poprawnego napięcia DC na DMM."),
("reference_noise","Kilka kanałów ADC jednocześnie wykazuje skorelowany szum.","Kod ADC jest proporcjonalny do Vin/Vref; szum referencji może pojawić się na wielu kanałach równocześnie.","Wspólny wzorzec między kanałami sugeruje wspólne Vref lub masę, nie niezależne czujniki.","Mierz Vref i masę ADC oscyloskopem równolegle z kodami kilku kanałów.","Skorelowane błędy wielu kanałów kierują do wspólnej referencji lub zasilania."),
("four_wire_measurement","Pomiar bardzo małej rezystancji przewodów jest zdominowany przez przewody pomiarowe.","Metoda Kelvin 4-wire rozdziela tor prądowy od pomiaru napięcia, eliminując większość rezystancji przewodów.","Dla miliomów dwuprzewodowy pomiar może mieć błąd większy od badanego elementu.","Wymuś znany prąd i mierz napięcie osobnymi przewodami bezpośrednio na badanym punkcie.","Do małych rezystancji użyj pomiaru czteroprzewodowego lub spadku pod znanym prądem."),
("return_current_path","Szybki sygnał cyfrowy ma dobrą ścieżkę sygnałową, ale emituje i dzwoni po przerwaniu płaszczyzny masy.","Prąd powrotny wysokiej częstotliwości płynie drogą minimalnej impedancji blisko ścieżki sygnału.","Szczelina w płaszczyźnie zmusza powrót do dużej pętli, zwiększając EMI i indukcyjność.","Śledź geometrię powrotu, porównaj przebieg przed/po zapewnieniu ciągłej referencji.","Integralność sygnału zależy od pełnej pętli prądowej, nie tylko od ścieżki sygnałowej."),
("transmission_line_reflection","Szybkie zbocze na długiej ścieżce powoduje overshoot i wielokrotne odbicia.","Gdy czas propagacji jest istotny wobec czasu zbocza, ścieżka zachowuje się jak linia transmisyjna o impedancji charakterystycznej.","Niedopasowanie źródła/obciążenia powoduje odbicia nawet przy niskiej częstotliwości powtarzania.","Zmierz przebieg na początku i końcu linii, zmień terminację lub spowolnij zbocze.","Problem wynika z czasu zbocza i impedancji, nie tylko z częstotliwości sygnału."),
("emi_common_mode","Zakłócenie pojawia się podobnie na obu przewodach pary względem masy.","Common-mode oznacza składową wspólną obu przewodów; differential-mode jest różnicą między nimi.","Filtr skuteczny dla różnicowej składowej może nie tłumić common-mode.","Mierz oba przewody względem odniesienia oraz różnicowo; sprawdź efekt dławika common-mode.","Najpierw sklasyfikuj tryb zakłócenia, potem dobierz filtr."),
("ground_loop","Dwa urządzenia połączone sygnałem mają różne potencjały masy i przez ekran płynie prąd.","Wielopunktowe połączenia mas mogą utworzyć pętlę zbierającą pole lub przenoszącą prądy wyrównawcze.","Błąd sygnału może pochodzić z prądu masy, a nie z samego nadajnika.","Zmierz różnicę potencjałów mas i prąd/napięcie na ekranie; porównaj po zmianie topologii uziemienia.","Pętla masy jest problemem topologii powrotu i odniesienia."),
]

HOLDOUT=[
("charge_pump","Driver high-side po kilku sekundach traci możliwość utrzymania bramki powyżej source.","Charge pump przenosi ładunek cyklicznie, a jego wydajność zależy od częstotliwości, kondensatorów i obciążenia.","Spadek może wynikać z niedostatecznego transferu ładunku lub upływu.","Zmierz napięcie pompy bez obciążenia i pod gate-load, przebiegi sterujące oraz kondensatory.","Trzeba rozdzielić brak sterowania od niewystarczającej wydajności pompy ładunkowej."),
("instrumentation_amp","Mały sygnał różnicowy na wysokim common-mode daje błędny wynik mimo poprawnego gain.","Wzmacniacz instrumentalny ma ograniczony zakres common-mode zależny od zasilania i wzmocnienia.","Układ może wyjść poza dozwolony zakres wejść lub wyjścia mimo małej różnicy.","Sprawdź oba napięcia wejściowe względem szyn i wymagany Vout dla ustawionego gain.","Poprawne rezystory nie gwarantują pracy, jeśli naruszony jest zakres common-mode/output."),
("tia_photodiode","Fotodioda z transimpedance amplifier oscyluje po zwiększeniu rezystora feedback.","Pojemność fotodiody i wzmacniacza wraz z feedbackiem wpływa na stabilność i noise gain.","Większy gain prąd-napięcie może zmniejszyć margines fazy.","Obserwuj odpowiedź impulsową, ringing i wpływ kondensatora równoległego do Rf.","Stabilność TIA wymaga uwzględnienia pojemności wejściowej, nie tylko Rf."),
("crystal_startup","MCU nie startuje, a na pinach kwarcu widać tylko mały zaszumiony sygnał.","Oscylator Pierce wymaga ujemnej rezystancji i odpowiednich pojemności obciążenia; pomiar sondą może sam go obciążyć.","Brak oscylacji może wynikać z elementów, layoutu, uszkodzenia układu lub sondy o zbyt dużej pojemności.","Użyj sondy o małej pojemności, sprawdź zasilanie/reset oraz komponenty i spróbuj źródła zegara zastępczego jeśli bezpieczne.","Diagnostyka kwarcu wymaga uwzględnienia wpływu samego pomiaru."),
("dac_settling","DAC osiąga poprawną wartość końcową, ale po zmianie kodu potrzebuje zbyt długo na ustalenie.","Settling time obejmuje slew, dynamikę wzmacniacza wyjściowego i obciążenie pojemnościowe.","Poprawna wartość DC nie gwarantuje poprawnej odpowiedzi czasowej.","Zadaj skok kodu, mierz czas wejścia w pasmo błędu i porównaj dla różnych obciążeń.","Problem jest dynamiczny i wymaga pomiaru settling, nie tylko wartości końcowej."),
("stub_reflection","Krótki odgałęziony stub na szybkiej magistrali powoduje lokalne dzwonienie.","Stub jest odcinkiem linii transmisyjnej, który odbija energię zależnie od długości elektrycznej i zakończenia.","Nawet nieaktywny odbiornik może pogarszać integralność sygnału przez samą geometrię odgałęzienia.","Porównaj przebieg po skróceniu/odłączeniu stubu lub spowolnieniu zbocza.","Długość odgałęzienia względem czasu zbocza może być krytyczna."),
("foldback_power","Zasilacz przy zwarciu ogranicza prąd do wartości mniejszej niż przy normalnym przeciążeniu.","Foldback celowo zmniejsza limit prądu wraz ze spadkiem Vout, ograniczając moc elementu regulacyjnego.","Niższy prąd przy głębszym zwarciu może być prawidłową ochroną.","Zmieniaj obciążenie i wykreśl Iout względem Vout, obserwując przejście do foldback.","Charakterystyka I-V pozwala odróżnić foldback od zwykłego stałego limitu."),
("common_mode_choke","Dławik common-mode tłumi zakłócenie pary przewodów, ale prawie nie wpływa na sygnał różnicowy.","Strumienie od prądów różnicowych znoszą się, a common-mode sumują w rdzeniu.","Dławik może mieć wysoką impedancję dla common-mode i małą dla użytecznego differential-mode.","Zmierz zakłócenie common-mode i różnicowe przed/za dławikiem oraz temperaturę przy prądzie roboczym.","Skuteczność zależy od trybu zakłócenia i właściwości rdzenia."),
]

Q=[
"Przeanalizuj od pierwszych zasad sytuację: {s}",
"W układzie obserwuję: {s} Jak rozdzielić możliwe przyczyny?",
"Jakiego modelu fizycznego użyć, gdy {s}",
"Jaki pomiar ma największą wartość diagnostyczną, jeśli {s}",
"Wyjaśnij krok po kroku, co wynika z sytuacji: {s}",
]

def answer(f):
    return (
        f"DANE: {f[1]}\nMODEL/PRAWO: {f[2]}\nWNIOSKOWANIE: {f[3]}\n"
        f"POMIAR/KONTROLA: {f[4]}\nODPOWIEDŹ: {f[5]}\nPEWNOŚĆ: Wysoka co do metody; "
        "pewność co do konkretnego elementu zależy od wyniku pomiaru."
    )

def norm(s):
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9ąćęłńóśźż]+"," ",s.lower())).strip()

def shingles(s,n=8):
    w=norm(s).split()
    return {tuple(w[i:i+n]) for i in range(max(0,len(w)-n+1))}

def load(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def build(families,split):
    out=[]; idx=1
    templates=Q if split=="train" else Q[:3]
    for f in families:
        for t in templates:
            out.append({
                "record_id":f"ELEC2-{split.upper()}-{idx:04d}",
                "system":SYSTEM,
                "user":t.format(s=f[1]),
                "assistant":answer(f),
                "metadata":{
                    "schema_version":2,"language":"pl","category":f[0],
                    "training_eligible":split=="train","split":split,
                    "source_kind":"project_owned_derived_electronics_principles",
                    "source_policy":"first_principles_no_external_text_copy",
                    "curriculum":"electronics-foundation-v2",
                }
            }); idx+=1
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out-dir",default=str(ROOT/"deploy/stage-p5/training/electronics_v2"))
    args=ap.parse_args()
    outdir=Path(args.out_dir); outdir.mkdir(parents=True,exist_ok=True)
    train=build(TRAIN,"train"); hold=build(HOLDOUT,"holdout")
    v1=load(V1_DIR/"electronics_foundation_train_v1.jsonl")+load(V1_DIR/"electronics_foundation_holdout_v1.jsonl")
    v1_text=[r["user"]+" "+r["assistant"] for r in v1]
    v1_norm={norm(x) for x in v1_text}; v1_sh=[shingles(x) for x in v1_text]
    for label,rows in (("train",train),("holdout",hold)):
        texts=[norm(r["user"]+" "+r["assistant"]) for r in rows]
        if len(texts)!=len(set(texts)): raise SystemExit(f"P5_3_DATASET=FAIL {label}_duplicate")
        for r in rows:
            txt=norm(r["user"]+" "+r["assistant"])
            if txt in v1_norm: raise SystemExit(f"P5_3_DATASET=FAIL v1_exact_overlap:{r['record_id']}")
            sh=shingles(r["user"]+" "+r["assistant"])
            best=max((len(sh&old)/max(1,len(sh|old)) for old in v1_sh),default=0)
            if best>=0.72: raise SystemExit(f"P5_3_DATASET=FAIL v1_shingle_overlap:{r['record_id']}:{best:.3f}")
    tn={norm(r["user"]+" "+r["assistant"]) for r in train}; hn={norm(r["user"]+" "+r["assistant"]) for r in hold}
    if tn&hn: raise SystemExit("P5_3_DATASET=FAIL train_holdout_overlap")
    tp=outdir/"electronics_foundation_v2_train.jsonl"; hp=outdir/"electronics_foundation_v2_holdout.jsonl"
    tp.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in train))
    hp.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in hold))
    manifest={
        "schema_version":2,"dataset_id":"electronics-foundation-v2",
        "train_records":len(train),"holdout_records":len(hold),
        "train_categories":len(TRAIN),"holdout_categories":len(HOLDOUT),
        "v1_records_checked":len(v1),"external_text_copied":False,
        "oem_material_used":False,"automotive_golden_used":False,
        "train_sha256":sha(tp),"holdout_sha256":sha(hp),
        "base_adapter":"electronics-foundation-v1/r1",
    }
    (outdir/"electronics_foundation_v2.manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("P5_3_ELECTRONICS_V2_DATASET_GATE=PASS")
    print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
