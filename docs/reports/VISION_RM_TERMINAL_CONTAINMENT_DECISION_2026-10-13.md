# Decyzja techniczna DEV: terminal-state i containment

**NO-GO. Propozycja architektury do decyzji właściciela, nie zgoda na runtime.**
Baza `b8e04dd`, gałąź `feature/vision-rm-system-security-20261013`, kontekst
Draft PR #163 podany przez zlecającego (bez odczytu PR z sieci). Zmiany lokalne,
bez commit/push, instalacji, zmiany jednostek, restartów, E2E i GPU.

## Rozstrzygnięcie

Obecny user scope UID 994 nie daje dowodu containment wobec dowolnego kodu
modelu. Observer tylko do odczytu nie może tego naprawić. W DEV zamknięto
zarówno pozytywne zakończenie oparte na późnym `systemctl show`, jak i nowe
admission Vision, zanim nastąpi I/O do providerów/GPU. To świadoma zmiana
kontraktu bezpieczeństwa: wcześniejsze pozytywne testy Vision wykorzystujące
wyłącznie mock członkostwa cgroup nie są już testem dopuszczalnej architektury.
Nie dodano flagi środowiskowej obchodzącej bramkę.

Rekomendacja: **systemowa usługa transient uruchamiająca worker UID 994**, z
polityką ustanowioną przez root przed exec. Nie wystarczy przenieść obecnego
procesu do root-managed `.scope`: scope nie uruchamia procesu i nie ustanawia
za niego pełnego sandboxu `systemd.exec`. Istniejący RM pozostaje jedynym
miejscem przydziału GPU, a istniejący observer miejscem zbierania dowodów.
Nie powstaje drugi daemon uprzywilejowany ani drugi scheduler.

## Dowody, założenia i przyczyna incydentu

Przeczytano oba wcześniejsze raporty FINISH_INDEPENDENT_AUDIT i
CROSSUID_TERMINAL_SECURITY_GATE z 13.10.2026. Historyczny CPU worker UID 994,
UID brokera 993, stan produkcji i marker absent to **dowody przekazane przez
operatora**, nie pomiary powtórzone w tej sesji. Nadal brak odpowiedzi HTTP
historycznego finish. Nie można przypisać incydentu jednej przyczynie.

Odczytano lokalnie bez działań administracyjnych:

- `/etc/os-release`: Ubuntu 26.04.1 LTS;
- `systemctl --version`: systemd 259 (259.5-0ubuntu3.4);
- `uname -sr`: Linux 7.0.0-38-generic;
- `python3 --version`: Python 3.14.4;
- `python3 -m pytest --version`: brak modułu pytest.

To wersje środowiska pracy agenta, nie atestacja sandboxu zainstalowanej
usługi na hoście nadzorcy. Nie odczytywano tokenów ani plików autoryzacji.
Nie sprawdzano urządzeń GPU ani bieżącej dostępności D-Bus.

Potwierdzone kodem: `scope_members_or_terminal` wcześniej dobierał user manager
z UID kontrolera, a scope należał do innego UID. Dodatkowo nawet poprawne
`loaded/inactive/dead/ControlGroup=""` nie zawiera historii instancji. Nazwa
jednostki i ścieżka cgroup mogą być użyte ponownie. Sam PID+birth wiąże tylko
jeden proces; nie obejmuje potomka poza obserwowanym drzewem.

Same-UID manager może świadczyć modelowi usługę uruchomienia sibling unit.
Nie przeprowadzono exploita. Jest to niewykluczona droga ucieczki, więc dla
adversarial model code oznacza odmowę, a nie założenie bezpieczeństwa.
`setsid` sam nie opuszcza cgroup, ale nie rozwiązuje migracji przez manager,
writable cgroup, IPC do innego procesu ani przekazania FD. Pusty katalog
cgroup/procs po wyjściu rodzica nie wyklucza uśpionego potomka, który otworzy
GPU później. Sandbox runnera nie jest automatycznie sandboxem workera
uruchamianego w innym managerze. Root-owned plik runnera uruchomiony jako UID
994 nie jest uprzywilejowaną granicą ochrony przed innym kodem tego UID.

## Semantyka źródeł systemd

