---
name: foto
description: Generuje jeden lokalny obraz FLUX z opisu przekazanego po komendzie /foto w komunikatorze.
platforms: [linux]
metadata:
  hermes:
    tags: [image, photo, flux, telegram, local]
    requires_toolsets: [terminal]
---

# Foto

Ta umiejętność obsługuje jawne żądanie lokalnej generacji obrazu przez komendę `/foto`.

## Zasady wykonania

1. Tekst przekazany przez użytkownika po `/foto` traktuj jako prompt obrazu.
2. Jeśli prompt jest pusty, odpowiedz krótko: `Użycie: /foto <opis obrazu>` i nie wywołuj żadnego narzędzia.
3. Jeśli prompt jest podany, użyj narzędzia `terminal` dokładnie jeden raz do uruchomienia istniejącego lokalnego wrappera `/usr/local/bin/generate-image-telegram`.
4. Przekaż cały prompt użytkownika jako **jeden poprawnie zacytowany argument powłoki** do `/usr/local/bin/generate-image-telegram`. Nie interpretuj fragmentów promptu jako osobnych poleceń powłoki.
5. Nie używaj `image_generate`, FAL.ai ani żadnego zewnętrznego generatora obrazów. Produkcyjnym backendem jest lokalny ComfyUI + FLUX.2 Klein 4B obsługiwany przez `generate-image-telegram`.
6. Nie używaj `web_search`, `web_extract`, `read_file`, `write_file`, `patch`, `search_files` ani `process_manage` do zwykłego `/foto`.
7. Nie opisuj obrazu zamiast jego wygenerowania i nie udawaj wykonania polecenia.
8. Wrapper sam wysyła wygenerowany PNG do Telegrama. Po sukcesie odpowiedz tylko krótko, np. `Gotowe.`; nie wysyłaj drugi raz tego samego pliku.
9. Jeśli wrapper zwróci błąd, odpowiedz krótko, że generowanie nie powiodło się, i podaj istotny komunikat błędu.
