# Granite 4.0 1B — zgodność GGUF/HF i bramka niezależnego GOLD

**26.10.2026 | AI Platform / Serwer AI | DEV-only | produkcyjny routing bez zmian**

## Wynik operacyjny

**Naprawiono konkretną rozbieżność inferencji:** wymuszony w lokalnej Ollamie strukturalny JSON Schema wpływał na semantykę pól i prowadził do niespójnych decyzji routera. Odłączenie constraintu oraz zachowanie rygorystycznego parsera po stronie Gateway poprawiło zgodność GGUF/HF na wcześniej używanej próbie diagnostycznej.

| Test / wariant | Zgodność z HF v4 | Niepoprawne kontraktowo | Mediana / p95 |
|---|---:|---:|---:|
| GGUF BF16 + Ollama `format=DECISION_SCHEMA` | 17/24 | 7/24 | 3209 / 4006 ms |
| GGUF BF16 bez `format`, walidator w Gateway | **24/24** | **0/24** | 3214 / 4032 ms |

Przed porównaniem 24 przypadków: 8 wcześniejszych zadań diagnozowano w dwóch trybach. `format=DECISION_SCHEMA`: 3/8 poprawnych kontraktowo; bez formatu: 8/8. Cztery przypadki `tool` miały przy ograniczonym JSON błędny `required_capability=other` zamiast `null`, choć `route=tool` i `selected_tools=[agent.ers]` były prawidłowe. W jednym przypadku `route=reasoning` otrzymywał `knowledge.search`, czego wariant bez schematu nie robił.

**Interpretacja:** 24/24 oznacza wyłącznie *zgodność implementacji GGUF z referencyjną predykcją HF* na **wielokrotnie używanym** zbiorze AI-only. Nie oznacza 100% trafności ani niezależnego Gold. Nie wolno trenować ani dalej kalibrować modelu na tych 24 przypadkach.

## Kontrakt wykonawczy

