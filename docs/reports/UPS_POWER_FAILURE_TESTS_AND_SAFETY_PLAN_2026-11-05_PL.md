# AI Platform / Global NAS / VISION — testy UPS i plan zabezpieczenia zasilania

**Data:** 2026-11-05 (Europe/Warsaw)  
**Status:** `BASELINE / PLAN ZATWIERDZONY DO WDROŻENIA` — pomiary wykonane, automatyczne wyłączenia i test na baterii **jeszcze niewdrożone / niezweryfikowane**  
**Systemy:** Minisforum AI Platform (Ubuntu), Global NAS (QNAP), PowerWalker UPS USB→NAS, switch UniFi, przyszły zestaw VISION + AgileX NERO, druga karta RTX  
**Repozytorium:** `autoklinika/AI-server`  
**Cel:** udokumentowanie rzeczywistych pomiarów, uzgodnionego budżetu 5 min oraz warunków bezpiecznego zamknięcia systemów po utracie zasilania.

> **Decyzja nadrzędna:** projektujemy tak, jakby UPS zapewniał **maksymalnie 300 sekund** dostępnego czasu. To konserwatywny limit projektowy, **nie zmierzony ani gwarantowany czas autonomii**. Celem jest zakończenie wszystkich czynności krytycznych do **120 s**, przy rezerwie do 300 s. W razie niepowodzenia testów rozważamy kompatybilny dodatkowy moduł bateryjny.

## 1. Zastany stan infrastruktury

- UPS jest rozpoznawany przez NAS po USB. NAS udostępnia dane protokołem NUT (Network UPS Tools, TCP/3493).
- Odczyt serwera NUT z Minisforum: `qnapups@192.168.1.101:3493`. Adres Minisforum: `192.168.1.100`.
- Odpowiedź serwera NUT: `Network UPS Tools upsd 2.7.4`; sterownik `usbhid-ups`.
- Zgłaszana identyfikacja urządzenia HID: producent `PHOENIXTEC`, model `Innova Unity`. Nazwa handlowa instalacji: **PowerWalker VFI 3000 ICR IoT**; **przed przyjęciem 3000 W jako twardej granicy potwierdzić tabliczkę znamionową / SKU i specyfikację używanego egzemplarza**.
- Podczas odczytów: status `OL CHRG` (zasilanie sieciowe/ładowanie), bateria `100%`.
- Zmienne udostępniane przez ten NAS: `ups.status`, `ups.load`, `battery.charge`, `battery.runtime`, `battery.voltage`, m.in. Zmienne `ups.realpower` oraz `input.voltage` zwracały `ERR VAR-NOT-SUPPORTED`.
- **Nie ma bezpośredniego pomiaru mocy wyjściowej w watach** z obecnie udostępnianego NUT; `ups.load` to wskaźnik procentowy, zaokrąglany/odświeżany z opóźnieniem.
- Na Minisforum w chwili audytu nie było zainstalowanego klienta NUT (`nut-monitor/upsmon`); dostępny był jedynie odczyt TCP. Automatyczne wyłączenie **nie jest jeszcze aktywne**.
- Główny switch UniFi łączący NAS z Minisforum **jest podłączony do UPS** — potwierdzenie użytkownika. Zasilanie bramy UniFi, routera INEA i pozostałych elementów toru do VISION należy jeszcze zweryfikować.

## 2. Metodyka i wyniki przeprowadzonych testów

Testy przeprowadzono **przy obecnym zasilaniu sieciowym (bez odłączania UPS)**, na faktycznie podłączonym Minisforum z Ryzen AI 9 HX 470 / Radeon 890M i RTX 5060 Ti 16 GB. Odczyty GPU: `nvidia-smi`; AMD: `/sys/class/drm/card0/device/gpu_busy_percent`, czujniki `amdgpu` i `k10temp`; UPS: NUT `GET VAR qnapups ...`. Obciążenie RTX generowano krótkimi zadaniami CUDA/cuBLAS; Radeona — shaderem compute Vulkan; CPU — obciążeniem AVX/FMA 24 wątków.

