"""Authored physical boundaries, not a table of failed components.

Each profile is exercised at load transition, temperature transition and against
an equivalent good channel. Category names describe investigation scope only.
"""
CATEGORIES = '''high_side_output low_side_output h_bridge solenoid relay injector motor can lin analog_input digital_input frequency_pwm_input sensor_5v_supply dc_dc_converter ldo reverse_polarity_protection current_sensing shunt ground_fault broken_via_track cracked_solder_joint corroded_connector thermal_fault intermittent_fault leakage_moisture short_or_current_limit excessive_esr reference_voltage oscillator_clock mcu_peripheral_vs_external duplicated_channel_reference power_vs_control'''.split()
# category | symptom | model | boundary | upstream observable | downstream observable
PROFILE_TEXT = '''high_side_output|odbiornik słabnie przy aktywnej komendzie|Stopień górny dostarcza prąd z szyny; strata na torze odejmuje napięcie odbiornika|tor między szyną drivera a wyjściem|napięcie szyny drivera|napięcie wyjścia względem tej samej masy
low_side_output|odbiornik reaguje słabo mimo komendy załączenia|Stopień dolny zamyka obwód do masy; jego spadek zmniejsza napięcie odbiornika|tor między powrotem odbiornika a masą mocy|potencjał powrotu odbiornika|potencjał masy mocy
h_bridge|napęd ma nierówne zachowanie przy zmianie kierunku|Mostek ustala różnicę napięć zacisków; poziom jednego zacisku nie opisuje energii silnika|aktywną gałąź mostka między szyną a zaciskiem|potencjał szyny aktywnej gałęzi|potencjał zacisku tej gałęzi
solenoid|siła zaworu maleje w trakcie wysterowania|Indukcyjność ogranicza narastanie prądu; opór toru zmniejsza dostępne napięcie cewki|przewód między wyjściem sterownika a cewką|napięcie na wyjściu sterownika|napięcie na zacisku cewki
relay|odbiornik za przekaźnikiem działa niestabilnie|Styk zamknięty przenosi prąd; rezystancja styku daje spadek zależny od obciążenia|zamknięty styk roboczy|potencjał wejścia styku|potencjał wyjścia styku
injector|odpowiedź elektryczna wtryskiwacza zanika w impulsie|Prąd cewki zależy od napięcia i indukcyjności; pomiar wymaga sondy odpowiedniej do przepięć|wiązkę między driverem a wtryskiwaczem|przebieg przy driverze|przebieg przy cewce
motor|silnik zwalnia przy wzroście momentu|Siła przeciwelektromotoryczna i opór wpływają na prąd; strata w przewodzie odbiera napięcie|przewód zasilający silnik|napięcie przy sterowniku silnika|napięcie przy zacisku silnika
can|ramki z odległego węzła zanikają okresowo|Magistrala różnicowa przenosi symbole; odgałęzienie może odkształcać zbocza|odgałęzienie magistrali|przebieg różnicowy przy głównej magistrali|przebieg różnicowy przy odległym węźle
lin|podrzędny węzeł nie zawsze odpowiada|Linia z podciąganiem zależy od pojemności i obciążenia; poziom stały nie dowodzi transmisji|odcinek linii do węzła|przebieg przy nadajniku nadrzędnym|przebieg przy węźle podrzędnym
analog_input|odczyt analogowy odbiega od sygnału źródła|Tor wejściowy filtruje i obciąża źródło; stała czasowa zmienia odpowiedź przejściową|filtr wejściowy|przebieg przed filtrem|przebieg za filtrem
 digital_input|wejście logiczne gubi część przełączeń|Bufor rozpoznaje poziomy względem lokalnej masy; zbocze może zostać zniekształcone w torze|tor ochrony wejścia|przebieg od strony złącza|przebieg od strony bufora
frequency_pwm_input|licznik zgłasza niestabilny okres|Układ wejściowy musi zachować zbocza; średnia napięcia nie opisuje okresu|kondycjoner impulsów|zbocza na wejściu kondycjonera|zbocza na jego wyjściu
sensor_5v_supply|wspólne zasilanie czujników zapada okresowo|Gałęzie dzielą źródło; opór wspólnego toru i nadmierny pobór dają podobny objaw|wspólny tor od regulatora do rozgałęzienia|napięcie przy regulatorze|napięcie na rozgałęzieniu
 dc_dc_converter|szyna przetwornicy siada przy pracy odbiornika|Przetwornica wymaga energii na wejściu; spadek przed nią może udawać wadę regulacji|doprowadzenie zasilania do przetwornicy|napięcie u źródła|napięcie wejścia przetwornicy
ldo|wyjście stabilizatora liniowego dryfuje|Regulacja wymaga zapasu napięcia; strata na doprowadzeniu może odebrać ten zapas|doprowadzenie wejścia stabilizatora|napięcie przed doprowadzeniem|napięcie przy wejściu stabilizatora
reverse_polarity_protection|płyta traci zasilanie podczas aktywności|Tor ochronny przewodzi energię; jego spadek zależy od stanu sterowania i prądu|blok ochrony polaryzacji|napięcie przed ochroną|napięcie za ochroną
current_sensing|raport prądu nie odpowiada zachowaniu odbiornika|Tor pomiarowy przenosi sygnał różnicowy; błąd wspólny może wejść przez niesymetrię|ścieżki pomiarowe od bocznika do wzmacniacza|napięcie różnicowe na boczniku|napięcie różnicowe na wejściu wzmacniacza
shunt|odczyt prądu zmienia się bez zmiany komendy|Pomiar Kelvina powinien wykluczać spadki toru mocy|połączenie od zacisku mocy bocznika do odczepu pomiarowego|potencjał zacisku mocy|potencjał odczepu pomiarowego
 ground_fault|kilka odczytów przesuwa się podczas pracy napędu|Wspólna impedancja masy zamienia prąd napędu w błąd odniesienia|powrót między masą sygnałową a masą zasilania|potencjał masy sygnałowej|potencjał masy zasilania
broken_via_track|napięcie dociera do sekcji tylko czasami|Przerwa lub opór połączenia może być niewidoczny bez przepływu prądu|odcinek ścieżki przechodzący między warstwami|potencjał przed przejściem warstw|potencjał za przejściem warstw
cracked_solder_joint|sekcja reaguje na niewielkie odkształcenie płytki|Połączenie lutowane może zmieniać rezystancję; korelacja mechaniczna nie lokalizuje jeszcze lutu|połączenie wyprowadzenia z polem lutowniczym|potencjał na wyprowadzeniu|potencjał na polu lutowniczym
corroded_connector|odbiornik zanika po pracy w wilgotnym środowisku|Warstwa na styku może przewodzić nieliniowo; wygląd złącza nie określa spadku|styk złącza w torze odbiornika|potencjał przed stykiem|potencjał za stykiem
thermal_fault|sekcja przestaje działać po rozgrzaniu|Temperatura zmienia parametry i rozszerzalność; objaw może pochodzić z doprowadzenia energii|doprowadzenie energii do sekcji|napięcie przed doprowadzeniem|napięcie przy sekcji
intermittent_fault|sekcja losowo resetuje się podczas pracy|Krótki zanik zasilania może zniknąć w średniej miernika|odcinek zasilania sekcji resetującej się|przebieg zasilania przed odcinkiem|przebieg zasilania przy sekcji
leakage_moisture|wejście dryfuje po zawilgoceniu|Upływ obciąża źródło o dużej impedancji i może naśladować zmianę czujnika|rezystancyjny tor między źródłem a wejściem|napięcie po stronie źródła|napięcie po stronie wejścia
short_or_current_limit|zasilanie pulsuje podczas próby uruchomienia|Ograniczenie prądu reaguje na przeciążenie; pulsowanie nie dowodzi zwarcia elementu|doprowadzenie do pulsującej sekcji|przebieg przed doprowadzeniem|przebieg przy pulsującej sekcji
excessive_esr|szyna ma duże zakłócenia podczas skoku obciążenia|Impedancja zasilania obejmuje doprowadzenie i kondensatory; tętnienie nie identyfikuje kondensatora|doprowadzenie od regulatora do kondensatora lokalnego|przebieg na wyjściu regulatora|przebieg przy kondensatorze lokalnym
reference_voltage|kilka kanałów pomiarowych dryfuje razem|Wspólne odniesienie przenosi swój błąd na wszystkie kanały|tor od źródła odniesienia do odbiornika|napięcie przy źródle odniesienia|napięcie przy odbiorniku odniesienia
oscillator_clock|komunikacja traci synchronizację|Zegar może zostać zniekształcony w buforze lub obciążony przez sondę|bufor dystrybucji zegara|przebieg na wejściu bufora|przebieg na wyjściu bufora
mcu_peripheral_vs_external|wyjście sterujące nie odpowiada oczekiwanej funkcji|Peryferium i układ zewnętrzny tworzą kaskadę; brak reakcji nie lokalizuje winy w MCU|tor między wyjściem peryferium a wejściem układu zewnętrznego|sygnał po stronie peryferium|sygnał po stronie układu zewnętrznego
duplicated_channel_reference|jeden z równoważnych kanałów działa niestabilnie|Równoważny kanał jest odniesieniem tylko przy zgodnych warunkach i obciążeniu|tor między wspólną szyną a odbiornikiem kanału|napięcie wspólnej szyny|napięcie przy odbiorniku kanału
power_vs_control|odbiornik traci funkcję mimo widocznej komendy|Komenda bez dostępnej energii nie zapewnia działania; spadek zasilania może udawać brak sterowania|tor mocy między źródłem a stopniem wykonawczym|napięcie źródła stopnia|napięcie przy stopniu wykonawczym'''
PROFILES = [dict(zip(('category','observation','model','boundary','before','after'), line.strip().split('|'))) for line in PROFILE_TEXT.splitlines()]
assert [p['category'] for p in PROFILES] == CATEGORIES
SYSTEM = 'Diagnozuj po polsku. Oddziel obserwacje od hipotez. Wybierz jeden test rozdzielający i warunkowe kroki; nie zgaduj części, pinów ani progów.'


