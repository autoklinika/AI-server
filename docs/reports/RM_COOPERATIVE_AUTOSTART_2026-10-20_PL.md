# AI Platform — Cooperative RM V1: autostart i ComfyUI (20.10.2026)

## Cel i status
**DEV / procedura do jednorazowego odbioru przez operatora.**
Zachowujemy jeden aktywny Gateway + PriorityScheduler + GPUResidency,
bez nowego schedulera i bez naruszania uprawnień systemowych GPU.

Celem jest wyłączyć autostart trzech zbędnych obecnie jednostek:
`comfyui.service`, `ollama-preload.service`,
`ai-bridge-analysis.timer`, następnie uruchomić **ComfyUI tylko
na bieżącą sesję** i potwierdzić gotowość do współpracy przez
istniejący Gateway/lease'y. Nie ma automatycznego N1 GPU grant.

## Potwierdzony baseline z hosta
- Ubuntu 26.04, `multi-user.target`, bez GDM.
- `ollama.service`, `ai-gateway.service`, `ai-bridge.service`,
  SSH, Tailscale i GPU Observer aktywne.
- `comfyui.service`, `ollama-preload.service`,
  `ai-bridge-analysis.timer` nieaktywne, ale **enabled**.
- Ollama `/api/ps` nie wykazuje załadowanych modeli.
- Gateway `/status`: `gpu_residency=llm`,
  `admission_blocked=false`, `max_concurrency=1`,
  `active_count=0`, `queued_count=0`, `lease_count=0`.
- KFD/fuser bez widocznych właścicieli GPU, bez znaczników DIRTY.
- Produkcja nadal `stage-o-28e3ea214660`.
- Konfiguracja ComfyUI zawiera istniejące rozszerzenie
  `/ai-platform/residency` i lokalne API `127.0.0.1:8188`.

## Dostarczony kod
`tools/rm_cooperative_autostart_v1.py`: tylko standardowa biblioteka
Pythona i ponowne użycie
`tools/restore_cooperative_v1.py` (z poprzedniego wdrożenia).
Bez flagi `--apply` wykonuje **wyłącznie odczyty**.

Po `--apply`, w terminalu operatora:
1. Weryfikuje symlink i SHA256 znanego release, konfigurację systemd,
   brak znaczników DIRTY, wolną kolejkę, brak modeli w Ollama,
   zgodność GPU PCI i brak GPU holders w KFD/fuser root.
2. Uzyskuje interaktywne `sudo -v` i wykonuje tylko
   `systemctl disable comfyui.service ollama-preload.service
   ai-bridge-analysis.timer`. Nie dotyka działających usług.
3. Powtarza krytyczne kontrole, a następnie wykonuje
   `systemctl start comfyui.service` dla istniejącej jednostki.
   `Restart=always` ComfyUI pozostaje bez zmian — aktywny
   proces systemd może restartować po crashu, ale po reboot
   **nie uruchomi się sam**. Nie instalujemy nowej jednostki.
4. Z lokalnych endpointów sprawdza `/system_stats` (Radeon 890M),
   `/ai-platform/residency` (model/queue/cleanup idle), `/queue`
   oraz ponownie stan Gateway, modele Ollamy i trzy jednostki.
5. Przy nieudanym ComfyUI po starcie próbuje zatrzymać **tylko**
   `comfyui.service` i zapisuje `BLOCKED`. Nie resetuje GPU,
   nie czyści markerów, nie zatrzymuje Gateway/Bridge/Ollamy.
   Automatyczne przywrócenie enablement jest celowo pominięte:
   operator sprawdza stan i raport.

Wynik sukcesu: `AUTOSTART_DISABLED_COMFY_READY`.
Komenda domyślna (tylko odczyty):
```bash
python3 /srv/ai-data/evaluation/rm-cooperative-autostart-20261020/tools/rm_cooperative_autostart_v1.py
```
Właściwa akcja operatorska:
```bash
python3 /srv/ai-data/evaluation/rm-cooperative-autostart-20261020/tools/rm_cooperative_autostart_v1.py --apply
```

