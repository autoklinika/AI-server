#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, random, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
SEED=20260929
SYSTEM=(
 "Jesteś inżynierem elektroniki uczącym rozumowania od pierwszych zasad. "
 "Nie zgaduj. Najpierw nazwij znane dane i model obwodu, potem zastosuj prawo fizyczne, "
 "wyprowadź wniosek, zaproponuj pomiar rozstrzygający jeśli dane są niepełne i na końcu podaj odpowiedź. "
 "Używaj struktury: DANE; MODEL/PRAWO; WNIOSKOWANIE; POMIAR/KONTROLA; ODPOWIEDŹ; PEWNOŚĆ."
)

def rec(rid, category, user, body, concepts, *, split="train"):
    return {
      "record_id":rid,
      "system":SYSTEM,
      "user":user,
      "assistant":body,
      "metadata":{
        "schema_version":1,
        "language":"pl",
        "category":category,
        "training_eligible":split=="train",
        "split":split,
        "source_kind":"project_owned_derived_electronics_principles",
        "source_policy":"first_principles_no_external_text_copy",
        "required_concepts":concepts,
      },
    }

def ans(data, law, reasoning, check, answer, confidence="Wysoka."):
    return (
      f"DANE: {data}\nMODEL/PRAWO: {law}\nWNIOSKOWANIE: {reasoning}\n"
      f"POMIAR/KONTROLA: {check}\nODPOWIEDŹ: {answer}\nPEWNOŚĆ: {confidence}"
    )

def ohm_records(split, start, count):
    out=[]
    for i in range(count):
        r=[47,68,100,150,220,330,470,680,1000][i%9]
        v=[3.3,5,9,12,15,24][(i*2+1)%6]
        current=v/r
        power=v*current
        q=f"Rezystor {r} Ω jest podłączony do {v:g} V. Jaki prąd płynie i ile mocy wydziela się w rezystorze?"
        b=ans(
          f"R={r} Ω, U={v:g} V.",
          "Prawo Ohma I=U/R oraz P=U·I=U²/R.",
          f"I={v:g}/{r}={current:.6f} A. P={v:g}·{current:.6f}={power:.4f} W.",
          "W praktyce sprawdzić tolerancję rezystora, temperaturę i czy źródło utrzymuje napięcie pod obciążeniem.",
          f"Prąd ≈ {current*1000:.2f} mA, moc ≈ {power:.3f} W.",
        )
        out.append(rec(f"ELEC-{split.upper()}-{start+i:04d}","ohms_law",q,b,["I=U/R","P=U*I"],split=split))
    return out

def divider_records(split,start,count):
    out=[]
    vals=[(10000,10000,5),(4700,10000,5),(22000,6800,12),(3300,6800,3.3),(100000,22000,12)]
    for i in range(count):
        r1,r2,vin=vals[i%len(vals)]
        vout=vin*r2/(r1+r2)
        q=f"Dzielnik ma R1={r1} Ω od {vin:g} V do węzła i R2={r2} Ω do masy. Jakie napięcie oczekujesz bez obciążenia?"
        b=ans(
          f"Vin={vin:g} V, R1={r1} Ω, R2={r2} Ω, wyjście nieobciążone.",
          "Dzielnik napięcia: Vout=Vin·R2/(R1+R2).",
          f"Vout={vin:g}·{r2}/({r1}+{r2})={vout:.4f} V.",
          "Pomiar DMM powinien mieć impedancję dużo większą od R1||R2; inaczej sam miernik obciąży dzielnik.",
          f"Oczekiwane Vout ≈ {vout:.3f} V.",
        )
        out.append(rec(f"ELEC-{split.upper()}-{start+i:04d}","voltage_divider",q,b,["voltage divider","loading"],split=split))
    return out

def rc_records(split,start,count):
    out=[]
    vals=[(1000,1e-6),(4700,10e-6),(10000,1e-6),(22000,4.7e-6),(47000,2.2e-6)]
    for i in range(count):
        r,c=vals[i%len(vals)]
        tau=r*c
        q=f"Obwód RC ma R={r} Ω i C={c*1e6:g} µF. Jaka jest stała czasowa i co oznacza?"
        b=ans(
          f"R={r} Ω, C={c*1e6:g} µF.",
          "Dla pierwszego rzędu τ=R·C; po 1τ odpowiedź skokowa osiąga ok. 63,2% zmiany, po ok. 5τ jest praktycznie ustalona.",
          f"τ={r}·{c:g}={tau:.6f} s.",
          "Na oscyloskopie zmierzyć czas dojścia do 63,2% końcowej zmiany i porównać z obliczeniem.",
          f"τ ≈ {tau*1000:.2f} ms; ~5τ ≈ {5*tau*1000:.2f} ms.",
        )
        out.append(rec(f"ELEC-{split.upper()}-{start+i:04d}","rc_time_constant",q,b,["tau=RC","63.2%","5 tau"],split=split))
    return out

def generic_family(start, split, category, qs, facts, law, reasoning, check, answer, concepts):
    return [
      rec(f"ELEC-{split.upper()}-{start+i:04d}",category,q,ans(facts,law,reasoning,check,answer),concepts,split=split)
      for i,q in enumerate(qs)
    ]

