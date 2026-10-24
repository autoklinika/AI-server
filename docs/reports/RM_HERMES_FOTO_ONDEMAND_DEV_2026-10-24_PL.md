# AI Platform / Hermes — izolowana integracja /foto → istniejący RM → ComfyUI (DEV)

Data: 24.10.2026. Host: harrypotter-AI-Series.

**Wynik: HERMES_FOTO_WORKER_TO_ISOLATED_RM_HTTP_DEV_PASS.**
**Zakres: prawdziwy kod Hermesa i istniejącego Resource Managera, ale
bez wykonania nowego modelu Qwen, bez aktualnego uruchomienia FLUX/ROCm,
bez Telegrama i bez przełączenia produkcji.**

## Architektura poddana rzeczywistym testom

Test importuje oryginalny kod działającego Hermesa:
- tools/local_image/hermes_foto_dispatch_global.py;
- tools/local_image/hermes_foto_dispatch.py;
- tools/hermes_resource_queue.py;
- tools/local_image/hermes_foto_prompt_compiler.py;
- src/ai_bridge/providers/media_admission.py.

SHA256 czterech odpowiedników wdrożonych w produkcji (entry
/foto, Resource Manager helper, prompt compiler i media gate)
był **bajtowo identyczny** z repozytorium DEV na rzeczywistym hoście.

Wywołana została faktyczna funkcja worker Hermesa, która wprowadza
original prompt, pozyskuje lease przez Resource Manager, wywołuje
media_admission oraz sprawdza i zwalnia rezerwację. Komunikacja
worker → DEV Gateway używa **prawdziwych żądań HTTP na 127.0.0.1:11656**.
Testowe źródło w izolowanym procesie przekierowuje wyłącznie
zakodowany w produkcyjnym kliencie port 11435 na ten port DEV.
Nie zmieniono żadnego działającego procesu, portu ani pliku Hermesa.

Gateway to prawdziwa aplikacja FastAPI uruchomiona przez Uvicorn
na 127.0.0.1:11656, z jednym istniejącym PriorityScheduler i
opcjonalnym cyklem ComfyUI on-demand w DEV. Kontroler procesu i
wywołania API ComfyUI są symulowane w httpx.MockTransport: **nie
otwierają fizycznego GPU** i nie podłączają się do produkcyjnego
ComfyUI na 8188.

Kompilator promptu Qwen ma deterministyczną odpowiedź testową.
Nie wykonano prawdziwego zadania inferencji Qwen ani oceny jakości
prompts. Generator obrazu to stub, który zwraca istniejący,
już wcześniej wygenerowany na prawdziwym Radeonie plik VAE 64x64
z staging; test nie tworzy nowego obrazu na GPU.
Wywołania dostarczenia do Telegrama zostały przechwycone w pamięci,
z adresem DEV_UNROUTABLE_NO_SEND. Nie wysłano wiadomości do odbiorcy.

## 11 rzeczywistych przypadków DEV

1. Worker /foto → rzeczywisty HTTP do RM → media lease →
   generator stub → /free → stop kontrolera → lease release: PASS.
2. Drugie zadanie oczekuje w **tej samej kolejce** RM, nie wyprzedza
   aktualnego użycia ComfyUI i uruchamia się po zwolnieniu: PASS.
3. Kontrolowana kolejka informuje o queued i active w przechwyconych
   notyfikacjach; nic nie trafia do Telegrama: PASS.
4. Brak poprawnej odpowiedzi Qwen odmawia uruchomienia ComfyUI: PASS.
5. Instrukcja edycji obrazu bez źródłowego zdjęcia nie uruchamia GPU: PASS.
6. Symulowany błąd generatora po wydaniu lease prowadzi do /free,
   zatrzymania silnika i zwolnienia miejsca RM: PASS.
7. Błąd /free zachowuje stan admission_blocked, rezydencję i marker,
   mimo że Hermes zakończył worker i wysłał komunikat błędu: PASS.
