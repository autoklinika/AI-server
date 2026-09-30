#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
V1=ROOT/"deploy/stage-p5/training/electronics"
V2=ROOT/"deploy/stage-p5/training/electronics_v2"
SYSTEM=(
 "Jesteś inżynierem diagnostyki elektroniki PCB. Rozumuj od pomiaru i topologii, nie od zgadywania części. "
 "Oddziel objaw od przyczyny, wskaż punkt odniesienia i stan obciążenia, porównuj dobry/zły kanał, "
 "a hipotezę uznawaj dopiero po pomiarze rozdzielającym. Odpowiadaj: "
 "DANE; MODEL/PRAWO; WNIOSKOWANIE; POMIAR/KONTROLA; ODPOWIEDŹ; PEWNOŚĆ."
)

TRAIN=[
("pcb_voltage_drop_tracing","Na zasilanej płycie szyna jest niższa tylko za jednym odcinkiem ścieżki lub złącza.",
 "Przy przepływie prądu lokalny spadek V=I·R ujawnia rezystancję ścieżki, styku, via lub lutu.",
 "Pomiar bez obciążenia może być poprawny; trzeba szukać różnicy potencjałów wzdłuż toru podczas rzeczywistego prądu.",
 "Mierz miliwolty kolejno między sąsiednimi punktami toru zasilania pod tym samym obciążeniem i porównuj z dobrym kanałem.",
 "Największy nienormalny spadek lokalizuje rezystancyjny fragment toru, niekoniecznie sam odbiornik."),
("comparative_channel_diagnosis","Kilka identycznych kanałów na PCB działa, a jeden ma inny przebieg lub napięcie.",
 "Identyczny dobry kanał jest lokalnym wzorcem topologii, punktów pracy i przebiegów dla tego samego projektu.",
 "Różnica pojawiająca się najwcześniej w torze jest bardziej diagnostyczna niż końcowy objaw.",
 "Mierz te same punkty dobrego i złego kanału w identycznym stanie: wejście, zasilanie, sterowanie, element mocy, wyjście.",
 "Porównanie kanałów skraca diagnostykę, jeśli warunki pracy są naprawdę równoważne."),
("current_injection_millivolt_mapping","Na wyłączonej płycie niskonapięciowa szyna ma podejrzenie zwarcia, ale wiele elementów jest równolegle.",
 "Przy bezpiecznym wstrzyknięciu prądu rozkład spadków mV na miedzi wskazuje kierunek przepływu prądu do zwarcia.",
 "Najcieplejszy element nie zawsze jest źródłem zwarcia; może jedynie przewodzić prąd do dalszej gałęzi.",
 "Ustal bezpieczne maksymalne napięcie szyny, ustaw limit prądu i mierz spadki mV po obu stronach cewek, zworek, via i gałęzi.",
 "Mapa spadków napięcia wraz z termiką jest mocniejszym dowodem niż sama kamera termiczna."),
("thermal_imaging_false_positive","Kamera termiczna pokazuje gorący regulator, ale nie wiadomo czy regulator jest przyczyną czy tylko dostarcza prąd do zwarcia.",
 "Temperatura pokazuje miejsce strat P, nie automatycznie pierwotną przyczynę strat.",
 "Element zasilający zwarcie może nagrzewać się bardziej niż faktycznie uszkodzony odbiornik.",
 "Porównaj moc wejście/wyjście, prąd gałęzi, spadki napięć oraz reakcję po odłączeniu downstream load.",
 "Hotspot jest wskazówką energetyczną; przyczynę potwierdza zmiana po izolacji gałęzi."),
("solder_joint_crack","Usterka znika po dociśnięciu elementu SMD lub po lekkim ugięciu płyty.",
 "Pęknięty lut tworzy rezystancję zależną od naprężenia, temperatury i drgań.",
 "Sama poprawa po nacisku lokalizuje obszar, ale nie rozróżnia lutu, via i pęknięcia elementu.",
 "Rejestruj napięcie przed i za połączeniem podczas kontrolowanego nacisku oraz wykonaj inspekcję mikroskopową bez reflow.",
 "Najpierw udowodnij zmianę elektryczną na konkretnym połączeniu; reflow przed pomiarem niszczy dowód."),
("via_barrel_crack","Sygnał przechodzi między warstwami przez via i zanika tylko przy zmianie temperatury lub naprężeniu PCB.",
 "Pęknięcie metalizacji via może zachowywać się jak rezystancja lub przerwa zależna mechanicznie.",
 "Widoczna ścieżka może być dobra, a uszkodzenie ukryte w przejściu między warstwami.",
 "Mierz ciągłość/spadek bezpośrednio między netami po obu stronach via podczas lokalnego grzania, chłodzenia i minimalnego ugięcia.",
 "Korelacja elektryczna z bodźcem mechanicznym/termicznym potwierdza problem połączenia międzywarstwowego."),
("bga_flex_fault","Funkcja MCU lub dużego BGA wraca po ugięciu płyty w określonym kierunku.",
 "Połączenia BGA mogą mieć mikropęknięcia reagujące na naprężenie, ale podobnie zachowują się via i elementy pod obudową.",
 "Reakcja na flex nie jest wystarczającym dowodem na konieczność reballingu.",
 "Koreluj flex z konkretnymi liniami zasilania, reset, clock i krytycznymi I/O; lokalizuj pierwszy sygnał, który zanika.",
 "Reballing jest uzasadniony dopiero po zawężeniu usterki do połączeń pod BGA, nie po samym objawie flex."),
("contamination_leakage","Wysokoimpedancyjne wejście zmienia wartość po wzroście wilgotności lub zabrudzeniu PCB.",
 "Warstwa zanieczyszczeń może tworzyć rezystancję powierzchniową i prądy upływu porównywalne z prądem wejścia.",
 "DMM może nie ujawnić problemu, jeśli sam ma podobnie wysoką impedancję i pomiar odbywa się w innych warunkach.",
 "Mierz prąd upływu lub napięcie w kontrolowanej wilgotności, oczyść obszar i porównaj przed/po bez zmiany innych elementów.",
 "Zmiana po kontrolowanym czyszczeniu i wilgotności wskazuje leakage powierzchniowy, nie zmianę wartości sensora."),
("passive_drift_under_bias","Rezystor lub element pasywny mierzy poprawnie bez zasilania, ale punkt pracy odpływa po kilku minutach.",
 "Wartość pasywna może zależeć od temperatury, napięcia, naprężeń lub jakości połączenia.",
 "Pomiar omomierzem przy małej energii nie odtwarza warunków pracy układu.",
 "Mierz napięcie i prąd elementu w czasie, wyznacz efektywną wartość pod biasem i porównaj z temperaturą.",
 "Element pasywny należy oceniać w warunkach zbliżonych do roboczych, gdy objaw jest zależny od obciążenia."),
("capacitor_leakage","Kondensator ma prawidłową pojemność, ale węzeł ładuje się zbyt wolno lub napięcie po odłączeniu szybko spada.",
 "Rzeczywisty kondensator ma prąd upływu równoległy do pojemności.",
 "Poprawne C nie wyklucza nadmiernego leakage, który zmienia punkt pracy wysokoimpedancyjnego obwodu.",
 "Naładuj kondensator przez znany tor, zmierz prąd ustalony lub krzywą samorozładowania i porównaj z dobrym elementem.",
 "Nadmierny prąd po fazie ładowania wskazuje leakage lub równoległą ścieżkę, nie brak pojemności."),
("ceramic_cap_crack","MLCC jest zwarty lub niestabilny po naprężeniu płyty, mimo braku śladów wizualnych.",
 "Ceramika jest krucha; pęknięcie może tworzyć upływ, zwarcie lub pojemność zależną od naprężenia.",
 "Objaw mechaniczny nie powinien być automatycznie przypisany BGA, jeśli w pobliżu są MLCC.",
 "Obserwuj rezystancję/prąd szyny podczas kontrolowanego ugięcia i izoluj podejrzany kondensator bez grzania całego obszaru.",
 "MLCC może dawać usterkę mechaniczną podobną do pękniętego lutu i wymaga osobnego potwierdzenia."),
("resistor_network_open","Jedna funkcja analogowa jest błędna, a pojedyncze rezystory wokół układu wyglądają poprawnie.",
 "Sieci rezystorowe mogą zawierać kilka powiązanych elementów i wspólny pin; przerwa jednej sekcji zmienia dzielnik lub bias.",
 "Pomiar tylko wartości między przypadkowymi pinami może maskować uszkodzoną gałąź przez ścieżki równoległe.",
 "Odtwórz wewnętrzną topologię sieci, porównaj każdą sekcję z dobrym kanałem i sprawdź napięcia w pracy.",
 "Diagnozuj sieć jako topologię wielu rezystorów, nie jako pojedynczy dwukońcówkowy element."),
("diode_leakage_reverse","Dioda przechodzi test diode-mode poprawnie, ale w układzie pojawia się nieoczekiwany prąd w kierunku zaporowym.",
 "Diode-test bada mały zakres napięcia i nie mierzy dobrze leakage przy rzeczywistym reverse bias.",
 "Element może wyglądać poprawnie na DMM, a upływać dopiero przy wyższym napięciu lub temperaturze.",
 "Zastosuj bezpieczny reverse bias przez ograniczenie prądu, mierz leakage i temperaturę, porównaj z dobrym elementem.",
 "Poprawny spadek forward nie wyklucza uszkodzenia zaporowego."),
("mosfet_partial_short","MOSFET nie jest całkowicie zwarty, ale ma nietypowy prąd przy VGS=0 i grzeje się.",
 "Uszkodzenie struktury może tworzyć leakage lub częściowo przewodzącą ścieżkę D-S/G-S bez idealnego zwarcia.",
 "Pomiar continuity może nie wykryć problemu, jeśli uszkodzenie ujawnia się pod napięciem lub temperaturą.",
 "Rozładuj gate, zmierz leakage D-S i G-S przy kontrolowanym biasie oraz porównaj z dobrym kanałem w kilku temperaturach.",
 "MOSFET może być uszkodzony częściowo; diagnoza wymaga pomiaru prądu, nie tylko testu zwarcia."),
("gate_driver_uvlo","Driver MOSFET-a przestaje przełączać przy spadku własnego zasilania, choć logika sterująca nadal działa.",
 "UVLO blokuje wyjście drivera poniżej progu, aby uniknąć niepełnego otwarcia tranzystora.",
 "Brak gate drive może być poprawną ochroną drivera, a nie jego uszkodzeniem.",
 "Mierz VDD drivera, wejście logiczne i wyjście gate równocześnie podczas powolnego obniżania zasilania.",
 "Próg, przy którym gate zostaje wyłączony i wraca z histerezą, wskazuje działanie UVLO."),
("bootstrap_cap_degradation","High-side działa przy krótkich impulsach, ale traci VGS przy dłuższym czasie włączenia.",
 "Bootstrap przechowuje ładunek potrzebny do utrzymania bramki ponad source; leakage i mała C powodują droop.",
 "Poprawny start nie gwarantuje utrzymania napięcia przez cały on-time.",
 "Mierz napięcie bootstrap względem source od początku do końca impulsu i porównaj droop z dobrym kanałem.",
 "Spadek napięcia bootstrap w czasie wskazuje problem C, leakage lub zbyt małe odświeżanie."),
("hbridge_recirculation","Prąd obciążenia indukcyjnego po zmianie kierunku nie zanika natychmiast i płynie inną ścieżką półmostka.",
 "Indukcyjność wymusza ciągłość prądu; ścieżka recyrkulacji zależy od stanów MOSFET-ów i body diode.",
 "Nietypowe napięcie na wyjściu podczas dead-time może być naturalnym skutkiem recyrkulacji.",
 "Mierz oba węzły mostka i prąd obciążenia podczas przełączenia, korelując z VGS wszystkich kluczy.",
 "Najpierw wyznacz oczekiwaną ścieżkę prądu w każdym stanie, zanim uznasz napięcie za zwarcie."),
("current_limit_signature","Wyjście mocy działa chwilę, po czym napięcie pulsuje lub cyklicznie wraca.",
 "Ochrona może działać jako stały limit, hiccup, retry lub thermal shutdown.",
 "Kształt czasowy Vout i Iout zawiera informację o mechanizmie ochrony.",
 "Rejestruj jednocześnie prąd, napięcie i enable/fault przez kilka cykli bez przekraczania energii elementu.",
 "Rozpoznanie sygnatury ochrony pozwala odróżnić przeciążenie od niestabilnego sterowania."),
("power_sequence_dependency","Kilka szyn ma poprawne wartości końcowe, lecz układ nie startuje, gdy ich kolejność jest inna.",
 "Niektóre układy wymagają zależności czasowych między core, I/O, reset, enable i power-good.",
 "Pomiar statyczny po starcie nie pokazuje błędnej sekwencji.",
 "Rejestruj wszystkie krytyczne szyny, RESET, EN i PGOOD na jednym triggerze od podania zasilania.",
 "Start diagnozuje się chronologią zdarzeń, nie zestawem końcowych napięć."),
("brownout_waveform_signature","MCU resetuje się przy krótkim obciążeniu zasilania, ale DMM pokazuje stabilne napięcie.",
 "Brownout może trwać mikro- lub milisekundy; liczy się minimalne napięcie i czas względem progu BOR.",
 "Wartość średnia nie opisuje krótkiego zapadu powodującego reset.",
 "Triggeruj oscyloskop na RESET/BOR lub spadek szyny, użyj krótkiej masy sondy i uchwyć zdarzenie przed resetem.",
 "Korelacja zapadu poniżej progu z resetem potwierdza brownout, nawet jeśli DMM nic nie pokazuje."),
("latchup_signature","Układ po zakłóceniu nagle pobiera duży prąd i wraca do normy dopiero po odłączeniu zasilania.",
 "Latch-up tworzy pasożytniczą strukturę przewodzącą podtrzymywaną prądem do czasu spadku poniżej holding current.",
 "Sam reset logiczny może nie wystarczyć, jeśli przewodzenie jest fizycznie podtrzymywane.",
 "Rejestruj prąd i napięcia I/O przed zdarzeniem, ogranicz energię i sprawdź czy pełny power-cycle usuwa stan.",
 "Nagły trwały wzrost prądu po impulsie z odzyskaniem dopiero po power-cycle jest zgodny z latch-up."),
("esd_latent_damage","Po zdarzeniu ESD układ działa, ale jeden pin ma większy leakage lub gorsze progi logiczne.",
 "ESD może częściowo uszkodzić strukturę wejściową bez natychmiastowego zwarcia.",
 "Funkcjonalny test pass nie wyklucza degradacji parametrów elektrycznych.",
 "Porównaj leakage, diode-mode, progi i zachowanie temperaturowe podejrzanego pinu z identycznym dobrym kanałem.",
 "Uszkodzenie ESD może być parametryczne i wymaga porównania charakterystyk, nie tylko funkcji binarnej."),
("clock_jitter_fault","Układ działa przy niższej częstotliwości, ale przy nominalnym zegarze pojawiają się losowe błędy.",
 "Jitter zmienia położenie zboczy i zmniejsza margines czasowy setup/hold.",
 "Poprawna częstotliwość średnia nie gwarantuje poprawnej jakości zegara.",
 "Mierz period jitter lub time-interval-error oraz amplitudę/zbocza zegara w punkcie odbiornika.",
 "Problemy zależne od częstotliwości mogą wynikać z jakości czasowej zegara, nie tylko logiki."),
("i2c_bus_stuck","SDA pozostaje LOW i cała magistrala I2C przestaje działać.",
 "I2C używa open-drain; każdy uczestnik może legalnie lub błędnie trzymać linię nisko.",
 "Sam pomiar 0 V nie wskazuje, które urządzenie wymusza stan.",
 "Sprawdź SCL, kolejno izoluj uczestników i obserwuj powrót SDA; mierz też prąd przez pull-up oraz sekwencję recovery clocks.",
 "Stuck-low lokalizuje się przez segmentację uczestników i stan protokołu, nie przez wymianę pull-up w ciemno."),
("spi_signal_integrity","SPI działa przy niskiej prędkości, a przy szybszym zegarze pojawiają się błędy bitów.",
 "Push-pull SPI jest wrażliwe na ringing, crosstalk, timing i punkt pomiaru przy szybkich zboczach.",
 "Zwiększenie częstotliwości może ujawnić integralność sygnału mimo poprawnej logiki DC.",
 "Mierz SCLK, MOSI, MISO i CS przy odbiorniku, porównaj timing do zbocza próbkowania i wpływ rezystora szeregowego.",
 "Najpierw rozdziel problem amplitudy/ringingu od problemu setup/hold."),
("uart_level_fault","UART ma poprawny baud rate w analizatorze, ale odbiornik okresowo widzi błędne znaki.",
 "UART wymaga poprawnych poziomów logicznych, polaryzacji, punktu odniesienia i tolerancji zegara.",
 "Poprawne dekodowanie części ramek nie wyklucza marginalnych progów lub ground offset.",
 "Mierz poziomy na pinie odbiornika względem jego lokalnej masy i sprawdź czas bitu oraz błędy przy zmianie obciążenia.",
 "Baud rate jest tylko jedną częścią diagnozy UART; poziom i referencja są równie ważne."),
("analog_mux_leakage","Nieaktywny kanał multipleksera wpływa na aktywny pomiar analogowy.",
 "Analog switch ma off-leakage, charge injection, rezystancję ON i pasożytnicze pojemności.",
 "Wysokoimpedancyjne źródło może być wrażliwe na mikroampery lub nawet nanoampery upływu.",
 "Porównaj napięcie przy odłączonym mux, zmieniaj stan sąsiednich kanałów i mierz błąd względem impedancji źródła.",
 "Wpływ nieaktywnego kanału może wynikać z leakage/charge injection bez zwarcia wewnętrznego."),
("opamp_output_current_limit","Op-amp ma poprawne wejścia i feedback, ale wyjście zapada tylko przy małej rezystancji obciążenia.",
 "Stopień wyjściowy ma ograniczony source/sink current i swing zależny od prądu.",
 "Poprawna praca bez obciążenia nie dowodzi zdolności napędzania wymaganej impedancji.",
 "Zmieniaj obciążenie kontrolowanie, mierz Vout i Iout oraz temperaturę; porównaj source i sink.",
 "Zapad zależny od obciążenia przy poprawnym feedback wskazuje limit wyjścia lub zbyt ciężkie obciążenie."),
("comparator_propagation_glitch","Komparator generuje bardzo krótki impuls przy szybkim przejściu wejścia przez próg.",
 "Propagation delay, overdrive, szum i różne czasy wejść mogą tworzyć glitch nawet przy poprawnych progach DC.",
 "Pomiar wolnym DMM nie pokaże problemu czasowego.",
 "Mierz oba wejścia i wyjście na jednym oscyloskopie z triggerem na glitch; sprawdź wpływ histerezy i slew input.",
 "Krótkie błędy komparatora diagnozuje się w domenie czasu, nie wyłącznie napięciami progowymi."),
("feedback_loop_instability","Regulator ma poprawne DC, ale po skoku obciążenia długo oscyluje.",
 "Pętla sprzężenia ma skończony margines fazy i gain; obciążenie, ESR i kompensacja zmieniają stabilność.",
 "Poprawna wartość średnia nie wyklucza małego marginesu stabilności.",
 "Zadaj kontrolowany load-step, obserwuj częstotliwość i wygasanie ringingu, porównaj z różnymi C/ESR lub kompensacją.",
 "Długie narastające lub słabo tłumione oscylacje po skoku wskazują problem dynamiki pętli."),
]

