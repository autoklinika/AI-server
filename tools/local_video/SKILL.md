---
name: wideo
description: Tworzy w pełni lokalne wideo z dźwiękiem przez ComfyUI i LTX-2.3 22B; obsługuje tryb standard oraz HQ 2x
version: 2.0.0
platforms: [linux]
metadata:
  hermes:
    tags: [video, audio, comfyui, ltx, local]
    category: media
    requires_toolsets: [terminal]
---

# Lokalne generowanie wideo LTX-2.3

## When to Use

Używaj tego skillu, gdy użytkownik wywołuje `/wideo` i prosi o wygenerowanie filmu lub animacji. Cała generacja odbywa się lokalnie na Serwerze AI.

## User modes

- `/wideo OPIS` -> tryb standardowy LTX-2.3, 640x384, 49 klatek, 24 fps, video + audio.
- `/wideo hq OPIS` -> tryb HQ LTX-2.3 z generatywnym spatial upscale 2x i drugim etapem refinementu; wynik 1280x768, 49 klatek, 24 fps, video + audio.

Token `hq` bezpośrednio po `/wideo` jest przełącznikiem trybu i nie może pozostać w promptcie sceny.

## Hard Rules

- Nigdy nie używaj FAL, xAI, DeepInfra ani żadnego innego chmurowego generatora wideo.
- Nie wysyłaj promptu ani wygenerowanego filmu poza lokalny Serwer AI.
- Do generowania używaj wyłącznie `/usr/local/bin/generate-video-telegram`.
- Nie zmieniaj konfiguracji Ollamy, AI Gatewaya, ComfyUI ani wentylacji podczas pojedynczego żądania generowania.
- Nie przełączaj na Wan jako fallback po błędzie LTX. Zwróć krótki błąd diagnostyczny.
- Sukces MUSI zakończyć się zwróceniem gotowego MP4 do tego samego czatu Telegram.

## Procedure

1. Odczytaj opis użytkownika po `/wideo`.
2. Jeśli pierwszy token opisu to dokładnie `hq` (bez uwzględniania wielkości liter), usuń go z opisu i wybierz tryb HQ.
3. Przepisz opis na jeden konkretny angielski prompt dla LTX-2.3. Zachowaj intencję użytkownika i opisz: główny obiekt/scenę, wyraźny ruch, zachowanie kamery, oświetlenie, styl oraz stabilność obiektów. Jeżeli dźwięk ma sens, dodaj sekcję `[SOUNDS]: ...`.
4. Dla trybu standard uruchom:

```bash
/usr/local/bin/generate-video-telegram -- "PROMPT"
```

5. Dla trybu HQ uruchom:

```bash
/usr/local/bin/generate-video-telegram --hq -- "PROMPT"
```

6. Polecenie przy sukcesie zwraca absolutną ścieżkę do istniejącego MP4 w `/srv/ai-data/hermes-media/video/`.
7. W finalnej odpowiedzi umieść tę absolutną ścieżkę jako osobną, niezmienioną linię. Nie otaczaj jej backtickami, nie dodawaj prefiksu `file://`, nie zamieniaj jej na Markdown i nie dodawaj tekstu w tej samej linii. Hermes Gateway wykrywa lokalną ścieżkę i wysyła plik natywnie do tego samego czatu Telegram.

## Expected timings from real server benchmark

- standard: zwykle około 4 min 30 s dla 640x384 / 49 klatek.
- HQ: około 8 min 43 s dla 1280x768 / 49 klatek po generatywnym upscale 2x.

Traktuj te wartości jako benchmark, nie gwarancję czasu wykonania.

## Return-to-chat contract

Generator nie kończy zadania na samym zapisaniu pliku. Gotowe wideo musi zostać zwrócone użytkownikowi w tym samym czacie.

Prawidłowy finalny wynik po sukcesie zawiera lokalną ścieżkę, np.:

```text
/srv/ai-data/hermes-media/video/ltx23-20260905-104700-febc07c8.mp4
```

albo dla HQ:

```text
/srv/ai-data/hermes-media/video/ltx23-2x-20260905-125338-821a062d.mp4
```

Nie odpowiadaj wyłącznie komunikatem typu „gotowe” lub „film został zapisany”. Ścieżka MP4 jest obowiązkowa, ponieważ uruchamia natywne dostarczenie media do Telegrama.

## Pitfalls

- Nie interpretuj słowa `hq` pojawiającego się później we właściwym opisie sceny jako przełącznika; przełącznikiem jest tylko pierwszy token po `/wideo`.
- LTX-2.3 generuje zsynchronizowany strumień audio; nie usuwaj audio z workflow.
- Nie próbuj tworzyć fikcyjnej ścieżki do pliku przy błędzie generatora.
- Obecny Stage 25 jest text-to-video. Nie udawaj obsługi image-to-video przez LTX, jeśli nie została osobno wdrożona i zweryfikowana.

## Verification

Sukces oznacza jednocześnie:

1. `/usr/local/bin/generate-video-telegram` kończy się kodem 0.
2. stdout zawiera absolutną ścieżkę do istniejącego, niepustego `.mp4`.
3. `/wideo` uruchamia LTX standard bez `--upscale-2x`.
4. `/wideo hq` uruchamia LTX z `--upscale-2x`.
5. Finalna odpowiedź Hermesa zawiera tę samą lokalną ścieżkę jako osobną linię.
6. Telegram dostarcza MP4 jako media/załącznik w tym samym czacie.
