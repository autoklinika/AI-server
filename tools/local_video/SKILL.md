---
name: wideo
description: Tworzy lokalne wideo przez ComfyUI i Wan2.2 bez chmury
version: 1.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [video, comfyui, wan, local]
    category: media
    requires_toolsets: [terminal]
---

# Lokalne generowanie wideo

## When to Use

Używaj tego skillu, gdy użytkownik prosi o wygenerowanie filmu lub animacji. Ten skill jest przeznaczony wyłącznie dla lokalnego generatora na Serwerze AI.

## Hard Rules

- Nigdy nie używaj FAL, xAI, DeepInfra ani innego płatnego/chmurowego generatora wideo.
- Nie wysyłaj promptu, obrazu wejściowego ani wygenerowanego filmu poza lokalny Serwer AI.
- Do generowania używaj wyłącznie `/usr/local/bin/generate-video-telegram`.
- Nie zmieniaj konfiguracji Ollamy, AI Gatewaya ani wentylacji.
- Domyślnie używaj presetu `fast`. Presetu `quality` używaj tylko wtedy, gdy użytkownik wyraźnie prosi o wysoką jakość/720p lub zaakceptuje dłuższe generowanie.

## Procedure

1. Zbuduj z prośby użytkownika jeden konkretny prompt opisujący scenę, ruch obiektów, ruch kamery, oświetlenie i styl.
2. Jeśli użytkownik załączył obraz i jego lokalna absolutna ścieżka jest dostępna w kontekście wiadomości, użyj trybu image-to-video:

```bash
/usr/local/bin/generate-video-telegram --preset fast --image "/ABSOLUTE/PATH/IMAGE" -- "PROMPT"
```

3. Bez obrazu użyj text-to-video:

```bash
/usr/local/bin/generate-video-telegram --preset fast -- "PROMPT"
```

4. Dla prośby o lepszą jakość użyj `--preset balanced`. `--preset quality` jest opcją ciężką i nie jest domyślna.
5. Polecenie zwraca absolutną ścieżkę do gotowego pliku MP4. Umieść tę ścieżkę jako osobną, niezmienioną linię w odpowiedzi. Gateway Hermesa wykryje plik i wyśle go natywnie do Telegrama.

## Presets

- `smoke`: bardzo krótki test instalacji.
- `fast`: domyślny, 640×352, około 2 s materiału, 10 kroków.
- `balanced`: 832×480, około 3.4 s materiału, 20 kroków.
- `quality`: 1280×704, około 5 s materiału, 20 kroków; używaj tylko na wyraźne życzenie.

## Pitfalls

- Generowanie wideo jest znacznie cięższe niż FLUX.2 Klein do obrazów. Nie obiecuj czasu wykonania przed realnym benchmarkiem na tym serwerze.
- Jeżeli ComfyUI zgłosi brak modelu lub node'a, nie próbuj zastępować generatora usługą chmurową.
- Jeżeli generator zwróci błąd, pokaż krótki błąd diagnostyczny i nie twórz fikcyjnej ścieżki do pliku.

## Verification

Sukces oznacza, że `/usr/local/bin/generate-video-telegram` kończy się kodem 0, zwraca istniejącą absolutną ścieżkę do niepustego pliku `.mp4`, a Telegram dostarcza ten plik jako media/załącznik.