HOLDOUT=[
("current_injection_parallel_paths","Przy current injection kilka równoległych gałęzi grzeje się podobnie i nie wiadomo, gdzie jest rzeczywiste zwarcie.",
 "Prąd dzieli się według impedancji gałęzi, a temperatura zależy od lokalnej mocy I²R.",
 "Kilka hotspotów może być skutkiem rozdziału prądu, więc sama termika jest niejednoznaczna.",
 "Mierz mV drop od punktu wstrzyknięcia do kolejnych rozgałęzień i izoluj gałęzie pojedynczo przy stałym limicie energii.",
 "Kierunek i udział prądu trzeba odtworzyć elektrycznie; termika jest wsparciem, nie jedynym dowodem."),
("intermittent_via_temperature","Via ma ciągłość na zimno, ale po lokalnym grzaniu sygnał znika bez widocznego ruchu PCB.",
 "Rozszerzalność cieplna może otwierać pęknięcie metalizacji wewnątrz via.",
 "Brak reakcji na nacisk nie wyklucza defektu mechanicznego aktywowanego temperaturą.",
 "Rejestruj rezystancję/spadek przez via w czasie kontrolowanego cyklu temperatury, porównując sąsiednie przejścia tego samego netu.",
 "Powtarzalna zmiana rezystancji tylko danego via z temperaturą silnie wskazuje pęknięcie metalizacji."),
("i2c_pullup_capacitance","I2C działa przy 100 kHz, ale przy 400 kHz zbocze SDA jest zbyt wolne mimo sprawnych urządzeń.",
 "Open-drain tworzy RC z pull-up i całkowitą pojemnością magistrali; rise time zależy od R·C.",
 "Ta sama amplituda DC może być poprawna, a czas narastania naruszać wymagania przy szybszym zegarze.",
 "Zmierz rise time SDA/SCL, oszacuj pojemność lub zmień pull-up kontrolowanie i obserwuj margines czasowy.",
 "Problem może wynikać z RC magistrali, a nie z uszkodzonego transceivera I2C."),
("hbridge_crossconduction_signature","H-bridge ma krótkie, duże piki prądu tylko przy zmianie kierunku, ale obciążenie jest lekkie.",
 "Jednoczesne przewodzenie górnego i dolnego klucza tworzy shoot-through niezależny od prądu obciążenia.",
 "Piki zsynchronizowane z przejściami kierunku sugerują problem dead-time/gate timing.",
 "Mierz wszystkie krytyczne VGS oraz prąd zasilania z odpowiednim pasmem i koreluj moment nakładania stanów ON.",
 "Cross-conduction potwierdza się czasowym nakładaniem przewodzenia, nie średnim prądem silnika."),
("power_good_sequence","Wszystkie napięcia końcowe są poprawne, ale PGOOD pojawia się za późno i system nie startuje.",
 "PGOOD jest elementem sekwencji startowej i może sterować resetem lub enable kolejnych bloków.",
 "Poprawne DC po kilku sekundach nie gwarantuje spełnienia okna czasowego startu.",
 "Rejestruj Vrail, PGOOD, RESET i enable na wspólnej osi czasu od power-on.",
 "Przyczyna może leżeć w timingu supervisor/PGOOD mimo poprawnych napięć ustalonych."),
("ceramic_microphonic","Dotknięcie lub dźwięk mechaniczny powoduje mały sygnał na analogowym węźle z MLCC.",
 "Niektóre ceramiki wykazują efekt piezoelektryczny/mikrofonowy i zamieniają naprężenie mechaniczne na napięcie.",
 "Sygnał zależny od drgań nie musi pochodzić z pękniętego lutu.",
 "Obserwuj węzeł przy kontrolowanym pobudzeniu mechanicznym, porównaj po zmianie typu kondensatora lub po odsprzęgnięciu mechaniki.",
 "Powtarzalny sygnał proporcjonalny do pobudzenia może być mikrofonowością MLCC."),
("opamp_phase_margin_load","Op-amp jest stabilny bez obciążenia, ale oscyluje po podłączeniu długiego przewodu lub dużej pojemności.",
 "Obciążenie pojemnościowe dodaje biegun i zmienia margines fazy pętli sprzężenia.",
 "Sam poprawny feedback rezystorowy nie gwarantuje stabilności dla dowolnego Cload.",
 "Porównaj odpowiedź skokową dla różnych obciążeń i sprawdź wpływ rezystora izolującego na wyjściu.",
 "Oscylacja zależna od pojemności obciążenia wskazuje problem marginesu fazy, niekoniecznie uszkodzony op-amp."),
("contamination_surface_leakage_humidity","Płyta działa po wysuszeniu, ale błąd wraca przy wysokiej wilgotności wokół wysokoimpedancyjnego wejścia.",
 "Wilgoć i pozostałości jonowe obniżają rezystancję powierzchniową między netami.",
 "Wysuszenie może chwilowo usunąć objaw bez naprawienia źródła zanieczyszczeń.",
 "Kontroluj wilgotność, mierz leakage między sąsiednimi netami i porównaj po prawidłowym czyszczeniu oraz ponownym suszeniu.",
 "Zależność od wilgotności z poprawą po czyszczeniu wskazuje przewodzenie powierzchniowe."),
]

