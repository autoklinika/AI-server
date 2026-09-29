#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "deploy/stage-p5/training/fixtures/automotive_curriculum_seed_v1.jsonl"
GOLDEN_DEFAULT = ROOT / "benchmarks/automotive_v1/datasets/golden.v1.jsonl"

SYSTEM = (
    "Jesteś technicznym asystentem diagnostyki ECU i elektroniki automotive. "
    "Nie zgaduj części do wymiany. Oddzielaj fakty od hipotez, wybieraj pomiar "
    "o najwyższej wartości diagnostycznej i jawnie zatrzymuj wnioskowanie, gdy "
    "evidence jest niewystarczające. Odpowiadaj po polsku w strukturze: FAKTY; "
    "WYKLUCZONE; HIPOTEZY; TEST ROZDZIELAJĄCY; OCZEKIWANE WYNIKI; "
    "INTERPRETACJA; NASTĘPNY KROK; PEWNOŚĆ."
)

# Each family expresses a reusable diagnostic skill rather than an OEM fact.
FAMILIES = [
{
"category":"sensor_signal_high_generic",
"questions":[
"Sygnał analogowego czujnika jest stale blisko napięcia referencyjnego. Co sprawdzić zanim wymienię czujnik?",
"Na wejściu ECU sygnał czujnika jest prawie równy 5 V przez cały czas. Jak rozdzielić czujnik od wiązki?",
"Czujnik ma poprawne 5 V i masę, ale sygnał jest stale wysoki. Jaki test ma największą wartość?",
"Po odpięciu czujnika wejście nadal jest wysokie. Co to zmienia w diagnozie?",
"Po podgrzaniu wiązki sygnał czujnika skacze do górnej granicy. Co mierzyć równolegle?"
],
"facts":"Sygnał jest nienaturalnie wysoki; nie ma jeszcze dowodu na uszkodzenie samego czujnika.",
"excluded":"Nie wykluczono zwarcia sygnału do referencji, przerwy masy, problemu wiązki ani wejścia ECU.",
"hyp":"Czujnik, zwarcie sygnału do plusa lub referencji, utrata masy czujnika, złącze albo wejście ECU.",
"test":"Porównać sygnał przy czujniku i przy ECU, sprawdzić spadek masy oraz reakcję wejścia po kontrolowanym odłączeniu lub obciążeniu testowym.",
"expected":"Różnica między końcami wiązki wskazuje przewód lub złącze; poprawna wiązka z nieprawidłową reakcją wejścia wzmacnia ECU; zmiana po odłączeniu czujnika pomaga ocenić źródło wysokiego poziomu.",
"interp":"Wysoki sygnał nie oznacza automatycznie uszkodzonego czujnika.",
"next":"Wykonać pomiary na obu końcach toru przed wymianą elementu.",
"confidence":"Wysoka co do procedury, niska co do komponentu bez pomiarów."
},
{
"category":"sensor_signal_low_generic",
"questions":[
"Sygnał czujnika jest stale blisko 0 V, ale zasilanie referencyjne wygląda dobrze. Co dalej?",
"ECU widzi minimalną wartość czujnika. Jak odróżnić zwarcie do masy od uszkodzonego czujnika?",
"Na pinie sygnałowym jest prawie 0 V. Czy to wystarcza do wymiany czujnika?",
"Po odłączeniu czujnika sygnał nadal pozostaje niski. Jak to interpretować?",
"Przy poruszaniu wiązką niski sygnał chwilowo wraca do normy. Co sprawdzać?"
],
"facts":"Sygnał jest stale niski, ale nie znamy jeszcze miejsca wymuszenia tego poziomu.",
"excluded":"Nie wykluczono zwarcia do masy, przerwy zasilania pod obciążeniem, problemu czujnika ani wejścia ECU.",
"hyp":"Zwarcie sygnału do masy, uszkodzony czujnik, złącze lub przewód, problem z masą referencyjną albo wejście ECU.",
"test":"Porównać napięcie sygnału po obu stronach wiązki i sprawdzić reakcję toru po odłączeniu czujnika oraz po podaniu bezpiecznego sygnału testowego zgodnego z zakresem wejścia.",
"expected":"Utrzymanie niskiego poziomu po odłączeniu czujnika kieruje do wiązki lub ECU; poprawna reakcja wejścia na sygnał testowy przesuwa podejrzenie do czujnika.",
"interp":"Niski poziom jest objawem toru, nie gotową diagnozą komponentu.",
"next":"Zlokalizować punkt, w którym niski poziom jest wymuszany.",
"confidence":"Wysoka co do planu testu."
},
{
"category":"reference_rail_overload",
"questions":[
"Linia 5 V spada dopiero po podłączeniu jednego z kilku czujników. Jak potwierdzić przeciążenie?",
"Referencja 5 V jest poprawna bez obciążenia, ale siada po podłączeniu wiązki. Co mierzyć?",
"Na kilku czujnikach pojawiają się jednocześnie błędy niskiego napięcia referencji. Od czego zacząć?",
"Po odłączeniu jednej gałęzi wraca 5 V. Czy to od razu oznacza uszkodzony czujnik na tej gałęzi?",
"Szyna 5 V pulsuje między poprawną i zaniżoną wartością. Jak rozdzielić regulator od zwarcia odbiornika?"
],
"facts":"Wspólna referencja jest przeciążana lub ograniczana w określonych warunkach.",
"excluded":"Nie ustalono, czy obciążenie pochodzi z czujnika, wiązki, złącza czy regulatora.",
"hyp":"Zwarcie lub nadmierny pobór na jednej gałęzi, uszkodzony odbiornik, przewód do masy albo wewnętrzne ograniczenie regulatora.",
"test":"Mierzyć prąd szyny i napięcie przy ECU podczas kolejnego odłączania gałęzi, a podejrzaną gałąź sprawdzić rezystancyjnie przy wyłączonym zasilaniu.",
"expected":"Odzyskanie napięcia i spadek prądu po odłączeniu gałęzi lokalizują obciążenie; brak poprawy bez odbiorników wzmacnia regulator lub PCB.",
"interp":"Gałąź może być winna, ale dopiero pomiar rozdziela czujnik od wiązki.",
"next":"Zlokalizować nadmierny pobór wewnątrz wskazanej gałęzi.",
"confidence":"Wysoka."
},
{
"category":"ground_offset",
"questions":[
"Czujnik ma poprawne zasilanie, ale wartości zmieniają się przy włączaniu dużego odbiornika. Czy sprawdzać masę?",
"Na stole wszystko działa, w maszynie pomiar czujnika pływa przy obciążeniu. Co rozdzieli problem masy?",
"Między masą czujnika a masą akumulatora pojawia się napięcie tylko podczas pracy siłownika. Jak to interpretować?",
"Kilka niezależnych wejść jednocześnie zmienia wartość przy dużym prądzie wyjściowym. Co sprawdzić?",
"ECU ma stabilne B+, ale sygnały analogowe przesuwają się wraz z obciążeniem. Jaki test?"
],
"facts":"Objaw koreluje z przepływem dużego prądu i może wynikać z przesunięcia potencjału masy.",
"excluded":"Nie zmierzono dynamicznych spadków masy na poszczególnych segmentach.",
"hyp":"Wspólna rezystancja masy, skorodowane połączenie, słaby przewód, lokalna masa ECU lub sprzężenie przez ścieżkę prądową.",
"test":"Mierzyć różnicowo spadki napięcia między masą ECU, masą czujnika i masą źródła zasilania podczas aktywacji dużego odbiornika.",
"expected":"Skok napięcia na konkretnym segmencie masy lokalizuje połączenie o nadmiernej rezystancji; brak spadków kieruje do innych mechanizmów sprzężenia.",
"interp":"Poprawne napięcie B+ nie wyklucza problemu po stronie powrotu prądu.",
"next":"Zidentyfikować i obciążyć podejrzany segment masy.",
"confidence":"Wysoka."
},
{
"category":"high_side_no_output",
"questions":[
"ECU podaje komendę na high-side, ale na wyjściu nie ma napięcia. Co sprawdzić przed wymianą drivera?",
"Sterowanie bramki pojawia się, lecz obciążenie nie dostaje zasilania. Jak rozdzielić driver od ścieżki PCB?",
"Na wejściu układu wykonawczego jest komenda, a wyjście pozostaje niskie. Jaki pomiar jest najważniejszy?",
"Wyjście high-side działa bez obciążenia, ale zapada się po podłączeniu cewki. Co to sugeruje?",
"Jedno z kilku identycznych wyjść high-side nie działa. Jak wykorzystać kanał referencyjny?"
],
"facts":"Komenda sterująca jest obecna, ale zachowanie wyjścia nie jest prawidłowe pod jednym lub większym obciążeniem.",
"excluded":"Nie wykluczono braku zasilania stopnia, uszkodzonego tranzystora, ograniczenia prądowego, ścieżki PCB ani zwarcia obciążenia.",
"hyp":"Driver lub MOSFET, power feed stopnia, ścieżka lub złącze, nadmierne obciążenie albo funkcja zabezpieczenia.",
"test":"Porównać napięcie zasilania drivera, sygnał gate lub control, napięcie wyjścia i spadek na elemencie mocy podczas komendy; jeśli dostępny, zestawić z dobrym kanałem.",
"expected":"Prawidłowe sterowanie i zasilanie przy braku wyjścia wzmacniają stopień mocy; zapad zasilania lub duży spadek przed driverem wskazuje power path; poprawa bez obciążenia wskazuje przeciążenie lub rezystancję toru.",
"interp":"Komenda logiczna nie gwarantuje poprawnego przeniesienia energii do obciążenia.",
"next":"Wykonać skorelowany pomiar wejście-zasilanie-wyjście pod obciążeniem.",
"confidence":"Wysoka."
},
{
"category":"low_side_no_output",
"questions":[
"Low-side dostaje komendę, ale cewka nie jest ściągana do masy. Jak diagnozować?",
"Na wejściu drivera low-side jest PWM, lecz na wyjściu brak odpowiedzi. Co dalej?",
"Jedno wyjście low-side ma dużo większy spadek napięcia niż pozostałe. Co zmierzyć?",
"Low-side działa na małym obciążeniu testowym, ale nie na właściwej cewce. Jak rozdzielić przyczyny?",
"Wyjście low-side po nagrzaniu przestaje przewodzić. Jaki pomiar ma największą wartość?"
],
"facts":"Sterowanie logiczne jest obecne, ale ścieżka do masy nie zachowuje się prawidłowo.",
"excluded":"Nie wykluczono zasilania drivera, uszkodzenia tranzystora, ograniczenia prądowego, ścieżki masy ani przeciążenia.",
"hyp":"Tranzystor low-side, gate drive, masa stopnia, ścieżka PCB, zabezpieczenie termiczne lub nieprawidłowe obciążenie.",
"test":"Mierzyć równolegle sygnał sterujący, napięcie drain-output względem masy drivera, spadek na masie i prąd obciążenia podczas aktywacji.",
"expected":"Wysokie napięcie na wyjściu mimo poprawnego sterowania i masy wskazuje stopień mocy; wzrost spadku masy wskazuje tor powrotny; działanie na małym obciążeniu może ujawniać problem prądowy.",
"interp":"Należy rozdzielić brak sterowania od braku zdolności prądowej.",
"next":"Porównać przebiegi z prawidłowym kanałem lub stanem zimnym.",
"confidence":"Wysoka."
},
{
"category":"output_intermit_vibration",
"questions":[
"Wyjście przerywa tylko przy wibracji ECU. Jak podejść do lokalizacji?",
"Po lekkim ugięciu PCB funkcja wraca. Czy od razu robić reflow?",
"ECU działa na stole, ale po stuknięciu w obudowę pojawia się błąd wyjścia. Co rejestrować?",
"Wibracja zmienia działanie tylko jednego kanału. Jak znaleźć miejsce usterki bez losowego lutowania?",
"Objaw reaguje na nacisk w okolicy złącza. Jak rozdzielić pin złącza od ścieżki PCB?"
],
"facts":"Usterka jest mechanicznie zależna i odwracalna.",
"excluded":"Nie zlokalizowano, który sygnał lub zasilanie znika w chwili wibracji.",
"hyp":"Pęknięty lut, via lub ścieżka, pin złącza, BGA lub QFN, pęknięty element albo naprężenie PCB.",
"test":"Wymusić łagodną, kontrolowaną wibrację lub ugięcie sekcjami i równocześnie rejestrować sygnał wejściowy, zasilanie oraz wyjście podejrzanego kanału.",
"expected":"Zanik jednego z sygnałów dokładnie przy mechanicznej zmianie zawęża obszar; brak korelacji wymaga innego bodźca.",
"interp":"Reflow bez lokalizacji może chwilowo zamaskować przyczynę i zniszczyć dowód.",
"next":"Lokalizacja elektryczna przed naprawą termiczną.",
"confidence":"Wysoka."
},
{
"category":"temperature_supply_fault",
"questions":[
"Po nagrzaniu ECU zanika wewnętrzna szyna zasilania, po schłodzeniu wraca. Co rozdzielić?",
"Regulator działa zimny, ale przy 70°C napięcie zaczyna pulsować. Co mierzyć oprócz wyjścia?",
"Po podgrzaniu sekcji zasilania MCU resetuje się. Jak znaleźć winny element?",
"Napięcie rdzenia spada tylko pod obciążeniem i po nagrzaniu. Co porównać?",
"Chłodzenie jednego obszaru przywraca ECU do pracy. Czy to wystarcza do wymiany PMIC?"
],
"facts":"Usterka power path jest zależna od temperatury.",
"excluded":"Nie ustalono, czy źródłem jest wejście, regulator, element zewnętrzny, obciążenie czy supervisor.",
"hyp":"Regulator lub PMIC, kondensator, element feedback, lut, wzrost poboru obciążenia albo zabezpieczenie termiczne.",
"test":"Rejestrować wejście regulatora, wyjście, feedback lub enable oraz prąd podczas lokalnego grzania i chłodzenia.",
"expected":"Stabilne wejście z załamaniem wyjścia wskazuje regulator lub jego otoczenie; utrata enable kieruje do sterowania; wzrost prądu przed zapadem wskazuje przeciążenie.",
"interp":"Reakcja na temperaturę lokalizuje obszar, lecz nie identyfikuje automatycznie układu.",
"next":"Powtórzyć test z mniejszym obszarem termicznym i korelacją elektryczną.",
"confidence":"Wysoka."
},
{
"category":"can_termination_fault",
"questions":[
"Przy wyłączonej sieci rezystancja między CAN-H i CAN-L jest wyraźnie inna niż oczekiwana dla dwóch terminatorów. Co robić?",
"CAN działa tylko po odłączeniu jednej gałęzi. Jak rozdzielić terminację od uszkodzonego node'a?",
"Po dołożeniu urządzenia do magistrali pojawiają się błędy ramek. Jak sprawdzić terminację bez zgadywania?",
"Rezystancja magistrali zmienia się po poruszeniu wiązką. Co to mówi?",
"Na jednej części maszyny CAN działa, na drugiej nie. Jak użyć pomiaru rezystancji do segmentacji?"
],
"facts":"Parametr pasywny magistrali lub zachowanie po segmentacji jest nieprawidłowe.",
"excluded":"Nie zlokalizowano brakującego lub nadmiarowego zakończenia ani zwarcia.",
"hyp":"Brak terminatora, dodatkowy terminator, przerwa magistrali, uszkodzony node lub rezystancyjne zwarcie.",
"test":"Przy wyłączonym zasilaniu mierzyć rezystancję na kolejnych punktach i odłączać sekcje, zapisując zmianę po każdej operacji.",
"expected":"Skok rezystancji po odłączeniu określonej sekcji identyfikuje udział tej gałęzi; brak ciągłości między segmentami wskazuje przerwę.",
"interp":"Pomiar rezystancji ma sens tylko przy kontrolowanym stanie zasilania i znanej topologii.",
"next":"Zbudować mapę segmentów oraz lokalizację terminatorów.",
"confidence":"Wysoka."
},
{
"category":"can_noise_dynamic",
"questions":[
"CAN działa na postoju, ale gubi komunikację przy pracy silnika lub dużych odbiorników. Co mierzyć?",
"Na analizatorze widać sporadyczne błędy CAN tylko podczas załączania pompy. Jak szukać przyczyny?",
"Magistrala jest poprawna rezystancyjnie, ale ramki psują się pod obciążeniem elektrycznym. Co dalej?",
"Zakłócenia CAN pojawiają się razem z PWM dużej mocy. Jak rozdzielić EMI od problemu masy?",
"Komunikacja wraca po skróceniu przewodu testowego. Jakie pomiary potwierdzą problem sygnałowy?"
],
"facts":"Problem jest dynamiczny i zależny od warunków zakłóceniowych lub obciążenia.",
"excluded":"Statyczna rezystancja nie wyklucza problemu jakości sygnału, masy ani EMC.",
"hyp":"Common-mode shift, zakłócenie przewodzone lub promieniowane, słaba masa, odbicia, uszkodzony transceiver albo problem prowadzenia przewodu.",
"test":"Oscyloskopem rejestrować CAN-H, CAN-L, różnicę i common-mode razem z sygnałem wyzwalającym obciążenie oraz spadkiem masy.",
"expected":"Korelacja błędu z common-mode lub impulsem zakłócającym wskazuje EMC lub masę; zniekształcone zbocza bez zmian masy wskazują topologię lub terminację.",
"interp":"Poprawna rezystancja DC nie potwierdza integralności sygnału dynamicznego.",
"next":"Capture synchroniczny z wydarzeniem zakłócającym.",
"confidence":"Wysoka."
},
{
"category":"lin_wakeup_unknown",
"questions":[
"LIN jest wysoko, ale moduł nie odpowiada po uśpieniu. Jak sprawdzić wake-up?",
"Node LIN działa po ręcznym resecie, ale nie budzi się z magistrali. Co mierzyć?",
"Na LIN widzę krótkie impulsy podczas wake, ale ECU nadal śpi. Jak rozdzielić transceiver od MCU?",
"Moduł budzi się tylko czasami. Czy wystarczy mierzyć napięcie DC na LIN?",
"Po podaniu wake sygnał na pinie RXD się zmienia, ale reszta ECU nie startuje. Co dalej?"
],
"facts":"Warstwa komunikacyjna w stanie aktywnym nie jest jeszcze potwierdzona; problem dotyczy przejścia sleep-wake.",
"excluded":"Nie ustalono, czy wake dociera przez transceiver, czy MCU reaguje i czy zasilania standby są stabilne.",
"hyp":"Brak prawidłowego impulsu wake, transceiver, RXD lub wake output, zasilanie standby, logika MCU lub konfiguracja sleep.",
"test":"Rejestrować równocześnie LIN, RXD lub wake output transceivera, zasilanie standby oraz reset lub enable MCU podczas próby wybudzenia.",
"expected":"Wake na LIN bez reakcji RXD wskazuje transceiver; reakcja RXD bez startu MCU kieruje do zasilania lub logiki wewnętrznej.",
"interp":"Stan DC linii nie opisuje całej sekwencji wake-up.",
"next":"Zarejestrować pełną chronologię wake.",
"confidence":"Wysoka."
},
{
"category":"j1939_no_tx_generic",
"questions":[
"Node ma poprawną warstwę CAN, ale po starcie nie wysyła żadnych ramek wyższego protokołu. Od czego zacząć?",
"Transceiver działa, oscyloskop pokazuje ruch innych urządzeń, ale badany sterownik milczy. Co sprawdzić?",
"Po wymianie ECU sieć fizyczna jest poprawna, lecz nowy node nie nadaje. Jak rozdzielić konfigurację od hardware?",
"ECU odbiera magistralę, ale nie widać jego własnych transmisji. Co mierzyć?",
"Na stole ECU nie nadaje mimo poprawnego CAN-H/CAN-L. Czy to musi być uszkodzony transceiver TX?"
],
"facts":"Fizyczna obecność magistrali nie potwierdza gotowości aplikacji do transmisji.",
"excluded":"Nie sprawdzono stanu zasilania aplikacji, wake, konfiguracji adresowej ani warunku rozpoczęcia komunikacji.",
"hyp":"Brak wake lub ignition, aplikacja nie wystartowała, konflikt lub brak konfiguracji protokołu, TX path albo warunek bezpieczeństwa.",
"test":"Potwierdzić stan startu ECU i warunki wymagane do nadawania, obserwować TX po stronie kontrolera lub transceivera oraz surową magistralę.",
"expected":"Aktywność TXD bez ramek na magistrali wskazuje transceiver lub fizyczny TX; brak TXD przy działającym ECU kieruje do logiki lub konfiguracji.",
"interp":"Poprawna warstwa fizyczna jest konieczna, ale niewystarczająca.",
"next":"Rozdzielić aplikację, kontroler CAN i transceiver.",
"confidence":"Wysoka."
},
{
"category":"crank_ground_drop",
"questions":[
"ECU resetuje się przy rozruchu, ale B+ mierzony na akumulatorze wygląda dobrze. Co jeszcze mierzyć?",
"Podczas crank napięcie dodatnie na ECU jest poprawne, ale sterownik się restartuje. Jaki kolejny pomiar?",
"Reset pojawia się tylko przy dużym prądzie rozrusznika. Jak sprawdzić tor masy?",
"Na stole ECU działa, w maszynie przy rozruchu nie. Czy przewód masowy może to powodować mimo dobrej rezystancji statycznej?",
"Przy rozruchu sygnały analogowe wariują zanim ECU się zresetuje. Co to może oznaczać?"
],
"facts":"Objaw występuje przy dużym prądzie rozruchowym, a pomiar B+ w jednym punkcie nie wykazał problemu.",
"excluded":"Nie znamy dynamicznego spadku na masie ECU ani potencjału lokalnej masy.",
"hyp":"Spadek na przewodzie lub połączeniu masowym, ground bounce, problem power input, regulator lub brownout.",
"test":"Mierzyć różnicowo napięcie między GND ECU a minusem źródła oraz równolegle B+ na samych pinach ECU podczas crank.",
"expected":"Znaczny spadek masy przed resetem wskazuje tor powrotny; stabilna masa i B+ przenoszą diagnozę do wewnętrznego zasilania.",
"interp":"Pomiar napięcia tylko względem lokalnej, przesuwającej się masy może ukryć problem.",
"next":"Capture różnicowy na pinach ECU.",
"confidence":"Wysoka."
},
{
"category":"power_reverse_aftereffect",
"questions":[
"Po omyłkowym odwrotnym podłączeniu zasilania ECU pobiera duży prąd. Jak bezpiecznie zacząć?",
"Sterownik po zdarzeniu reverse polarity nie startuje, ale nie widać spalenia. Co sprawdzić?",
"Po błędnym podłączeniu polaryzacji ECU ma zwarcie na wejściu. Czy od razu podejrzewać główny regulator?",
"Prąd na zasilaczu laboratoryjnym rośnie już przy niskim napięciu po reverse polarity. Jak lokalizować?",
"ECU działa częściowo po zdarzeniu odwrotnej polaryzacji. Jak ocenić uszkodzenia wtórne?"
],
"facts":"Wystąpiło zdarzenie odwrotnej polaryzacji i obecny jest problem z wejściem zasilania lub startem.",
"excluded":"Nie wiadomo, który element ochronny lub dalszy stopień jest uszkodzony.",
"hyp":"Dioda lub MOSFET ochronny, TVS, bezpiecznik lub rezystor wejściowy, PMIC, kondensator albo zwarcie wtórne.",
"test":"Zasilać z ograniczeniem prądowym, mierzyć rezystancje szyn bez zasilania i lokalizować nagrzewanie przy bezpiecznej energii; sprawdzić napięcia przed i za elementami ochronnymi.",
"expected":"Zwarcie przed PMIC wskazuje wejściową ochronę; prawidłowe wejście z brakiem dalszych szyn kieruje do regulatorów; lokalne grzanie zawęża element.",
"interp":"Po reverse polarity nie należy podawać pełnego napięcia bez kontroli prądu.",
"next":"Sekcyjna diagnostyka power path z limitem prądowym.",
"confidence":"Wysoka."
},
{
"category":"inductive_flyback_fault",
"questions":[
"Wyjście steruje cewką, ale przy wyłączeniu pojawiają się bardzo wysokie przepięcia. Co sprawdzić?",
"Driver działa, lecz MOSFET mocno się grzeje podczas wyłączania cewki. Jak ocenić flyback?",
"Po kilku cyklach sterowania indukcyjnym obciążeniem ECU się resetuje. Jaki pomiar?",
"Na dobrym kanale przebieg wyłączenia cewki wygląda inaczej niż na uszkodzonym. Co porównywać?",
"Cewka działa, ale po jej wyłączeniu pojawia się błąd komunikacji. Jak połączyć te objawy?"
],
"facts":"Problem koreluje z energią indukcyjną przy wyłączaniu obciążenia.",
"excluded":"Nie sprawdzono ścieżki clamp lub flyback, napięcia na elemencie mocy ani sprzężenia do zasilania i masy.",
"hyp":"Uszkodzony clamp, dioda lub TVS, zła ścieżka recyrkulacji, nieprawidłowy element mocy, sprzężenie do zasilania albo masa.",
"test":"Oscyloskopem porównać napięcie wyjścia, prąd cewki i szynę zasilającą w chwili wyłączenia; zestawić z dobrym kanałem, jeśli jest.",
"expected":"Nadmierny pik na uszkodzonym kanale wskazuje problem absorpcji energii; zaburzenie szyny równocześnie z resetem lub CAN wskazuje sprzężenie do zasilania.",
"interp":"Sama poprawna aktywacja cewki nie potwierdza poprawnego wyłączania energii.",
"next":"Zlokalizować element lub ścieżkę clamp.",
"confidence":"Wysoka."
},
{
"category":"current_measurement_disagreement",
"questions":[
"ECU raportuje 1 A, a zewnętrzny miernik pokazuje 3 A. Któremu wynikowi ufać?",
"Current-sense w ECU pokazuje zero mimo widocznego prądu obciążenia. Co rozdzielić?",
"Prąd według diagnostyki rośnie, ale spadek na shuncie się nie zmienia. Jak to interpretować?",
"Zewnętrzna sonda prądowa i telemetria ECU różnią się tylko przy wysokim prądzie. Co sprawdzić?",
"Po naprawie drivera wyjście działa, lecz odczyt prądu nadal jest błędny. Co mierzyć?"
],
"facts":"Dwa niezależne źródła pomiaru prądu są niespójne.",
"excluded":"Nie ustalono kalibracji, zakresu, shuntu, wzmacniacza ani toru ADC.",
"hyp":"Błąd current-sense, shunt, wzmacniacz, filtr lub ADC, saturacja pomiaru, błąd zewnętrznego miernika albo interpretacji danych.",
"test":"Zmierz bezpośrednio spadek na elemencie pomiarowym i porównaj go z prądem niezależnym oraz napięciem na wejściu ADC lub wzmacniacza.",
"expected":"Zgodny shunt z pomiarem zewnętrznym i błędna telemetria wskazują tor sense lub software; błędny spadek na shuncie wskazuje element lub połączenie.",
"interp":"Nie wybieramy wyniku na podstawie wygody; budujemy łańcuch pomiarowy.",
"next":"Zweryfikować każdy etap od prądu do ADC.",
"confidence":"Wysoka."
},
{
"category":"adc_channel_fault",
"questions":[
"Jeden kanał ADC jest zły, a inne wejścia analogowe działają poprawnie. Jak rozdzielić pin od firmware?",
"Na pinie MCU jest poprawne napięcie, ale odczyt diagnostyczny jest błędny. Co dalej?",
"Po zamianie sygnałów między dwoma wejściami błąd zostaje na tym samym kanale ECU. Jak to interpretować?",
"Wszystkie elementy zewnętrzne wejścia sprawdzone, ale ADC pokazuje skoki. Co mierzyć przy MCU?",
"Problem jednego kanału analogowego znika po resecie ECU. Czy to dowód na software?"
],
"facts":"Problem jest ograniczony do jednego toru odczytu analogowego lub jego reprezentacji.",
"excluded":"Nie rozdzielono jeszcze analog front-end, pinu MCU, ADC i warstwy software.",
"hyp":"Filtr lub zabezpieczenie wejścia, uszkodzenie pinu MCU lub ADC, referencja ADC, konfiguracja kanału albo software.",
"test":"Porównać napięcie przed i za front-endem oraz bezpośrednio na pinie MCU; jeśli możliwe, podać znany sygnał testowy i porównać z drugim kanałem.",
"expected":"Poprawne napięcie na pinie przy błędnym kodzie ADC kieruje do MCU lub konfiguracji; rozbieżność przed pinem wskazuje front-end.",
"interp":"Poprawny sygnał w złączu nie gwarantuje poprawnego sygnału na pinie MCU.",
"next":"Prześledzić tor analogowy do punktu konwersji.",
"confidence":"Wysoka."
},
{
"category":"unknown_pinout_fail_closed",
"questions":[
"Nie mam schematu ECU, ale chcę go uruchomić na stole. Czy mogę szukać B+ omomierzem i próbować?",
"Mam złącze bez opisów pinów. Jak bezpiecznie ustalić zasilanie ECU?",
"Podejrzewam, który pin jest ignition, ale nie mam potwierdzenia. Jak postąpić?",
"Na kilku pinach jest przejście do kondensatorów wejściowych. Czy mogę podać zasilanie na pierwszy z nich?",
"Chcę znaleźć wake pin bez dokumentacji. Jakie dowody są wystarczające przed podaniem napięcia?"
],
"facts":"Pinout zasilania lub wake nie jest potwierdzony.",
"excluded":"Nie znamy dopuszczalnych napięć, funkcji pinów ani topologii zabezpieczeń.",
"hyp":"Wybrane piny mogą należeć do B+, ignition, wejść logicznych, komunikacji albo wyjść.",
"test":"Wykonać trace PCB od pinów do ochrony wejściowej, kondensatorów i regulatorów, porównać wiele mas i zasilania, a pierwszy aktywny test robić z ograniczeniem prądowym i niską energią.",
"expected":"Spójna ścieżka do elementów power-input wraz z masą i ochroną daje podstawę do kontrolowanego zasilania; niejednoznaczność oznacza brak zgody na aktywny test.",
"interp":"Próba napięciowa nie może zastąpić identyfikacji pinu.",
"next":"Zdobyć lub odtworzyć wystarczający fragment schematu wejścia.",
"confidence":"Wysoka co do zasady bezpieczeństwa."
},
{
"category":"dtc_no_measurements",
"questions":[
"Jest aktywny DTC obwodu wyjściowego, ale nie mam żadnych pomiarów. Czy można wskazać uszkodzony driver?",
"Klient podał tylko kod błędu i objaw. Jaką odpowiedź powinien dać system diagnostyczny?",
"Znam DTC i część, której dotyczy opis, ale nie mam dostępu do maszyny. Czy mogę zamówić część?",
"DTC wraca natychmiast po skasowaniu, ale nie mamy pomiaru napięć. Czy to dowód zwarcia?",
"Ten sam kod pojawia się na dwóch maszynach. Czy przyczyna powinna być taka sama?"
],
"facts":"Dostępny jest kod diagnostyczny, lecz brak pomiarów rozdzielających mechanizmy fizyczne.",
"excluded":"Nie wykluczono wiązki, zasilania, masy, obciążenia, złącza ani ECU.",
"hyp":"Wszystkie mechanizmy zgodne z opisem obwodu pozostają otwarte do czasu pomiaru.",
"test":"Wybrać minimalny zestaw pomiarów na granicy ECU i instalacji: zasilanie, masa, sygnał lub wyjście oraz ciągłość lub rezystancja obciążenia.",
"expected":"Pomiary rozdzielą problem zewnętrzny od wewnętrznego; brak danych nie uzasadnia wskazania części.",
"interp":"DTC jest wskazówką o obserwowanej nieprawidłowości, nie automatycznym root cause.",
"next":"Poprosić o konkretny pomiar o najwyższej wartości informacyjnej.",
"confidence":"Wysoka co do ograniczenia wiedzy, niska co do przyczyny."
},
{
"category":"customer_replaced_parts",
"questions":[
"Wymieniono czujnik i wiązkę, ale problem został. Klient uważa, że teraz musi być ECU. Co odpowiedzieć?",
"Dwie części zostały już wymienione bez efektu. Czy to statystycznie wskazuje sterownik?",
"Po trzech próbach naprawy klient chce od razu nowy ECU. Jak podejść technicznie?",
"Poprzedni warsztat wymienił driver, ale objaw został. Czy należy wymienić MCU?",
"Wymieniono wszystko poza ECU. Czy to wystarczający dowód na ECU?"
],
"facts":"Historia wymian nie zawiera sama w sobie pomiaru potwierdzającego przyczynę.",
"excluded":"Nie wiadomo, czy poprzednie części były testowane, poprawnie zamontowane i czy problem został zlokalizowany pomiarowo.",
"hyp":"ECU, instalacja, wspólne zasilanie lub masa, błędna diagnoza, nieprawidłowa część albo warunkowa usterka.",
"test":"Wrócić do boundary measurements i potwierdzić wejścia, zasilania, masy oraz wyjście ECU w chwili usterki.",
"expected":"Poprawne warunki wejściowe przy błędnym zachowaniu na granicy ECU wzmacniają ECU; błąd przed ECU zatrzymuje kolejną wymianę.",
"interp":"Liczba wymienionych części nie zwiększa jakości dowodu.",
"next":"Zebrać niezależny zestaw pomiarów.",
"confidence":"Wysoka."
},
{
"category":"bench_only_limit",
"questions":[
"Naprawiony ECU przechodzi test komunikacji na stole. Czy można go wydać jako w pełni sprawny?",
"Na stole wszystkie zasilania są poprawne, ale nie mamy obciążenia docelowego. Jak opisać status?",
"ECU odpowiada diagnostycznie po naprawie, lecz nie testowano funkcji mocy. Czy case jest zamknięty?",
"Sterownik działa z symulatorem, ale nie był jeszcze w pojeździe. Co powinno znaleźć się w raporcie?",
"Po klonowaniu ECU bootuje i komunikuje. Czy to kończy walidację?"
],
"facts":"Potwierdzono tylko zakres funkcji dostępny na stanowisku.",
"excluded":"Nie wykonano pełnej walidacji w docelowej instalacji, obciążeniu lub sieci.",
"hyp":"Naprawa może być poprawna, ale mogą pozostać problemy ujawniane tylko przez realne obciążenie, konfigurację lub komunikację.",
"test":"Zdefiniować brakujące funkcje i wykonać vehicle lub application verification albo odpowiedni emulator obciążenia.",
"expected":"Przejście testu docelowego pozwala zamknąć naprawę; niepowodzenie wraca do diagnostyki bez utraty wiedzy z bench testu.",
"interp":"Bench-pass należy opisać jako częściową walidację, nie pełne potwierdzenie.",
"next":"Wykonać brakujący test funkcjonalny.",
"confidence":"Wysoka."
},
{
"category":"schematic_missing",
"questions":[
"Nie mam schematu, a jeden kanał wyjściowy jest martwy. Jak działać bez zgadywania topologii?",
"PCB jest wielowarstwowe i nie widać ścieżek. Jak rozpocząć reverse engineering uszkodzonego wyjścia?",
"Znam pin złącza, ale nie wiem, który driver go obsługuje. Co mierzyć?",
"Na płycie są dwa podobne drivery. Jak ustalić, który steruje danym pinem?",
"Chcę znaleźć tor sygnałowy od złącza do MCU bez schematu. Jaka metoda?"
],
"facts":"Brakuje schematu lub mapy netów.",
"excluded":"Nie znamy pełnej topologii toru ani wszystkich elementów pośrednich.",
"hyp":"Tor może przechodzić przez ochronę, rezystory, filtr, driver, multiplexer lub bezpośrednio do MCU.",
"test":"W stanie bezpiecznym użyć continuity, diode-mode i porównania z analogicznym kanałem; dokumentować każdy potwierdzony punkt jako mapę netu.",
"expected":"Powtarzalne połączenia i komponenty referencyjne pozwalają odtworzyć tor bez przypisywania niepotwierdzonych funkcji.",
"interp":"Reverse engineering powinien budować dowody krok po kroku.",
"next":"Stworzyć minimalną mapę złącze-element-pin przed aktywnym testem.",
"confidence":"Wysoka."
},
{
"category":"pwm_low_duty",
"questions":[
"Multimetr pokazuje prawie 0 V na wyjściu PWM o bardzo małym duty-cycle. Jak potwierdzić sterowanie?",
"Zawór dostaje krótkie impulsy testowe, ale DMM nic nie pokazuje. Jak mierzyć?",
"Wyjście wygląda na martwe na mierniku, lecz słychać klik obciążenia. Jaki pomiar?",
"PWM pojawia się tylko podczas startu. Jak go uchwycić?",
"Chcę porównać dwa kanały PWM o różnych duty-cycle. Jakie parametry rejestrować?"
],
"facts":"Pomiar średni może nie pokazywać krótkich lub rzadkich impulsów.",
"excluded":"Nie zarejestrowano przebiegu czasowego.",
"hyp":"Sterowanie jest obecne z małym duty-cycle, występują tylko impulsy diagnostyczne albo wyjście faktycznie nie przełącza.",
"test":"Użyć oscyloskopu z odpowiednim triggerem i pamięcią, mierzyć oba końce obciążenia oraz prąd, jeśli to możliwe.",
"expected":"Impulsy pokażą amplitudę, czas i częstotliwość niewidoczne na DMM; brak impulsów przy oczekiwanej komendzie potwierdzi problem sterowania.",
"interp":"DMM odpowiada na inne pytanie niż oscyloskop.",
"next":"Zarejestrować pełny przebieg w warunku aktywacji.",
"confidence":"Wysoka."
},
{
"category":"flash_program_verify",
"questions":[
"Programator zgłosił sukces, ale ECU zachowuje stary identyfikator. Co zrobić zanim oskarżę pamięć specjalną?",
"Po zapisie flash część danych wygląda na starą. Jak potwierdzić, co faktycznie zostało zapisane?",
"Checksum po programowaniu jest poprawny według narzędzia, ale ECU działa jak wcześniej. Jaki kolejny krok?",
"Programowanie zakończyło się bez błędu, ale jeden blok może być chroniony. Jak to sprawdzić?",
"Po klonowaniu wynik jest częściowy. Czy można ufać samemu komunikatowi write OK?"
],
"facts":"Narzędzie zadeklarowało zapis, ale zachowanie lub identyfikatory budzą wątpliwość.",
"excluded":"Nie wykonano niezależnego pełnego read-back lub porównania blokowego.",
"hyp":"Nie zapisano wszystkich sektorów, część obszaru była chroniona, narzędzie pominęło blok, dane pochodzą z innej pamięci albo zachowanie zależy od innej konfiguracji.",
"test":"Wykonać pełny read-back tym samym zakresem adresowym i porównać blok po bloku z plikiem docelowym oraz kopią sprzed zapisu.",
"expected":"Różniący się blok bezpośrednio dowodzi niepełnego zapisu; pełna zgodność przesuwa analizę do innych pamięci lub logiki.",
"interp":"Komunikat programatora nie zastępuje weryfikacji zawartości.",
"next":"Binarny verify z mapą zakresów.",
"confidence":"Wysoka."
},
{
"category":"eeprom_unknown_structure",
"questions":[
"W EEPROM widać numery części, ale reszta danych jest niezrozumiała. Czy mogę edytować tylko string?",
"W dwóch EEPROM-ach tylko 80% bajtów jest zgodne. Jak bezpiecznie podejść do klonowania?",
"Znalazłem VIN w pamięci, ale nie znam checksum. Czy ręczny patch jest dobrym pomysłem?",
"Kilka pól EEPROM wygląda czytelnie, reszta jest binarna. Jak rozpoznać zależności?",
"Po zmianie jednego identyfikatora ECU odrzuca konfigurację. Co to sugeruje?"
],
"facts":"Struktura EEPROM nie jest w pełni znana i może zawierać dane powiązane.",
"excluded":"Nie znamy checksum, redundancji, liczników, kodowania ani relacji z inną pamięcią.",
"hyp":"Pola są powiązane checksumą lub redundancją, istnieją kopie lustrzane, liczniki albo konfiguracja krytyczna.",
"test":"Porównywać wiele obrazów, identyfikować powtarzalne regiony i zależności, a eksperymenty wykonywać wyłącznie na pełnych backupach z możliwością rollback.",
"expected":"Powtarzalne zmiany między obrazami pomagają odtworzyć strukturę; brak zrozumienia oznacza zakaz losowej edycji.",
"interp":"Czytelny string nie oznacza, że jest niezależnym polem.",
"next":"Budować mapę struktury zanim powstanie edytor lub patch.",
"confidence":"Wysoka."
},
{
"category":"thermal_localization_incomplete",
"questions":[
"Chłodzenie całego ECU przywraca funkcję. Czy można już wskazać uszkodzony element?",
"Objaw znika po sprayu chłodzącym na pół płyty. Co dalej?",
"Grzanie obudowy wywołuje błąd, ale nie wiem która sekcja jest winna. Jak zawęzić?",
"ECU reaguje na temperaturę, lecz na stole brak schematu. Jak nie zgadywać?",
"Po nagrzaniu znika komunikacja i wyjście jednocześnie. Czy to driver?"
],
"facts":"Istnieje potwierdzona zależność temperaturowa, lecz obszar jest nadal zbyt szeroki.",
"excluded":"Nie wiadomo, który sygnał pierwotnie zanika i który komponent jest źródłem.",
"hyp":"Power path, clock, reset, MCU, transceiver, driver, lut lub połączenie mechaniczne.",
"test":"Zmniejszać obszar grzania lub chłodzenia i równolegle rejestrować kluczowe szyny, reset, clock lub komunikację oraz lokalny sygnał funkcji.",
"expected":"Pierwszy elektryczny sygnał, który zmienia się razem z temperaturą, wskazuje warstwę usterki.",
"interp":"Globalna reakcja termiczna jest dowodem warunkowości, nie identyfikacją elementu.",
"next":"Termiczna segmentacja połączona z pomiarem.",
"confidence":"Wysoka co do procedury, niska co do elementu."
},
{
"category":"intermittent_no_repro",
"questions":[
"Klient zgłasza losowy błąd, ale na stole ECU działa idealnie. Co zrobić zamiast wymieniać części?",
"Usterka występuje raz dziennie i nie daje się odtworzyć. Jak zaplanować diagnostykę?",
"Brak kodów aktywnych podczas testu, ale historia błędów istnieje. Jak zwiększyć szansę złapania przyczyny?",
"ECU wróciło z opisem sporadycznie gaśnie, lecz bench test jest PASS. Co dalej?",
"Intermittent fault nie wystąpił przez godzinę testu. Czy można uznać ECU za dobre?"
],
"facts":"Usterka jest zgłoszona, ale nie została odtworzona w bieżącym teście.",
"excluded":"Nie znamy warunku wyzwalającego ani pierwszego sygnału, który zmienia się podczas zdarzenia.",
"hyp":"Temperatura, wibracja, zasilanie, wilgoć, komunikacja, obciążenie lub problem instalacji poza ECU.",
"test":"Zaprojektować logging i bodźce odtwarzające warunki zgłoszenia: temperatura, wibracja, napięcie, obciążenie i komunikacja; rejestrować sygnały przed zdarzeniem.",
"expected":"Korelacja z jednym warunkiem lub sygnałem przekształca problem losowy w powtarzalny test.",
"interp":"Brak reprodukcji nie jest dowodem braku usterki.",
"next":"Zebrać warunki wystąpienia i uruchomić monitoring zdarzeniowy.",
"confidence":"Wysoka co do metodologii."
},
]

