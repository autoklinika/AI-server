"""Sealed from training selection: difficult, separately authored prompts/anchors.

Anchors are alternative substrings, not a reference answer for training.
Scoring is an auditable heuristic, never automatic quality acceptance.
"""
from curriculum import SYSTEM
# prompt | hypothesis anchors | test anchors | result A | result B | next A | next B | good channel applicable
CASES = [
('Nieczytelny układ przy złączu grzeje się, a odbiornik milczy. Nie znam schematu. Serwisant chce zamówić ten układ po zdjęciu obudowy. Zaproponuj diagnostykę z jednym testem i dalszymi krokami zależnymi od wyniku.', ['przeciąż','wewnętrz'], ['prąd','ogranicz'], ['maleje','spada'], ['pozostaje','utrzym'], ['obciąż','wiąz'], ['zasil','sterow'], False),
('Na parze komunikacyjnej analizator pokazuje błędy tylko po dołączeniu długiej odnogi. Pomiar rezystancji w spoczynku wygląda tak samo jak wcześniej. Czy winny jest transceiver? Wybierz jeden test, przewidź oba wyniki i dalsze kroki.', ['odbici','nadaj'], ['różnic','zbocz'], ['odnod','odbici'], ['nadaj','źródł'], ['zakończ','topolog'], ['zasil','wejści'], False),
('Po zamianie miejscami dwóch zgodnych obciążeń błąd pozostał w kanale. Sąsiadujący kanał działa. Zmierzono tylko napięcia względem obudowy. Czy można już skazać driver? Rozdziel fakty i przypuszczenia; jeden test z obiema gałęziami.', ['mas','driver'], ['spad','różnic'], ['mas','powrot'], ['stabil','brak'], ['połącze','powrot'], ['komend','sterow'], True),
('Pompa startuje na stole, lecz sterownik w pojeździe przerywa jej rozruch. Zasilacz stołowy miał inne przewody. Czy wyłączyć ochronę prądową? Podaj bezpieczny test rozdzielający i dwie ścieżki dalszej diagnostyki.', ['rozruch','doprowadz'], ['zasil','przebieg'], ['zapad','spad'], ['stabil','nie zapad'], ['przew','styk'], ['prąd','ochron'], False),
('Odczyty kilku czujników zmieniają znak błędu po włączeniu ogrzewania. Napięcie referencyjne mierzono tylko względem masy zasilacza. Nie ma zapisu masy przy przetworniku. Czy wymienić referencję? Jeden test i warunkowe kroki.', ['mas','referenc'], ['różnic','mas'], ['przesu','spad'], ['stabil','brak'], ['powrot','połącze'], ['referenc','wejści'], False),
('Odbiornik impulsów gubi zdarzenia, ale średnia z multimetru się nie zmienia. Drugi identyczny tor z tym samym generatorem liczy poprawnie. Nie znamy ustawień filtra cyfrowego. Wybierz rozdzielający pomiar i obie interpretacje.', ['zbocz','konfigur'], ['wejści','oscyloskop'], ['zniekształ','brakuje'], ['zgodn','identycz'], ['kondyc','tor'], ['konfigur','filtr'], True),
('Po wysuszeniu płytki sygnał wrócił, lecz samo dotknięcie sondą też poprawia odczyt. Brak oznaczenia aktywnego elementu. Wyjaśnij, dlaczego to nie dowód jego awarii; wybierz test i dwa dalsze kroki.', ['upływ','sond'], ['impedanc','sond'], ['zależ','zmienia'], ['niezależ','bez zmian'], ['izolac','upływ'], ['źródł','zasil'], False),
('Zamknięty przekaźnik ma sygnał ciągłości, ale obciążenie gaśnie po kilku minutach. Zasilanie cewki obserwowano jedynie przed zanikiem. Czy ciągłość wyklucza przekaźnik? Zaplanuj jeden test z dwoma wynikami.', ['styk','cewk'], ['spad','styk'], ['rośnie','pojawia'], ['mały','nie rośnie'], ['cewk','podtrzym'], ['odbior','powrot'], False),
('Sterownik resetuje się przy hamowaniu silnika, a podczas rozpędzania działa. Nie ma przebiegu zasilania w momencie resetu. Sugerowano wadę programu. Oddziel obserwację od hipotezy, podaj test i obie gałęzie.', ['przepię','program'], ['zasil','wyzwal'], ['przepię','wzrost'], ['stabil','bez zmian'], ['energi','hamow'], ['reset','watchdog'], False),
('Płyta działa po schłodzeniu okolicy generatora. Sonda pasywna zatrzymuje oscylacje także w dobrym egzemplarzu. Nie znamy parametrów kryształu. Jak wykonać jeden wiarygodny test i zinterpretować oba wyniki?', ['zegar','zasil'], ['bufor','małej pojemno'], ['zanik','niestabil'], ['stabil','obecny'], ['zasil','generator'], ['reset','peryfer'], True),
('Wzmacniacz pomiarowy nasyca się tylko przy zmianie kierunku prądu, choć pomiar między zaciskami bocznika jest powtarzalny. Identyczny kanał działa w obu kierunkach. Bez zgadywania oznaczenia układu wybierz test i dalsze kroki.', ['wspóln','wzmacni'], ['wejści','wspóln'], ['zakres','przekracz'], ['zgodn','poprawn'], ['odnies','mas'], ['wyjści','wzmocn'], True),
('Szyna opada równocześnie z zanikiem komendy enable. Miernik nie pokazuje, co nastąpiło pierwsze. Ktoś uznał, że MCU jest uszkodzony. Zaproponuj jeden pomiar ustalający kierunek przyczynowy, obie interpretacje i kroki.', ['zasil','sterow'], ['równocz','czas'], ['najpierw zasil','zasilanie przed'], ['najpierw komend','enable przed'], ['źródł','obciąż'], ['warunk','logik'], False),
]


def smoke_records():
    rows=[]
    for i,(prompt,h,t,a,b,na,nb,good) in enumerate(CASES,1):
        anchors=dict(hypotheses=h, discriminating_test=t, result_a=a, result_b=b,
                     next_a=na,next_b=nb,missing_data=['brak','nie znam','nie wiadomo','nie można'],
                     observation_vs_inference=['obserw','fakt'],
                     unsupported_component_guess=['nie można wskazać','nie identyfikuje','nie dowodzi','nie przesądza','brak podstaw'],
                     good_channel=['sprawn','dobr','identycz'])
        rows.append(dict(record_id=f'P512-SMOKE-{i:02}',system=SYSTEM,user=prompt,
                         metadata=dict(split='smoke',training_eligible=False,good_channel_applicable=good,
                                       scoring_boundary='HEURISTIC_REQUIRES_HUMAN_REVIEW'),expected_anchors=anchors))
    return rows
