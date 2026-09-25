# AI Control Center / GUI — zatwierdzona architektura

**Projekt:** AI Platform / Serwer AI  
**Data decyzji:** 2026-09-25  
**Status:** ACCEPTED BASELINE  
**Zakres:** GUI, aplikacje domenowe, integracja z AI Platform API, observability, MCP-ready architecture

---

## 1. Cel

AI Control Center ma być centralnym interfejsem operatorskim AI Platform, ale nie monolityczną aplikacją zawierającą całą logikę systemu.

Główne założenie:

> **GUI jest cienkim klientem AI Platform. Cała logika operacyjna i domenowa pozostaje za stabilnym AI Platform API.**

AI Control Center pełni trzy role:

1. **cockpit** — szybki podgląd kondycji całej platformy,
2. **launcher** — punkt wejścia do osobnych aplikacji domenowych,
3. **panel operacyjny** — dostęp do agentów, modeli, zasobów, jobów, backupu, logów i integracji.

Nie wolno budować architektury, w której frontend komunikuje się bezpośrednio z PostgreSQL, Qdrant, Ollama, systemd lub innym backendem.

---

## 2. Nadrzędna granica architektoniczna

Dozwolony kierunek:

```text
AI Control Center / Apps
          |
          v
   AI Platform API
          |
   Capability layer
          |
   +------+------+------+------+
   |      |      |      |      |
 Agents Models Knowledge Jobs  MCP
                 |
              adapters
                 |
           Qdrant / future
```

Niedozwolony kierunek:

```text
GUI ----------> Qdrant
GUI ----------> PostgreSQL
GUI ----------> Ollama
GUI ----------> systemd
Benchmark App -> model runtime directly
Knowledge App -> vector DB directly
```

Backendy mają pozostać wymienne bez konieczności przebudowy GUI.

Przykładowo:

- Qdrant może zostać zastąpiony innym retrieval backendem,
- Ollama może zostać zastąpiona vLLM lub innym runtime,
- provider modelu może się zmienić,
- implementacja storage lub telemetry może się zmienić.

Dopóki kontrakt AI Platform API pozostaje stabilny, GUI i aplikacje nie powinny wymagać istotnych zmian.

---

## 3. Struktura głównego GUI

Zatwierdzony jest podział na trzy główne sekcje:

```text
AI CONTROL CENTER
|
+-- OPERATIONS
|   +-- Dashboard
|   +-- Agents
|   +-- Models
|   +-- Resources
|   +-- Jobs
|   +-- Backup
|   +-- Logs
|
+-- APPLICATIONS
|   +-- Knowledge
|   +-- Benchmarks
|   +-- ECU Repair Service
|   +-- future apps...
|
+-- PLATFORM
    +-- Settings
    +-- Providers
    +-- Security
    +-- Integrations
```

Control Center ma pozostać lekki. Funkcje, które zyskują na własnym wyspecjalizowanym interfejsie lub workflow, należy wydzielać jako osobne aplikacje.

Zasada:

> **Jeżeli osobna aplikacja daje lepszy UX, czytelniejszy workflow lub większą możliwość rozwoju — wydzielamy ją z Control Center.**

---

## 4. Dashboard / pierwsza strona

Pierwsza strona ma umożliwiać ocenę stanu platformy w kilka sekund.

Nie powinna być przeładowana dużymi wykresami.

### 4.1. Kompaktowy pasek statusu

Przykład:

```text
GPU/UMA 73/96 GB | RAM 61/96 GB | Storage 38% | Jobs 2 | Alerts 0
Gateway ● | Hermes ● | Knowledge ● | ComfyUI ● | PostgreSQL ● | Qdrant ●
```

Elementy mają być klikalne i prowadzić do odpowiednich widoków szczegółowych.

### 4.2. Current Work

Kompaktowy widok aktualnie wykonywanej pracy, np.:

```text
Stage N0 | RUNNING | 30_runtime_validation | 72% | 18m
```

### 4.3. Ostatnie zdarzenia

Krótki blok ostatnich istotnych zdarzeń, bez zastępowania nim pełnego logowania.

### 4.4. App Launcher

Pierwsza strona zawiera kafle aplikacji:

```text
Knowledge      READY
Benchmarks     IDLE
ERS            READY
```

Każdy kafel pozwala przejść do osobnej aplikacji.

