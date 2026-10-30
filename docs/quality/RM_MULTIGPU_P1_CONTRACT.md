# P1 — czysta ocena zasobów, DEV

P0 dopuszcza wyłącznie CPU-only P1. Produkcja pozostaje **NO-GO**. Moduły
nie są podłączone do RM, schedulerów, aplikacji ani lifecycle. Nie odkrywają
sprzętu, nie wykonują I/O, nie pobierają czasu, nie przydzielają ani nie zwalniają
zasobów. Nie ma drugiej kolejki, dziennika ani polityki dla całego hosta.

## Zaufanie i dane wejściowe

Wywołujący dostarcza niezmienną topologię, istniejący `AcceleratorRegistry`,
kompletny snapshot zobowiązań, telemetrię, żądanie i jawny zegar monotoniczny.
To deklaracje z zaufanej granicy przyszłego RM, a nie dowody tożsamości,
izolacji, dostępności ani bezpieczeństwa sprzętu. P1 nie potrafi wykryć pominiętego
zobowiązania, fałszywego pomiaru ani nieprawidłowo zadeklarowanej domeny awarii.

Modele są zamrożone, zagnieżdżenia są modelami i krotkami. Liczby są ścisłymi
nieujemnymi liczbami całkowitymi; pojemność i nowe zapotrzebowanie są dodatnie.
`bool`, liczby zmiennoprzecinkowe (także NaN/Inf), napisy zamiast liczb,
listy zamiast krotek i dodatkowe pola są odrzucane. Nie ma konwersji jednostek.
Wszystkie bajty oznaczają szczyt zużycia: ładowanie, model, KV/kontekst i narzuty
zadeklarowanej współbieżności; nie rozmiar pliku wag.

Topologia jest ponownie walidowana na obowiązkowej granicy `validate_against`
przy każdej ocenie. Walidacja obejmuje referencje, unikalność, enabled, backend,
memory_class, node i znaną górną granicę pojemności N0. Node każdej domeny musi
występować w inwentarzu N0, także dla żądania wyłącznie CPU. Topologia może opisywać
podzbiór N0. Nieznany backend N0 nie kwalifikuje urządzenia; nieznana pojemność
N0 wymaga kompletnej jawnej pojemności domeny P1. Stary kod N0 zachowuje swoje
dotychczasowe zachowanie. Znana pojemność N0 ogranicza całą przypisaną domenę,
także wspólny host RAM; P1 nie modeluje osobnych apertur UMA.

Każdy GPU ma logiczny identyfikator, niepustą zatwierdzoną przez dostawcę danych
trwałą tożsamość fizyczną i generację. P1 sprawdza strukturę i zgodność, ale nie
rozstrzyga, czy napis jest rzeczywistym UUID. Ordinal jest wyłącznie mapowaniem
w `(node, runtime)`; różne runtime mogą mieć ordinal 0. Runtime na danym node
ma jeden backend. Aliasy logiczne/fizyczne i powtórzone ordinale są zabronione.

Dedykowana domena należy do dokładnie jednego fizycznego GPU. Każdy node ma
najwyżej jedną domenę host RAM; UMA wskazuje właśnie ją. Pamięć kart nigdy nie
jest sumowana. Żądanie wskazuje dokładne urządzenia, backend/runtime, fizyczne
tożsamości, generacje i zapotrzebowania. Każdy wybrany GPU wymaga dodatniego
zapotrzebowania na swoją domenę. Dodatkowy bufor CPU może obciążać tylko host RAM
node żądania. Cudze VRAM i zdalny host RAM są niedozwolone. Nie ma wyboru GPU
ani domyślnego tensor parallelism.

## Rachunek pamięci

Snapshot jawnie zawiera obserwowane całkowite zajęcie domeny `O`, krotkę
atrybucji oraz wszystkie żywe zobowiązania `R_i`. Atrybucja `A_i` wskazuje
unikalny istniejący identyfikator alokacji w tej samej domenie. Brak wpisu
atrybucji oznacza zero potwierdzonych bajtów tej alokacji, nie zero zajęcia.
Musi zachodzić `0 <= suma(A_i) <= O <= total`. Niepewnych bajtów nie przypisuje
się alokacji: pozostają w obserwowanym zajęciu zewnętrznym. Brak obserwacji
odmawia oceny wymaganej domeny. Niepusta atrybucja bez obserwacji jest błędem.

```
external = O - suma(A_i)
committed = suma(max(R_i, A_i))
remaining = total - system_reserved - external - committed - demand
```

`remaining == 0` mieści się; wartość ujemna odmawia całemu zestawowi.
`pending`, `active` i `uncertain` są jednakowo obciążane. Nie ma TTL, cleanup,
release ani domniemania zwolnienia po anulowaniu, śmierci PID lub restarcie.
Zajęcie częściowo ładowanego modelu nie jest liczone podwójnie, a jego
niewczytana rezerwacja i niezależne zajęcie zewnętrzne nadal obciążają limit.

Kluczem jest `(domain_id, allocation_id)`. Także identyczne duplikaty są błędem,
a ponowne użycie klucza istniejącego zobowiązania przez nowe żądanie jest
zabronione. Wspólna alokacja UMA/CPU musi mieć jeden kanoniczny wpis; P1 nie
scala aliasów. Osobny bufor CPU ma osobny identyfikator i jest doliczany.
Ten sam identyfikator w różnych domenach oznacza oddzielne obciążenia.

