---
name: foto
description: Generuje jeden obraz z opisu przekazanego po komendzie /foto w komunikatorze.
platforms: [linux]
metadata:
  hermes:
    tags: [image, photo, flux, telegram]
    requires_toolsets: [image_gen]
---

# Foto

Ta umiejętność obsługuje jawne żądanie generowania obrazu przez komendę `/foto`.

## Zasady wykonania

1. Tekst przekazany przez użytkownika po `/foto` traktuj jako prompt obrazu.
2. Jeśli prompt jest pusty, odpowiedz krótko: `Użycie: /foto <opis obrazu>` i nie wywołuj żadnego narzędzia.
3. Jeśli prompt jest podany, **musisz** użyć narzędzia `image_generate` dokładnie jeden raz, chyba że samo narzędzie zwróci błąd wymagający zakończenia zadania.
4. Domyślnie generuj dokładnie jeden obraz.
5. Używaj aktualnie skonfigurowanego providera, modelu i parametrów domyślnych `image_generate`, chyba że użytkownik jawnie poda inne wymagania obsługiwane przez narzędzie.
6. Dla zwykłego `/foto` nie używaj `terminal`, `process_manage`, `web_search`, `web_extract`, `read_file`, `write_file`, `patch` ani `search_files`.
7. Nie opisuj obrazu zamiast jego wygenerowania i nie udawaj wywołania narzędzia.
8. Po sukcesie zwróć wynik wygenerowany przez `image_generate` w sposób pozwalający gatewayowi komunikatora wysłać obraz jako media. Ogranicz dodatkowy tekst do minimum.
9. Jeśli `image_generate` jest niedostępne albo zwróci błąd, poinformuj krótko, że generowanie obrazu nie powiodło się, i podaj istotny komunikat błędu bez wymyślania wyniku.
