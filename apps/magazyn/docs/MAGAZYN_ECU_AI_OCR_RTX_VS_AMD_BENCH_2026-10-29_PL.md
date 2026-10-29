# Magazyn V1 — Qwen3-VL 8B Instruct: Radeon 890M vs RTX 5060 Ti

Data: 2026-10-29. **Rzeczywisty benchmark na harrypotter-AI-Series, bez przełączenia produkcyjnej aplikacji Magazyn.**

## Warunki pomiaru
- Wariant modelu: `qwen3-vl:8b-instruct`, identyczny digest `70e58e37beb1...` na obu instancjach Ollama 0.40.7.
- AMD Radeon 890M: backend Vulkan, wbudowany AI Gateway `127.0.0.1:11435/api/chat` z RM.
- NVIDIA RTX 5060 Ti 16 GB: CUDA0, istniejąca osobna instancja `ollama-rtx-small.service` na `127.0.0.1:11436`; **tylko podczas testu**, po przyznaniu i utrzymaniu zewnętrznej rezerwacji RM `workload=llm`. Nie modyfikowano serwisów ani schedulerów. Po teście rezerwację zwolniono.
- `stream=false`, `think=false`, `temperature=0`, `num_ctx=4096`, `num_predict=300`. Prompt: `Read all visible text from the ECU label exactly, preserving digits and line breaks. No guesses.`
- Te same pliki JPEG 1400x700 z syntetyczną naklejką Bosch; 36 tokenów wyjściowych, 1088 wejściowych; wszystkie odczyty były poprawne.
- Pomiar end-to-end HTTP z localhost (bez narzutu Androida, Tailscale i autentycznej fotografii).

## Wyniki

| Warunek | RTX 5060 Ti CUDA | Radeon 890M Vulkan | Przyspieszenie RTX |
|---|---:|---:|---:|
| Pierwszy start (zimny, nie wszystkie cache rozgrzane) | 22,570 s | 11,351 s | nie dotyczy |
| Nowy obraz A, model w pamięci | **1,532 s** | 7,335 s | **4,79×** |
| Nowy obraz B, model w pamięci | **1,505 s** | 7,255 s | **4,82×** |
| Średnia dwóch nowych obrazów, model w pamięci | **1,519 s** | **7,295 s** | **4,80×** |
| Powtórzenie identycznego zdjęcia (cache promptu) | 0,501 s | — | pomiar nieporównywalny |

Dodatkowy warmup potwierdził 5,934 s RTX (z tego 4,389 s ładowanie modelu) vs 8,802 s AMD (z tego 1,367 s ładowanie). **Nie używać wyniku 0,501 s do prognozy czasu nowych zdjęć**.

RTX: szczytowo ok. 7046 MiB VRAM, około 141 W podczas nowych obrazów (próbkowanie nvidia-smi co 0,5 s).

## Interpretacja
- Dla kolejnych nowych zdjęć z modelem trzymanym w pamięci RTX jest średnio **około 4,8× szybszy** w tej krótkiej próbie.
- Czas startu modelu na RTX może być dłuższy od czasu pojedynczej analizy na AMD. Aby użytkownik uzyskał krótkie opóźnienie w praktyce, potrzeba kontrolowanego `keep_alive` i zarządzania rezydencją w RM.
- Produkcyjny Magazyn **nadal używa AMD przez Gateway**, nie przestawiono go na RTX; produkcyjna funkcja OCR ma aktualnie `keep_alive=0`.
- Obecny RM nie ma gotowego route'u modelu OCR na odrębną instancję RTX. Stałe przełączenie wymaga zaprojektowania dopuszczonej przez RM ścieżki; nie łączyć produkcyjnego Magazynu bezpośrednio z portem 11436.
- Wyniki dotyczą czystych obrazów syntetycznych, nie dowodzą skuteczności i latencji na faktycznych uszkodzonych etykietach ECU.

## Kontrole po teście
- `ollama.service`, `ollama-rtx-small.service`, `ai-gateway.service`: active.
- RTX: 2 MiB zajętej VRAM, brak rezydentnego Qwen3-VL po `keep_alive=0`.
- RM: `active_count=0`, `queued_count=0`, `admission_blocked=false`, `gpu_residency=llm`, brak wymaganego recovery.
- Magazyn /healthz: `status=ok`, `environment=production`.
- Dane testowe / log wyników: `/srv/ai-data/staging/magazyn-ecu-ai-rtx-benchmark-20261029/results.json` i `fresh-results.json` (bez zdjęć klientów).

## Rekomendacja
Utrzymać obecny serwis produkcyjny bez zmian. Przygotować w DEV obsługę Qwen3-VL na RTX z właściwą kontrolą RM oraz sterowaniem czasem utrzymania modelu w VRAM, po czym zweryfikować na rzeczywistych zdjęciach z Androida.
