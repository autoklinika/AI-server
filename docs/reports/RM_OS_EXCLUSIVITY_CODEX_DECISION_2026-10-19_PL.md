# Decyzja RM — wyłączność GPU, 2026-10-19

**Decyzja:** obecne dowody potwierdzają granicę dostępu usług zarządzanych, nie globalną wyłączność GPU. Na teraz wybrać D: jawny tryb konserwacyjny bez zatwierdzania ponownego użycia GPU. Docelowo rozważyć B+A dla wydzielonego GPU obliczeniowego; pozostawić jeden RM N1–N5. `os_gpu_boundary.py` uznajemy za wystarczający zgodnie z dyspozycją użytkownika; bez zmian kodu i produkcji.

**Pochodzenie i status dowodów.** Odczytano `CODEX_TASK_OS_EXCLUSIVITY.md`. Poniższe wyniki pochodzą z tego opisu; w tej skróconej drugiej analizie nie odczytywano logów ani nie uruchamiano poleceń lub testów. Nie jest to niezależna ponowna weryfikacja.

- Host: Ubuntu 26.04, systemd 259, Radeon 890M `0000:c6:00.0`, ROCm HIP. `/dev/kfd` i `/dev/dri/renderD128`: `0660 root:render`; harrypotter, ollama i ai-vision należą do render, istnieje też ACL gdm-greeter.
- Według zadania systemowy systemd z UID ai-vision i `DevicePolicy=strict` odmawiał obu otwarć, a dwie dokładne reguły `DeviceAllow` je umożliwiały. Wskazany artefakt: `docs/reports/RM_OS_GPU_SYSTEMD_EVIDENCE_2026-10-19.json`; logi: `/srv/ai-data/evaluation/os-gpu-gate-20261019-182354-209705`.
- Menedżer użytkownika nie blokował dostępu tymi właściwościami; `PrivateDevices=yes` kończyło się `218/CAPABILITIES`. Nie jest to skuteczna granica egzekwowania.
- Po wyjściu jednostki odczyt KFD wskazał PID bez zapisania jego wartości; późniejsze puste KFD/fuser nie dowodzą zakończenia wszystkich operacji ani E_safe. Historyczne 558 testów CPU PASS nie dowodzi izolacji sprzętu.
- Usługi produkcyjne zatrzymano celowo; obserwator pozostaje aktywny. Starszy szablon jednostki ROCm jest kandydatem niezainstalowanym i nieautoryzowanym, nie dowodem wdrożenia.

**Ranking wariantów według bezpieczeństwa możliwego następnego kroku:**

| Miejsce | Wariant | Ocena i luka |
|---|---|---|
| 1 | D — zachować dostęp, jawny tryb konserwacyjny | Najmniejsza zmiana teraz. Przy pozostawieniu dostępu użytkownika brak egzekwowalnej wyłączności wobec procesów niezarządzanych. Zatrzymanie znanych usług jest procedurą, nie dowodem izolacji ani E_safe. |
| 2 | B + A — oddzielne tożsamości compute i systemowy launcher | Kierunek docelowy, najlepiej z osobnym GPU dla pulpitu. B wymaga usunięcia wszystkich niezamierzonych uprawnień grupowych/ACL/udev; A ogranicza uruchamiane usługi. Migracja Ollama/ComfyUI wymaga weryfikacji danych, socketów i dostępu urządzeń. Na jednej iGPU pozostawiony dostęp pulpitu wyklucza deklarację globalnej fizycznej wyłączności. |
| 3 | A — systemowe cgroup v2 device BPF + stały launcher root | Udokumentowana skuteczność odmowy otwarcia w zarządzanej jednostce. Launcher musi mieć stałe, chronione parametry i uprawnienia; RM pozostaje jedynym decydentem. Współpracujący właściciel może przestrzegać RM, niewspółpracujący uruchomi proces poza jednostką i wykorzysta własne uprawnienia render. |
| 4 | C — AppArmor/LSM | Możliwe uzupełnienie po sprawdzeniu polityki i kernela. Profile wybranych programów nie obejmują automatycznie każdego procesu tego samego UID. Trzeba objąć alternatywne ścieżki DRM, przejścia profili i przekazywanie deskryptorów. Brak dowodu kompletności; nie wybierać jako szybkiej samodzielnej naprawy. |

