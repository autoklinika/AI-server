# Vision GPU RM — cross-UID terminal-state evidence, security gate (13.10.2026)

**Status: NO-GO / tylko gałąź DEV PR #163, bez cutover, bez restartu produkcji.**

## Wynik faktyczny CPU-only E2E

Po autoryzowanym przebiegu 21:17:18 CEST diagnostyka administratora zwróciła:

- `DEV_CPU_RESULT_PRESENT=True`, oczekiwany schemat `True`, wynik `cpu_only`, `worker_uid=994`, `rm_control_credential_absent=True`, `gpu_imports=False`.
- `DEV_JOB_1_worker_log_EXISTS=True`, `VISION_CROSS_UID_CPU_WORKER=PASS`, plik autoryzacji workera istniał.
- `DEV_BLOCK_MARKER_PRESENT=False`, `DEV_BROKER_SOCKET_PRESENT=False`.
- DEV gateway i broker inactive/success, runner failed/exit-code.
- Produkcyjny Gateway i Ollama active; produkcyjne GPU residency=llm, recovery_required=false, leases=0.

**Potwierdzenie:** to rzeczywiście działający CPU worker pod UID 994, autoryzowany przez brokera pod UID 993. **Niepotwierdzone:** pozytywny cleanup/release w izolowanym DEV RM. Nie uznawać całego E2E za PASS.

**Uwaga co do przyczyny:** brak DEV markera przy jednoczesnym błędzie `finish` nie pasuje jednoznacznie do scenariusza, w którym `GPUResidency.leave_vision()` odmawia zwolnienia (taki błąd powinien pozostawić marker). Również błąd późniejszego `DELETE /resource/leases`, odpowiedź `denied` lub `gateway_error` mogły zakończyć `finish` niepowodzeniem. Bez przechwyconego, **niesekretnego statusu odpowiedzi brokera** nie da się wskazać jedynej przyczyny awarii 21:17. Nie przypisywać jej kategorycznie cross-UID. Wykryty defekt terminalnego potwierdzania scope jest niezależnym blokującym problemem bezpieczeństwa.

## Konkretna blokada dowodu cleanupu

`vision_residency_evidence.scope_members_or_terminal()` jest wywoływane przez DEV gateway pod UID 993, podczas gdy worker i systemd user scope należą do UID 994. Po zakończeniu workera kernelowy katalog `vision-bench-*.scope` znika. Funkcja wówczas sprawdza ścieżkę systemd z bieżącym UID 993, nie 994, co zwraca brak dowodu (`None`). Niezależny odczyt `systemctl --user --machine=ai-vision@.host` jako nieuprawniony użytkownik odmówił dostępu (`Permission denied`). Ta własność to uzasadniona hipoteza przyczyny `cleanup not verified`; specyficzny kod odpowiedzi `finish` nie został zalogowany, więc bez dodatkowych dowodów nie traktować jej jako jedynej pewnej przyczyny.

### Dodatkowe znalezisko — jednostka `not-found`

Odczyt prawdziwego systemd dla nieistniejącej jednostki (z poprawnym dostępem do lokalnego user bus) zwrócił `LoadState=not-found`, `ActiveState=inactive`, `SubState=dead`, `ControlGroup=` **i exit code 0**. Dawny kod akceptował sam stan inactive + pusty ControlGroup jako dowód terminalny, co groziło fałszywym release dla nieistniejącej jednostki.

Poprawka w DEV: przy pustym **lub nieobecnym** `cgroup.procs` dopuszczalny jest wyłącznie kompletny, odczytany od uprawnionego systemd `LoadState=loaded, ActiveState=inactive, SubState=dead, ControlGroup=""`. Brak pola, `not-found`, działająca jednostka, brak dostępu do managera, jakiekolwiek niejednoznaczności => `None` (fail-closed). Nie przyjęto osłabienia dowodów. Testy deterministyczne obejmują m.in. `not-found`, pusty cgroup przy active, brak uprawnień między UID oraz brak lub fałszywe pola.

## Rekomendowany kierunek do decyzji architektonicznej

Wykorzystać **istniejącego** uprzywilejowanego obserwatora GPU, zamiast tworzyć nowy harmonogram GPU. Dodać wyłącznie wąski, odczytowy protokół *identity-bound terminal attestation* dla scope UID 994:

1. Kontroler UID 993 rejestruje dokładnie autoryzowany scope podczas życia procesu i przed jego odblokowaniem: PID, birth ticks, UID 994, dokładną nazwę `vision-bench-[0-9a-f]{12}.scope` i ścieżkę cgroup; root weryfikuje je z `/proc`, kernelowym cgroup oraz właściwą jednostką systemd user managera.
2. Obserwator zaufany monitoruje cykl życia jednostki do terminalnego stanu (nie akceptuje `not-found` jako dowodu). Ponieważ transient units mogą zniknąć zaraz po zakończeniu, potrzebny jest **dowód zaobserwowanego przejścia**, nie późniejsze sprawdzenie nazwy jednostki, której już nie ma.
3. Przed pozytywnym release wymagana jest nieprzerwana weryfikacja tożsamości (PID+birth), zakończenia workera, braku potomków cgroup i niesprzecznego stanu systemd, oraz istniejące dowody z obserwatora GPU: lista nowych FD, VRAM baseline, Ollama/Comfy idle. Jeśli jakiś dowód nie był zbierany, obserwator stracił stan albo pojawiła się niezgodność — BLOCKED, marker zachowany.
4. Kontroler nadal jest jedynym właścicielem sekretu RM. Worker UID 994 dostaje tylko ograniczoną capability do jednego use. Obserwator root nie wykonuje dowolnych poleceń, nie przyjmuje dowolnych ścieżek ani nie udostępnia szerokiego systemd API. `SO_PEERCRED` i ścisły schemat muszą zabraniać dostępu `ai-vision` do endpointu terminalnego.
5. Przed uruchomieniem pełnego E2E wykonać testy: nieistniejąca jednostka, reuse PID, podmiana UID, sfałszowany scope, potomek opuszczający cgroup, restart obserwatora, utrata systemd bus, utrata GPU FD snapshot, marker po crash, runner SIGKILL.

To **projekt rozwiązania do niezależnego security review**, nie wdrożona funkcja. Rozszerzenie observera lub jego restart wymaga osobnej oceny zakresu i decyzji właściciela projektu. Root observer może mieć ograniczenie `ProtectHome=yes`, obejmujące `/run/user`: przed decyzją trzeba wykazać najwęższy możliwy sposób odczytu systemd user managera bez rozszerzania uprawnień modelu.

## Następne bramki

- [x] Rzeczywisty worker CPU-only pod UID 994; brak sekretu, prawidłowy wynik.
- [x] Bezpieczny cleanup usług DEV po niepowodzeniu; produkcja bez zmian.
- [x] Walidacja `not-found` i pustego cgroup w DEV, testy negatywne.
- [ ] Niezależnie zweryfikowany cross-UID terminal-state attestation.
- [ ] Ponowny realny CPU-only E2E, pełny `released`, marker absent, wszystkie jednostki DEV stopped i GPU leases 0.
- [ ] WinCLIP ROCm cross-UID + awarie SIGKILL/timeouts + niezależny audyt PR #162.
- [ ] Jawna decyzja właściciela projektu o ewentualnym merge/cutover.

**Nie uruchamiać kolejnego E2E w obecnym stanie. Nie resetować markera ani nie zwalniać lease na podstawie `not-found`, samego `worker.log` lub niepotwierdzonego stanu scope.**