## Odmowy i wynik

Błędy kształtu/typu zgłasza publiczny `pydantic.ValidationError`; spójności —
`ResourceInputError` z `InputCode` i identyfikatorem zasobu. Nie są zamieniane
w pozorny sukces. Sprzeczności całego dostarczonego snapshotu są błędami także
wtedy, gdy dotyczą niewybranej domeny. Wyniki operacyjne zawierają jawne kody
`RefusalCode`, posortowane deterministycznie. Brak telemetrii, nieznany stan,
stara/przyszła próbka, zła epoka, generacja lub rewizja, brak pojemności,
niezgodny wybór urządzenia i niedobór pamięci wykluczają propozycję.

Każda próbka zawiera generację, epokę, monotoniczny czas w nanosekundach oraz
stan zdrowia; próbki domen pamięci dodatkowo obserwację i atrybucję.
`0 <= now_ns - observed_at_ns <= max_age_ns` jest wymagane. Epoka snapshotu,
żądania, zegara i wymaganych próbek musi być zgodna; porównywanie samych
timestampów po restarcie nie wystarcza. Snapshot i żądanie wskazują rewizję
topologii, a żądanie także oczekiwaną rewizję snapshotu.

Wymagane są zdrowe wybrane urządzenia i żądane domeny. `busy`, `unavailable`,
`quarantined`, `unknown` odmawiają. Kwarantanna A sama nie blokuje niezależnego B.
Niezdrowa wspólna domena pamięci blokuje jej użytkowników. Jawna domena awarii
wymaga zdrowej próbki grupy i wszystkich zadeklarowanych członków; jej członek
A może więc blokować B. P1 nie wyprowadza domen awarii ze wspólnego node,
runtime ani samego współdzielenia RAM. Brak deklaracji wspólnej awarii nie
jest dowodem izolacji sprzętowej.

Wynik odmowny nie zawiera częściowych budżetów ani propozycji. Udana ocena
zawiera kanoniczne żądanie i budżety uporządkowane po identyfikatorach.
`authorizes_execution` zawsze wynosi `False`, również na propozycji;
konwersja wyniku/propozycji do `bool` jest błędem. `fits` oznacza wyłącznie
warunkowe dopasowanie do przekazanego snapshotu. Wejścia nie są mutowane.

## Obowiązki P2 i pochodzenie

P2 musi uzyskać zaufane discovery i atrybucję, komplet zobowiązań, wiarygodne
domeny awarii oraz wersjonować każdą istotną zmianę. W istniejącym RM musi
atomowo ponownie sprawdzić topologię, identyfikatory, generacje, epokę, świeżość,
rewizję, zdrowie i wszystkie budżety, a następnie zatwierdzić cały zestaw.
P1 nie tworzy rezerwacji i nie chroni przed TOCTOU ani równoległym żądaniem.
Wyniku nie wolno traktować jako uprawnienia, nawet przy takim samym numerze
rewizji. I/O nie może blokować globalnego zamka. Cleanup i zwalnianie pozostają
odrębnym protokołem istniejącego RM, z ochroną właściciela i generacji oraz
utrzymaniem kwarantanny bez zaufanego potwierdzenia.

To oryginalny kod projektu i adaptacja pojęć opisanych w P0 oraz bramce jakości
(tożsamość/generacja, jawne UNKNOWN, rewizja, brak autoryzacji). Nie kopiowano
ani nie transplantowano plików N1–N5 lub kodu zewnętrznego. Użyto istniejącego
N0 i zainstalowanego Pydantic. Audyt zewnętrzny P0 nie jest zweryfikowanym
pochodzeniem i nie stanowi podstawy twierdzeń licencyjnych.

Testy są syntetyczne, CPU-only: host 96 GiB, pierwsza RTX 16 GiB, druga RTX
parametryzowana; 48 GiB jest wyłącznie fiksturą. Nie dowodzą bezpieczeństwa
sprzętu. Osobna recenzja i zamrożony rerun supervisora pozostają wymagane;
autor nie zastępuje niezależnego recenzenta. Nie uruchamiano sprzętu ani usług.

## Regresje z osobnego przeglądu

Dodatkowy plik `tests/test_resource_foundation_p1_supervisor.py` zachowuje
niezależne przypadki kontrolne prowadzącego: między innymi obcy node, maksymalny
identyfikator domeny, częściowe ładowanie i zajętość zewnętrzna, UMA/CPU oraz
rozdzielne budżety kart. Te testy powstały oddzielnie od testów autora.
Poprawki nazw zmiennych i adnotacji typów nie zastępują testów zachowania.

## Limit host RAM a częściowa topologia

Znane limity `unified` i `host` z całego przekazanego inwentarza N0 ograniczają
wspólną domenę RAM tego samego node, również gdy urządzenie pominięto w
`topology.devices` lub jego descriptor jest wyłączony. Zmiana wyboru urządzeń
nie może zwiększać fizycznej pojemności hosta. Przy kilku znanych limitach
obowiązuje ich minimum; nie są sumowane. Dedykowane VRAM oraz limity innych
node nie ograniczają tej domeny. Nadal nie interpretujemy tych pól jako
odrębnych apertur UMA — to jawne ograniczenie obecnego kontraktu P1.
