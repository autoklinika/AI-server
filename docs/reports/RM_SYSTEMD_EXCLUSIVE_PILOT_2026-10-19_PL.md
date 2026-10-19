# RM EXCLUSIVE — systemd runtime pilot (DEV), 2026-10-19

## Zakres

Dostarczono jeden z góry ustalony, odwracalny pilot dla Radeon 890M:
`tools/run_rm_systemd_exclusive_three_engine_dev.sh`. Uruchamiany
**przez zwykłego operatora**, używa sudo wyłącznie do wywołań systemowego
systemd-run i zatrzymania własnych transient units. Nie wdraża żadnych
stałych unitów ani polityk, nie zmienia grup, udev, sterownika lub
`/opt/ai-platform/current`.

## Sekwencja

1. Preflight: GDM, Gateway, Bridge, Ollama, ComfyUI i timer analiz muszą
   być inactive; GPU AMD PCI 1002:150e; KFD+cross-UID root fuser puste.
   Globalny flock uniemożliwia dwa równoległe wykonania tego pilota.
2. Start root-managed transient service Ollama jako UID ollama,
   DevicePolicy=strict i allowlist tylko /dev/kfd oraz renderD128,
   RuntimeMaxSec 95s, Restart=no, KillMode=control-group.
   Model bge-m3; lokalny API embedding 1024. Zidentyfikuj każdy GPU FD PID,
   sprawdź jego systemd cgroup i dopiero zatrzymaj całą własną jednostkę.
3. Zaliczenie postflight wymaga zakończonej jednostki, pustego cgroup,
   zatrzymania pozostałych usług i trzech kolejnych pustych próbek KFD/fuser.
4. Analogicznie ComfyUI z osobnymi DEV input/output/user/temp,
   portem 8189, bez custom nodes, tylko inicjalizacja ROCm.
5. Vision jako jednorazowy fixed 64x64 ROCm worker w transient systemd
   z tym samym DevicePolicy; status WORKER_LOCAL_SYNC i postflight.
6. Dowolna odmowa/awaria/unknown powoduje przerwanie i DIRTY.
   EXIT trap zatrzymuje **tylko własną** transient jednostkę.
   Systemowe usługi AI pozostają nieaktywne.

## Wyniki faktyczne

- DEV source i `bash -n`: PASS.
- `tests/test_rm_systemd_exclusive_three_engine_dev.py`: offline PASS,
  sprawdzone deny/boundaries/ordered engines, brak możliwości zmiany stałej
  konfiguracji hosta w pilocie.
- Szersza regresja N1–N5 + Gateway + nowe narzędzia: **617/617 PASS**,
  exit 0, log `/tmp/rm-systemd-exclusive-full-20261019.log`.
- `SYSTEMD_SUPERVISED_THREE_ENGINE_HARDWARE=NOT_RUN`: root manager
  wymaga interaktywnego operatora/sudo; zdalny agent nie otrzymał
  uprawnień administracyjnych. Nie zastępowano tego obejściem.
- Wcześniejszy lokalny test trzech silników: 3/3 PASS, ale pracował
  poza systemowym systemd (zob. RM_THREE_ENGINE_HARDWARE_SMOKE_2026-10-19_PL.md).

## Bardzo ważne ograniczenia

To akceptacyjny **pilot operacyjny systemd**, nie implementacja
production N1 GPU grant. NonApprovingSafetyAdapter N3 niezmieniony.
Pomyślne zakończenie procesu, puste KFD i fuser, nawet poprawne cgroup
nie są atomowym dowodem E_safe dla GPU/sterownika. Inni członkowie
grupy render nadal potencjalnie mogą otwierać GPU poza pilotem.
Nie można na tej podstawie włączyć automatycznego N1.recover/release.

## Operator

Przy aktywnym oknie serwisowym (wszystkie pięć usług AI inactive):

```bash
bash /srv/ai-data/evaluation/rm-exclusive-handoff-dev-20261019/tools/run_rm_systemd_exclusive_three_engine_dev.sh
```

Skrypt prosi o sudo -v, tworzy unikalny katalog
`/srv/ai-data/evaluation/rm-exclusive-handoff-dev-20261019/systemd-pilot/attempt-*`
i zapisuje `summary.log`, `ollama.json`, `http.json`, `vision.log`.
Przed zleceniem skryptu operatorowi należy jeszcze przejrzeć utrwalenie
PID/cgroup przy różnych UID na docelowym serwerze. Jeżeli unit nie ruszy
lub cleanup pozostawi kontekst, STOP i niezależna diagnoza, bez resetu GPU.
