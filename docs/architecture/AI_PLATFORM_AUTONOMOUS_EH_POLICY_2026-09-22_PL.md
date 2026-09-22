# AI Platform — Autonomous Stage E–H policy

**Data:** 2026-09-22  
**Status:** control-plane policy

## Cel

Stage E–H mogą być prowadzone bez bieżącego nadzoru operatora przez lokalnego
supervisora. Codex jest wykonawcą implementacji, ale nie kontroluje GitHub ani nie
decyduje samodzielnie o dopuszczeniu własnej zmiany do produkcji.

## Rozdział odpowiedzialności

1. **Implementer (Codex, workspace-write)** — implementuje pojedynczy Stage i jego testy
   oraz przygotowuje jawny zestaw skryptów production gate.
2. **Reviewer (osobny przebieg Codex, read-only)** — ocenia diff, scope, testy, rollback
   i production gate. Brak jednoznacznego PASS blokuje etap.
3. **Supervisor** — jako jedyny wykonuje commit/push/PR/CI/merge oraz production gate.
4. **Telegram notifier** — jednokierunkowy kanał alarmowy niezależny od procesu Hermesa.
   Używa wyłącznie Bot API `sendMessage`; nie pobiera update'ów.

## Kolejność etapu

`IMPLEMENT -> DEV GATE -> INDEPENDENT REVIEW -> DEV COMMIT/PUSH -> DRAFT PR/CI
-> PREFLIGHT -> BUILD/INSTALL -> CUTOVER -> LIVE SMOKE -> ROLLBACK -> ROLLBACK SMOKE
-> REACTIVATE -> FINAL SMOKE -> EVIDENCE -> FINAL CI -> MERGE -> POST-MERGE CI`.

Następny Stage rozpoczyna się wyłącznie po pełnym PASS poprzedniego.

## Fail closed

Błąd przed cutover nie zmienia produkcji i zatrzymuje etap.

Błąd po rozpoczęciu zmian produkcyjnych uruchamia automatyczny rollback oraz smoke
poprzedniego zweryfikowanego stanu. Po rollbacku etap przechodzi do `BLOCKED`; supervisor
nie podejmuje kolejnych Stage.

Jeżeli rollback albo rollback-smoke nie przechodzi, stan jest krytyczny i supervisor
nie podejmuje dalszych automatycznych zmian.

## Telegram

Powiadomienia użytkownika są ograniczone do:
- STARTED,
- COMPLETE,
- automatyczny ROLLBACK,
- BLOCKED.

Token i docelowy chat ID nie trafiają do repo. Prywatny plik
`~/.config/ai-platform/autopilot.env` ma prawa 0600. Token może zostać skopiowany
jednorazowo z prywatnego środowiska Hermesa, lecz późniejsze wysyłanie nie zależy od
procesu, kodu ani stanu Hermesa.

## Stage F

Przed mutacją Hermesa wymagany jest snapshot odtwarzalny: wersja/commit, patch/diff,
wymagane config/state i artefakty integracyjne. Telegram multiuser, Discord, media oraz
WAIT/START są twardymi kryteriami produkcyjnymi.

## Stage H

Cleanup stosuje quarantine-first. Autopilot nie wykonuje ostatecznego, nieodwracalnego
purge. D.0/D.6 oraz ostatnie wymagane rollback points pozostają chronione do czasu
zweryfikowanego cyklu rollback Stage H.


## Launcher runtime

Supervisor E–H jest uruchamiany w odłączonej sesji `tmux`, tak jak zweryfikowany
supervisor Stage D. Nie uruchamiamy procesu Codex bezpośrednio jako user service systemd,
ponieważ lokalny sandbox Codex/bubblewrap jest niekompatybilny z tym kontekstem i może
kończyć się przed rozpoczęciem implementacji. Systemd może zarządzać usługami platformy,
ale nie jest launcherem procesu agenta Codex.


## PRE_PROD_CI resume