| ID | Zakres i czas | Uzyskane obciążenie | Maks. moc RTX | Maks. temperatura | Obciążenie UPS |
|---|---|---|---:|---|---:|
| T0 | Stan bez obciążenia | RTX 0%, GPU AMD 0% | ~3–5 W | RTX ~33–40°C | 10% |
| T1 | RTX CUDA compute, 45,1 s | RTX 100% | 97,26 W | RTX 59°C | 10→13% |
| T2 | RTX cuBLAS, 60,0 s (FP32 32 s + TF32 28 s) | RTX 100% | 161,94 W (FP32); TF32 ~97 W | RTX 65°C | 10→15%, później 13% |
| T3 | RTX FP32, większe macierze, 35,0 s | RTX 100% | **168,57 W** | RTX 66–67°C | 10→15% |
| T4 | CPU + Radeon + RTX, 38,6 s | CPU **100%**, Radeon do **98%**, RTX **100%** | **167,04 W** | CPU 63°C, Radeon 61°C, RTX 66°C | **10→17%** |

**Dodatkowe wyniki T4:**
- Maksymalny odczyt `amdgpu power1_average` (`PPT`) ~**64,99 W**. **To nie jest niezależny watomierz Radeona** — metryka obejmuje domenę raportowaną przez AMD i nie należy sumować jej bezpośrednio z osobnym poborem CPU.
- `ups.status=OL CHRG`, `battery.charge=100%` przez cały test.
- `battery.runtime` zmieniło się z **4853 s** do **2515 s** (~41 min 55 s) w trakcie T4. **To tylko wewnętrzna estymacja UPS podczas pracy z sieci, nie wynik testu autonomii baterii i nie przesłanka do wydłużenia 5-minutowego założenia.**
- Po T4: RTX 0%, ~4,63 W, Radeon 0%, brak uruchomionych procesów stresowych, UPS nadal `OL CHRG`; brak błędów podczas testów.
- Odczyt NUT zmieniał procent obciążenia z opóźnieniem. Największy zarejestrowany odczyt w T4 to **17%**; nie wyklucza krótkich pików pomiędzy odczytami.
- RTX **nie osiągnęła 180 W** (ustawionego limitu mocy), ale uzyskano ~**93,7% limitu** w teście T3. Wskaźnik „100% GPU” nie jest synonimem „100% limitu mocy”.

### Ograniczenia pomiarów

1. Brak pomiaru watomierzem AC i brak `ups.realpower` w NUT. `17%` nie jest pomiarem dokładnie 510 W. Przy **założeniu** nominalnych 3000 W i przy założeniu, że `ups.load` odpowiada procentowi mocy czynnej, daje to **orientacyjnie ~510 W**, nie wynik laboratoryjny.
2. Obecny test nie obejmował dodatkowej RTX ani VISION/NERO — oba urządzenia to przyszłe odbiorniki.
3. Nie testowano pracy na akumulatorze, rzeczywistego czasu rozładowania, wyłączenia NAS/Ubuntu, zachowania stanu NUT po wyłączeniu NAS, ani ponownego uruchomienia po powrocie zasilania.
4. CPU i iGPU korzystają ze wspólnych ograniczeń energetycznych APU; jednoczesne 100% CPU i ~98% GPU oznacza nasycenie jednostek, nie sumę ich hipotetycznych indywidualnych maksimów.
5. Testy trwały kilkadziesiąt sekund i nie potwierdzają długookresowej stabilności termicznej całej zabudowy; dotyczy to również przyszłego drugiego GPU.

## 3. Docelowy bilans obciążenia (projektowy, nie pomiar)

| Pozycja | Maksimum / przyjęta baza | Źródło |
|---|---:|---|
| Obecne urządzenia na UPS przy T4 | **~510 W (orientacyjnie)** | 17% × *założone* 3000 W, obarczone zastrzeżeniami |
| Planowana druga RTX | **+300 W** | wartość maksymalna podana przez użytkownika |
| Planowane AgileX NERO + VISION | **+500 W** | wartość maksymalna podana przez użytkownika |
| **Suma robocza** | **~1310 W** | 510 + 300 + 500, wyłącznie orientacyjnie |
| **Udział w 3000 W** | **~43,7%** | tylko jeżeli rzeczywista moc znamionowa tego UPS wynosi 3000 W |