8. Brak możliwości startu ComfyUI blokuje RM i nie wpuszcza
   generatora: PASS.
9. Rzeczywista ścieżka image-edit korzysta z capability image-edit
   w tym samym providerze ComfyUI i tym samym RM: PASS.
10. Realny guard generatora require_external_media_use:
    prawidłowy identyfikator lease/use upoważnia; brak use_id
    i niewłaściwa capability są odrzucane: PASS. Niezgodny port
    produkcyjnego guard został podmieniony wyłącznie w kontekście DEV.
11. Hash aktualnie wdrożonych źródeł Hermesa i zabezpieczeń
    odpowiada DEV, a izolowane testy nie mają działających
    adresów dostarczania wiadomości: PASS.

Wynik tego pliku testowego:
tests/test_hermes_foto_rm_ondemand_e2e_dev.py — **11/11 PASS**.
Pełna regresja wcześniej istniejących i nowych testów Hermesa,
gateway admission, priorytetów, rezydencji i ComfyUI — **535/535 PASS**
(następująca po poprawieniu historycznej asercji o markerze
recovery). Oryginalny marker został prawidłowo **zarchiwizowany**
przez operatora; nie należy oczekiwać jego dalszej obecności w
aktywnym staging po zaakceptowanym archiwum.

## Gwarancje izolacji w tym konkretnym teście

- Produkcyjny Gateway 11435 nie jest używany przez klienta Hermesa
  podczas testu; helper został sklonowany w pamięci jednego procesu.
- Produkcyjny ComfyUI 8188 jest nietknięty; symulowane ComfyUI
  używa MockTransport i kontrolera procesów bez GPU.
- Produkcyjny Hermes/Telegram nie otrzymuje żądania ani wiadomości.
- Produkcyjny Ollama/Qwen nie jest wywoływany. Nie ładowano modeli.
- Testowy port 11656 jest zamykany po każdym scenariuszu.
- Nie zmieniano unitów systemd, firmware, GRUB, sterownika, PCIe,
  power limit, autostartu ComfyUI ani praw urządzeń.
- Oryginalna produkcyjna kolejka priorytetowa Radeona pozostaje
  jedną instancją RM, bez nowego koordynatora.

## Co pozostaje NIEZALICZONE

To test **integracji logicznej** oryginalnego Hermesa z nową ścieżką
on-demand DEV, a nie full-chain live generation. Osobno wcześniej
udowodniono jeden rzeczywisty cykl ComfyUI/VAE na AMD 890M i
kontrolowaną awarię finalizacji, ale te dwie ścieżki nie były
jeszcze fizycznie połączone w jednym uruchomieniu.

Kolejny etap przed produkcją:
1. Operator-only okno serwisowe: prawdziwy Hermes /foto (bez wysyłki
   wiadomości) z rzeczywistym, zarządzanym procesem ComfyUI na GPU,
   rzeczywistym prompt compilerem Qwen i docelowym generatorem.
2. Utrzymanie jednego RM i sprawdzenie wspólnej kolejki dla WVC,
   obrazów, Hermes oraz Vision; brak równoległej rezydencji GPU.
3. Audyt uprawnień systemowych i portów bezpośrednich Ollama/ComfyUI,
   odpowiedzialności za proces ComfyUI, stanów stop/cgroup oraz
   driver safe reuse.
4. Testy hard-fault podczas obliczeń ROCm pod ścisłą kontrolą
   rollbacku, następnie akceptacja produkcyjnego cutoveru po
   osobnej zgodzie.

**Stan końcowy: HERMES /foto ↔ RM DEV HTTP PASS. Produkcja bez zmian.
GPU_REUSE_SAFE / E_safe NOT_VERIFIED. N1/SHARED NOT_ADMITTED.
PRODUCTION_CUTOVER NOT_DEPLOYED. PR #178 nadal Draft.**