- Usunięto `format=DECISION_SCHEMA` z żądania Ollama w **nieaktywnym domyślnie** backendzie podglądu (PR #182).
- Model może zwrócić dowolny tekst, ale **wyłącznie** pełny JSON z czterema prawidłowymi polami przechodzi przez `parse_router_decision`. Mapowanie trasa → narzędzia jest ścisłe, a każde odstępstwo powoduje fail-closed.
- Gateway nigdy nie wykonuje narzędzi na podstawie predykcji Granite i nie zmienia odpowiedzi produkcyjnego Qwena.
- Każda próba korzystała z istniejącego globalnego RM i lokalnej Ollamy RTX, zakończona unload i `/api/ps` przed zwolnieniem lease. Brak dodatkowego schedulera/usługi systemd.

## Rzeczywiste wypowiedzi: osobna diagnostyka 68/68

Uruchomiono istniejący, prywatny zbiór **68 dosłownych cytatów użytkownika** z pakietu `granite-real-user-bench-v1-20261025`. Weryfikacja lokalnych SHA-256: 68/68; żadnego pytania nie parafrazowano, nie dodano do treningu ani nie wysłano poza lokalny serwer.

| Wskazanie Granite | Liczba |
|---|---:|
| `route` | 31 |
| `clarify` | 26 |
| `fallback` | 10 |
| `router_invalid_output` / fail-closed | 1 |
| **Suma** | **68** |

Mediana opóźnienia 3217 ms, p95 około 4019 ms. 67/68 wyników spełniało kontrakt techniczny. **Nie raportować accuracy, recall, F1 ani jakości jako zweryfikowanych** — brak niezależnych ludzkich etykiet, dla większości cytatów brak pełnego referenta lub kontekstu.

W danych istniejącego **AI-only audytu** 26 wypowiedzi miało status `needs_context` (w pięciu model wskazał `route`), pięć `not_a_request` (w czterech `route`) i siedem `out_of_scope` (w czterech `route`). To sygnał ryzyka nadmiernego routingu, lecz poprzednie etykiety same wymagają weryfikacji. Żadna automatyczna promocja do produkcji nie jest dopuszczona.

## GOLD — audyt faktycznego pochodzenia

Przygotowano **dwa zaślepione zestawy recenzenckie po 68 oryginalnych cytatów** w prywatnym katalogu (0700, pliki 0600):
`/srv/ai-data/staging/granite-router-gguf-dev-20261026/gold-review-real-68-v2`.

Źródło i kopia: 68/68 SHA-256 PASS. Kolejki **nie zawierają etykiet AI**, predykcji Granite ani etykiet innych recenzentów. Zabezpieczono również kontrolny `audit_gold_review_gate_v2.py` oraz manifest źródeł, bez modyfikacji zamrożonego testu lub zbioru treningowego.

**Bramka jest zablokowana i ma pozostać zablokowana:**
- Oryginalne identyfikatory wiadomości/transkrypty: **0/68**. Lokalne hashe dowodzą niezmienności zebranych cytatów, ale NIE ich pierwotnego pochodzenia.
- Zakończone niezależne ludzkie recenzje: **0**.
- Zatwierdzone Gold: **0**.
- Źródła do końcowej niezależnej walidacji: nadal niewystarczające.

**Do rzeczywistego Gold potrzebujemy:** oryginalnych rozmów z identyfikatorami i poprzedzającym kontekstem, dwóch niezależnych uwierzytelnionych ludzkich recenzji wraz z uzasadnieniem źródłowym, rozstrzygnięcia konfliktów oraz izolacji `train/validation/final_holdout` według grup źródłowych i podobieństwa semantycznego. Nie można zastąpić tych warunków jednomyślnością Codexa, GPT ani Granite. Użytkownik nie musi osobiście oznaczać danych, ale musi istnieć niezależny proces potwierdzenia źródeł i etykiet.

## Ograniczenia dalszych działań

1. Zachować model `granite-router-v4-tpl1:dev` wyłącznie w DEV. Nie uruchamiać produkcyjnego routing cutover ani automatycznego wykonywania narzędzi.
2. Nie używać żadnego z zestawów diagnostycznych 24, 68 lub zamrożonego 120 do poprawiania LoRA/promptu.
3. Przed kolejną decyzją jakościową zebrać **nieużywane wcześniej autentyczne przypadki** z dowodem oryginalnego transkryptu, uzyskać niezależny Gold i dopiero na nim wykonać ślepy benchmark.
4. Nie rozpoczynać automatycznej masowej inwentaryzacji dokumentów; uprzednio zablokowany audyt bezpieczeństwa `granite-large-dataset-v1-20261025` pozostaje bez zmian.

## Ślady

- Poprzedni HF: `/srv/ai-data/staging/granite-lora-dev-20261025/data/V4_DIAGNOSTIC_RESULTS_170.jsonl`.
- GGUF constrained: `/srv/ai-data/staging/granite-router-gguf-dev-20261026/gateway_v4_tpl1_frozen24_summary.json`.
- Bez constrained: `/srv/ai-data/staging/granite-router-gguf-dev-20261026/gateway_v4_unconstrained_frozen24_summary.json`.
- Rzeczywiste pytania: `/srv/ai-data/staging/granite-router-gguf-dev-20261026/real_quotes_68_gguf_unscored_report.json`.
- Audyt GOLD: `/srv/ai-data/staging/granite-router-gguf-dev-20261026/gold-review-real-68-v2/GOLD_V2_READINESS_REPORT.json`.
- Dalsze zmiany kodu, wyłącznie Draft: [PR #182](https://github.com/autoklinika/AI-server/pull/182).

**Werdykt: `GGUF/HF_RUNTIME_PARITY_DIAGNOSTIC_PASS`; `REAL_USER_ROUTER_CONTRACT_67_OF_68`; `INDEPENDENT_GOLD_0`; `PRODUCTION_CUTOVER_BLOCKED`.**