INCOMPLETE_CATEGORIES = {
    "dtc_no_measurements", "customer_replaced_parts", "bench_only_limit",
    "unknown_pinout_fail_closed", "thermal_localization_incomplete", "intermittent_no_repro",
}

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ąćęłńóśźż]+", " ", s.lower())).strip()

def shingles(s: str, n=8):
    w = norm(s).split()
    return {tuple(w[i:i+n]) for i in range(max(0, len(w)-n+1))}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def answer(f):
    return (
        f"FAKTY: {f['facts']}\n"
        f"WYKLUCZONE: {f['excluded']}\n"
        f"HIPOTEZY: {f['hyp']}\n"
        f"TEST ROZDZIELAJĄCY: {f['test']}\n"
        f"OCZEKIWANE WYNIKI: {f['expected']}\n"
        f"INTERPRETACJA: {f['interp']}\n"
        f"NASTĘPNY KROK: {f['next']}\n"
        f"PEWNOŚĆ: {f['confidence']}"
    )

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--golden", default=str(GOLDEN_DEFAULT))
    ap.add_argument("--seed", default=str(SEED))
    ap.add_argument("--output", default=str(ROOT/"deploy/stage-p5/training/fixtures/automotive_curriculum_v2.jsonl"))
    ap.add_argument("--manifest", default=str(ROOT/"deploy/stage-p5/training/fixtures/automotive_curriculum_v2.manifest.json"))
    args=ap.parse_args()

    seed=[json.loads(x) for x in Path(args.seed).read_text().splitlines() if x.strip()]
    golden=[json.loads(x) for x in Path(args.golden).read_text().splitlines() if x.strip()]
    if not all(r.get("training_exclusion") is True for r in golden):
        raise SystemExit("P5_1_V2=FAIL golden_training_exclusion")
    forbidden_cases={c for r in golden for c in r.get("provenance",{}).get("case_ids",[])}
    gold_text=[]
    for r in golden:
        gold_text.extend([r.get("question",""), r.get("acceptable_answer",{}).get("reference","")])
    gold_norm={norm(x) for x in gold_text if x}
    gold_shingles=[shingles(x) for x in gold_text if x]

    rows=list(seed)
    next_id=21
    for fam in FAMILIES:
        target=answer(fam)
        for q in fam["questions"]:
            rid=f"P51-V2-{next_id:04d}"
            next_id+=1
            if norm(q) in gold_norm or norm(target) in gold_norm:
                raise SystemExit(f"P5_1_V2=FAIL exact_golden_overlap:{rid}")
            cand=shingles(q+" "+target)
            best=max((len(cand & g)/max(1,len(cand | g)) for g in gold_shingles),default=0.0)
            if best >= 0.70:
                raise SystemExit(f"P5_1_V2=FAIL golden_shingle_overlap:{rid}:{best:.3f}")
            rows.append({
                "record_id":rid,
                "system":SYSTEM,
                "user":q,
                "assistant":target,
                "metadata":{
                    "schema_version":2,
                    "language":"pl",
                    "category":fam["category"],
                    "training_eligible":True,
                    "source_kind":"project_owned_synthetic",
                    "source_policy":"ERS_AUTOMOTIVE_MODEL_TRAINING_STRATEGY",
                    "case_ids":[],
                    "benchmark_contamination":"checked_no_direct_case_or_record_reuse",
                    "incomplete_evidence": fam["category"] in INCOMPLETE_CATEGORIES,
                },
            })

    ids=[r["record_id"] for r in rows]
    if len(ids)!=len(set(ids)):
        raise SystemExit("P5_1_V2=FAIL duplicate_ids")
    normalized=[norm(r["user"]+" "+r["assistant"]) for r in rows]
    if len(normalized)!=len(set(normalized)):
        raise SystemExit("P5_1_V2=FAIL normalized_duplicate")

    out=Path(args.output)
    out.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows))
    categories=sorted({r["metadata"]["category"] for r in rows})
    incomplete=sum(1 for r in rows if r["metadata"].get("incomplete_evidence"))
    manifest={
        "schema_version":2,
        "dataset_id":"automotive-curriculum-v2",
        "records":len(rows),
        "seed_v1_records":len(seed),
        "generated_v2_records":len(rows)-len(seed),
        "unique_categories":len(categories),
        "categories":categories,
        "incomplete_evidence_records":incomplete,
        "source_kinds":{"project_owned_synthetic":len(rows)},
        "reserved_benchmark_case_families":sorted(forbidden_cases),
        "golden_records_seen":len(golden),
        "golden_sha256":sha(Path(args.golden)),
        "dataset_sha256":sha(out),
        "purpose":"P5.1 contamination-safe automotive reasoning curriculum; serious calibration blocked until confirmed unbenchmarked real cases are added",
    }
    Path(args.manifest).write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("P5_1_V2_DATASET_GATE=PASS")
    print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