Czytano lokalne man5: `org.freedesktop.systemd1`, `systemd.exec`,
`systemd.resource-control`, a dokumentację upstream przypięto do v259:
[API D-Bus](https://raw.githubusercontent.com/systemd/systemd/v259/man/org.freedesktop.systemd1.xml),
[sandbox wykonania](https://raw.githubusercontent.com/systemd/systemd/v259/man/systemd.exec.xml).
Publiczny serwer HTML zwrócił 403; użyto oficjalnych źródeł XML.

`UnitRemoved` opisuje wyładowanie obiektu, nie dowód końca wszystkich procesów.
`JobRemoved(done)` dotyczy zadania managera, także zadania start. `Subscribe`
jest potrzebne do strumienia sygnałów. `RefUnit`/`UnrefUnit` wiążą referencję
z klientem; pin ogranicza GC, nie uniemożliwia nowego cyklu aktywacji.
`InvocationID`, manager identity i historia są nadal konieczne. RefUnit
zmienia lifetime obiektu, więc nie jest całkowicie pasywną obserwacją.
API zawiera mapowania PIDFD/invocation/cgroup; obecność w dokumentacji nie
dowodzi dostępności i uprawnień w docelowej usłudze. `ProtectHome=yes` obejmuje
`/run/user`; nie należy usuwać tej ochrony, aby zgadywać stan user managera.
Systemowy manager eliminuje potrzebę otwierania tego kanału.

## Porównanie wariantów

| Wariant | Koszt | Wartość i blokada |
|---|---|---|
| Późny odczyt user scope | mały | Nie identyfikuje instancji, GC i ucieczek; odrzucony |
| Bounded observer + RefUnit/subskrypcja user managera | średni | Może śledzić lifecycle, lecz nie egzekwuje containment; samodzielnie NO-GO |
| Systemowa transient service + istniejący observer | większy, ograniczony do Vision | Root ustanawia granicę przed exec; rekomendowany, wymaga decyzji i walidacji |

Najmniejsza bezpieczna zmiana widoczna po ewentualnym wdrożeniu obecnego diffu
jest **odmową Vision admission/niepotwierdzonego release**, bez zmiany polityki
pozostałych workloadów. To nie jest naprawa dostępności. Docelowa zmiana to
zastąpienie uruchamiania przez user manager pojedynczą systemową usługą i
włączenie obserwacji w istniejącym observerze. Uprawnień wykonawczych do
observera nie dodano. Jeśli ma je kiedyś dostać, właściciel musi osobno
zatwierdzić rozszerzenie jego obecnej roli tylko do odczytu.

## Docelowa granica wykonania — PROPOZYCJA, nie plik do instalacji

1. Root-controlled launcher stanowiący wąską część istniejącej infrastruktury
   Vision uruchamia wyłącznie ustalony, root-owned gate/manifest jako
   `User=ai-vision` (UID 994). Żadne argv, executable, environment, ścieżki,
   nazwy urządzeń ani właściwości jednostki nie pochodzą z modelu/IPC.
   Preferować preprovisioned stały szablon usługi z kontrolowaną instancją.
   Jeśli istniejący observer ma obsługiwać start tego szablonu, to osobna,
   niewdrożona decyzja o uprawnieniach; obecny protokół startu nie ma.
2. Model i runner nie dostają sekretu RM. Broker UID 993 kontroluje lease i
   admission. Gate przed uruchomieniem modelu jest zaufanym kodem, czeka na
   pojedynczy sygnał powiązany z generacją/use, nie na plik zapisywalny przez
   innego workera UID 994. Model startuje dopiero po przypięciu use w RM,
   rejestracji watch i potwierdzeniu niezmienności granicy.
3. Minimalna polityka usługi: `Delegate=no`, `ProtectControlGroups=yes`,
   `NoNewPrivileges=yes`, pusty capability bounding set, brak ambient caps,
   `RestrictSUIDSGID=yes`, `RestrictNamespaces=yes`, `ProtectSystem=strict`,
   `ProtectHome=yes`, `PrivateTmp=yes`, prywatny PID/proc i network namespace,
   `KillMode=control-group`, `SendSIGKILL=yes`, `Restart=no`, limity czasu,
   pamięci i liczby zadań. Nie wolno pozwolić UID 994 na restart/attach/start
   systemowych jednostek przez polkit. Prywatny mount namespace nie może
   wystawiać alternatywnych writable cgroup, host `/proc` ani socketów managera.
4. Zablokować user bus, system bus, prywatny socket systemd i kanały IPC do
   innych procesów zdolnych wykonać pracę za model. Samo ukrycie `/run/user`
   nie wystarcza: są abstract AF_UNIX, host `/proc/<pid>/root`, odziedziczone
   FD i udostępnione katalogi z socketami. Preferować brak sieci i tworzenia
   socketów przez model (seccomp), wynik przez odziedziczony jednokierunkowy
   pipe i pliki danych bez socketów. ROCm może wymagać dopuszczeń — nie wolno
   uznać tego profilu za kompatybilny bez walidacji. Gate zamyka niepotrzebne
   FD; broker/observer sockets i sekret nigdy nie trafiają do modelu.
5. UID 994 musi być dedykowany: brak niekontrolowanych procesów, usług user
   managera, loginów, zaplanowanych zadań i globalnego dostępu GPU poza granicą.
   Same UID + proc/ptrace/IPC potrafi obalić izolację samymi flagami jednostki.
   Prywatny PID namespace i kontrola socketów wymagają testu ataku. Nie opierać
   bezpieczeństwa wyłącznie na aktualnym Yama ani grupach Unix.
6. `DevicePolicy=strict` z ustalonymi `DeviceAllow` tylko dla właściwego GPU
   i niezbędnych urządzeń podstawowych; dla CPU profilu brak GPU. DAC/ACL musi
   współdziałać z cgroup device filter i być ograniczony do wykonania; globalne
   członkostwo UID 994 w render/video nie jest capability RM. Filtr urządzeń
   nie unieważnia wcześniej otwartego lub przekazanego FD. Należy wykluczyć
   takie FD przed exec i zewnętrznych odbiorców FD. Nie ma prostego przełączenia
   `PrivateDevices=yes` gwarantującego działające ROCm: profil urządzeń trzeba
   osobno przygotować i sprawdzić. Brak ogólnych wyjątków dla wszystkich GPU.

## Docelowy protokół i sekwencja dowodu po GC — PROPOZYCJA

Obecny socket AF_UNIX z SO_PEERCRED, terminal ops wyłącznie peer UID 993,
worker UID 994 stały. Klient musi sprawdzać root UID serwera. SO_PEERCRED
nie zastępuje autoryzacji procesów samego UID ani ochrony socket directory.
Brak podpisów przesyłanych przez model: zaufanie pochodzi z kanału i kolektora.

`register_scope` v1 rezerwuje nazwę ABI. Obecny szkic ma dokładnie:
`version, op, runner_pid, runner_birth, pid, birth, scope_suffix`.
Suffix 12 lowercase hex, limit 512 B, brak extra/duplicate keys, bool nie jest
int. Runner nadal UID 994, **peer kontrolera** to UID 993; nie należy ich mylić.
Docelowy root-managed service zmieni rodzaj jednostki, więc wymaga nowej wersji
ABI, a nie cichego reinterpretowania user scope. `query_terminal` ma wyłącznie
`version, op, handle, epoch`. Handle to identyfikator watch, nie token RM.

Przed admission kolektor musi wykonać poniższe kroki w jednej serializowanej
sesji; żadnego etapu nie zastępują pola podane przez klienta:

1. Związać boot identity, losowy observer epoch, manager PID+birth/pidfd,
   uwierzytelniony unique bus owner i generację połączenia. Zainstalować match
   rules i Subscribe przed odczytami. Sprawdzić sender, path, interface, member,
   D-Bus signature i typy każdego zdarzenia, nie tylko nazwę unit.
2. Uruchomiony zaufany gate jest zaparkowany, model jeszcze nie wykonany.
   Sprawdzić runner PID+birth/UID/cgroup oraz worker pidfd, UID 994, birth przed
   i po snapshotach. Przypiąć RefUnit, InvocationID, ControlGroup, otwarty FD
   katalogu cgroup i jego tożsamość. Sprawdzić efektywną politykę sandbox/device
   i jej root ownership. Ponowić tożsamości po opróżnieniu kolejki zdarzeń.
   Nazwa/path/inode w izolacji nie są tożsamością całej historii.
3. Maksymalnie jeden aktywny watch zgodny z istniejącym pojedynczym Vision use;
   przy limicie odmówić, nigdy nie wyrzucać aktywnego watch, by przyjąć nowy.
   Proponowany deadline 180 s obejmuje obecne wykonanie do 120 s, terminal
   tombstone 30 s; limity wymagają zgrania z timeoutami RM. Wygaśnięcie wymaga
   recovery, nie domyślnego release. Utrata heartbeat/death kontrolera nie
   daje terminal. Nie trzymać nieograniczonej kolejki sygnałów.
4. Po końcu gate/modelu: pidfd potwierdza koniec, **cały** cgroup subtree ma
   `cgroup.events populated=0` i kompletne dane. Odczyt `cgroup.procs` z samego
   korzenia nie wystarczy. Musi istnieć dowód, że procesy nie mogły wyjść i
   nikt nie może ich ponownie uruchomić/attachować. Nie jest nim lista PPID.
5. Zablokować ponowne aktywacje i zatwierdzić końcowy snapshot tej samej
   invocation/manager generacji. Dopiero wtedy zachować root-owned terminal
   tombstone i zwolnić RefUnit. GC **po** tym zapisie nie kasuje dowodu;
   GC przed domknięciem dowodu daje unknown. Reuse nazwy, reload/reexec managera,
   utrata bus, brak sygnału, zmiana generacji, overflow, PID reuse, timeout
   lub observer restart unieważniają watch. Nie odtwarzać go z pustego cgroup.
6. RM trzyma admission lock i marker przez query, kontrolę GPU FD, VRAM,
   idle providerów i zatwierdzenie release. Żadnych awaited kroków poza tą
   serializacją umożliwiających nowe admission. Terminal history dotyczy
   granicy nieodwracalnie zamkniętej, więc jej pustość jest monotoniczna.
   Sam dodatkowy snapshot przed unlink markera nie usuwa TOCTOU. Potrzebna
   jest transakcja prepare/consume związana z lease/use i generacją watch;
   utrata odpowiedzi to ownership unknown. D-Bus/observer disconnect przed
   consume blokuje release, po potwierdzonym consume nie otwiera starej granicy.
   Ten interfejs transakcyjny **nie jest zaimplementowany**.

Snapshot FD/VRAM pozostaje dodatkową negatywną kontrolą, nie dowodem braku
uśpionych potomków. Dla ROCm zakończenie procesów nie zastępuje potwierdzenia
zwolnienia zasobów sterownika. CPU-only nie może „zaliczyć” profilu ROCm.

## Faktyczna implementacja tego diffu

- `src/ai_bridge/gateway/vision_residency_evidence.py`: ograniczony odczyt
  całego subtree (1024 katalogi, 32768 PID, 64 KiB/procs, odmowa symlinków,
  błędów i brakujących danych). To snapshot diagnostyczny/admission, nie
  atomowy dowód. Funkcja terminalna nigdy nie zwraca pozytywnego pustego zbioru.
  `scope_containment_available` zawsze false: nie istnieje zatwierdzony backend.
- `src/ai_bridge/gateway/residency.py`: odmowa nowego Vision przed I/O,
  zachowany blokujący cleanup. Registry po błędzie enter nadal przypina use,
  blokuje scheduler i zapisuje marker zgodnie z istniejącą obsługą wyjątków.
- `deploy/vision-rm-security/vision_gpu_observer.py`: ścisły parser również
  dla starych operacji, bounded terminal ABI i losowy epoch. Register zawsze
  unknown/containment_unavailable, query unknown/unregistered lub epoch_mismatch.
  **Nie sprawdza jeszcze tożsamości runnera/managera, nie alokuje watch, nie
  pobiera D-Bus events i nie wydaje terminal.** Zero stanu watch jest celowym
  limitem, nie gotowym lifecycle engine. Brak dowolnej ścieżki/komendy/startu.
- `deploy/vision-rm-security/vision_rm_runner.py`: sprawdzenie SO_PEERCRED
  brokera UID 993 przed wysłaniem żądania.
- `src/ai_bridge/benchmarks/vision_rm_broker.py`: nieznany wynik POST lease
  blokuje ponowne create w tym procesie; błędny schemat nie tworzy sesji.
  Restart nie odtwarza tej pamięci — recovery/reaper i RM pozostają konieczne.
- Testy: nowy `tests/test_vision_terminal_boundary_dev.py`, rozszerzony
  `tests/test_vision_rm_cleanup_diagnostics_dev.py`, zaostrzone oczekiwania
  `tests/test_vision_rm_crossuid_terminal_evidence_dev.py`. Usunięto oczekiwanie
  sukcesu z samego loaded/dead; nie zmieniono zainstalowanych testów ani gates.

Review b8e04dd: latch admission_uncertain prawidłowo poprzedza POST /uses;
`released:1`, dodatkowe pola i negatywne HTTP pozostają odmową. DELETE lease
może nadal oznaczać deferred release w API; broker nie stosuje go do unknown
begin. Po use cleanup i nieudanym lease delete sesja pozostaje do retry.
Brak/idempotentny use nie jest nowym pomiarem fizycznego cleanupu. Nie zmieniano
tego kontraktu globalnego RM. Naprawiono lokalne retry create i uwierzytelnienie
serwera IPC, ale nie twierdzi się, że rozwiązano recovery po restarcie brokera.

## Walidacja i ograniczenia

Nowe testy są deterministyczne, stdlib, bez root, realnych usług i GPU. Mocki
patchują granice I/O; test integracji ładuje rzeczywistą klasę GPUResidency,
zastępując jedynie nieużywany moduł httpx. Test markerów używa katalogu tymczasowego.
Test nested child czyta sztuczne drzewo plików. Test escaped child sprawdza
odmowę przy pustym snapshot, **nie wykonuje exploita ucieczki**. Testy GC,
reuse i manager restart dowodzą braku pozytywnego fallbacku w niedostępnym
backendzie, nie obsługi autentycznych sygnałów D-Bus. Fałszywe podpisy/zdarzenia
są niedozwolonymi polami/operacjami, nie testem kryptografii.

Wynik: **50/50 PASS**: 21 terminal boundary + 12 cleanup diagnostics +
9 cross-UID terminal + 3 observer disconnect + 5 credential boundary.
`py_compile` dla 5 zmienionych modułów i 3 testów: PASS. `bash -n` dla
wszystkich 9 skryptów shell w katalogu wdrożeniowym: PASS. `git diff --check`: PASS.
Starszych testów
stagingu zależnych od rzeczywistego systemd/plików instalacji nie wykonywano.
Pełny pytest jest niedostępny; nie instalowano zależności i nie uruchamiano
ogólnego discovery mogącego włączyć testy GPU/E2E. Historyczne 34/34 nadzorcy
nie jest wynikiem tej sesji.

## Migracja, rollback i wymagane decyzje

Właściciel musi zatwierdzić systemową usługę wykonawczą, wyłączność UID 994,
politykę urządzeń/IPC oraz wąską rolę istniejącego observera/launchera. Samo
zatwierdzenie tego diffu nie upoważnia do instalacji ani restartu.

Po decyzji: zaimplementować zaufany kolektor i launcher, kontrakt register /
prepare / consume w RM i brokerze, następnie niezależny review. Dopiero potem
osobno autoryzowane testy izolowanego CPU DEV z próbami ucieczki: user/system
bus, abstract socket, SCM_RIGHTS, ptrace, cgroup attach, nested fork, GC,
RefUnit disconnect, invocation/name reuse, manager reexec, observer restart,
SIGKILL kontrolera, utrata odpowiedzi POST/DELETE i ponowienie consume.
Potrzebny też test realnego root sandboxu observera, migracji cgroup i
zachowania DevicePolicy na docelowym kernelu. Dopiero później odrębna bramka ROCm.

Staging musi mieć nowe niezależnie sprawdzone hashe i root-owned artefakty;
obecne manifesty/hash gates nie były zmieniane. Rollback polega na wyłączeniu
nowego admission Vision, zatrzymaniu zatwierdzoną procedurą starej granicy,
zachowaniu markerów/lease przy unknown i recovery nadzorcy. Nie wolno cofać
się do pozytywnego dowodu z samego `inactive` ani usuwać markera „dla retry”.
Nie ma obecnie rekomendowanej komendy start/cutover. **Pozytywne E2E pozostaje
zablokowane przez brak zatwierdzonej i zaimplementowanej granicy oraz kolektora.**


Odtwarzalny zestaw CPU-only (bez globalnego discovery):

```bash
python3 -m unittest discover -s tests -p test_vision_terminal_boundary_dev.py
python3 -m unittest discover -s tests -p test_vision_rm_cleanup_diagnostics_dev.py
python3 -m unittest discover -s tests -p test_vision_rm_crossuid_terminal_evidence_dev.py
python3 -m unittest discover -s tests -p test_vision_observer_disconnect_dev.py
python3 -m unittest discover -s tests -p test_vision_rm_executor_protected_file_dev.py
```

W tej sesji uruchomiono te pięć wzorców także łącznie w jednym procesie
`unittest.TestSuite`, aby sprawdzić wzajemną izolację importów/mocków.