Q=[
 "Na PCB obserwuję: {s} Jak przeprowadzić diagnostykę bez zgadywania?",
 "Wyjaśnij krok po kroku, jak rozdzielić przyczyny, gdy {s}",
 "Jaki pomiar rozstrzygający wybrać w sytuacji: {s}",
 "Jak wykorzystać topologię i przebieg czasowy, gdy {s}",
 "Co jest najmocniejszym dowodem diagnostycznym, jeśli {s}",
]

def answer(f):
    return (
      f"DANE: {f[1]}\nMODEL/PRAWO: {f[2]}\nWNIOSKOWANIE: {f[3]}\n"
      f"POMIAR/KONTROLA: {f[4]}\nODPOWIEDŹ: {f[5]}\n"
      "PEWNOŚĆ: Wysoka co do procedury; wskazanie konkretnego elementu wymaga wyniku pomiaru rozdzielającego."
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
    templates=Q if split=="train" else Q[:3]
    out=[]; idx=1
    for f in families:
        for t in templates:
            out.append({
              "record_id":f"ELEC3-{split.upper()}-{idx:04d}",
              "system":SYSTEM,
              "user":t.format(s=f[1]),
              "assistant":answer(f),
              "metadata":{
                "schema_version":3,"language":"pl","category":f[0],
                "training_eligible":split=="train","split":split,
                "source_kind":"project_owned_derived_electronics_principles",
                "source_policy":"first_principles_no_external_text_copy",
                "curriculum":"electronics-foundation-v3",
              },
            }); idx+=1
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out-dir",default=str(ROOT/"deploy/stage-p5/training/electronics_v3"))
    args=ap.parse_args()
    outdir=Path(args.out_dir); outdir.mkdir(parents=True,exist_ok=True)
    train=build(TRAIN,"train"); hold=build(HOLDOUT,"holdout")
    prior=[]
    for p in [
      V1/"electronics_foundation_train_v1.jsonl",
      V1/"electronics_foundation_holdout_v1.jsonl",
      V2/"electronics_foundation_v2_train.jsonl",
      V2/"electronics_foundation_v2_holdout.jsonl",
    ]:
        prior += load(p)
    prior_text=[r["user"]+" "+r["assistant"] for r in prior]
    prior_norm={norm(x) for x in prior_text}; prior_sh=[shingles(x) for x in prior_text]
    for label,rows in (("train",train),("holdout",hold)):
        texts=[norm(r["user"]+" "+r["assistant"]) for r in rows]
        if len(texts)!=len(set(texts)): raise SystemExit(f"P5_4_DATASET=FAIL {label}_duplicate")
        for row in rows:
            raw=row["user"]+" "+row["assistant"]; n=norm(raw)
            if n in prior_norm: raise SystemExit(f"P5_4_DATASET=FAIL prior_exact:{row[record_id]}")
            sh=shingles(raw)
            best=max((len(sh&o)/max(1,len(sh|o)) for o in prior_sh),default=0)
            if best>=0.72: raise SystemExit(f"P5_4_DATASET=FAIL prior_shingle:{row[record_id]}:{best:.3f}")
    tn={norm(r["user"]+" "+r["assistant"]) for r in train}
    hn={norm(r["user"]+" "+r["assistant"]) for r in hold}
    if tn&hn: raise SystemExit("P5_4_DATASET=FAIL train_holdout_overlap")
    tp=outdir/"electronics_foundation_v3_train.jsonl"
    hp=outdir/"electronics_foundation_v3_holdout.jsonl"
    tp.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in train))
    hp.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in hold))
    manifest={
      "schema_version":3,"dataset_id":"electronics-foundation-v3",
      "train_records":len(train),"holdout_records":len(hold),
      "train_categories":len(TRAIN),"holdout_categories":len(HOLDOUT),
      "prior_records_checked":len(prior),
      "external_text_copied":False,"oem_material_used":False,"automotive_golden_used":False,
      "train_sha256":sha(tp),"holdout_sha256":sha(hp),
      "base_adapter":"electronics-foundation-v2/current",
    }
    (outdir/"electronics_foundation_v3.manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("P5_4_ELECTRONICS_V3_DATASET_GATE=PASS")
    print(json.dumps(manifest,ensure_ascii=False,sort_keys=True))

if __name__=="__main__":
    main()