## Testy / ograniczenia
- Nowe testy CPU obejmują odmowy przy zajętym RM, brak modeli,
  poprawny porządek działań, awarie Comfy i ochronę Ollamy/Gateway.
- Niezależna regresja **647/647 PASS**, exit 0:
  `/tmp/rm-cooperative-autostart-regression-20261020.log`.
- Read-only preflight **PASS** na rzeczywistym serwerze.
- `--apply` **jeszcze niewykonane**; wymaga terminala operatora.
- ComfyUI aktywne nie znaczy, że jest aktywne zadanie GPU;
  Gateway dopuszcza obciążenia poprzez istniejący Resource Lease.
  Podczas startu ComfyUI mogą powstać konteksty ROCm. Nie zaliczamy
  sprzętowej generacji obrazu ani prawdziwego N1 handoff.
- GPU_REUSE_SAFE pozostaje **NOT_VERIFIED**; nie obiecujemy
  absolutnej wyłączności wobec pozostałych procesów Ubuntu.

## Po restarcie Ubuntu / rollback
Ollama, Gateway, Bridge pozostają enabled; ComfyUI i preload
nie wystartują automatycznie, podobnie timer analizy.
Przed przyszłym manualnym `systemctl start comfyui.service`
należy sprawdzić bieżącą rezerwację RM i modele Ollamy.
Nie uruchamiać wszystkiego naraz przez `systemctl enable --now`.

Jeśli wymagane jest przywrócenie starego autostartu, operator
najpierw ocenia faktyczny stan usług i przyczyny ewentualnego
`BLOCKED`; może następnie selektywnie zastosować
`sudo systemctl enable <nazwa-jednostki>`.
Nie wykonywać automatycznego rollbacku bez kontroli procesów
i stanów pośrednich.


## Incydent pierwszego uruchomienia o 08:00 i poprawka

Operator wykonał wcześniejsze `--apply`; skrypt wykonał poprawnie
`systemctl disable` dla trzech jednostek, ale zgłosił `BLOCKED`
z komunikatem `operation failed: systemctl is-enabled comfyui.service`.
Przyczyną był błędny parser kodu wyjścia: dla jednostki `disabled`
systemctl is-enabled zwraca **exit code 1**. Skrypt odrzucał
ten oczekiwany rezultat.

Faktyczne odczyty po incydencie:
- `comfyui.service=disabled`, `ollama-preload.service=disabled`,
  `ai-bridge-analysis.timer=disabled`, wszystkie nieaktywne.
- `ollama.service`, `ai-gateway.service`, `ai-bridge.service`
  aktywne; Gateway `status=ok`, brak aktywnych rezerwacji;
  KFD/fuser bez wykazanych klientów GPU.
- Nie wykonano startu ComfyUI. Nie było potrzeby rollbacku.

Poprawka w `rm_cooperative_autostart_v1.py`:
- `systemctl is-enabled` dopuszcza wyłącznie dokładnie
  `(exit=0,stdout=enabled)` lub `(exit=1,stdout=disabled)`;
  pozostałe odpowiedzi są błędem.
- Preflight rozpoznaje wcześniej wyłączone jednostki.
  Kolejne `--apply` wyłącza tylko jeszcze aktywne autostarty,
  a przy wszystkich `disabled` przechodzi od razu do weryfikacji
  i uruchomienia ComfyUI. Stan `masked`/nieznany blokuje akcję.
- Poprawkę sprawdzono na rzeczywistym hoście przez
  `READ_ONLY_PREFLIGHT_PASS` przy wszystkich trzech `disabled`.
- Pełna regresja po korekcie **651/651 PASS**, exit 0,
  `/tmp/rm-autostart-resume-regression-20261020.log`.

Jedyną pozostałą akcją jest wykonanie ponownie tej samej komendy
`--apply` przez operatora; tym razem skrypt **nie będzie ponownie
wyłączał poprawnie wyłączonych jednostek**. Przy nieznanym stanie
wyświetli `BLOCKED` i nie uruchomi nowego silnika.

Faktyczne uruchomienie ComfyUI w poprawionej wersji:
**NOT_RUN**, wymaga operatora.
