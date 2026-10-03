# ADR-009 — Shared Technical Reasoning + Domain Adapters

**Data:** 2026-10-03  
**Status:** accepted architecture direction

## Kontekst

Bazowym modelem AI Platform pozostaje **Qwen3.8 27B**. Ten sam model ma obsługiwać
więcej niż jedną domenę techniczną: obecnie przede wszystkim automotive/ERS, ale
również analizę logów i telemetrii wentylacji WVC, a w przyszłości kolejne domeny.

Dalsze dokładanie całej wiedzy i zachowań do jednego coraz bardziej
wyspecjalizowanego adaptera automotive zwiększa ryzyko biasu domenowego i regresji
w innych zastosowaniach.

## Decyzja

Rozdzielamy trening na dwie warstwy kompetencji:

1. **shared technical reasoning** — wspólne rozumowanie techniczne,
2. **domain adapters** — specjalizacja dla konkretnej domeny.

Docelowa linia treningowa:

```text
Qwen3.8 27B
    |
    +-- technical-reasoning-vN
            |
            +-- automotive-vN
            +-- wvc-vN
            +-- kolejne domeny
```

Wspólny reasoning ma uczyć przede wszystkim:

- rozdzielania obserwacji od hipotez,
- analizy przyczynowo-skutkowej,
- wyboru pomiaru/testu o wysokiej wartości informacyjnej,
- interpretacji logów, trendów i sekwencji czasowych,
- rozdzielania sterowania od wykonania,
- porównania dobrego i złego kanału,
- pracy z niepełnymi danymi,
- poprawnego wyrażania niepewności,
- unikania zgadywania pinów, części, progów i parametrów.

Adapter domenowy ma uczyć słownictwa, typowych struktur problemu i wzorców
diagnostycznych charakterystycznych dla domeny, ale nie powinien przejmować roli
Knowledge Service.

## Kontrakt treningowy i runtime

Bazowe wagi Qwen3.8 pozostają niezmienione. Adaptery pozostają artefaktami LoRA
i nie są trwale scalane z wagami bazowymi.

Domena może być trenowana przez kontynuację zaakceptowanego adaptera
`technical-reasoning-vN`. Wynikowy adapter domenowy dziedziczy kompetencje
wspólne i dodaje specjalizację domenową.

Nie zakładamy obowiązkowego jednoczesnego stackowania wielu LoRA w runtime.
Najprostszy docelowy runtime może używać jednego artefaktu na żądanie:

- generic technical -> `technical-reasoning-vN`,
- automotive/ERS -> `automotive-vN`,
- WVC -> `wvc-vN`.

Sposób fizycznej kompozycji adapterów musi być osobno zwalidowany przed
wdrożeniem; architektura nie może zależeć od niepotwierdzonego multi-adapter
runtime.

## WVC

Nie przenosimy automatycznie danych WVC do treningu automotive.

Najpierw obecny model jest testowany ręcznie na realnych logach i telemetrii WVC.
Osobny `wvc-v1` powstaje dopiero wtedy, gdy ręczny audyt pokaże powtarzalne braki,
których nie rozwiązuje shared technical reasoning + Knowledge/RAG.

Do wag modelu nie powinny trafiać zmienne fakty instalacyjne, np.:

- mapowanie konkretnych punktów i urządzeń WVC,
- bieżące nastawy i progi,
- identyfikatory czujników,
- konfiguracja konkretnej instalacji,
- historia zmian i incydentów.

Takie informacje pozostają w Knowledge Service / telemetry API i są podawane
modelowi jako kontekst. Trening ma uczyć **jak analizować dane**, a nie
zapamiętywać konfigurację jednej instalacji.

## Wybór adaptera

Kolejność decyzji runtime:

```text
App Context
  > Explicit User Override
  > Intent Router
  > Safe Fallback
```

Zasady:

- ERS/ECU Repair Service ustawia domenę automotive,
- aplikacja WVC lub dane pochodzące z WVC telemetry API ustawiają domenę WVC,
- Telegram, Discord, StackChan i ogólny Control Center mogą korzystać z routera,
- jawny wybór użytkownika ma pierwszeństwo przed routerem,
- przy niskiej pewności routera używany jest `technical-reasoning-vN` bez
  dodatkowej specjalizacji domenowej.

Router nie ustala polityki systemu i nie podejmuje decyzji projektowych. Wykonuje
jedynie wybór zgodnie z zatwierdzonymi regułami. Docelowo może to być lekki model
decyzyjny z osobnego benchmarku routerów.

## Workflow oceny jakości

Automatyczne skrypty **nie decydują o jakości semantycznej odpowiedzi modelu**.

Skrypty mogą sprawdzać wyłącznie fakty techniczne i zbierać materiał, np.:

- integralność treningu,
- poprawność adaptera i runtime,
- błędy GPU/MES,
- completion status,
- latency i zużycie zasobów,
- deterministyczne zapisanie promptów i pełnych odpowiedzi.

Ocena jakości odpowiedzi jest wykonywana ręcznie przez AI review w pełnym
kontekście odpowiedzi. Ocena obejmuje m.in.:

- poprawność fizyczną i techniczną,
- sens toku diagnostycznego,
- jakość proponowanych pomiarów,
- rozdzielenie przyczyn,
- nieuzasadnione założenia i halucynacje,
- właściwe obchodzenie się z brakującymi danymi,
- praktyczną użyteczność dla technika,
- zachowanie w normalnej rozmowie, nie tylko w sztucznym fixture.

Na podstawie tego review AI planuje następny trening i wskazuje konkretne luki
kompetencyjne. Realne rozmowy z Telegrama, ERS i WVC są wartościowym materiałem
ewaluacyjnym, jeśli są dostępne i nadają się do użycia.

## Aktualny stan P5

P5.11 pozostaje produkcyjnym adapterem automotive do czasu świadomej promocji
następcy.

P5.12 pozostaje kandydatem do **manual semantic review**. Wynik automatycznego
anchor/sub-string scorera nie jest quality gate i nie może samodzielnie
zaakceptować ani odrzucić modelu.

W obecnej ręcznej ocenie P5.12 wykazuje użyteczne postępy w diagnostyce, natomiast
CAN/topologia/odbicia oraz current-sense/common-mode pozostają przykładami luk do
dalszej pracy.

## Konsekwencje

Korzyści:

- jeden wspólny model bazowy dla wielu domen,
- ograniczenie automotive bias w WVC,
- ponowne użycie ulepszeń reasoning między domenami,
- możliwość niezależnego rozwijania automotive i WVC,
- mniejsze ryzyko zapamiętywania zmiennej konfiguracji instalacji w wagach,
- jakość oceniana na realnej użyteczności, nie na dopasowaniu do słów-kluczy.

Koszty:

- konieczny routing domeny,
- więcej niż jedna linia adapterów do utrzymania,
- obowiązek replay/regression testów przy kolejnych treningach,
- ręczny semantic review przed promocją jakościową.

## Zasada nadrzędna

**Model ma uczyć się sposobu technicznego rozumowania; Knowledge/RAG dostarcza
zmienne fakty domenowe, a adapter domenowy specjalizuje sposób zastosowania
reasoning w danym obszarze.**
