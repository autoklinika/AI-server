# Granite — audyt źródeł GOLD z oryginalnego eksportu ChatGPT

**Data: 30.10.2026 | AI Platform / Serwer AI | Status: przygotowane źródła, etykiety GOLD nadal niezatwierdzone**

## Odbiór archiwum

- Eksport ZIP: **665 577 843 B**; przechowywany prywatnie na NVMe.
- **1576/1576** wpisów przeszło pełną kontrolę CRC, bez zaszyfrowanych wpisów, duplikatów nazw, ścieżek absolutnych, odwołań `..` i symlinków.
- SHA-256 archiwum został zapisany **wyłącznie w prywatnym manifestcie**.
- Historia z sześciu `conversations-000…005.json`, razem **545 rozmów**, zakres **10.02.2025–26.10.2026 UTC**.
- Wstępnie **174** rozmowy tematyczne o AI Platform, ECU, Vision, Magazynie i infrastrukturalnych zagadnieniach. `chat.html`, `codex.json` i binarne załączniki nie były potrzebne do przygotowania Gold; ZIP nie został hurtowo rozpakowany.

## Izolacja i dobór kandydatów

- Po weryfikacji aktywnych ścieżek rozmów: **2903 unikalne kwalifikujące się wypowiedzi** techniczne, wybrane z oryginalnych wiadomości użytkownika (bez automatycznego etykietowania).
- **59** przykładów pokrywających się z dotychczasowymi materiałami Silver/68 cytatami wykluczono. Dodatkowy test na pozostałych archiwalnych plikach Granite nie wykrył dokładnych konfliktów treści z wybranym zestawem.
- **98** wiadomości z niezweryfikowanymi załącznikami multimedialnymi odłożono; nie mogą zostać fałszywie oznaczone jako testy wizji bez dostępnego obrazu.
- **250** kandydatów z **155 odrębnych rozmów** zostało zamrożonych do przyszłej niezależnej oceny. Metoda doboru była zdefiniowana przed uruchamianiem jakichkolwiek predykcji Granite na tych przypadkach.

| Obszar źródeł | Wpisów do zaślepionej oceny |
|---|---:|
| ECU / diagnostyka | 88 |
| AI Platform | 73 |
| Vision / robotyka | 45 |
| Serwer / DevOps / bezpieczeństwo | 38 |
| Magazyn | 6 |
| **Łącznie** | **250** |

Pierwszy wariant próbki nadmiernie reprezentował ECU; został zastąpiony **wersją zbalansowaną** (poprzedni szkic jest oznaczony jako zastąpiony, nie używać go do recenzji). Magazyn ma mało wpisów w granicach tego eksportu, więc nie wyrównywano kategorii sztucznymi przykładami.

## Dowód pochodzenia i ochrona prywatności

Niezależna kontrola **ponownie otworzyła oryginalny eksport** i sprawdziła:
- **250/250** oryginalnych identyfikatorów wiadomości i przynależność do aktualnej gałęzi danej rozmowy;
- **352/352** odwołania do wcześniejszych wiadomości, ich kolejność i SHA-256 oryginalnej treści;
- integralność dwóch osobnych kolejek dla recenzentów i niezmienność zamrożonych danych;
- brak etykiet Gold, wyników Granite, AI-podpowiedzi tras i zgód na wykonanie narzędzi w zestawach recenzenckich.

Wykluczono treści z podejrzeniem sekretów, maskowano wykryte numery telefonów, adresy IP, ścieżki kont i linki. Wersje oryginalne pozostają wyłącznie w chronionym archiwum. Katalogi mają uprawnienia 0700, pliki 0600. **Żadnych wypowiedzi, identyfikatorów ani obrazów nie publikowano do repo GitHub.** Przed udostępnieniem danych recenzentom konieczny jest jeszcze ręczny przegląd poufności i bezpieczna dystrybucja.

## Niezależny GOLD — nierozstrzygnięty etap

**Źródła są autentycznie powiązane z eksportem, jednak nie oznacza to gotowego GOLD.** Obie zaślepione kolejki mają po 250 nierozstrzygniętych pozycji; brak uwierzytelnionych ocen recenzentów.

Do certyfikacji potrzebne są:
1. Dwaj niezależni, rzeczywiści recenzenci, uwierzytelnieni i pracujący bez dostępu do odpowiedzi Granite oraz do wzajemnych ocen.
2. Indywidualne etykiety `route/clarify/fallback/no_action`, a dla `route` i `fallback` odpowiednio dozwolona trasa / capability; wyjaśnienie i kontrola kontekstu.
3. Rozstrzygnięcie różnic przez człowieka oraz wykluczenie przypadków niedających się zweryfikować.
4. Niezmienny finalny holdout, źródłowe oddzielenie od treningu/walidacji oraz benchmark wykonywany **dopiero po zatwierdzeniu etykiet**.

**Zatwierdzony niezależny GOLD: 0.** Nie uruchamiano Granite na 250 wybranych przypadkach i nie używano ich do nowego treningu.

## Dalsze prace i odtwarzalność

Prywatne ślady na serwerze: `/srv/ai-data/staging/granite-gold-export-inbox-20261030` (archiwum i skrypty integralności) oraz `/srv/ai-data/staging/granite-gold-review-export-balanced-20261030` (zamrożony manifest, źródła, dwie kolejki, protokół i raport weryfikacji).

W chwili audytu produkcyjny Resource Manager był `IDLE`. Nie uruchomiono GPU, nie zmieniano produkcyjnego routingu ani Qwena. Powiązana implementacja Granite v4 pozostaje wyłącznie w **[roboczym PR #182](https://github.com/autoklinika/AI-server/pull/182)**.

**Status: `EXPORT_ZIP_INTEGRITY_PASS`; `MESSAGE_PROVENANCE_250_PASS`; `BLIND_REVIEW_QUEUES_READY`; `INDEPENDENT_GOLD_PENDING`; `PRODUCTION_CUTOVER_BLOCKED`.**