TRAIN_FAMILIES=[
("series_parallel",
["Dwa rezystory są połączone szeregowo. Jak przewidzieć prąd i spadki napięć zanim coś zmierzysz?",
 "W szeregu jeden rezystor zwiększył rezystancję. Jak zmienią się prąd i podział napięcia?",
 "Dwa rezystory równoległe mają różne wartości. Która gałąź pobierze większy prąd?",
 "Po zwarciu jednej gałęzi równoległej zasilacz wchodzi w ograniczenie. Jak to wyjaśnić?",
 "Pomiar rezystancji całego układu jest mniejszy niż najmniejszy rezystor. Kiedy to jest normalne?"],
"Znana jest topologia rezystancyjna, ale wynik zależy od połączenia.",
"Dla szeregu rezystancje się sumują i prąd jest wspólny; dla równoległego wspólne jest napięcie, a przewodności się sumują.",
"Najpierw zredukuj sieć do rezystancji zastępczej, potem użyj prawa Ohma i odtwórz prądy lub spadki w gałęziach.",
"Sprawdzić napięcia w węzłach i prądy gałęzi; w układzie bez zasilania upewnić się, że inne ścieżki nie fałszują omomierza.",
"Nie wolno interpretować rezystora bez uwzględnienia całej topologii połączeń.",["series","parallel","equivalent resistance"]),
("kcl_kvl",
["W węźle wpływa kilka prądów. Jak sprawdzić, czy pomiary są ze sobą zgodne?",
 "Suma spadków napięć w oczku nie zgadza się z zasilaniem. Co to oznacza diagnostycznie?",
 "Prąd wejściowy zasilacza jest większy niż suma dwóch zmierzonych gałęzi. Jak szukać brakującej ścieżki?",
 "Na rezystorach w oczku zmierzone spadki dają mniej niż napięcie źródła. Co sprawdzić?",
 "Jak wykorzystać KCL do znalezienia prądu upływu na płycie?"],
"Znamy część prądów lub spadków w sieci.",
"Pierwsze prawo Kirchhoffa: algebraiczna suma prądów w węźle wynosi zero. Drugie: algebraiczna suma napięć w zamkniętym oczku wynosi zero.",
"Niespełnienie bilansu wskazuje brakujący tor, błąd punktu odniesienia, błąd pomiaru albo zmienny stan obwodu.",
"Powtórzyć pomiary względem wspólnego odniesienia i policzyć bilans prądów lub napięć z uwzględnieniem znaków.",
"KCL/KVL są kontrolą spójności pomiarów i pomagają wykryć niewidoczną gałąź.",["KCL","KVL","measurement consistency"]),
("thevenin_source_impedance",
["Napięcie jest poprawne bez obciążenia, ale zapada po podłączeniu odbiornika. Jak to modelować?",
 "Źródło 5 V mierzy 5 V na DMM, lecz czujnik po podłączeniu dostaje 3 V. Co rozdziela przyczynę?",
 "Jak oszacować rezystancję wewnętrzną źródła z dwóch pomiarów napięcia?",
 "Linia pull-up jest wysoka bez obciążenia i niska po podłączeniu modułu. Co może z tego wynikać?",
 "Dlaczego pomiar napięcia bez obciążenia może ukryć skorodowane złącze?"],
"Źródło ma poprawne napięcie jałowe, ale zachowanie zmienia się pod obciążeniem.",
"Rzeczywiste źródło można lokalnie modelować jako idealne napięcie Thévenina z rezystancją szeregową.",
"Spadek pod znanym obciążeniem ujawnia impedancję źródła lub połączenia, której DMM bez obciążenia prawie nie obciąża.",
"Zmierz napięcie bez obciążenia i pod znanym bezpiecznym obciążeniem; z różnicy i prądu oblicz efektywną rezystancję szeregową.",
"Test pod obciążeniem rozdziela poprawne napięcie jałowe od zdolności źródła do dostarczenia prądu.",["Thevenin","source impedance","loaded voltage"]),
("pullup_pulldown",
["Wejście cyfrowe jest losowe po odłączeniu czujnika. Jaką rolę ma pull-up lub pull-down?",
 "Linia open-drain ma 0 V poprawnie, ale bardzo wolno wraca do HIGH. Co sprawdzić?",
 "Zmiana rezystora pull-up zmieniła czas zbocza. Dlaczego?",
 "Wejście jest zawsze HIGH mimo poprawnego tranzystora open-drain. Co zmierzyć?",
 "Czy silniejszy pull-up zawsze jest lepszy?"],
"Wejście wymaga określonego stanu, gdy aktywny nadajnik go nie wymusza.",
"Pull-up/pull-down ustala stan domyślny; wraz z pojemnością linii tworzy RC i wpływa na prąd w stanie przeciwnym.",
"Za duża rezystancja daje słabe i wolne podciąganie, za mała zwiększa prąd i obciążenie nadajnika.",
"Sprawdzić wartość rezystora, pojemność/zbocze oscyloskopem i napięcie przy aktywnym wymuszeniu LOW/HIGH.",
"Dobór pull-up/down jest kompromisem poziom logiczny–szybkość–prąd.",["pull-up","open drain","RC edge"]),
("diode_basic",
["Jak rozpoznać zwykłą diodę krzemową w trybie diode-test bez wylutowania?",
 "Dioda przewodzi w obu kierunkach na PCB. Czy na pewno jest zwarta?",
 "Dioda ma prawidłowy spadek w jedną stronę i OL w drugą. Co to mówi?",
 "Dlaczego pomiar diody na płycie może być mylący?",
 "Jak odróżnić zwarcie diody od równoległej ścieżki w układzie?"],
"Badamy nieliniowe złącze półprzewodnikowe w układzie, który może mieć równoległe drogi.",
"Złącze PN przewodzi głównie w kierunku przewodzenia; tryb diode-test podaje mały prąd i mierzy spadek.",
"Nietypowy wynik w obu kierunkach może pochodzić z samej diody lub z innego elementu równoległego.",
"Porównać oba kierunki, analogiczny kanał i w razie potrzeby odłączyć jedną końcówkę elementu.",
"Pomiar in-circuit jest wskazówką; izolacja elementu rozstrzyga, gdy istnieją ścieżki równoległe.",["diode test","PN junction","in circuit"]),
("clamp_tvs",
["Na wejściu jest TVS lub dioda clamp. Jak sprawdzić, czy zwarcie wejścia pochodzi właśnie z niej?",
 "Po przepięciu wejście ma niską rezystancję do masy. Jak lokalizować element ochronny?",
 "Dlaczego uszkodzony TVS często daje zwarcie zamiast przerwy?",
 "Jak bezpiecznie potwierdzić podejrzany clamp bez podawania pełnego napięcia?",
 "Po wylutowaniu TVS zwarcie znika. Jaki następny krok przed założeniem nowego?"],
"Tor wejściowy zawiera element ochronny, który może przejąć energię przepięcia.",
"Clamp/TVS ogranicza napięcie przez gwałtowny wzrost przewodzenia powyżej progu; awaria może pozostać zwarciowa.",
"Niska rezystancja po zdarzeniu może pochodzić z ochrony albo dalszej szyny, więc trzeba lokalizować sekcyjnie.",
"Zasilanie z ograniczeniem prądowym przy niskiej energii, termowizja/spadki oraz izolacja podejrzanego elementu.",
"Usunięcie zwarcia po izolacji TVS potwierdza lokalizację, ale trzeba sprawdzić, czy dalszy układ nie został również uszkodzony.",["TVS","clamp","current limit"]),
("bjt_switch",
["NPN ma sterować przekaźnikiem, ale kolektor pozostaje wysoki mimo napięcia na bazie. Co sprawdzić?",
 "Tranzystor BJT mocno się grzeje jako klucz. Jak sprawdzić, czy jest w nasyceniu?",
 "Na bazie NPN jest prawie tyle samo co na emiterze. Czy tranzystor powinien przewodzić?",
 "PNP high-side nie wyłącza się całkowicie. Jak analizować napięcia względem emitera?",
 "Jak odróżnić przerwę rezystora bazowego od uszkodzonego BJT?"],
"BJT pracuje jako sterowany prądem element; istotne są napięcia złączy i dostępny prąd bazy.",
"Dla krzemowego BJT złącze B-E musi być spolaryzowane w kierunku przewodzenia; jako klucz wymagany jest odpowiedni prąd bazy i małe VCE w nasyceniu.",
"Ocena względem absolutnej masy może mylić, szczególnie PNP; trzeba mierzyć VBE i VCE bezpośrednio.",
"Zmierz VBE, VCE i spadek na rezystorze bazowym podczas komendy; porównaj z prądem obciążenia.",
"Najpierw potwierdź sterowanie złączem i warunki nasycenia, dopiero potem oceniaj tranzystor.",["BJT","VBE","saturation"]),
("mosfet_low_side",
["N-MOSFET low-side ma 5 V na bramce względem masy, ale nie przewodzi. Co jeszcze trzeba znać?",
 "MOSFET low-side grzeje się przy dużym prądzie. Jak rozdzielić Rds(on) od złego sterowania bramki?",
 "Na bramce jest PWM, ale dren nie schodzi nisko. Jak diagnozować?",
 "MOSFET działa zimny, a po nagrzaniu spadek VDS rośnie. Co mierzyć?",
 "Czy napięcie gate mierzone względem masy zawsze wystarcza do oceny MOSFET-a?"],
"N-MOSFET przewodzi zależnie od VGS, prądu, temperatury i charakterystyki elementu.",
"Kluczowe jest napięcie gate-source, nie gate-ground; straty przewodzenia ~I²·Rds(on), a Rds(on) zależy od temperatury i VGS.",
"Poprawne logiczne HIGH nie gwarantuje pełnego otwarcia konkretnego MOSFET-a.",
"Mierzyć VGS i VDS pod obciążeniem oraz prąd; obliczyć P≈VDS·I i porównać w temperaturze zimnej/gorącej.",
"Ocena MOSFET-a wymaga napięć względem source oraz warunków prądowych.",["MOSFET","VGS","Rds_on","VDS"]),
("mosfet_high_side",
["P-MOSFET high-side ma source przy VBAT. Jak ocenić, czy bramka jest sterowana poprawnie?",
 "N-MOSFET high-side ma bramkę tylko kilka woltów ponad masą. Dlaczego może nie przewodzić?",
 "High-side działa przy niskim VBAT, ale nie przy wyższym. Co sprawdzić w driverze bramki?",
 "Na source high-side napięcie się zmienia, a gate wygląda stałe względem masy. Jak mierzyć poprawnie?",
 "Bootstrap high-side przestaje działać przy 100% duty. Jakie zjawisko trzeba uwzględnić?"],
"High-side ma ruchomy potencjał source, więc napięcie bramki trzeba odnosić do source.",
"MOSFET steruje się przez VGS; N-MOSFET high-side często wymaga gate powyżej source, realizowanego charge-pump lub bootstrapem.",
"Pomiar gate-ground może wyglądać poprawnie, a VGS być za małe lub zbyt duże.",
"Mierzyć różnicowo gate-source i drain-source w czasie, z zachowaniem bezpiecznego sposobu sondowania.",
"High-side diagnozuje się w układzie odniesienia source; architektura drivera ogranicza dostępne VGS i duty.",["high side","VGS","bootstrap"]),
("body_diode",
["MOSFET przewodzi w jednym kierunku mimo 0 V na bramce. Czy to od razu zwarcie kanału?",
 "W diode-test między drain i source jest spadek w jednym kierunku. Co może go powodować?",
 "Po odwróceniu polaryzacji obciążenie dostaje prąd przez MOSFET mimo wyłączenia. Dlaczego?",
 "Jak odróżnić body diode od zwartego MOSFET-a?",
 "W półmostku prąd płynie chwilowo przez drugi tranzystor po wyłączeniu. Jaką rolę ma body diode?"],
"MOSFET mocy zawiera pasożytniczą diodę body pomiędzy drain i source.",
"Body diode może przewodzić niezależnie od VGS w jednym kierunku; zwarcie kanału przewodziłoby zwykle niskoohmowo w obu kierunkach.",
"Sam jednokierunkowy spadek D-S przy wyłączonej bramce nie jest dowodem zwarcia.",
"Rozładować gate, wykonać pomiar obu kierunków i porównać z oczekiwaną orientacją body diode; wątpliwości rozstrzyga pomiar poza układem.",
"Trzeba odróżniać przewodzenie body diode od włączonego lub zwartego kanału.",["body diode","MOSFET off state"]),
("gate_resistor",
["Rezystor bramkowy MOSFET-a ma przerwę. Jakiego objawu spodziewać się na gate i drain?",
 "Po zmniejszeniu gate resistor pojawiły się oscylacje. Dlaczego?",
 "MOSFET przełącza bardzo wolno mimo poprawnego drivera. Co sprawdzić w torze bramki?",
 "Jeden kanał półmostka ma inne zbocza bramki niż drugi. Jak wykorzystać porównanie?",
 "Rezystor gate ma poprawną wartość statycznie, ale lut pęka po nagrzaniu. Jak to złapać?"],
"Bramka MOSFET-a jest pojemnościowa, a rezystor bramkowy wraz z impedancją drivera kontroluje prąd ładowania i szybkość zbocza.",
"Za duża impedancja spowalnia przełączanie i zwiększa straty, za mała może zwiększyć dzwonienia/EMI i przeciążyć driver.",
"Przerwa lub wzrost rezystancji może zostawić gate na nieokreślonym potencjale albo powodować bardzo wolne zbocza.",
"Oscyloskopem porównać VGS, czas narastania/opadania i sygnał przed/za rezystorem.",
"Tor bramki ocenia się dynamicznie, nie tylko omomierzem.",["gate charge","gate resistor","switching edge"]),
("halfbridge_deadtime",
["W półmostku oba MOSFET-y grzeją się mimo małego obciążenia. Co sprawdzić w sterowaniu?",
 "Na przejściach PWM zasilacz pokazuje krótkie piki prądu. Jak podejrzewać shoot-through?",
 "Jaką rolę ma dead-time w półmostku?",
 "Po zmianie drivera bramki wzrosło grzanie bez zmiany obciążenia. Co porównać?",
 "Półmostek działa statycznie, ale psuje się przy większej częstotliwości. Dlaczego?"],
"Dwa tranzystory tej samej gałęzi nie mogą przewodzić jednocześnie.",
"Dead-time zapobiega shoot-through; rzeczywiste opóźnienia zależą od drivera, gate charge, rezystorów i progów MOSFET-ów.",
"Za mały dead-time powoduje prąd zwarciowy, za duży zwiększa czas przewodzenia diody i straty.",
"Mierzyć jednocześnie oba VGS i prąd zasilania z odpowiednim pasmem, obserwując momenty przełączeń.",
"Diagnostyka półmostka wymaga analizy czasowej obu bramek, nie tylko średniego prądu.",["half bridge","dead time","shoot through"]),
("inductor_flyback",
["Po wyłączeniu cewki napięcie na tranzystorze gwałtownie rośnie. Skąd bierze się ten pik?",
 "Dioda flyback ma przerwę. Jakiego przebiegu spodziewasz się przy wyłączeniu cewki?",
 "Dlaczego szybsze wygaszanie prądu cewki często wymaga wyższego napięcia clamp?",
 "Przekaźnik działa, ale po jego wyłączeniu MCU się resetuje. Jak połączyć zjawiska?",
 "Jak ocenić energię indukcyjnego obciążenia przed doborem ochrony?"],
"Cewka magazynuje energię w polu magnetycznym i sprzeciwia się nagłej zmianie prądu.",
"Energia E=1/2·L·I² musi zostać rozproszona; v=L·di/dt pokazuje, że szybka zmiana prądu wymaga napięcia.",
"Bez kontrolowanej ścieżki energia podnosi napięcie do poziomu, przy którym zacznie przewodzić inna ścieżka lub nastąpi przebicie.",
"Oscyloskopem mierzyć napięcie na kluczu i prąd cewki przy wyłączeniu; sprawdzić element clamp/flyback.",
"Indukcyjne przepięcie jest konsekwencją zachowania energii; ochrona definiuje bezpieczną ścieżkę jej rozproszenia.",["inductor energy","flyback","L di/dt"]),
("capacitor_esr",
["Kondensator ma poprawną pojemność, ale zasilanie nadal mocno tętnie. Co jeszcze może być złe?",
 "Elektrolit mierzy nominalne µF, a regulator oscyluje pod obciążeniem. Co sprawdzić?",
 "Jak wysoki ESR wpływa na skoki napięcia przy zmianie prądu?",
 "Kondensator grzeje się przy dużym ripple current. Jak to interpretować?",
 "Dlaczego pomiar pojemności DMM nie wystarcza do oceny kondensatora w przetwornicy?"],
"Kondensator ma pojemność, ESR, ESL i dopuszczalny ripple; te parametry wpływają na zachowanie dynamiczne.",
"Skok napięcia ma składnik ΔV≈ΔI·ESR oraz składnik pojemnościowy; straty ESR rosną z prądem RMS.",
"Nominalna pojemność nie wyklucza wyschnięcia lub wzrostu ESR.",
"Zmierz ESR odpowiednią metodą, ripple oscyloskopem i temperaturę; porównaj z dobrym elementem.",
"Ocena kondensatora w zasilaniu wymaga parametrów dynamicznych, nie tylko µF.",["ESR","ripple","capacitor"]),
("decoupling",
["MCU resetuje się przy szybkim przełączaniu wyjść. Jaką rolę mogą mieć kondensatory odsprzęgające?",
 "Na szynie 3,3 V widać krótkie zapady przy zboczach cyfrowych. Co sprawdzić?",
 "Dlaczego kondensator 100 nF powinien być blisko pinu zasilania układu?",
 "Duży elektrolit jest obecny, a mimo to szybkie piki zasilania są duże. Dlaczego?",
 "Po wymianie kondensatora SMD przy MCU problem z resetem zniknął. Jak to wyjaśnić?"],
"Układ cyfrowy pobiera szybkie impulsy prądu lokalnie.",
"Odsprzęganie zapewnia niską impedancję zasilania w wysokich częstotliwościach; pasożytnicza indukcyjność ścieżek ogranicza skuteczność odległego kondensatora.",
"Duża pojemność daleko od pinu nie zastępuje małego kondensatora o krótkiej pętli prądowej.",
"Mierzyć szynę sondą z bardzo krótkim połączeniem masy bezpośrednio przy pinie układu.",
"Decoupling to problem impedancji i geometrii pętli, nie tylko sumy pojemności.",["decoupling","ESL","local current loop"]),
("ldo_dropout",
["LDO ma na wejściu 5 V, a na wyjściu zamiast 3,3 V jest 2,9 V pod obciążeniem. Co sprawdzić?",
 "Regulator liniowy działa bez obciążenia, ale zapada przy prądzie. Jak rozdzielić dropout od limitu prądowego?",
 "Napięcie wejściowe LDO spada blisko wyjściowego podczas crank. Co się stanie?",
 "LDO grzeje się przy 12 V wejścia i 5 V wyjścia. Jak oszacować straty?",
 "Wyjście LDO pulsuje. Jakie warunki poza samym układem scalonym mogą powodować niestabilność?"],
"LDO wymaga zapasu Vin−Vout i ma ograniczenia prądowe, termiczne oraz wymagania dotyczące kondensatorów.",
"W dropout regulator nie ma wystarczającego zapasu napięcia; straty liniowe P≈(Vin−Vout)·I.",
"Spadek wyjścia może wynikać z dropout, limitu prądu, temperatury, wejścia lub niestabilności pętli.",
"Mierzyć jednocześnie Vin, Vout, prąd i temperaturę; sprawdzić kondensatory i warunki obciążenia.",
"Najpierw ustalić, które ograniczenie regulatora zostało osiągnięte.",["LDO","dropout","linear power dissipation"]),
("buck_basic",
["Przetwornica buck ma prawidłowe Vin, ale za niskie Vout. Jak rozdzielić sterowanie od przeciążenia?",
 "Na nodzie SW w bucku brak przełączeń. Co sprawdzić przed wymianą kontrolera?",
 "Buck działa bez obciążenia i wyłącza się pod obciążeniem. Jak diagnozować?",
 "Dławik bucka mocno się grzeje. Jakie mechanizmy brać pod uwagę?",
 "Vout bucka ma duże tętnienia mimo prawidłowej wartości średniej. Co porównać?"],
"Buck przekazuje energię impulsowo przez klucz, dławik i kondensator, a pętla sprzężenia reguluje wartość średnią.",
"Brak lub zła wartość Vout może wynikać z enable, przełączania, zasilania drivera, przeciążenia, dławika, kondensatora lub feedback.",
"Najpierw ustal, czy kontroler przełącza i czy energia dociera przez dławik; potem oceniaj pętlę feedback.",
"Mierzyć EN, node SW, prąd/dławik, Vout i feedback; zacząć od bezpiecznego obciążenia.",
"Diagnostyka bucka jest sekwencją: start -> switching -> transfer energii -> filtr -> feedback.",["buck","switch node","feedback","inductor"]),
("boost_basic",
["Boost ma 12 V wejścia, ale wyjście nie rośnie powyżej 12 V. Od czego zacząć?",
 "Przetwornica boost pracuje, ale napięcie zapada pod obciążeniem. Co mierzyć?",
 "Dioda w boost jest zwarta. Jakiego zachowania oczekujesz?",
 "Node przełączający boost ma impulsy, ale wyjście jest niskie. Jak rozdzielić dławik, diodę i kondensator?",
 "Boost pobiera duży prąd z wejścia bez wzrostu napięcia. Jak bezpiecznie diagnozować?"],
"Boost magazynuje energię w dławiku podczas jednego stanu klucza i przekazuje ją na wyższe napięcie podczas drugiego.",
"Do wzrostu napięcia potrzebne są poprawne przełączanie, dławik, ścieżka prostująca, kondensator i feedback.",
"Same impulsy gate nie dowodzą poprawnego transferu energii.",
"Mierzyć node SW, prąd wejściowy lub dławika, napięcie przed/za diodą i feedback; używać ograniczenia prądowego.",
"Rozdziel sterowanie od toru energii i od regulacji.",["boost","inductor energy","rectifier","feedback"]),
("opamp_linear",
["Wzmacniacz operacyjny ma poprawne zasilanie, ale wyjście siedzi na dodatniej szynie. Jak analizować?",
 "Op-amp ma wzmacniać mały sygnał, lecz wyjście jest stałe. Co sprawdzić na wejściach?",
 "Czy op-amp zawsze wymusza V+=V-?",
 "Układ odwracający daje złe wzmocnienie mimo poprawnych rezystorów. Jakie ograniczenia sprawdzić?",
 "Wyjście op-ampa nie dochodzi do szyny zasilania. Czy to zawsze usterka?"],
"Op-amp w poprawnej pętli ujemnego sprzężenia dąży do zmniejszenia różnicy wejść, ale tylko w granicach zakresu wejść, wyjścia, pasma i zasilania.",
"Reguła V+≈V- jest konsekwencją pracy liniowej z ujemnym feedbackiem, nie uniwersalnym prawem dla saturacji.",
"Saturacja może wynikać z sygnału wejściowego, braku feedback, common-mode lub ograniczenia swing.",
"Mierzyć oba wejścia, wyjście i zasilania; sprawdzić ciągłość i znaki sprzężenia.",
"Najpierw ustal, czy op-amp pracuje liniowo czy jest nasycony.",["op amp","negative feedback","saturation","common mode"]),
("comparator_hysteresis",
["Komparator drga przy napięciu blisko progu. Jak pomaga histereza?",
 "Wyjście komparatora zmienia stan przy dwóch różnych napięciach zależnie od kierunku. Czy to normalne?",
 "Komparator open-collector nie osiąga HIGH. Co sprawdzić?",
 "Szum na wejściu powoduje wiele przełączeń. Jak zmienić układ bez filtrowania sygnału przez długi czas?",
 "Jak zmierzyć progi Schmitta w gotowym układzie?"],
"Komparator decyduje na podstawie znaku różnicy wejść; dodatnie sprzężenie może tworzyć dwa progi.",
"Histereza zapobiega wielokrotnemu przełączaniu przy szumie blisko pojedynczego progu.",
"Dwa różne progi przy narastaniu i opadaniu są oczekiwanym skutkiem Schmitta.",
"Powoli przemiatać napięcie w obu kierunkach i zanotować punkty przełączeń; dla open-collector sprawdzić pull-up.",
"Histereza to kontrolowane rozdzielenie progów, nie błąd pomiaru.",["comparator","hysteresis","Schmitt"]),
("shunt_current",
["Na shuncie 10 mΩ mierzysz 20 mV. Jaki prąd płynie?",
 "Pomiar prądu z shuntu różni się od cęgów. Co sprawdzić w pierwszej kolejności?",
 "Shunt low-side powoduje przesunięcie masy obciążenia. Jak to wpływa na inne pomiary?",
 "Shunt high-side ma mały sygnał na wysokim common-mode. Dlaczego zwykły op-amp może sobie nie poradzić?",
 "Ścieżki mocy do shuntu są grube, a pomiarowe cienkie i osobne. Po co Kelvin connection?"],
"Prąd można wyznaczyć z małego, znanego spadku napięcia na rezystorze pomiarowym.",
"I=Vshunt/Rshunt; dokładność zależy od wartości shuntu, pomiaru różnicowego, common-mode, ścieżek i temperatury.",
"Spadki na ścieżkach mocy nie powinny być mylone ze spadkiem na samym elemencie pomiarowym.",
"Mierzyć różnicowo bezpośrednio na padach Kelvin i porównać z niezależnym pomiarem prądu.",
"Poprawny current-sense wymaga zarówno prawa Ohma, jak i właściwej geometrii pomiaru.",["shunt","Kelvin","current sense"]),
("adc_quantization",
["ADC 12-bit mierzy zakres 0–5 V. Jaki jest przybliżony krok jednego LSB?",
 "Dwa kolejne odczyty ADC różnią się o 1 count przy stałym napięciu. Czy to musi być usterka?",
 "Jak wpływa napięcie referencyjne ADC na wynik pomiaru?",
 "ADC pokazuje pełną skalę mimo napięcia nieco ponad zakres. Jak to interpretować?",
 "Czy większa liczba bitów ADC zawsze daje dokładniejszy pomiar?"],
"ADC mapuje ciągłe napięcie na skończoną liczbę kodów zależnych od referencji i rozdzielczości.",
"LSB≈Vref/2^N; kwantyzacja, szum, dokładność referencji i front-end ograniczają wynik.",
"Jeden count różnicy może być normalną kwantyzacją lub szumem, a saturacja przy końcu zakresu nie mówi, jak daleko sygnał wyszedł poza zakres.",
"Porównać napięcie rzeczywiste, Vref i kod ADC; sprawdzić stabilność w wielu próbkach.",
"Rozdzielczość kodu nie jest tym samym co całkowita dokładność toru.",["ADC","LSB","quantization","reference"]),
("pwm_average",
["PWM 12 V ma 25% duty. Jakiego napięcia średniego oczekujesz idealnie?",
 "DMM pokazuje 6 V na PWM 12 V. Czy to znaczy, że amplituda wynosi 6 V?",
 "Silnik reaguje na duty-cycle, ale oscyloskop pokazuje stałą amplitudę impulsów. Dlaczego?",
 "Jak odróżnić zmianę duty od zmiany amplitudy PWM?",
 "PWM 50% ma tę samą wartość średnią przy dwóch różnych częstotliwościach. Czy obciążenie musi zachować się identycznie?"],
"PWM przełącza między poziomami, a duty-cycle określa ułamek czasu w stanie aktywnym.",
"Dla idealnego 0/V PWM wartość średnia to D·V, ale odpowiedź rzeczywistego obciążenia zależy też od częstotliwości i dynamiki.",
"DMM może raportować średnią lub RMS zależnie od miernika, niekoniecznie amplitudę impulsu.",
"Oscyloskopem mierzyć poziomy HIGH/LOW, duty i częstotliwość osobno.",
"Nie utożsamiaj napięcia średniego PWM z amplitudą sygnału.",["PWM","duty cycle","average"]),
("lowpass_filter",
["RC low-pass tłumi szybkie zakłócenia. Jak częstotliwość graniczna zależy od R i C?",
 "Po zwiększeniu kondensatora filtr reaguje wolniej. Dlaczego?",
 "Sygnał czujnika jest stabilniejszy po filtrze, ale opóźniony. Jaki kompromis widzisz?",
 "Jak sprawdzić, czy RC na wejściu nie tłumi użytecznego sygnału?",
 "Filtr działa inaczej po podłączeniu ADC. Co może go obciążać?"],
"Filtr RC pierwszego rzędu ma charakterystyczną stałą czasową i częstotliwość graniczną.",
"fc=1/(2πRC); większe R lub C obniża pasmo i spowalnia odpowiedź.",
"Tłumienie szumu jest okupione opóźnieniem i możliwym osłabieniem sygnału użytecznego.",
"Porównać odpowiedź skokową i sinusoidalną przed/za filtrem oraz uwzględnić impedancję następnego stopnia.",
"Filtr dobiera się do pasma informacji, nie tylko do maksymalnego wygładzenia.",["low pass","fc=1/(2piRC)","bandwidth"]),
("open_short_reasoning",
["Węzeł jest na 0 V. Jak rozróżnić zwarcie do masy od przerwy z pull-down?",
 "Napięcie jest równe zasilaniu. Jak odróżnić open-load od zwarcia do plusa?",
 "Rezystancja do masy jest niska in-circuit. Czy to wystarcza do stwierdzenia zwarcia?",
 "Po odłączeniu obciążenia napięcie wraca. Co to mówi o torze?",
 "Jak użyć znanego rezystora testowego do rozróżnienia open i short?"],
"To samo napięcie statyczne może powstać z różnych topologii uszkodzeń.",
"Open i short rozróżnia się przez odpowiedź na kontrolowane wymuszenie oraz rezystancję/ciągłość przy bezpiecznym stanie.",
"Trzeba sprawdzić, czy węzeł jest aktywnie wymuszany czy tylko pasywnie ustawiany przez rezystory.",
"Zmierz rezystancję bez zasilania, potem użyj bezpiecznego znanego pull-up/pull-down lub obciążenia i obserwuj reakcję.",
"Diagnostyka topologii wymaga zmiany warunku i obserwacji odpowiedzi.",["open circuit","short circuit","controlled stimulus"]),
("dmm_limits",
["DMM pokazuje poprawne 5 V, ale układ nadal się resetuje. Czego miernik może nie pokazać?",
 "Na PWM multimetr pokazuje 2 V. Jakie informacje są utracone?",
 "Pomiar rezystancji na zasilanej płycie daje dziwne wyniki. Dlaczego nie wolno tak robić?",
 "DMM nie wykrywa krótkiego zapadu zasilania. Jakie narzędzie wybrać?",
 "Dwie sondy DMM mają różne wyniki na szybko zmiennym sygnale. Co sprawdzić?"],
"DMM jest narzędziem o ograniczonym paśmie i określonej metodzie uśredniania.",
"Szybkie transienty, duty-cycle, ringing i kolejność zdarzeń wymagają obserwacji czasowej.",
"Pomiar rezystancji wymaga braku obcego napięcia; inaczej wynik jest niewiarygodny i można uszkodzić miernik.",
"Do zjawisk dynamicznych użyć oscyloskopu lub rejestratora, a DMM pozostawić do wartości wolnozmiennych/statycznych.",
"Dobór narzędzia wynika z czasu i natury mierzonego zjawiska.",["DMM bandwidth","oscilloscope","measurement mode"]),
("scope_grounding",
["Chcę zmierzyć high-side zwykłą sondą oscyloskopu. Czy mogę przypiąć krokodylek masy do dowolnego punktu?",
 "Po podłączeniu masy sondy zrobiło się zwarcie. Co mogło się stać?",
 "Jak bezpiecznie mierzyć napięcie między dwoma punktami, z których żaden nie jest masą oscyloskopu?",
 "Długi przewód masy sondy pokazuje duże ringing. Jak sprawdzić, czy to artefakt?",
 "Dwa kanały oscyloskopu mają wspólną masę. Jak to wpływa na pomiary półmostka?"],
"Standardowy oscyloskop stołowy często ma masy BNC połączone ze sobą i z PE.",
"Podłączenie klipsa masy może elektrycznie połączyć badany punkt z ziemią i zmienić lub uszkodzić obwód.",
"Pomiar różnicowy wymaga odpowiedniej sondy różnicowej, izolacji lub bezpiecznej techniki zgodnej z konfiguracją sprzętu.",
"Przed pomiarem sprawdzić odniesienie masy oscyloskopu i użyć krótkiej pętli sondy dla szybkich zboczy.",
"Bezpieczeństwo i topologia uziemienia są częścią pomiaru, nie dodatkiem.",["oscilloscope ground","differential measurement","probe loop"]),
("pcb_short_localization",
["Na szynie 3,3 V jest zwarcie. Jak lokalizować je bez podawania pełnego napięcia?",
 "Płyta pobiera duży prąd przy 1 V z ograniczeniem. Jak wykorzystać temperaturę do lokalizacji?",
 "Wstrzykiwanie prądu nagrzewa kilka elementów. Jak nie pomylić przyczyny ze ścieżką prądu?",
 "Rezystancja szyny do masy jest niska, ale identyczna dobra płyta ma podobną. Co to zmienia?",
 "Jak bezpiecznie dobrać napięcie do current injection na niskonapięciowej szynie?"],
"Szyna ma niską impedancję lub podejrzenie zwarcia; nie znamy jeszcze winnego elementu.",
"Bezpieczna lokalizacja wykorzystuje ograniczoną energię: napięcie poniżej bezpiecznego maksimum szyny, limit prądu i obserwację spadków/temperatury.",
"Najcieplejszy punkt może być zwarciem, ale może też przewodzić energię do właściwego zwarcia; potrzebna jest korelacja z topologią.",
"Porównać z dobrą płytą, mierzyć spadki mV wzdłuż zasilania i termicznie zawężać obszar.",
"Current injection ma lokalizować zwarcie bez przekraczania bezpiecznego napięcia szyny.",["current injection","short localization","current limit"]),
("thermal_diagnostics",
["Układ przestaje działać po podgrzaniu. Jak stosować freeze spray bez zgadywania?",
 "Chłodzenie jednego scalaka przywraca działanie. Czy to już dowód jego uszkodzenia?",
 "Jak rozdzielić problem termiczny półprzewodnika od pękniętego lutu?",
 "Usterka reaguje zarówno na temperaturę, jak i nacisk PCB. Co sugeruje taki wzorzec?",
 "Jak rejestrować dane podczas lokalnej próby termicznej?"],
"Objaw zależy od temperatury, ale temperatura wpływa na wiele elementów i połączeń jednocześnie.",
"Zmiana temperatury modyfikuje parametry półprzewodników, rezystancje, ESR oraz naprężenia mechaniczne.",
"Reakcja na chłodzenie lokalizuje obszar, nie automatycznie konkretny komponent.",
"Stosować coraz mniejszy obszar termiczny i równolegle mierzyć pierwszy sygnał elektryczny, który zmienia się przed objawem.",
"Termiczna diagnoza jest eksperymentem z kontrolowaną zmienną i pomiarem korelacji.",["thermal fault","correlation","localization"]),
("connector_contact",
["Na złączu bez obciążenia jest poprawne napięcie, ale pod obciążeniem znika. Co podejrzewać?",
 "Pin złącza wygląda dobrze, lecz grzeje się przy dużym prądzie. Jak to wyjaśnić?",
 "Pomiar omomierzem pokazuje prawie 0 Ω, a obwód nadal traci napięcie pod prądem. Dlaczego?",
 "Poruszanie złączem zmienia objaw. Jak wykonać test bez polegania tylko na obserwacji?",
 "Jak wykorzystać spadek napięcia do wykrycia wysokiej rezystancji styku?"],
"Połączenie może mieć małą, ale istotną rezystancję, niewidoczną dla prostego pomiaru ciągłości.",
"P=I²R i Vdrop=I·R powodują, że mała rezystancja staje się problemem dopiero przy dużym prądzie.",
"Test bez obciążenia może nie ujawnić styku o zwiększonej rezystancji.",
"Mierzyć spadek napięcia bezpośrednio na styku podczas rzeczywistego prądu i obserwować temperaturę.",
"Spadek pod obciążeniem jest lepszą miarą jakości połączenia mocy niż beep continuity.",["contact resistance","voltage drop","I2R"]),
("relay_diagnostics",
["Cewka przekaźnika dostaje napięcie, ale styki nie przewodzą. Co rozdzielić?",
 "Przekaźnik klika, lecz obciążenie nie działa. Czy klik oznacza sprawne styki?",
 "Na stykach przekaźnika jest duży spadek pod obciążeniem. Jak to interpretować?",
 "Cewka przekaźnika ma przerwę. Jak potwierdzić bez aktywowania układu?",
 "Przekaźnik działa zimny, a po nagrzaniu kontakt znika. Co mierzyć?"],
"Przekaźnik ma oddzielony tor cewki i tor styków.",
"Energia cewki powoduje ruch mechaniczny, ale klik nie potwierdza niskiej rezystancji styków pod obciążeniem.",
"Trzeba osobno potwierdzić cewkę, mechanikę oraz spadek na stykach.",
"Mierzyć rezystancję cewki bez zasilania, napięcie/prąd cewki przy sterowaniu i spadek napięcia na stykach pod obciążeniem.",
"Diagnoza przekaźnika wymaga rozdzielenia aktuacji od przewodzenia obciążenia.",["relay coil","contacts","voltage drop"]),
("reset_supervisor",
["Linia RESET MCU jest cyklicznie aktywowana. Jak ustalić, czy robi to supervisor czy sam MCU?",
 "Zasilanie wygląda stabilnie na DMM, ale reset supervisor przełącza. Co mierzyć?",
 "MCU nie startuje mimo poprawnej głównej szyny. Jakie sygnały startowe sprawdzić?",
 "Po zmianie kondensatora reset timing ECU się zmienił. Jak to może być powiązane?",
 "Jak odróżnić brownout MCU od zewnętrznego resetu?"],
"Start MCU zależy od zasilania, resetu, często clock i sekwencji enable.",
"Supervisor obserwuje napięcia i czas; reset może być skutkiem krótkiego zapadu niewidocznego na DMM.",
"Kolejność Vin/Vcore/RESET/clock rozdziela źródło problemu.",
"Rejestrować oscyloskopem zasilania i RESET równocześnie, najlepiej z triggerem na zboczu resetu.",
"Najpierw ustal, kto generuje reset i co wydarzyło się tuż przed nim.",["reset supervisor","brownout","power sequencing"]),
("logic_open_drain",
["Wyjście open-drain nie generuje HIGH samodzielnie. Dlaczego?",
 "Dwa układy mogą współdzielić linię open-drain. Jak unikają zwarcia swoich wyjść?",
 "Linia open-drain jest stale niska. Jak znaleźć urządzenie, które ją trzyma?",
 "Pull-up jest do 5 V, a jeden układ toleruje tylko 3,3 V. Co trzeba sprawdzić?",
 "Open-drain działa wolno na długiej linii. Jakie parametry decydują?"],
"Open-drain aktywnie wymusza zwykle tylko LOW, a HIGH zapewnia zewnętrzny pull-up.",
"Współdzielona linia jest logicznym wired-AND; urządzenia nie powinny aktywnie wymuszać przeciwnego stanu HIGH.",
"Stale LOW może być poprawnym wymuszeniem, zwarciem lub uszkodzonym nadajnikiem.",
"Odłączać uczestników, mierzyć prąd i napięcie LOW oraz czas narastania z pull-up.",
"Trzeba rozumieć kierunek aktywnego wymuszenia i zgodność poziomów napięć.",["open drain","wired AND","pull up"]),
("measurement_reference",
["Dwa napięcia mierzone względem różnych mas wyglądają sprzecznie. Jak je porównać?",
 "Sygnał jest poprawny względem lokalnej masy, ale błędny względem masy ECU. Co to znaczy?",
 "Czy napięcie istnieje bez określenia dwóch punktów pomiarowych?",
 "Jak błąd wyboru punktu odniesienia może udawać uszkodzony czujnik?",
 "Dlaczego pomiar różnicowy jest ważny przy dużych prądach masy?"],
"Napięcie jest różnicą potencjałów między dwoma punktami.",
"Bez jawnego punktu odniesienia wartość napięcia jest niepełną informacją; różne masy mogą mieć różne potencjały pod obciążeniem.",
"Pozorna zmiana sygnału może być w rzeczywistości zmianą punktu odniesienia.",
"Zapisać dokładnie oba punkty każdego pomiaru i, gdy trzeba, mierzyć bezpośrednio różnicowo.",
"Każdy wniosek o napięciu musi zawierać odniesienie.",["voltage reference","ground offset","differential"]),
]

