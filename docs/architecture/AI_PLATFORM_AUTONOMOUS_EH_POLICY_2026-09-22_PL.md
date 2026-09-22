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