**Nie traktować 1310 W jako potwierdzonego najgorszego przypadku.** Zweryfikować: rzeczywistą moc UPS (VA/W), wszystkie odbiorniki i straty zasilaczy, pozostały zapas na prądy rozruchowe / skoki obciążenia, obciążalność gniazd oraz rzeczywisty pobór drugiej karty i robota po instalacji. Jeśli UPS podtrzymuje infrastrukturę sieciową, jej pobór musi znaleźć się w bilansie (sprawdzić, czy zawierał się już w 17%).

Przyjęte przez użytkownika **5 min** obowiązuje **niezależnie od wskazania `battery.runtime`**. W razie stwierdzenia niewystarczającej autonomii: rozważyć **wyłącznie kompatybilny** moduł baterii po potwierdzeniu możliwości rozszerzenia dla konkretnego SKU UPS.

## 4. Ostateczne założenia projektowe procedury

1. **Cel:** bezpieczne zamknięcie obciążeń i danych do **120 sekund** od potwierdzonego zaniku sieci; **300 sekund** to twardy budżet planowania autonomii, a nie moment rozpoczęcia wyłączenia.
2. **NUT:** NAS jest źródłem informacji UPS po USB i udostępnia odczyty Minisforum. Należy wdrożyć po stronie Ubuntu monitor NUT oraz kontrolowaną logikę zdarzeń; dla VISION/NERO wymagane niezawodne powiadomienie po LAN lub dodatkowa niezależna ścieżka.
3. **RM:** blokuje nowe zadania, zatrzymuje obliczenia obu RTX / Radeona i długie prace bez oczekiwania na ich naturalne zakończenie; zapewnia zakończenie transakcji / zapisów baz danych i plików.
4. **NERO:** automatyczne parkowanie **obowiązkowe, o ile stan robota pozwala na bezpieczny ruch**; przy sprzętowym E-STOP nie wykonywać automatycznego ruchu/parkowania. Nie zastępować E-STOP software'em. Przed wyłączeniem napędów trzeba potwierdzić działanie hamulców i bezpieczny stan robota; awaria parkowania → udokumentowany stan bezpieczny zgodny z dokumentacją producenta, bez niekontrolowanego ruchu.
5. **VISION:** utrzymywać zasilanie jego sterowania i toru komunikacji do potwierdzenia końca parkowania / bezpiecznego zatrzymania.
6. **NAS:** kończy własne operacje i zamyka woluminy **po otrzymaniu potwierdzenia** zakończenia krytycznych zapisów klientów lub upływie niezależnego limitu. Sprawdzić, czy jego tryb UPS oferuje Auto-protection / shutdown i jakie są rzeczywiste opóźnienia. Nie zakładać, że zostało to już skonfigurowane.
7. **UniFi:** główny switch jest na UPS — nie musi otrzymywać osobnego zdarzenia zaniku napięcia, jeśli zapewnia komunikację między urządzeniami. Brama/router i WAN są potrzebne do powiadomień zewnętrznych, ale samo lokalne zamknięcie musi działać bez Internetu.
8. **Telegram:** alert zaniku / przywrócenia zasilania i wyników zamknięcia to element **do wdrożenia/weryfikacji**, a nie potwierdzony działający alarm.
9. **Bezpieczny powrót zasilania:** wznowienie dopiero przy stabilnym zasilaniu i po sprawdzeniu integralności NAS, gotowości sieci, RM, GPU, magazynu i backupów. Samo „AC Power Restore” BIOS nie uruchomi komputera, jeśli UPS nigdy nie odcina napięcia — sprawdzić WoL lub inny kontrolowany mechanizm restartu.
10. **Utrata LAN/NUT:** nie polegać wyłącznie na jednej komunikacji sieciowej, rozróżniać chwilowy brak odczytu od utraty zasilania; wdrożyć lokalny watchdog/czas ostateczny i tryb degradacji, aby urządzenia nie zawisły w oczekiwaniu na sygnał od NAS. Czas wyłączenia monitorować i logować.

### Proponowany harmonogram — wymaga potwierdzenia testami

