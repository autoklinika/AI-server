# AI Platform — kontrolowany worker w istniejącym Gateway / Resource Manager
**17.10.2026 | DEV / CPU-integracja PASS / GPU admission NOT VERIFIED**

Repo: autoklinika/AI-server, gałąź feature/gpu-managed-worker-gateway-dev-20261017, baza N5 c1bd58f. Produkcja bez zmian.

## Wykonano

- `src/ai_bridge/gateway/managed_worker.py`: nowy, **wewnętrzny** komponent wykorzystuje **ten sam obiekt `PriorityScheduler`** co Gateway i ResourceLeaseRegistry. Nie istnieje nowy proces serwisowy, harmonogram, HTTP endpoint ani token pozwalający klientowi wymusić wykonanie. Gateway umieszcza obiekt w `app.state.managed_worker`, domyślnie `enabled=False`; brak jakiejkolwiek zewnętrznej ścieżki jego aktywacji w konfiguracji produkcyjnej.
- Zatwierdzony program: wyłącznie `synthetic-cpu-v1`, stała krótka komenda stdlib Python z N5 przez `WorkerObserver`. Brak GPU/ROCm, dowolnej komendy, przekazanych ścieżek czy nieufnego workera jako źródła decyzji admission. Inne typy, w tym `gpu`, są odrzucane.
- Realny nadzorowany CPU child otrzymuje slot przez obecne `scheduler.acquire(..., JobMetadata(capability="external-reservation"))`, jest uruchamiany w osobnej sesji i monitorowany przez PID, start ticks, boot ID i oryginalny uchwyt subprocess. Współdzielenie obiektu schedulera uniemożliwia zwykłemu requestowi Gateway przejście przez ten sam slot, dopóki worker go zajmuje.
- Niejednoznaczny start, utrata tożsamości, crash, niezerowy exit, timeout, anulowanie klienta, przerwanie w trakcie kolejki, przerwanie w trakcie uruchamiania lub shutdown — stan `DIRTY`, blokada `scheduler.admission_blocked`, trwały znacznik oraz brak przedwczesnego release. Zadanie wewnętrzne zwraca `DIRTY` zamiast wyrzucać nieobsłużony wyjątek po anulowaniu. Nie wydaje żadnych sygnałów produkcyjnym procesom.
- Tylko **udany syntetyczny CPU worker** kończy się `PROCESS_CLOSED` i zwolnieniem slotu. Nie jest to dowód GPU_REUSE_SAFE. Marker DEV nie może zablokować Gateway, jeżeli komponent jest domyślnie **wyłączony**.
- Statusy `gpu_admission=NOT_ADMITTED` i `gpu_status=NOT_VERIFIED` pozostają stałe; brak realnego adaptera dla GPU. N1 SHARED/EXCLUSIVE nadal służy tylko do syntetycznych testów, N2-dev-blocked nadal nie dopuszcza pracy.

## Walidacja

- 26/26 testów wewnętrznego worker Gateway PASS. Sprawdzono konkurencyjne żądanie HTTP, brak drugiego schedulera, niepoświadczone GPU, odmowę innych typów, anulowanie/wyrwanie podczas kolejki, awarię, shutdown, powtórne uruchomienie procesu CPU i brak wpływu nieaktywnego komponentu na legacy Gateway.
- **616/616 PASS** w rozszerzonej regresji CPU i API poza sandboxem Codexa (22 wybrane pliki testowe N1-N5, nowe ManagedWorker, Gateway, Resource API, WVC, Stage O, Media i Platform API); zakończenie kod 0. Jedno istniejące ostrzeżenie deprecacyjne `Starlette / httpx`. Wynik lokalny w `GATEWAY_WORKER_FULL_REGRESSION.log`, log nie jest potrzebny w repo.
- Brak zmian do /opt/ai-platform, systemd, kernel lub usług produkcyjnych. GPU nie zostało uruchomione z nowego workera.

## Warunki dopuszczenia **jednego rzeczywistego workera GPU** (NO-GO obecnie)

1. Jedna jawna, zaufana implementacja GPU runtime (konkretny backend i PCI urządzenia) w obrębie istniejącego Gateway; **nie** akceptować ogólnych programów/shell/Python i nie otwierać nowej ścieżki omijającej RM.
2. Dowód fizycznego przypięcia do Radeona 890M, procesowej inkarnacji/scope wszystkich submitterów, zakazu dalszej emisji zleceń, synchronizacji zadanych strumieni, zamknięcia kontekstów KFD/DRM i bezpiecznego cleanup; „proces zakończony” lub „fences signaled” same nie wystarczają.
3. Brak konkurującego punktu admission i aktywnych niezarejestrowanych GPU submitterów. Obecna Ollama i ComfyUI mają aktywne usługi i lokalne porty, więc `localhost` nie jest egzekwowalną izolacją. Przy braku dowodu **pozostawić GPU zamknięte**, nie wypuszczać kolejnych zadań.
4. Mały pilot GPU należy wykonać dopiero z zatwierdzonym profilem zasobów, po testach fałszywych release i rozłączeń oraz preflight stanu sterownika. Nie wykonywać stresu, zmian drivera lub resetów bez osobnej decyzji.

**Wniosek:** cel architektoniczny jest zachowany: jeden Resource Manager, bez nowego koordynatora, z możliwością przyszłej obsługi wielu GPU i SHARED/EXCLUSIVE. Ten etap kończy integrację *wewnętrznego wykonawcy i schedulera* w DEV. Nie należy opisywać go jako ukończonego uruchomienia rzeczywistego workera Radeon; ten punkt pozostaje otwarty.

## Zależności
PR #167 N1, #168 N2, #169 N3, #170 N4, #171 N5. Ten etap w osobnym Draft PR, bez merge do main.
