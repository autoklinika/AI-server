# Hermes — lokalne generowanie wideo, Stage 23

Data: 2026-09-05

## Decyzja

Wszystkie płatne/chmurowe backendy wideo zostały odrzucone. Stage 23 działa lokalnie:

```text
Telegram /wideo
    -> Hermes skill
    -> /usr/local/bin/generate-video-telegram
    -> /usr/local/bin/generate-video
    -> ComfyUI 127.0.0.1:8188
    -> Wan2.2 TI2V-5B
    -> MP4 na Serwerze AI
    -> Hermes gateway dostarcza plik do Telegrama
```

To celowo kopiuje sprawdzony wzorzec lokalnego `/foto`, który korzysta z istniejącego `comfyui.service` i FLUX.2 Klein. Nie dokładamy `video_gen` do stałego Telegram toolsetu, dzięki czemu zwykłe rozmowy zachowują lekki profil `terminal + file + web`.

## Model

Pierwszy lokalny backend:

- Wan2.2 TI2V-5B,
- text-to-video i image-to-video w jednym modelu,
- natywne nody ComfyUI,
- 24 FPS,
- oficjalny model obsługuje do 720p,
- brak zewnętrznego API podczas inferencji.

Pliki ComfyUI:

- `models/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors`
- `models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`
- `models/vae/wan2.2_vae.safetensors`

Wagi są pobierane z publicznych repozytoriów Comfy/Wan tylko podczas instalacji. Po pobraniu renderowanie jest lokalne.

## Dlaczego Wan2.2 5B jako pierwszy

Serwer ma już działający lokalny ComfyUI/ROCm dla FLUX.2 Klein. Wan2.2 5B korzysta z natywnych nodów ComfyUI i jest znacznie lżejszy od nowych modeli 20B+ takich jak LTX-2.3 22B. Najpierw mierzymy realną wydajność na Radeon 890M, a dopiero potem rozważamy drugi cięższy backend.

## Profile renderowania

| preset | rozdzielczość | klatki | fps | czas materiału | kroki |
| --- | ---: | ---: | ---: | ---: | ---: |
| `smoke` | 512×288 | 17 | 24 | ~0.7 s | 4 |
| `fast` | 640×352 | 49 | 24 | ~2.0 s | 10 |
| `balanced` | 832×480 | 81 | 24 | ~3.4 s | 20 |
| `quality` | 1280×704 | 121 | 24 | ~5.0 s | 20 |

`fast` jest domyślny dla Hermesa. `quality` nie jest uruchamiany automatycznie.

## Ochrona istniejących usług

Stage 23:

- nie modyfikuje Ollamy,
- nie zmienia AI Gatewaya,
- nie zmienia analizy wentylacji,
- nie zmienia istniejących wrapperów `/foto`,
- nie aktualizuje automatycznie ComfyUI,
- przed renderem czeka krótko, aż AI Gateway nie ma aktywnego ani oczekującego zadania,
- po renderze wywołuje ComfyUI `/free` z `unload_models=true` i `free_memory=true`, żeby zwolnić pamięć po Wan2.2.

ComfyUI ma własną kolejkę, więc lokalne obrazy FLUX i lokalne wideo Wan nie uruchamiają się jednocześnie w ramach tego samego ComfyUI.

## Instalacja

Rozwój jest na osobnej gałęzi. Z produkcyjnego `main` nie wykonujemy merge bez osobnej zgody.

Na Serwerze AI:

```bash
cd ~/AI-server
git fetch origin
git worktree add ../AI-server-local-video-stage23 origin/feat/hermes-local-video-stage23
cd ../AI-server-local-video-stage23
bash tools/install_hermes_local_video_stage23.sh
```

Instalator:

1. sprawdza `comfyui.service` i `hermes-gateway.service`,
2. sprawdza API ComfyUI na `127.0.0.1:8188`,
3. sprawdza obecność natywnych nodów Wan2.2/SaveVideo,
4. wykrywa aktywny katalog ComfyUI z PID/WorkingDirectory,
5. sprawdza miejsce na dysku,
6. tworzy backup instalowanych wrapperów i skillu,
7. pobiera brakujące wagi do obecnych katalogów modeli ComfyUI,
8. instaluje lokalne wrappery,
9. instaluje skill `/wideo`,
10. wykonuje preflight bez renderowania,
11. restartuje tylko Hermes gateway.

## Pierwszy test sprzętowy

Najpierw minimalny smoke test:

```bash
/usr/local/bin/generate-video \
  --preset smoke \
  --prompt "A small red robot waves at the camera in an electronics workshop, gentle camera push-in, realistic light"
```

Sukces:

- kod wyjścia `0`,
- zwrócona absolutna ścieżka,
- istniejący niepusty plik MP4 pod `/srv/ai-data/hermes-media/video/`,
- ComfyUI pozostaje aktywne.

Następnie test Telegram:

```text
/wideo Mały czerwony robot stoi na stole elektronika i macha do kamery. Kamera powoli się zbliża, realistyczne światło warsztatu.
```

Po tym mierzymy czas i pamięć dla `fast`, a dopiero potem `balanced`.

## Image-to-video

CLI:

```bash
/usr/local/bin/generate-video \
  --preset fast \
  --image /absolute/path/input.png \
  --prompt "The camera slowly circles the object while workshop lights reflect on the metal surface"
```

Skill `/wideo` ma używać lokalnej ścieżki załączonego obrazu, jeżeli Hermes udostępni ją w kontekście wiadomości.

## Rollback

```bash
cd ../AI-server-local-video-stage23
bash tools/rollback_hermes_local_video_stage23.sh
```

Rollback przywraca stan sprzed Stage 23 dla:

- `/usr/local/libexec/ai-server/generate_video.py`,
- `/usr/local/bin/generate-video`,
- `/usr/local/bin/generate-video-telegram`,
- `${HERMES_HOME}/skills/wideo`.

Pobrane wagi Wan2.2 są zachowywane, bo nie wpływają na działanie ComfyUI i ich ponowne pobieranie byłoby niepotrzebne.

## Następny etap po benchmarku

Jeżeli Wan2.2 5B okaże się akceptowalny czasowo:

1. utrwalamy preset produkcyjny pod realny czas 890M,
2. dodajemy telemetrykę renderu: czas, rozdzielczość, liczba klatek, peak pamięci,
3. testujemy image-to-video z obrazem wygenerowanym przez lokalny FLUX.2 Klein,
4. dopiero potem rozważamy LTX-2.3 jako opcjonalny backend jakości/audio.