---

## 5. Osobne aplikacje

Aplikacje są odrębnymi modułami UX, ale pozostają częścią jednej AI Platform.

Powinny współdzielić:

- logowanie i sesję,
- system uprawnień,
- design system,
- główną nawigację,
- AI Platform API,
- telemetry,
- Resource Manager,
- job system,
- notifications,
- deep-linking.

Rekomendowany model routingu:

```text
/                  -> AI Control Center
/knowledge/        -> Knowledge App
/benchmarks/       -> Benchmark App
/ers/              -> ECU Repair Service App
```

Osobna aplikacja nie oznacza osobnego backendu ani osobnego systemu autoryzacji.

---

## 6. Knowledge App

Knowledge ma być pełnoprawną aplikacją użytkową, a nie zakładką administracyjną.

Podstawowe tryby:

### 6.1. Szukaj

Surowy retrieval dla człowieka:

- fragment,
- relevance score,
- źródło,
- strona,
- możliwość otwarcia dokumentu.

### 6.2. Zapytaj AI

RAG:

- odpowiedź AI,
- claim-level citations,
- źródła,
- otwarcie źródła/dokumentu.

### 6.3. Biblioteka / Import

Docelowo aplikacja może obejmować:

- dokumenty,
- kolekcje,
- źródła,
- import,
- status ingestu,
- indeksowanie / reindeksację,
- wersje dokumentów,
- source viewer,
- Graphify / knowledge graph.

Knowledge App komunikuje się wyłącznie z Knowledge Service przez AI Platform API.

Qdrant pozostaje implementacją retrieval, a nie kontraktem GUI.

---

## 7. Benchmark App

Benchmarki są osobną aplikacją.

Planowane klasy benchmarków:

- General LLM,
- Decision Models / Routers,
- Vision,
- Embeddings,
- Automotive reasoning,
- RAG / Knowledge.

Aplikacja powinna obsługiwać:

- wybór modeli,
- wybór datasetu,
- zestawy testów,
- uruchamianie benchmarków,
- porównania,
- wyniki per-case,
- latency,
- RAM / resource usage,
- accuracy / task metrics,
- routing confidence,
- multilingual PL,
- tool selection / handoff.

### 7.1. Routing / Policy Playground

Zatwierdzony jest kierunek dodania trybu dry-run dla routerów decyzyjnych.

Przykład:

```text
INPUT:
"Sprawdź na tym zdjęciu PCB, który układ prawdopodobnie steruje zasilaniem ECU."

DOMAIN:
automotive_electronics 0.98

INTENT:
image_analysis 0.96

ROUTE:
Vision        YES
Knowledge     YES
General LLM   YES
ERS Agent     NO
```

Możliwy workflow:

```text
Dry Run -> Execute -> Compare Routers -> Add to Benchmark
```

Rzeczywiste błędne routingi mogą w przyszłości zasilać dataset benchmarkowy.

---

## 8. ECU Repair Service App

ERS ma być docelowo osobną aplikacją domenową korzystającą ze wspólnych usług AI Platform.

Nie należy implementować ERS jako kolejnej rozbudowanej zakładki Control Center.

ERS może korzystać z:

- Knowledge Service,
- Vision,
- agentów,
- modeli reasoning,
- job system,
- telemetry,
- future MCP capabilities.

Szczegółowy workflow ERS pozostaje odrębnym zakresem projektu.

---

## 9. Operations

### 9.1. Agents

Widok agentów ma pokazywać m.in.:

- RUNNING / IDLE / WAITING / BLOCKED,
- bieżący etap / krok,
- checkpoint / gate,
- runtime,
- log danego agenta.

Kontrolowane akcje mogą obejmować np. Pause / Resume / Stop / Retry step.

GUI nie może udostępniać dowolnego shell/sudo.

Operacje uprzywilejowane muszą przechodzić przez istniejący kontrolowany model privilege bridge / Platform API.

### 9.2. Models

Widok modeli powinien pokazywać:

- model,
- rolę,
- backend/provider,
- context,
- memory residency,
- stan READY / ACTIVE,
- latency / podstawową telemetrykę.

Możliwy jest także routing trace pokazujący, dlaczego wybrano konkretny model/usługę.

### 9.3. Resources

Widok Resource Managera:

- całkowita pamięć AI,
- rezerwacja systemowa,
- modele resident,
- pamięć dostępna,
- klasy priorytetu,
- aktywne lease'y.

Celem jest widoczność nie tylko "ile pamięci zajęto", ale też **dlaczego zasób został przydzielony lub odmówiony**.

### 9.4. Jobs

Centralna kolejka:

- RUNNING,
- QUEUED,
- FINISHED,
- owner/source,
- model/provider,
- resource lease,
- latency,
- wynik,
- trace.

### 9.5. Backup / DR

GUI ma pokazywać status istniejącego Stage K, m.in.:

- GlobalNAS,
- ostatni daily/weekly,
- restore validation,
- PostgreSQL dump,
- Knowledge restore/reindex status,
- platform config,
- encrypted secrets.

### 9.6. Messaging

Status kanałów może być prezentowany operacyjnie, np.:

- Telegram,
- Discord,
- Hermes,
- media capabilities.

### 9.7. Logs

Filtrowane logi użytkowe + możliwość zejścia do pełnego logu technicznego.

---

## 10. Observability / Flight Recorder

Zatwierdzony jest kierunek wydzielenia zaawansowanej observability jako osobnego modułu/aplikacji.

Preferowany fundament telemetryczny: **OpenTelemetry**, ze wsparciem dla telemetryki GenAI tam, gdzie jest to praktyczne.

Każde istotne żądanie powinno mieć trace pokazujący jego drogę przez platformę:

```text
Telegram
  -> Gateway
  -> Decision Router
  -> Knowledge / Vision
  -> Model
  -> Response
```

Trace powinien umożliwiać analizę:

- latency każdego kroku,
- model/provider,
- routing decision + confidence,
- tool calls,
- Knowledge/RAG,
- citations,
- resource lease,
- kolejkę,
- retry/error,
- wykorzystanie zasobów.

---

## 11. Replay

Trace powinien móc zostać użyty jako wejście do kontrolowanego replay.

Przykład:

```text
Original: Qwen X
Candidate: Model Y

RUN WITHOUT SIDE EFFECTS
```

Porównania mogą obejmować:

- odpowiedź,
- routing,
- latency,
- zasoby,
- RAG citations,
- tool selection.

Replay ma łączyć obserwację produkcyjnych przypadków z Benchmark App.

Domyślnie replay nie powinien wykonywać operacji z efektami ubocznymi.

---

## 12. Live System Map

Zatwierdzony jest kierunek interaktywnej mapy architektury pokazującej rzeczywisty ruch.

Przykład:

```text
Telegram -> Gateway -> Router -> Qwen
                         |
                         +-> Knowledge -> Qdrant
```

Mapa może pokazywać:

- aktywne requesty,
- przepływy,
- latency,
- problemy,
- zależności usług.

Ma to być narzędzie diagnostyczne, nie dekoracyjny diagram.

---

## 13. Incident Timeline / Time Machine

Zatwierdzony jest kierunek osi czasu incydentu.

Przykład:

```text
21:42:13 Vision loaded
21:42:16 Resource pressure 91%
21:42:17 Qwen lease preempted
21:42:19 Qwen unloaded
21:42:22 Hermes request received
21:42:23 Qwen loading
21:42:31 Hermes response 8.2 s
```

Celem jest możliwość odtworzenia stanu platformy w określonym momencie:

- modele,
- pamięć,
- lease'y,
- queue,
- requesty,
- błędy,
- zmiany stanu usług.

---

## 14. AI Operator

Control Center może posiadać interfejs języka naturalnego typu:

```text
Ask AI Platform...
```

AI Operator ma odpowiadać na pytania na podstawie rzeczywistej telemetryki i stanu AI Platform, np.:

- "Dlaczego Hermes odpowiadał 8 sekund?"
- "Co teraz zajmuje pamięć?"
- "Dlaczego Knowledge jest DEGRADED?"
- "Co wydarzyło się przed błędem o 21:46?"

AI Operator:

- korzysta z AI Platform API,
- nie otrzymuje dowolnego sudo/shell,
- nie omija capability/permission layer,
- nie wykonuje niekontrolowanych operacji administracyjnych.

Ma być narzędziem operatorskim opartym o dane platformy, a nie niezależnym chatbotem przyklejonym do GUI.

---

## 15. App Registry / Capability Registry