GitHub Actions może zarejestrować pierwszy check kilka sekund po utworzeniu draft PR.
Supervisor nie interpretuje braku jeszcze niezarejestrowanego checka jako wyniku CI:
najpierw oczekuje na workflow dla dokładnego SHA, a dopiero potem na jego zakończenie.

Jeśli starsza wersja supervisora zatrzymała się dokładnie w `PRE_PROD_CI` przed
jakąkolwiek mutacją produkcji, dozwolone jest jawne wznowienie. Resume wymaga:
czystego worktree, oczekiwanej gałęzi `agent/stage-X`, otwartego PR do `main`,
aktualizacji kandydata do bieżącego `main` oraz ponownego zielonego CI. Inne stany
nie są automatycznie konwertowane na PRE_PROD_CI.


## Read-only preflight failure

`00_preflight.sh` nie może wykonywać mutacji produkcji. Jeżeli ten krok FAIL,
supervisor normalizuje stan z powrotem do `PRE_PROD_CI`, więc etap może zostać
jawnie wznowiony po korekcie przyczyny bez rollbacku. Historyczny stan
`PRODUCTION:00_preflight.sh` z wcześniejszej wersji supervisora jest traktowany
tak samo wyłącznie przez fail-closed resume helper; inne stany `PRODUCTION:*`
nie są uznawane za bezpiecznie wznawialne.


## Privilege bridge

Autonomiczny supervisor działa jako zwykły użytkownik, ale build/install/cutover/
rollback wymagają uprawnień root. Stage D validation korzystał z uprzywilejowanych
wrapperów; E–H nie mogą zakładać, że przypadkowy cache `sudo` albo interaktywny
terminal będzie dostępny.

Dlatego przed pierwszym production gate instalowany jest **jednorazowo** root-owned
helper `/usr/local/libexec/ai-platform/autopilot-root-exec` oraz wąska reguła
`/etc/sudoers.d/ai-platform-autopilot`. Instalacja wymaga świadomego podania hasła
sudo przez operatora. Potem supervisor używa tylko `sudo -n`.

Helper nie udostępnia ogólnej powłoki root. Akceptuje wyłącznie Stage E/F/G/H oraz
dziewięć jawnych kroków production gate. Przed wykonaniem sprawdza: wywołującego
użytkownika/UID, stały worktree, oczekiwaną gałąź `agent/stage-X`, dokładny HEAD,
zgodność z `origin/agent/stage-X`, clean tree, ancestry względem `origin/main`,
tracked step i hash working-tree równy obiektowi Git. Weryfikacja Git wykonywana jest
jako właściciel worktree; dopiero zatwierdzony skrypt uruchamia się jako root z
minimalnym środowiskiem.

Brak lub utrata autoryzacji privilege bridge blokuje etap **przed** production mutation
i jest zgłaszana jako `PRIVILEGE_BRIDGE_REQUIRED`.


## Safe self-retry przed mutacją produkcji

Stan `PRE_PROD_CI` jest granicą przed jakąkolwiek mutacją produkcji. Supervisor
nie kończy już całego autopilota dla przejściowych lub naprawialnych błędów tej
fazy. Dla kodów `31` (read-only preflight), `91` i `94` (rejestracja/timeout
CI bez terminalnego FAIL) pozostaje uruchomiony w `tmux`, zapisuje
`WAITING_SAFE_RETRY` i ponawia próbę z rosnącym backoffem 30–300 s.

Każda ponowna próba pobiera aktualny `origin/main` i `agent/stage-X`, wykonuje
DEV gate/review wymagany przez resume path i ponownie sprawdza CI. Dzięki temu
poprawka dostarczona do gałęzi Stage przez GitHub zostaje podjęta bez interwencji
operatora i bez ręcznego `resume`.

Terminalny CI FAIL, błąd review/dev gate oraz wszystkie stany po rozpoczęciu
mutacji produkcji nadal są fail-closed. Dla przerwania podczas produkcji obowiązuje
rollback/recovery, nie automatyczne ponowienie.
