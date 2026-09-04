---
name: foto
description: Generuje lub przerabia lokalny obraz FLUX przez komendę /foto w komunikatorze.
platforms: [linux]
metadata:
  hermes:
    tags: [image, photo, edit, flux, telegram, local]
    requires_toolsets: [terminal]
---

# Foto

Ta umiejętność obsługuje jawne żądanie lokalnej generacji albo edycji obrazu przez komendę `/foto`.

## Rozpoznanie trybu

Hermes może dołączyć do instrukcji techniczny blok bieżącej wiadomości:

```text
[HERMES_FOTO_INPUT_IMAGE]
path=/absolutna/sciezka/do/obrazu
[/HERMES_FOTO_INPUT_IMAGE]
```

Ten blok NIE jest częścią promptu użytkownika. `path=` jest zaufaną ścieżką zdjęcia pobranego z tej samej bieżącej wiadomości Telegram.

- Jeśli blok `HERMES_FOTO_INPUT_IMAGE` nie występuje, wykonaj zwykłe text-to-image.
- Jeśli blok występuje, wykonaj image-edit na wskazanym pliku.
- Nie szukaj „najnowszego” zdjęcia w cache i nie zgaduj ścieżki.
- Obecnie edycja dotyczy zdjęcia załączonego bezpośrednio do tej samej wiadomości `/foto`; nie zakładaj obsługi zdjęcia tylko z historii/reply, jeśli bieżący blok ścieżki nie został dostarczony.

## Zasady wspólne

1. Rzeczywistym promptem jest wyłącznie tekst użytkownika po `/foto`, z pominięciem technicznego bloku `HERMES_FOTO_INPUT_IMAGE`.
2. Jeśli rzeczywisty prompt jest pusty, odpowiedz krótko: `Użycie: /foto <opis obrazu lub instrukcja edycji>` i nie wywołuj żadnego narzędzia.
3. Użyj narzędzia `terminal` dokładnie jeden raz.
4. Nie używaj `tool_call`, `tool_search`, `tool_describe`, `image_generate`, FAL.ai ani żadnego zewnętrznego generatora obrazów.
5. Nie używaj `web_search`, `web_extract`, `read_file`, `write_file`, `patch`, `search_files` ani `process_manage` do `/foto`.
6. Nie opisuj obrazu zamiast wykonania zadania i nie udawaj wykonania polecenia.
7. Wszystkie wartości przekazywane do powłoki zacytuj bezpiecznie jako pojedyncze argumenty. Nie interpretuj fragmentów promptu ani ścieżki jako osobnych poleceń powłoki.

## Tryb 1 — tworzenie nowego obrazu

Jeśli nie ma bloku `HERMES_FOTO_INPUT_IMAGE`, uruchom bezpośrednio przez `terminal`:

`/usr/local/bin/generate-image-telegram "<PROMPT>"`

`<PROMPT>` to cały rzeczywisty prompt użytkownika jako jeden poprawnie zacytowany argument powłoki.

## Tryb 2 — edycja załączonego zdjęcia

Jeśli blok `HERMES_FOTO_INPUT_IMAGE` występuje, odczytaj dokładną wartość `path=` i uruchom bezpośrednio przez `terminal`:

`/usr/local/bin/generate-image-edit-telegram --input "<PATH>" --prompt "<PROMPT>"`

- `<PATH>` musi być dokładną wartością z technicznego bloku bieżącej wiadomości.
- `<PROMPT>` musi być wyłącznie rzeczywistą instrukcją użytkownika, bez technicznego bloku.
- Nie zmieniaj ścieżki i nie wybieraj innego pliku.

## Backend i odpowiedź

Produkcyjnym backendem obu trybów jest lokalny ComfyUI + FLUX.2 Klein 4B.
Wrapper sam wysyła wynikowy PNG do Telegrama. Po sukcesie odpowiedz tylko krótko, np. `Gotowe.`; nie wysyłaj drugi raz tego samego pliku.
Jeśli wrapper zwróci błąd, odpowiedz krótko, że generowanie/edycja nie powiodła się, i podaj istotny komunikat błędu.