def authored_spec(p, variant):
    b, before, after = p['boundary'], p['before'], p['after']
    shared = dict(observation=p['observation'], known_facts='Topologia badanego toru jest potwierdzona; brak lokalizacji usterki.', physical_model=p['model'],
                  unknowns=['Brak wartości granicznych producenta i identyfikacji elementów.'],
                  non_conclusion='Nie można wskazać części do wymiany ani uznać całego układu za sprawny.',
                  confidence='Pewność lokalizacji niska; brakuje zapisu podczas objawu.',
                  good_channel_applicable=variant == 3)
    if variant == 1:
        shared.update(context='Objaw pojawia się przy przejściu ze spoczynku do pracy; dopuszczalny zakres obciążenia jest znany.',
            hypotheses=[f'Strata lub zniekształcenie obejmuje {b}.', 'Zakłócenie dociera już ze strony źródła.'],
            test=dict(quantity='różnica przebiegów', points=[before, after], condition='spoczynek i dopuszczalne obciążenie, wspólna oś czasu',
                      instruction=f'Zarejestruj równocześnie {before} oraz {after} podczas przejścia spoczynek–obciążenie, bez zmiany komendy; użyj właściwej sondy różnicowej.'),
            branches=[dict(hypothesis=0, result='A: strona źródła stabilna, różnica przez tor rośnie wraz z objawem.', interpretation=f'Wynik zawęża stratę do badanego toru; nadmierny pobór za nim nadal możliwy.', next_step=f'Zarejestruj prąd odbiornika przy tym samym obciążeniu, aby oddzielić opór toru od przeciążenia.'),
                      dict(hypothesis=1, result='B: oba przebiegi pogarszają się razem, bez dodatkowej różnicy.', interpretation='Wynik osłabia hipotezę lokalnej straty i kieruje przed badany tor.', next_step='Zmierz różnicę na doprowadzeniu źródła podczas tego samego zdarzenia.')],
            trap='Prawidłowy wynik bez obciążenia nie dowodzi sprawnego toru.')
    elif variant == 2:
        shared.update(context='Objaw zależy od rozgrzania; komenda i obciążenie są powtarzalne. Nie ma pomiaru w chwili zaniku.',
            hypotheses=[f'Temperatura zmienia przenoszenie przez {b}.', 'Temperatura zmienia sygnał lub zasilanie jeszcze przed badanym torem.'],
            test=dict(quantity='zmiana różnicy zimno/ciepło', points=[before, after], condition='zimno i ciepło przy tej samej komendzie oraz obciążeniu',
                      instruction=f'Porównaj równoczesny zapis: {before} i {after}, na zimno i po naturalnym rozgrzaniu; zachowaj obciążenie i komendę.'),
            branches=[dict(hypothesis=0, result='A: tylko za torem pojawia się odchylenie na ciepło.', interpretation='Zależność cieplna leży w badanej granicy lub jej obciążeniu, bez identyfikacji elementu.', next_step='Sprawdź prąd obciążenia na zimno i ciepło przy tej samej komendzie.'),
                      dict(hypothesis=1, result='B: odchylenie na ciepło jest obecne już przed torem.', interpretation='Samo schłodzenie sekcji nie dowiedzie jej uszkodzenia; przyczyna może być wcześniej.', next_step='Zarejestruj wejście źródła na zimno i ciepło, aby oddzielić jego zasilanie od regulacji.')],
            trap='Reakcja na temperaturę nie identyfikuje konkretnego półprzewodnika.')
    else:
        shared.update(context='Dostępny jest sprawny kanał o potwierdzonej tej samej topologii; objaw nasila się nieliniowo z obciążeniem.',
            hypotheses=[f'Badany {b} ma inną charakterystykę niż odpowiednik.', 'Wspólne źródło ogranicza oba kanały w tych warunkach.'],
            test=dict(quantity='charakterystyka różnicy względem dobrego kanału', points=[before, after], condition='dwa dopuszczalne stany obciążenia, identyczne warunki kanałów',
                      instruction=f'Porównaj różnicę: {before} minus {after}, ze sprawnym kanałem w dwóch dopuszczalnych stanach obciążenia przy tej samej komendzie.'),
            branches=[dict(hypothesis=0, result='A: tylko zły kanał ma rosnącą nieliniowo różnicę.', interpretation='Wynik wspiera lokalną nieliniowość toru lub jego obciążenia, nie nazwę części.', next_step='Porównaj prądy kanałów w tym samym stanie, aby rozdzielić tor od odbiornika.'),
                      dict(hypothesis=1, result='B: oba kanały mają podobne załamanie charakterystyki.', interpretation='Wspólna przyczyna staje się bardziej prawdopodobna; dobry kanał nie jest wzorcem poza zakresem.', next_step='Zarejestruj wspólne zasilanie podczas załamania, aby sprawdzić ograniczenie źródła.')],
            trap='Inny typ kanału lub inne obciążenie nie stanowi poprawnego odniesienia.')
    # Signal paths need timing/impedance follow-ups, not a power-current recipe.
    signal_followups = {
        'can': ('Zarejestruj odbicie zbocza przy początku odnogi, aby rozdzielić niedopasowanie od zakłócenia odbiornika.', 'Porównaj logiczny sygnał nadawania z przebiegiem magistrali przy nadajniku.'),
        'lin': ('Zmierz czas narastania po zwolnieniu linii przy bezpiecznie odłączonej odnodze, aby ocenić jej obciążenie.', 'Porównaj komendę nadawania z przebiegiem przy transceiverze nadrzędnym.'),
        'analog_input': ('Zmierz odpowiedź filtra na znaną, dopuszczalną zmianę źródła, aby oddzielić stałą czasową od przesunięcia stałego.', 'Zarejestruj sygnał źródła względem jego lokalnej masy, aby sprawdzić błąd odniesienia.'),
        'digital_input': ('Zarejestruj zasilanie bufora podczas zbocza, aby oddzielić problem polaryzacji od zniekształcenia wejścia.', 'Porównaj sygnał źródła względem jego masy i masy odbiornika.'),
        'frequency_pwm_input': ('Zarejestruj zasilanie kondycjonera w chwili zgubionego zbocza, aby sprawdzić jego warunki pracy.', 'Zmierz odstępy między zboczami u źródła, aby rozdzielić generator od transmisji.'),
        'current_sensing': ('Zmierz składową wspólną wejść względem masy wzmacniacza, aby oddzielić błąd odniesienia od toru różnicowego.', 'Porównaj prąd niezależną metodą z napięciem bocznika przy tej samej komendzie.'),
        'oscillator_clock': ('Porównaj wyjście bufora sondą o mniejszej pojemności, aby rozdzielić obciążenie pomiarowe od usterki toru.', 'Zarejestruj zasilanie generatora podczas utraty zegara, aby rozdzielić źródło energii od oscylacji.'),
        'mcu_peripheral_vs_external': ('Zmierz zasilanie układu zewnętrznego podczas komendy, aby sprawdzić możliwość zaciskania sygnału przez ochronę.', 'Porównaj rejestr konfiguracji peryferium z żądanym trybem, zanim obwinisz MCU.'),
        'leakage_moisture': ('Zmierz upływ badanego odcinka po bezpiecznym odizolowaniu źródła, aby oddzielić powierzchnię PCB od odbiornika.', 'Porównaj źródło z obciążeniem o znanej dopuszczalnej impedancji, aby ocenić jego wydajność.'),
        'reference_voltage': ('Zmierz zmianę odniesienia po bezpiecznym odłączeniu jednej znanej gałęzi, aby oddzielić pobór od toru rozdziału.', 'Zarejestruj zasilanie źródła odniesienia w chwili dryfu.'),
    }
    if p['category'] in signal_followups:
        followups = signal_followups[p['category']]
        for branch, step in zip(shared['branches'], followups):
            branch['next_step'] = step + (' Zachowaj ten sam stan cieplny.' if variant == 2 else '')
    return shared


def render(s):
    return '\n'.join([
        'OBSERWACJA: '+s['observation'], 'FAKTY: '+s['known_facts'], 'MODEL: '+s['physical_model'],
        'HIPOTEZY: '+' / '.join(s['hypotheses']), 'TEST: '+s['test']['instruction'],
        *[b['result']+' Interpretacja: '+b['interpretation']+' Dalej: '+b['next_step'] for b in s['branches']],
        'PUŁAPKA: '+s['trap'], 'NIE WNIOSKUJ: '+s['non_conclusion'],
        'PEWNOŚĆ/BRAKI: '+s['confidence']+' '+' '.join(s['unknowns'])])


def new_records():
    rows=[]
    for p in PROFILES:
        for variant in (1,2,3):
            s=authored_spec(p,variant)
            rows.append(dict(record_id=f'P512-NEW-{p["category"]}-{variant}', system=SYSTEM,
                user=s['observation']+'. Potwierdzona topologia; badana granica: '+p['boundary']+'. '+s['context']+' Jak rozdzielić przyczyny?', assistant=render(s),
                metadata=dict(category=p['category'], variant=variant, split='train', training_eligible=True, language='pl', source_kind='project_owned_synthetic', p512_origin='new'), spec=s))
    return rows
