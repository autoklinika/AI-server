# AI Platform — systemd EXCLUSIVE: wynik rzeczywisty 2026-10-19

## Decyzja po pilocie

**LOCAL_SYSTEMD_HANDOFF_PASS_3_OF_3 — PASS (sprzęt, operator, realny Radeon 890M).**

Operator wykonał skrypt:
`tools/run_rm_systemd_exclusive_three_engine_dev.sh`

Dowód lokalny:
`systemd-pilot/attempt-20261019-204102-jaYfEzik/`.
Sprawdzono `summary.log`, `ollama.json`, `vision.log`, dziennik
systemd oraz stan hosta po próbie. SHA256 czterech oryginalnych
artefaktów i wynikowe identyfikatory jednostek są w pliku
`RM_SYSTEMD_EXCLUSIVE_HARDWARE_RESULT_2026-10-19.json`.
Surowe logi i embeddingi pozostają lokalnie i nie są publikowane.

## Faktycznie zakończone kroki

| Silnik | Jednostka transient systemd | Wynik |
|---|---|---|
| Ollama | ai-rm-p204102-230626-ollama.service | PASS — bge-m3 embed 1024, GPU runner PID 230816 w przypisanym cgroup |
| ComfyUI | ai-rm-p204102-230626-comfy.service | PASS — ROCm runtime/init, KFD PID 230971 we właściwym cgroup |
| Vision | ai-rm-p204102-230626-vision.service | PASS — ROCm 64×64, status WORKER_LOCAL_SYNC i exit 0 |

Potwierdzono `DevicePolicy=closed` oraz jawne dopuszczenie tylko
`/dev/kfd` i `/dev/dri/renderD128` dla transient jednostek.
Ollama i ComfyUI zostały zatrzymane poprzez systemd, nie przez
samo odładowanie modelu. Obie jednostki odnotowały
`Deactivated successfully`, a Vision zakończył się statusem
`0/SUCCESS`. Po każdym etapie były trzy kolejne puste odczyty
KFD/fuser. O 22:42 CEST jednostki były nieaktywne i nie wykryto
aktywnych właścicieli KFD/DRM. W sprawdzonych logach kernela brak
wpisów wskazujących na nowy reset/hang/timeout AMDGPU/MES.

Pierwsza próba tego dnia skończyła się `208/STDIN` wskutek
`DevicePolicy=strict` bez standardowego `/dev/null`. Poprawka
`DevicePolicy=closed` przeszła poprzednio 617/617 testów i ten pilot.

## Ograniczenia, których nie wolno przemilczeć

- `REAL_N1_GPU_GRANT=NOT_ADMITTED`: ten test wykonał skrypt
  operatora, NIE produkcyjny Resource Manager.
- `GPU_REUSE_SAFE=NOT_VERIFIED`: KFD/fuser są punktową obserwacją,
  nie niezależną certyfikacją zamknięcia kolejek w sterowniku AMDGPU/MES.
- `GLOBAL_OS_EXCLUSIVITY=NOT_VERIFIED`: inne procesy hosta z
  uprawnieniami grupy `render` mogą ominąć RM poza transient usługami.
- ComfyUI potwierdziło inicjalizację ROCm, ale nie generowało obrazu;
  Ollama liczyła lekki embedding na GPU, nie pełny Qwen 27B.
- Nie wykonywano awarii z wstrzyknięciem błędu sterownika,
  hot handoff pod dużym obciążeniem ani rzeczywistego N1.release.

## Architektura — kolejne 2 kroki

1. Ustalić wyłączny, zaufany punkt uruchamiania
   `systemd-run` pod istniejącym Gateway RM: stały profil silnika,
   tożsamość boot/PID/starttime/cgroup/InvocationID, ograniczona
   kolejka, brak równoległego bypassu przez inne API/usługi oraz
   idempotentne stop/recovery. Zmiany najpierw DEV, bez dodania
   nowego schedulera czy root demona.
2. Oddzielnie opracować wiarygodny profil zaufania dla sterownika
   i politykę zatrzymania `BLOCKED` przy niepewnym release,
   bez włączania `NonApprovingSafetyAdapter` na True w DEV.
   Dopiero po pozytywnym odbiorze realny N1 EXCLUSIVE.

## Stan hosta po pilocie

GDM, Gateway, Bridge, Ollama, ComfyUI, timer analizy — inactive;
`ai-vision-gpu-observer` — active. Headless `multi-user.target`.
Brak zmian produkcyjnych; żadna transient jednostka nie pozostała
aktywna.