| Od zaniku | Cel i zależność | Status |
|---|---|---|
| 0–5 s | Sygnał `OB` / wykrycie braku sieci, blokada nowych zadań, alert | plan |
| 5–15 s | RM zatrzymuje zadania; VISION przygotowuje NERO do parkowania | plan |
| 5–30 s | NERO parkuje, o ile nie ma E-STOP / niebezpiecznego stanu; potwierdzenie stanu bezpiecznego | plan, czas **niezmierzony** |
| 15–60 s | Zamknięcie usług AI, utrwalenie danych i wyłączenie Ubuntu | plan, czas **niezmierzony** |
| 30–60 s | Po parkowaniu / safe state wyłączenie napędów NERO i zbędnych odbiorników | plan |
| 60–120 s | Końcowa ochrona danych i wyłączenie QNAP; weryfikacja zamknięcia wszystkich klientów | plan, czas **niezmierzony** |
| 120–300 s | Rezerwa energetyczna na opóźnienia; nie planować normalnej pracy | rezerwa |

**Ważne:** krytycznie niski stan baterii / `LB` uruchamia natychmiastową ścieżkę awaryjną, bez czekania na timery. Nie może wywołać niebezpiecznego ruchu robota. Projekt nie może zakładać, że czas pracy baterii jest liniowo zależny od procentu obciążenia. Jeśli napięcie wróci po rozpoczęciu fazy nieodwracalnego zamykania, nie należy automatycznie przerywać sekwencji bez jawnej reguły stanu.

## 5. Kryteria akceptacyjne GO (niezaliczone jeszcze)

- [x] UPS → NAS USB; status i parametry NUT odczytane przez Minisforum.
- [x] Potwierdzone zasilanie głównego switcha UniFi z UPS.
- [x] Testy obciążenia CPU, Radeon 890M i RTX 5060 Ti oraz pomiar `ups.load`.
- [ ] Zweryfikować SKU / rzeczywistą moc znamionową UPS i obciążalność całego toru.
- [ ] Zainstalować i skonfigurować monitor NUT na Minisforum bez konfliktu z usługami produkcyjnymi.
- [ ] Zatwierdzić działającą procedurę QNAP UPS (Auto-protection vs shutdown) i kolejność zamykania względem NUT.
- [ ] Wdrożyć blokadę nowych zadań RM, bezpieczne zatrzymanie usług i baz danych, logi oraz alerty.
- [ ] Wdrożyć procedurę NERO: parkowanie, E-STOP, failure path, bezpieczne wyłączenie napędów i VISION.
- [ ] Potwierdzić podtrzymanie infrastruktury sieciowej także na trasie do VISION i dla Telegrama.
- [ ] Przeprowadzić **symulację zdarzenia bez odłączenia sieci**; potwierdzić timery i brak przypadkowego wyłączenia produkcji.
- [ ] Zmierzyć realny czas zamknięcia Ubuntu, NAS i NERO podczas kontrolowanego testu.
- [ ] Po akceptacji testu na sucho przeprowadzić nadzorowany test rzeczywistego zaniku wejścia UPS z zabezpieczonymi danymi oraz odtworzeniem.
- [ ] Powtórzyć pomiar po dołączeniu drugiej RTX i VISION/NERO (wartości +300/+500 W są dziś tylko założeniami maksymalnymi).
- [ ] Zweryfikować zachowanie po powrocie zasilania (NAS, WoL/BIOS Minisforum, kontrola RM/GPU/usług, brak samoczynnego startu NERO bez kontroli).

## 6. Decyzja końcowa (2026-11-05)

**Akceptujemy budżet projektowy 5 minut i najpierw wdrażamy oraz testujemy procedury zamknięcia.** Nie zamawiamy na tym etapie dodatkowych baterii; decyzję o rozbudowie podejmiemy dopiero po wykazaniu niewystarczającej autonomii lub marginesu bezpieczeństwa. UniFi nie wymaga osobnego sterowania awaryjnego — zasadnicze jest jego podtrzymanie, już potwierdzone dla głównego switcha.

**Ograniczenie zakresu niniejszego wpisu:** dokument opisuje wyniki pomiarów i docelowe wymagania; **nie poświadcza wdrożenia ani zaliczenia testu wyłączeniowego**.
