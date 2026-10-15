# Stage O — awaryjne przywrócenie komunikacji po recovery rollback (operator)

**15.10.2026 | PR #166 | procedura do przyszłej autoryzowanej operacji, NIE wykonano na produkcji**

## Zakres i preflight (GO/NO-GO przed uruchomieniem)

Jedynym celem jest odzyskanie wcześniej **zaakceptowanego** release zapisanego
w oryginalnym, root-owned `baseline.json` transakcji
`5e104ea69d0bfa342209acdc8dc88145b34ae72e`.
Nazwa i SHA rollbacku muszą być odczytane i niezależnie potwierdzone przez
operatora; nie zakładać, że sam katalog release jest zaakceptowany.
Stary current: `stage-o-5e104ea69d0b`. Nie używać PR #165 ani wymyślać `accepted.json`.

Przed operacją: zgoda właściciela na okno serwisowe; CI PR #166 PASS;
zatwierdzony merge i synchronizacja **czystego** `agent/stage-o` z dokładnym
`main`; test głównego root executora `--self-test`; potwierdzenie checksumów
obu release, baseline/installed/rollback accepted, Stage K PASS, modelu P511
i LoRA, braku aktywnych jobs/leases, pustej kolejki ComfyUI i zdrowia usług.
Zapisać: current, PID+InvocationID Gateway/Bridge/ComfyUI, stan Hermes i timera.
Dopiero po komplecie bramek operator może uruchomić istniejący
`40_rollback` **raz** przez zatwierdzoną drogę Stage O; nie uruchamiać
bezpośrednio `switch()` ani komend z tego dokumentu „na próbę”.

## Odczyt diagnostyczny po niepowodzeniu (nie zmienia stanu)

```bash
readlink -f /opt/ai-platform/current
systemctl is-active ai-gateway.service ai-bridge.service ollama.service comfyui.service ai-bridge-analysis.timer
systemctl show ai-gateway.service ai-bridge.service comfyui.service -p ActiveState -p MainPID -p InvocationID -p NeedDaemonReload
systemctl --user is-active hermes-gateway.service
curl -fsS --max-time 5 http://127.0.0.1:11435/health
curl -fsS --max-time 5 http://192.168.1.55:8080/health
curl -fsS --max-time 5 http://127.0.0.1:8188/queue
```

**Stan A — błąd przed mutacją:** `current` nadal wskazuje
`stage-o-5e104ea69d0b`; istniejący `switch()` próbuje przywrócić Hermes
i timer w `finally`. Jeśli tego nie potwierdzono, sprawdzić stan usług.
Nie dotykać symlinku, nie ponawiać rollbacku bez ponownego preflight.
Wznowić tylko brakujące usługi, gdy Gateway i Bridge na aktualnym
release są zdrowe i nie ma zmiany PID/InvocationID.

**Stan B — błąd po rozpoczęciu mutacji:** `current` może już wskazywać
wcześniej zaakceptowany release, a Hermes/timer celowo pozostają wstrzymane.
To **nie jest stan PASS** nawet przy działającym Gateway. Nie uruchamiać
automatycznie `40_rollback` po raz drugi, nie wymuszać `current` ani
nie startować komunikacji bez sprawdzenia docelowego release.

Jeśli `current` wskazuje dokładnie uprzednio zweryfikowany i zaakceptowany
rollback, jego checksumy, konfiguracja i preload są poprawne, ComfyUI jest
idle, a nie zaszła kolejna zmiana tożsamości procesu, wolno operatorowi
w ramach osobnej decyzji przywracać usługi w **minimalnej kolejności**:

1. Najpierw Gateway/Bridge: jeśli są nieaktywne, operator może użyć
   `sudo systemctl start ai-gateway.service ai-bridge.service`;
   potwierdzić dwa `/health`, właściwe procesy/cwd, schemat DB,
   0 jobs/leases i brak błędów `journalctl`.
2. Dopiero po ich zdrowiu przywrócić Hermes poleceniem
   `systemctl --user start hermes-gateway.service` z właściwego konta
   `harrypotter` i sprawdzić podłączenia Telegram/API/Discord.
3. Następnie `sudo systemctl start ai-bridge-analysis.timer`, o ile
   timer był aktywny w oryginalnym baseline; zweryfikować jego status.

Jeśli `current` wskazuje nieznany release, żaden z endpointów nie przechodzi
kontroli, model/preload lub backup są niespójne, brakuje zaufanej tożsamości
rollbacku albo systemd zgłasza nieoczekiwane PID/InvocationID: **STOP**.
Zachować zatrzymany ingress, zebrać `journalctl` i ustalić odrębny plan.
Nie robić restartów „na ślepo”, `ln -sfn`, resetów GPU, modyfikacji
adapterów ani ręcznego zapisu `accepted.json`.

## Próby DEV, bez wykonywania działań na produkcji

Test pozytywny symuluje rzeczywisty `switch()` po reboocie i odzyskanie
ingress. Test negatywny symuluje zmianę InvocationID ComfyUI po `quiesce`:
odmowa health i pozostawienie ingress zatrzymanego. Test błędu
przed mutacją dowodzi przywrócenia ingress przez `finally`.
Testy nie są dowodem zachowania realnego serwera podczas cutover:
ostateczne GO wymaga podpisanego planu z potwierdzonym rollback target.

**Nie wykonywać produkcyjnego rollbacku ani merge na podstawie tego dokumentu.
Każda z tych operacji wymaga oddzielnej zgody.**
