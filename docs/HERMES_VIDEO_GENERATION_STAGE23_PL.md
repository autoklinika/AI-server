# Hermes — generowanie wideo, Stage 23

Data przygotowania: 2026-09-05

## Cel

Dodać do produkcyjnego Hermesa działającego na Serwerze AI natywne narzędzie `video_generate`, dostępne również z Telegrama, bez ingerencji w AI Gateway, Ollamę, analizę wentylacji ani ustawienie `agent.reasoning_effort: 'none'`.

## Dlaczego korzystamy z natywnego `video_gen`

Zainstalowany Hermes 0.21.0 (commit `254158f4530cada634c4ef8f4cff93257c5b4f77`) zawiera już toolset `video_gen` oraz wbudowane backendy:

- `fal` — FAL.ai,
- `xai` — xAI Grok Imagine,
- `deepinfra` — DeepInfra.

Nie dokładamy własnego wrappera na poziomie AI Gateway. AI Gateway nadal zarządza wyłącznie ruchem do Ollamy. Generowanie wideo jest osobnym zewnętrznym zadaniem Hermesa.

## Zakres Stage 23

Po wdrożeniu profil Telegrama zmienia się z:

```yaml
platform_toolsets:
  telegram: [terminal, file, web]
```

na:

```yaml
platform_toolsets:
  telegram: [terminal, file, web, video_gen]
```

oraz w `config.yaml` ustawiany jest wybrany backend:

```yaml
video_gen:
  provider: fal
```

`fal` jest domyślnym providerem skryptu wdrożeniowego, ale można użyć również `xai` albo `deepinfra`.

## Sekrety

Klucz API nie jest zapisywany w repozytorium ani w `config.yaml`.

Stage 23 tworzy:

- `/srv/ai-data/hermes/video-gen.env` — mode `0600`,
- `~/.config/systemd/user/hermes-gateway.service.d/30-video-gen.conf` — user-systemd drop-in z `EnvironmentFile=`.

Mapowanie providerów:

| Provider | Zmienna środowiskowa |
| --- | --- |
| `fal` | `FAL_KEY` |
| `xai` | `XAI_API_KEY` |
| `deepinfra` | `DEEPINFRA_API_KEY` |

Skrypt nigdy nie wypisuje wartości klucza.

## Wdrożenie

Domyślnie FAL:

```bash
cd ~/AI-server
bash tools/cutover_hermes_video_generation_stage23.sh fal
```

Alternatywnie:

```bash
bash tools/cutover_hermes_video_generation_stage23.sh xai
bash tools/cutover_hermes_video_generation_stage23.sh deepinfra
```

Jeżeli odpowiednia zmienna środowiskowa nie jest już ustawiona, skrypt uruchomiony interaktywnie poprosi o klucz bez jego wyświetlania.

## Co waliduje cutover

Skrypt sprawdza przed zmianą:

- obecność produkcyjnego Hermesa,
- działający AI Gateway i Ollamę,
- literalne `agent.reasoning_effort: 'none'`,
- aktualny produkcyjny profil Telegrama,
- obecność `video_gen` w zainstalowanym Hermesie,
- obecność wybranego bundled providera.

Po zmianie sprawdza:

- `platform_toolsets.telegram == [terminal, file, web, video_gen]`,
- poprawny `video_gen.provider`,
- zachowanie dotychczasowych narzędzi Telegrama,
- obecność model-facing `video_generate`,
- brak przypadkowego wystawienia `kanban_*`,
- restart `hermes-gateway.service`,
- ponowne połączenie Telegram + API,
- health AI Gatewaya.

Skrypt celowo nie wykonuje automatycznie płatnego requestu generowania wideo.

## Pierwszy test realny

Po udanym wdrożeniu na Telegramie:

> Wygeneruj 5-sekundowe wideo 16:9: nocny warsztat elektroniczny, kamera powoli przesuwa się nad stołem z ECU i oscyloskopem, realistyczne oświetlenie.

Oczekiwane zachowanie: Hermes powinien wywołać `video_generate`, zaczekać na zakończenie joba providera i dostarczyć wynik jako plik lub URL obsługiwany przez gateway Hermesa.

## Rollback

```bash
cd ~/AI-server
bash tools/rollback_hermes_video_generation_stage23.sh
```

Rollback przywraca dokładny backup `config.yaml`, a także stan pliku środowiskowego i systemd drop-in sprzed Stage 23.

## Ważne ograniczenia

1. Backend chmurowy oznacza, że prompt i ewentualny obraz wejściowy opuszczają lokalną infrastrukturę i są wysyłane do wybranego providera.
2. Generowanie może być płatne. Stage 23 nie uruchamia żadnego płatnego joba automatycznie.
3. `video_gen` nie korzysta z kolejki AI Gatewaya, ponieważ nie jest inferencją Qwen/Ollama.
4. Przy równoległym lokalnym generatorze GPU w przyszłości potrzebny będzie osobny Resource Manager, aby nie dopuścić do konfliktu z Ollamą.

## Etap następny — lokalny generator

Docelowo możemy dodać własny backend `video_gen` do Hermesa i skierować go do lokalnego ComfyUI. Dla Serwera AI z Radeon 890M (`gfx1150`) aktualny ROCm wspiera tę architekturę, a Wan2.2 TI2V 5B ma oficjalny workflow ComfyUI z offloadingiem. Ten etap wymaga jednak osobnego benchmarku GPU/RAM i polityki współdzielenia zasobów z Ollamą, dlatego nie jest częścią Stage 23.