HOLDOUT_FAMILIES=[
("loaded_divider",
 ["Dzielnik napięcia daje dobrą wartość bez obciążenia, ale po podłączeniu wejścia ADC napięcie spada. Jak dojść do przyczyny?",
  "Dlaczego wejście o skończonej impedancji zmienia wynik dzielnika?",
  "Jak sprawdzić, czy błąd dzielnika wynika z jego obciążenia?"],
 "Dzielnik jest obciążony przez następną impedancję.",
 "Obciążenie jest równoległe do dolnego rezystora, więc zmienia efektywny podział napięcia.",
 "Trzeba policzyć R2||Rload i ponownie użyć wzoru dzielnika.",
 "Zmierz impedancję wejścia lub dodaj bufor i porównaj wynik.",
 "Obciążenie dzielnika jest częścią obwodu i może istotnie zmienić Vout.",
 ["loaded divider","parallel load"]),
("opamp_saturation_holdout",
 ["Wyjście op-ampa jest przy dolnej szynie mimo małej różnicy wejść. Jak ustalić, czy to saturacja czy awaria?",
  "Wzmacniacz działa dla małych sygnałów, ale obcina większe. Jak rozumować?",
  "Dlaczego poprawny feedback nie wystarcza, gdy wymagane wyjście jest poza zakresem?"],
 "Wyjście jest ograniczone zakresem możliwego swing lub warunkami wejściowymi.",
 "Ujemne sprzężenie działa tylko wtedy, gdy wzmacniacz ma zapas napięcia i zakres common-mode.",
 "Należy policzyć wymagane idealne wyjście i porównać je z fizycznym zakresem układu.",
 "Zmierz wejścia, wyjście i szyny dla kilku poziomów sygnału.",
 "Saturacja jest ograniczeniem modelu rzeczywistego, nie dowodem uszkodzenia.",
 ["op amp saturation","output swing"]),
("mosfet_body_holdout",
 ["Wyłączony MOSFET przepuszcza prąd tylko w jednym kierunku. Jak krok po kroku wyjaśnić wynik?",
  "Dlaczego pomiar D-S może wyglądać jak dioda mimo wyłączonej bramki?",
  "Jak bezpiecznie rozstrzygnąć body diode kontra zwarcie kanału?"],
 "MOSFET mocy zawiera body diode, a gate może zachowywać ładunek.",
 "Jednokierunkowe przewodzenie może pochodzić z diody strukturalnej; kanał zależy od VGS.",
 "Najpierw rozładuj gate, potem zmierz oba kierunki i orientację względem source/drain.",
 "W razie niejednoznaczności odizoluj element od równoległych ścieżek.",
 "Jednokierunkowy spadek nie jest równoważny zwartemu MOSFET-owi.",
 ["body diode","gate discharge"]),
("esr_holdout",
 ["Zasilanie ma poprawną wartość DC, lecz duży ripple pod obciążeniem. Jak dojść do kondensatora ESR?",
  "Pojemność kondensatora jest nominalna, a transient response zła. Jak rozumować?",
  "Jak odróżnić małą pojemność od wysokiego ESR z przebiegu?"],
 "Dynamiczna odpowiedź zależy od C i ESR.",
 "Natychmiastowy skok napięcia wiąże się z ESR, późniejsze nachylenie z ładowaniem/rozładowaniem C.",
 "Rozdziel szybki skok od wolniejszej części transientu.",
 "Zmierz ripple i odpowiedź skokową krótką pętlą sondy oraz ESR niezależnie.",
 "Nominalne µF nie gwarantują niskiej impedancji dynamicznej.",
 ["ESR","transient response"]),
("scope_aliasing_holdout",
 ["Oscyloskop pokazuje niestabilną niską częstotliwość na szybkim PWM. Co może być artefaktem próbkowania?",
  "Dwa pomiary tego samego sygnału przy różnych timebase wyglądają inaczej. Jak to sprawdzić?",
  "Jak uniknąć błędnego wniosku z aliasingu?"],
 "Próbkowanie dyskretne może odwzorować szybki sygnał jako fałszywie wolny, jeśli sample rate jest zbyt niski.",
 "Trzeba spełnić odpowiednie warunki próbkowania i sprawdzić rzeczywisty sample rate, nie tylko szerokość ekranu.",
 "Zwiększ sample rate, zmień timebase i użyj stabilnego triggera.",
 "Porównać kilka ustawień oraz, jeśli dostępne, pomiar częstotliwości sprzętowej.",
 "Artefakt akwizycji może wyglądać jak rzeczywista modulacja.",
 ["aliasing","sample rate","trigger"]),
("current_sense_holdout",
 ["Shunt daje poprawny spadek, ale ADC raportuje inny prąd. Jak przejść przez tor krok po kroku?",
  "Pomiar na shuncie jest stabilny, a telemetria skacze. Gdzie szukać?",
  "Jak odseparować błąd shuntu, wzmacniacza i ADC?"],
 "Tor pomiarowy ma kolejne etapy: prąd -> shunt -> wzmacniacz/filtr -> ADC -> software.",
 "Należy porównać oczekiwany sygnał na każdym etapie z rzeczywistym.",
 "Pierwszy punkt rozbieżności lokalizuje warstwę usterki.",
 "Zmierz różnicowo shunt, wyjście wzmacniacza, Vref ADC i surowy kod.",
 "Diagnoza jest śledzeniem transformacji sygnału, nie wyborem jednego układu.",
 ["signal chain","shunt","ADC"]),
("flyback_holdout",
 ["Po wyłączeniu cewki resetuje się logika. Jak dojść od energii cewki do resetu?",
  "Dlaczego uszkodzony clamp może wywołać problem z MCU zamiast tylko z MOSFET-em?",
  "Jak potwierdzić sprzężenie przepięcia do zasilania logicznego?"],
 "Energia cewki musi znaleźć drogę rozproszenia, a przepięcie może sprzęgać się do wspólnych szyn lub mas.",
 "Brak poprawnego clamp zwiększa dv/dt i energię w niepożądanych ścieżkach.",
 "Korelacja czasu piku z zapadem Vcore/RESET wskazuje mechanizm.",
 "Rejestrować jednocześnie wyjście indukcyjne, zasilanie logiczne i RESET.",
 "Trzeba połączyć przyczynę energetyczną z obserwowanym resetem czasowo.",
 ["inductive energy","clamp","reset correlation"]),
("unknown_component_holdout",
 ["Nie znam oznaczenia układu SMD, ale wiem do jakich netów jest podłączony. Jak wnioskować bez zgadywania numeru części?",
  "Jak funkcjonalnie zidentyfikować nieopisany układ na PCB?",
  "Czy podobna obudowa wystarcza do identyfikacji scalaka?"],
 "Brak identyfikacji części nie blokuje analizy funkcjonalnej topologii.",
 "Połączenia do zasilania, masy, wejść, wyjść i elementów zewnętrznych ograniczają możliwą rolę układu.",
 "Najpierw zbuduj funkcję z netów i przebiegów, potem dopiero szukaj identyfikatora.",
 "Trace PCB, napięcia, kierunek sygnału i porównanie kanałów.",
 "Obudowa sama nie jest wiarygodnym identyfikatorem funkcji.",
 ["functional identification","PCB nets"]),
]