Aplikacje nie powinny być wpisywane na sztywno w wiele miejsc frontend/backend.

Preferowany jest centralny manifest/registry.

Przykładowy model:

```yaml
app:
  id: knowledge
  name: Knowledge
  route: /apps/knowledge

capabilities:
  - search
  - ask
  - document.read
  - document.import

exposure:
  gui: true
  agent: true
  mcp: true
```

Registry może być źródłem dla:

- App Launchera,
- routingu UI,
- permissions,
- dokumentacji capabilities,
- agent tools,
- MCP exposure.

---

## 16. MCP-ready, ale nie MCP-dependent

To jest zatwierdzona zasada architektoniczna.

> **AI Platform API pozostaje kręgosłupem systemu. MCP jest warstwą integracyjną, a nie wewnętrznym fundamentem całej platformy.**

Model:

```text
AI Control Center
       |
AI Platform API
       |
Capability Layer
       |
 +-----+------------------+
 |                        |
Internal Services      MCP Gateway/Host
                          |
                  external MCP servers
```

AI Platform może:

1. konsumować wybrane zewnętrzne MCP,
2. wystawiać wybrane własne capabilities przez MCP.

Przykładowe przyszłe capabilities:

```text
knowledge_search
knowledge_ask
get_platform_health
inspect_job
analyze_ecu_case
run_benchmark
```

Możliwe resources:

```text
knowledge://documents/...
ers://cases/...
platform://status/...
```

### 16.1. MCP i GUI

GUI nie powinno komunikować się bezpośrednio z przypadkowym serwerem MCP.

Preferowana droga:

```text
GUI
 -> AI Platform API
 -> Capability / Permission layer
 -> service or MCP
```

### 16.2. Bezpieczeństwo MCP

MCP nie otrzymuje automatycznie dostępu administracyjnego.

Capabilities powinny mieć jawny poziom dostępu, np.:

```text
READ
EXECUTE
WRITE
ADMIN
```

Integracje zewnętrzne wymagają kontrolowanego registry/whitelisty, permissions i izolacji.

---

## 17. MCP Apps

Architektura ma pozostawać gotowa na wykorzystanie interaktywnych aplikacji/widoków dostarczanych przez MCP, jeśli okaże się to użyteczne.

Przyszły Control Center może prezentować zarówno aplikacje natywne platformy, jak i zatwierdzone integracje MCP.

Przykład:

```text
APPLICATIONS

Knowledge
Benchmarks
ERS

External / MCP
GitHub
Network Inspector
Future Tool
```

Nie oznacza to automatycznego zaufania do zewnętrznego MCP.

---

## 18. A2A readiness

Nie wdrażamy A2A na siłę w pierwszej wersji GUI.

Należy jednak utrzymać granice API i agentów w sposób, który w przyszłości pozwoli na interoperacyjność agent-agent bez przebudowy domen.

Potencjalnie:

```text
Platform Agent
ERS Agent
Research Agent
```

mogą w przyszłości deklarować swoje capabilities i delegować zadania przez standardowy protokół.

---

## 19. Deep links

**Deep links są wymaganiem pierwszej klasy.**

Każdy istotny obiekt powinien posiadać stabilny adres, np.:

```text
/jobs/J-4831
/traces/T-19281
/models/qwen36
/incidents/INC-004
/knowledge/doc/D-882
/ers/cases/CASE-0002
```

Dzięki temu:

- alert Telegram może prowadzić bezpośrednio do incydentu,
- użytkownik może udostępnić link do konkretnego joba,
- AI Operator może wskazać konkretny trace,
- aplikacje mogą bezpośrednio otwierać obiekty z innych modułów.

Deep link powinien prowadzić do obiektu, a nie tylko do strony głównej danej aplikacji.

---

## 20. PWA / urządzenia mobilne

Nie planujemy osobnej natywnej aplikacji iOS/Android na obecnym etapie.

GUI ma być:

- responsywne,
- instalowalne jako PWA,
- użyteczne na desktopie,
- użyteczne na telefonie jako szybki cockpit.

Desktop:

- pełne Control Center,
- konfiguracja,
- troubleshooting,
- benchmarki,
- Knowledge,
- ERS.

Telefon:

- health,
- alerts,
- jobs,
- aktywne zadania,
- szybkie wejście przez deep link,
- podstawowe widoki operacyjne.

