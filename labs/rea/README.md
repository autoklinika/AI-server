# REA — odseparowane laboratorium AI Platform

Odbiór 2026-10-21: **PASS** dla REA 6.7.0 + Ghidra 12.1.4 przez CLI i MCP.
Node 24.22.0, pełny OpenJDK 21.0.12.1, Debian 13 wewnątrz kontenera.
Przetestowano syntetyczny ELF x86_64. Lokalny model językowy i rzeczywisty wsad ECU nie były częścią odbioru.

## Lokalizacja i uruchomienie

Kod na hoście: `/srv/ai-data/tools/rea-lab/labs/rea`.
Dane: `/srv/ai-data/tools/rea-lab-data`.

```bash
/srv/ai-data/tools/rea-lab/labs/rea/rea-lab --version
/srv/ai-data/tools/rea-lab/labs/rea/rea-lab doctor --provider ghidra --json
/srv/ai-data/tools/rea-lab/labs/rea/rea-lab function /input/ecu_demo pressure_to_dtc --provider ghidra --json
python3 /srv/ai-data/tools/rea-lab/labs/rea/smoke-mcp.py
```

MCP przez stdio: ten sam launcher z jedynym argumentem `mcp`.
Klient startuje proces launchera na AI Platform i obsługuje standardowy protokół MCP.
Połączenie z klientem jest kanałem stdio; serwer nie publikuje portu.
Nie uruchamiano globalnego `rea setup` i nie zmieniano konfiguracji Codexa, Hermesa ani Ollamy.

Pliki do analizy trzeba jawnie skopiować do katalogu danych `input`.
W REA używamy ścieżki `/input/nazwa_pliku`.
Raporty zapisane do `/work` pojawiają się w katalogu danych `output`.
Katalog `state` jest prywatnym katalogiem domowym REA, niezależnym od konta użytkownika hosta.

## Izolacja i zasoby

- Kontener Docker uruchamiany na czas polecenia, usuwany po zakończeniu.
- Sieć `none`, bez opublikowanych portów i dostępu do Ollamy po loopback.
- UID/GID 1000, bez roota, capabilities usunięte, no-new-privileges, standardowy seccomp.
- System plików obrazu tylko do odczytu. Wejście `/input` tylko do odczytu.
- Zapisy: wyłącznie dedykowane `/work`, `/home/node` i tymczasowe `/tmp`.
- Bez katalogów produkcyjnych, domowego katalogu hosta, tokenów, socketu Docker i GPU.
- Limit CPU: quota równoważna 2 rdzeniom; RAM 4 GiB; swap wyłączony; 256 PID.
- Sterta JVM 2 GiB; tmpfs 1 GiB mieści się w limicie RAM kontenera.
- Kontener współdzieli jądro hosta. Odbiór dotyczy analizy statycznej; nie uruchamiano badanego programu.

Obraz uruchomieniowy przypięty jest do identyfikatora SHA-256 w `image.lock`.
Archiwum Ghidry zweryfikowano sumą SHA-256 opublikowaną przy oficjalnym wydaniu.
REA pochodzi z pakietu npm `rea-agents@6.7.0`, bez skryptów instalacyjnych i opcjonalnej Fridy.
Zaobserwowany lockfile zależności jest w `acceptance/npm-package-lock.json`.
Nie wykonujemy automatycznych aktualizacji.

## Wyniki odbioru

- Ghidra doctor w wybranym zakresie: PASS. Brak Hopper/IDA/JADX i globalnego skilla jest oczekiwany; audyt całego opcjonalnego środowiska nie jest zielony.
- MCP initialize i tools/list: PASS; serwer udostępnił 207 definicji narzędzi.
- Sprawdzenie ustawień Docker i warunków wewnątrz kontenera: PASS.
- Otwieranie ELF, lista funkcji, dekompilacja, asembler i lista wywołujących: PASS.
- Funkcja `pressure_to_dtc`: poprawnie odtworzone kody 0x1234 i 0x5678 oraz próg ciśnienia 250.
- Ghidra zapisała równoważny warunek `pressure < 0xfb`; to 251 w zapisie dziesiętnym.
- Sterta 2 GiB potwierdzona w działającym JVM; pomiar RSS około 465 MiB podczas tego małego testu.
- Zamknięcie sesji: open=false, cleanup_pending=false; kontener usunięty.
- ai-gateway, ollama, hermes: identyczne stany, PID i InvocationID przed/po testach.
- Główny checkout AI-server pozostał czysty. Prace są w osobnym worktree i gałęzi.

Dowody: `acceptance/result.json` i `acceptance/pressure_to_dtc.c`.
Pełne logi odbioru znajdują się na hoście w katalogu danych `output`.
Wstępny test porównywał literalny zapis progu 250; skorygowano go po obejrzeniu równoważnego pseudokodu Ghidry. Końcowy odbiór przeszedł cały przebieg.

## Następny etap: rzeczywisty wsad ECU

Przed importem ustalamy format, procesor, endian i adres ładowania. Nie zgadujemy mapy pamięci.
Schemat `open_binary` w sprawdzonym REA 6.7.0 przyjmuje raw-binary dla 6502, x86, x86_64, ARM, ARM64 i m68k.
To nie potwierdza obsługi surowych wsadów TriCore/PowerPC przez ten interfejs, nawet jeśli sama Ghidra obsługuje procesor.
Obsługę konkretnego ECU i jakość analizy należy odebrać osobno.
Na tym etapie nie łączymy lokalnego LLM z GPU ani Resource Managerem.

## Odtworzenie obrazu

```bash
docker build -t ai-platform-rea-lab:6.7.0-ghidra12.1.4 /srv/ai-data/tools/rea-lab/labs/rea
docker image inspect ai-platform-rea-lab:6.7.0-ghidra12.1.4 --format '{{.Id}}' > /srv/ai-data/tools/rea-lab/labs/rea/image.lock
```

Nowa budowa wymaga sieci do oficjalnych repozytoriów i ponownego odbioru. Obecny launcher wymaga trzech istniejących katalogów danych, dostępnych dla UID 1000.
Obraz zawiera fixture w `/opt/fixtures`; egzemplarze wejściowe należy skopiować do katalogu `input`.
To recepta budowy i zapis zaobserwowanych zależności; nie deklarujemy identyczności bajtowej przyszłej budowy.

Źródła: [REA](https://github.com/morluto/rea), [instalacja](https://github.com/morluto/rea/blob/main/docs/installation.md), [Ghidra 12.1.4](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build).