**Model bezpieczeństwa i granica.** Root oraz administrator konfiguracji są zaufani i poza modelem przeciwnika. Proces nieuprzywilejowany poza RM należy traktować jako potencjalnie niewspółpracujący. Wyjątek dla pulpitu musi być jawny: jeśli pulpit używa tego samego GPU, zakres gwarancji może obejmować tylko usługi zarządzane, a nie cały fizyczny GPU. Jeden GPU ze współdzieloną RAM nie zapewnia podziału sprzętowego przez sam podział UID. KFD i DRM trzeba analizować łącznie; `/dev/kfd` nie stanowi samo w sobie selektora pojedynczego GPU. Identyfikacja PCI pomaga mapować urządzenia, lecz nie dowodzi egzekwowania dostępu ani zakończenia pracy.

Punkty odniesienia dokumentacji: systemd `systemd.resource-control(5)` — `DevicePolicy=`, `DeviceAllow=`; `systemd.exec(5)` — `PrivateDevices=`; kernel cgroup v2 — Device controller, `BPF_PROG_TYPE_CGROUP_DEVICE`; kernel DRM — render nodes; Linux `unix(7)` — `SCM_RIGHTS`. Są to nazwane interfejsy, nie nowe wyniki badań. Ukrycie węzła w przestrzeni montowania nie unieważnia otwartego deskryptora. Odmowa nowego otwarcia nie dowodzi odebrania już posiadanego dostępu, zakończenia kolejek GPU ani E_safe.

**Brakujący dowód i późniejsza macierz akceptacji** — do wykonania oddzielnie przez operatora, z root tam, gdzie potrzebna jest konfiguracja systemowa; niczego z tej macierzy teraz nie wykonano:

| Przypadek | Wymagany dowód |
|---|---|
| Usługa zarządzana deny/allow na tym samym GPU | Zapis UID, cgroup, mapowania PCI–węzły, polityki i wyników otwarcia KFD/DRM; kontrola pozytywna musi dotyczyć tego samego urządzenia. |
| Niezarządzany użytkownik i użytkownicy usług | Próba poza launcherem; dla B oczekiwana odmowa przez wszystkie dostępne ścieżki, dla A/D jawnie udokumentowana luka. |
| Root, pulpit, gdm | Zapis wyjątków i wpływu na działanie pulpitu; dostęp do tego samego GPU oznacza brak globalnej wyłączności. |
| Deskryptor otwarty wcześniej, dziedziczony i SCM_RIGHTS | Weryfikacja rzeczywistej możliwości użycia po zmianie polityki oraz między rolami; samo nieudane nowe open nie wystarcza. |
| Wyjście procesu i potomków | Zapis konkretnych PID, cgroup i stanu KFD/DRM; osobny wiarygodny dowód zakończenia pracy/zwolnienia zasobów. Puste migawki nie zastępują E_safe. |
| AMD 890M/W7900 i Intel Arc, konfiguracja mieszana | Oddzielna walidacja każdego backendu, mapowania węzłów i zakresu KFD; deny jednego GPU przy allow drugiego. Nie przenosić wyniku ROCm na Intel. |

**Minimalny bezpieczny następny krok:** utrzymać obecny stan zatrzymania usług i zakaz zatwierdzania reuse; uzgodnić zakres gwarancji: tylko usługi RM albo wydzielony fizyczny GPU compute z migracją uprawnień. Następnie zaplanować jedną kontrolowaną sesję operatora według powyższej macierzy, wykorzystując istniejący audyt zamiast dodawać moduł lub drugi scheduler. Zmiany systemowe wymagają odrębnie zatwierdzonego zakresu i planu wycofania.

**Warunki stop:** nieznany właściciel zasobów/PID, niepełne mapowanie urządzeń, niekontrolowany dostęp lub deskryptor, potrzeba naruszenia pulpitu poza uzgodnionym zakresem albo brak E_safe. `NonApprovingSafetyAdapter` pozostaje zawsze False; bez obejścia N3, release ani deklaracji `GPU_REUSE_SAFE`. Brak commit/push/merge/deploy. Ta analiza dostarcza decyzję warunkową, nie certyfikat wyłączności.