Nie należy próbować przenosić każdego skomplikowanego widoku desktopowego 1:1 na telefon.

---

## 21. UX / wygląd

Kierunek:

- dark mode jako naturalny domyślny wariant operatorski,
- wizualnie bliżej cockpit/system console niż klasycznego formularza administracyjnego,
- mała liczba dużych elementów na dashboardzie,
- szczegóły po kliknięciu,
- czytelne stany: healthy / warning / failed / active / idle,
- wspólny design system wszystkich aplikacji.

GUI ma być spokojne i operacyjne, a nie efektowne kosztem czytelności.

---

## 22. Zakres odrzucony / niezatwierdzony na 2026-09-25

Poniższe pomysły z dyskusji **nie są obecnie wymaganiami projektu** i nie powinny zostać przypadkowo dopisane do scope bez osobnej decyzji:

- global Command Palette,
- stały Task Tray,
- Action Preview jako ogólny obowiązkowy mechanizm GUI,
- automatyczny checkpoint przed każdą zmianą,
- globalne "Explain this" przy elementach GUI,
- Diagnostic Bundle jako funkcja GUI,
- Maintenance Mode jako nowa funkcja GUI,
- WebAuthn/YubiKey step-up dla operacji administracyjnych.

Nie oznacza to zakazu ich użycia w przyszłości. Po prostu nie należą do aktualnie zatwierdzonego baseline.

---

## 23. Priorytety implementacyjne

### Faza GUI-0 — fundament

1. shell AI Control Center,
2. routing i wspólny layout,
3. AI Platform API client,
4. Operations / Applications / Platform,
5. kompaktowy Dashboard,
6. App Registry,
7. deep links,
8. responsywność + PWA.

### Faza GUI-1 — aplikacje podstawowe

1. Knowledge App,
2. Benchmark App,
3. integracja ERS App / placeholder i kontrakt.

### Faza GUI-2 — observability

1. Flight Recorder,
2. trace viewer,
3. Replay,
4. Live System Map,
5. Incident Timeline.

### Faza GUI-3 — AI-native operations

1. AI Operator,
2. routing/policy playground,
3. integracja rzeczywistych przypadków z Benchmark App.

### Faza GUI-4 — integracje

1. Capability Registry,
2. MCP Gateway/Host,
3. wybrane wewnętrzne MCP exposures,
4. wybrane zewnętrzne MCP integrations,
5. ewentualne MCP Apps,
6. A2A readiness / późniejsza interoperacyjność agentów.

Kolejność faz może zostać dostosowana do bieżących etapów AI Platform, ale granice architektoniczne tego dokumentu pozostają obowiązujące.

---

## 24. Definition of Done dla architektury GUI

Architektura GUI jest zgodna z tym baseline, jeżeli:

- frontend nie komunikuje się bezpośrednio z backendami infrastrukturalnymi,
- wszystkie aplikacje używają stabilnego AI Platform API,
- Control Center pozostaje cockpit/launcherem, a nie monolitem,
- Knowledge i Benchmarks są osobnymi aplikacjami,
- ERS jest traktowany jako osobna aplikacja domenowa,
- nowe duże workflow mogą być wydzielane jako kolejne aplikacje,
- App Registry nie wymaga twardego kodowania aplikacji w wielu warstwach,
- MCP jest integracją, a nie kręgosłupem platformy,
- observability ma trace/telemetry możliwe do wykorzystania przez Replay i AI Operator,
- deep links obejmują ważne obiekty,
- GUI działa responsywnie i jest przygotowane jako PWA,
- wymiana Qdrant/Ollama/providerów nie wymaga przepisywania GUI.

---

## 25. Decyzja końcowa

Przyjęty kierunek można streścić następująco:

```text
AI CONTROL CENTER = cockpit + launcher + operations

APPLICATIONS
  Knowledge
  Benchmarks
  ERS
  future domain apps

ALL UI
  -> AI Platform API
  -> Capability Layer
  -> internal services / adapters / MCP

OBSERVABILITY
  traces + replay + system map + incident timeline

INTEGRATIONS
  MCP-ready, not MCP-dependent

ACCESS
  desktop-first full GUI
  responsive mobile cockpit
  PWA
  deep links
```

Ten dokument jest bazowym kontraktem projektowym dla kolejnych prac nad AI Control Center / GUI.
