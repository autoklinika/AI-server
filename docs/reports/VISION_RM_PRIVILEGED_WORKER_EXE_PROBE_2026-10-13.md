# Security gate — cross-UID /proc/PID/exe, 13 października 2026

## Fakt z rzeczywistej próby

Operator wykonał `probe-cross-uid-worker.sh --verify` pod rootem. Podmiot `ai-gateway-rm` czyta PID właściciela `ai-vision` (994), `/proc/<pid>/stat`, `cgroup`, `cmdline`, ale `/proc/<pid>/exe` zwraca **EACCES errno=13**. Powiązanie z programem przez zwykły readlink jest więc nieosiągalne dla nieuprzywilejowanego kontrolera.

Po zakończeniu testu PID 73669 nie istniał; produkcyjny Resource Manager był idle (leases=0), usługi ai-gateway, ollama i root read-only observer active. Nie należy nadawać `ai-gateway-rm` CAP_SYS_PTRACE ani uruchamiać całego brokera jako root.

## Poprawka w DEV, bez zmian produkcji

- `vision_gpu_observer.py`: jedna nowa operacja `inspect_worker`, wymagająca **SO_PEERCRED dokładnie ai-gateway-rm**. Żądanie ma tylko `op,version,pid,birth`. Root weryfikuje, że dany PID należy do `ai-vision`, czas startu procesu zgadza się **przed i po** odczycie, a `/proc/pid/exe` jest plikiem regularnym z dev/inode identycznym z plikiem na dysku. Wynik zawiera wyłącznie ścieżkę interpretera i tożsamość procesu. Brak jakiegokolwiek API arbitralnej ścieżki, komend lub GPU ioctl. Konto modelu `ai-vision` może korzystać z dawnego `snapshot`, ale `inspect_worker` jest dla niego **DENIED**.
- `vision_gpu_observer_client.py`: wymusza root-owned server SO_PEERCRED, pełny schemat, UID modelu, birth i PID, max 8 KiB, timeout 3 s. Nieznane/missing dane => **None / fail-closed**.
- `vision_attestation.py` / `gateway/app.py`: opcjonalna zależność na obserwatorze w przypadku oddzielnych UID. Bez potwierdzenia root observer nie wydaje autoryzacji Vision. W trybie strict wymaga jawnego worker UID.
- `upgrade-observer-worker-exe.sh`: administrator może zaktualizować **wyłącznie obserwator**, bez restartu produkcyjnego Gatewaya i Ollamy. Weryfikuje bezczynność produkcyjnego GPU, zabezpiecza poprzedni plik w root-only katalogu, instaluje nowy atomowo, restartuje jedynie obserwator, wykonuje rzeczywisty test cross-UID i automatycznie przywraca poprzednią wersję w przypadku błędu.
- `test-observer-worker-exe.py`: tworzy na maksymalnie 30 sekund proces `ai-vision` **wyłącznie CPU** w odrębnej sesji; weryfikuje root observer pod `ai-gateway-rm`, odmowę modelowi, błędny birth, zgodność exe i cleanup. Test jest **do wykonania dopiero po zatwierdzonej aktualizacji usługi**.

## Wyniki i wymagania zamknięcia

- Testy jednostkowe/negatywne z mock i lokalnym /proc: PASS. Sprawdzają prawidłowy proces, błędny birth, obcy UID i żądania z dodatkowymi argumentami.
- Pełny lokalny zestaw testów repo uruchomiono; wymagane jeszcze jedno jawne potwierdzenie kodu zakończenia oraz GitHub CI nowego commitu.
- **Real privilege-crossing E2E nie jest jeszcze PASS** dopóki administrator nie wykona upgrade-only obserwatora, a prawdziwy PID ai-vision nie zostanie pozytywnie atestowany przez ai-gateway-rm przez socket.
- Samo uzyskanie `CROSS_UID_EXE_ATTESTATION=PASS` nie kończy audytu pełnego RM. Pozostaje root-owned broker/runner installation w DEV, handshake między rzeczywistymi kontami, test GPIO/GPU cleanup, crash recovery, niezależna ocena bezpieczeństwa i osobna zgoda na merge/cutover.
- Produkcyjna flaga Vision pozostaje OFF. Żadnych zmian modelu Qwen/adapterów/main.

**Gate: code-level worker-exe probe PASS; privileged installed observer verification NOT YET RUN; production NO-GO.**

## Incydent podczas pierwszej aktualizacji obserwatora (17:53 CEST)

Administrator uruchomił aktualizację. Preflight produkcyjnego GPU PASS. Systemd rozpoczął usługę, ale skrypt natychmiast testował gniazdo AF_UNIX i wykrył `observer socket missing`. Oprogramowanie wycofało zmianę i uruchomiło ponownie poprzedni obserwator. Zdalnie potwierdzono po incydencie: observer, ai-gateway i ollama **active**; marker GPU clean, 0 leases, main clean, poprzedni kod nadal zainstalowany.

Ważne: sam komunikat `observer socket missing` nie dowodzi niezgodności nowego handlera. Typ systemd `simple` zgłasza active przed `socket.bind()` w procesie Python. Poprawka w `upgrade-observer-worker-exe.sh`: po restarcie **maksymalnie 10 s** na realną gotowość AF_UNIX; test połączenia od root oczekuje poprawnie zdekodowanego statusu **denied**, ponieważ root nie należy do klientów autoryzowanych. Tylko potem wykonywany jest faktyczny test atestacji ai-gateway-rm → ai-vision. Po rollback skrypt również sprawdza gotowość starej usługi, zamiast opierać się wyłącznie na `systemctl active`.

Aktualizacja nie została powtórzona automatycznie: wymaga jawnego ponownego polecenia administratora. Wynik rzeczywistego testu E2E pozostaje nieustalony do czasu tej próby. Targeted testy izolacji nowej ścieżki: **14/14 PASS**.