def generic_records(split,start,families):
    out=[]; rid=start
    for category,qs,facts,law,reasoning,check,answer,concepts in families:
        for q in qs:
            out.append(rec(f"ELEC-{split.upper()}-{rid:04d}",category,q,ans(facts,law,reasoning,check,answer),concepts,split=split))
            rid+=1
    return out

def norm(s):
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9ąćęłńóśźż]+"," ",s.lower())).strip()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out-dir",default=str(ROOT/"deploy/stage-p5/training/electronics"))
    args=ap.parse_args()
    outdir=Path(args.out_dir); outdir.mkdir(parents=True,exist_ok=True)

    train=[]
    train += ohm_records("train",1,9)
    train += divider_records("train",10,5)
    train += rc_records("train",15,5)
    train += generic_records("train",20,TRAIN_FAMILIES)

    holdout=[]
    holdout += generic_records("holdout",1,HOLDOUT_FAMILIES)

    train_norm={norm(r["user"]+" "+r["assistant"]) for r in train}
    hold_norm={norm(r["user"]+" "+r["assistant"]) for r in holdout}
    if len(train_norm)!=len(train): raise SystemExit("ELECTRONICS_GATE=FAIL train_duplicate")
    if len(hold_norm)!=len(holdout): raise SystemExit("ELECTRONICS_GATE=FAIL holdout_duplicate")
    if train_norm & hold_norm: raise SystemExit("ELECTRONICS_GATE=FAIL train_holdout_exact_overlap")

    train_path=outdir/"electronics_foundation_train_v1.jsonl"
    hold_path=outdir/"electronics_foundation_holdout_v1.jsonl"
    train_path.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in train))
    hold_path.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in holdout))

    cats=sorted({r["metadata"]["category"] for r in train})
    manifest={
      "schema_version":1,
      "dataset_id":"electronics-foundation-v1",
      "train_records":len(train),
      "holdout_records":len(holdout),
      "train_categories":len(cats),
      "categories":cats,
      "source_kind":"project_owned_derived_electronics_principles",
      "external_text_copied":False,
      "oem_material_used":False,
      "automotive_golden_used":False,
      "train_sha256":digest(train_path),
      "holdout_sha256":digest(hold_path),
      "seed":SEED,
    }
    (outdir/"electronics_foundation_v1.manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("P5_2_ELECTRONICS_DATASET_GATE=PASS")
    print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
