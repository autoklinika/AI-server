# Hermes + LTX-2.3 — Stage 27: lokalny Qwen prompt-compiler

Stage 27 zachowuje deterministyczny transport Stage 26 i dodaje wyłącznie warstwę przygotowania promptu przed LTX-2.3.

## Przepływ

`Telegram /wideo -> Hermes quick command -> worker -> Qwen3.6 przez lokalny AI Gateway -> LTX-2.3 -> MP4 -> ten sam czat Telegram`

Dla `/wideo hq` pozostaje ten sam dwustopniowy pipeline LTX z x2 upscale.

## Zasada fallbacku

Qwen nie jest elementem krytycznym wykonania. Jeśli prompt-compiler zwróci błąd, timeout albo pustą odpowiedź, worker użyje oryginalnego opisu użytkownika, ale fallback nigdy nie może być cichy.

Przed startem LTX worker musi wysłać do tego samego czatu komunikat:

`⚠️ Qwen został pominięty — używam oryginalnego opisu do LTX.`

Jeśli tego ostrzeżenia nie da się dostarczyć, render LTX nie startuje.

## Telemetria joba

`worker.log` i `result.json` zapisują:

- `qwen_used`
- `original_prompt`
- `effective_prompt`
- `qwen_failure_reason`
- `qwen_elapsed_seconds`

## Prywatność i lokalność

Prompt-compiler akceptuje wyłącznie adres AI Gateway na loopback (`127.0.0.1`, `localhost`, `::1`). Zdalny endpoint jest odrzucany i uruchamia jawny fallback.

Domyślny endpoint: `http://127.0.0.1:11435/clients/hermes/v1/chat/completions`.

Domyślny model: `qwen3.6:35b-hermes64k`.

## Wdrożenie

`tools/cutover_hermes_ltx23_prompt_stage27.sh`

Rollback:

`tools/rollback_hermes_ltx23_prompt_stage27.sh`

Stage 27 nie zmienia `main`, modeli ComfyUI, konfiguracji Ollama, konfiguracji wentylacji ani routingu Stage 26.
