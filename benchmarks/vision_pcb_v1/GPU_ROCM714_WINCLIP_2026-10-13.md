# Vision PCB — GPU-01/02/03 i WinCLIP B1 GPU smoke — 2026-10-13

Status: **GPU-01/02/03 PASS**, trzy wznawialne partie po 24 obrazy PASS; pełny B1 GPU NIEUKOŃCZONY. Brak promocji modelu.

## Hardware, środowisko i zgodność

- Serwer AI Platform: Ubuntu 26.04.1 LTS, kernel 7.0.0-38-generic; AMD Radeon 890M, gfx1150; /dev/kfd i /dev/dri/renderD128 dostępne.
- Dokumentacja AMD: https://rocm.docs.amd.com/en/docs-7.14.1/compatibility/compatibility-matrix.html i https://rocm.docs.amd.com/en/docs-7.14.1/install/rocm.html.
- Oficjalna izolowana instalacja: PyTorch 2.12.0+rocm7.14.1, torchvision 0.27.0+rocm7.14.1, ROCm 7.14.1 z oficjalnego https://repo.amd.com/rocm/whl-multi-arch/ z extras device-gfx1150.
- Później zainstalowano anomalib 2.7.0 i open-clip-torch 2.24.0; instalacja nie nadpisała pakietu PyTorch ROCm.
- Ścieżka venv na NVMe: /srv/ai-data/evaluation/vision-pcb-envs/winclip-rocm714-py311.
- Nie modyfikowano sterownika, systemowego Pythona, Ollama, modelu Qwen3.8, adapterów ani repo Vision.

## GPU-01 — fizyczny smoke test

Wykonano pod manualną rezerwacją Gateway:
- PyTorch hip 7.14.60850; device AMD Radeon 890M Graphics, gcnArchName=gfx1150, CUDA/ROCm device_count=1.
- FP16 GEMM 512x512: PASS, wynik finite; pojedyncze obliczenie ok. 0.07305 s.
- FP16 Conv2d: PASS, wynik finite, [1,16,128,128].
- Peak allocated małego testu 37 062 144 B.
- Ostrzeżenia ROCm o libnuma/xnack nie zatrzymały testu; bez włączania eksperymentalnych flag AOTriton.
- W żadnym teście nie pojawiła się nowa awaria GPU w logach jądra (sprawdzono w podanym przedziale).

## GPU-02/03 — ten sam WinCLIP, 50 obrazów CPU versus GPU

- Model: ViT-B-16-plus-240 / laion400m_e31, checkpoint SHA256 8fb26589b9a8bab2e7a683d280e48df89b8e742f3a82132707282620b36facba.
- Dane: fold0 VisA PCB3, 25 normal i 25 anomaly; identyczna kolejność sample_id, oryginalne obrazy i transformacja, 2 wątki CPU.
- Median warm inference CPU: 2.365463 s, GPU: 0.710947 s. **3.32720x przyspieszenie**.
- Cały 50-obrazowy przebieg: CPU 118.927 s, GPU 36.8694 s (bez model init; uwzględnia wczytywanie, preprocessing i wykonanie).
- Maks. bezwzględna różnica image_score: 0.000001162291; średnia 0.000000258088.
- Peak GPU PyTorch allocated: 949 791 232 B. Nie interpretować zgłoszonego 96 GiB UMA jako wolnych 96 GiB dedykowanego VRAM.
- **Jakość klasyfikacji nie została podniesiona** przez samą zmianę backendu; zgodność wyników potwierdza techniczną przydatność do dalszego benchmarku.

## Wznawialny runner B1 GPU

- Skrypt winclip_b1_resume.py dodaje parametr --device cuda, zachowując poprzedni tryb CPU.
- Osobny katalog GPU: /srv/ai-data/evaluation/vision-pcb-datasets/visa-20220922/b1_full_winclip_gpu_fold0
- Po 24 **realne obrazy z mapami 256x256** na calibration PCB2, holdout PCB3 i challenge PCB4 = **72/3312**, każdy wpis z oryginalnym hash i mapą, wznawialny bez mieszania z poprzednimi 319 wynikami CPU.
- Trzy osobne krótkie sesje ~28 sekund inferencji/24 obrazy; procesy zakończyły się poprawnie, a Gateway po każdej pozostał wolny.
- Brak oficjalnego punktowego raportu B1 przed ukończeniem 3312/3312. Nie wolno scalać wyników CPU i GPU bez osobnego porównania polityki/proweniencji.

## Ważne ograniczenie bezpieczeństwa / brak automatyzacji

Gateway Resource Manager ma istniejący profil external obejmujący Ollama/ComfyUI, **nie natywny Vision GPU provider**. Wykorzystano go wyłącznie do krótkich, ręcznie autoryzowanych okien konserwacyjnych z potwierdzeniem pustego /api/ps, kontrolą statusu, rezerwacją slotu, heartbeat, limitem czasu, wymuszeniem przerwania procesu przy utracie heartbeat i zwolnieniem slotu w finally.

Ten guard **nie stanowi docelowej GPU admission authority dla Vision**. Nie uruchamiać ciągłego zadania ani treningu GPU bez wprowadzenia i zatwierdzenia specjalizowanego profilu Vision GPU w Resource Managerze i testu recovery/rollback. Należy unikać bezpośredniego równoległego użycia GPU poza Gateway.

Test ścieżki negatywnej: brak ROCm w wersji PyTorch CPU spowodował odmowę; timeout fikcyjnego zadania przerwał proces. Po obu testach lease_count=0, active=0. Nie pozostawiono GPU residency marker.

## Status CI / produkcji

Skrypty na gałęzi feature/vision-pcb-benchmark-v1-20261013, PR #160 (draft; merge wymaga zgody właściciela). Oryginalny main czysty, Ollama i AI Gateway aktywne, brak rezydentnych modeli.

Następny etap: GPU Resource Manager Vision provider (dev + testy), potem pełny B1 z kontrolą obciążenia, kompletnością, pixel-AUPRO256 i audytem jakości.
