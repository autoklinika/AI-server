# AI Platform — Cooperative GPU Handoff V1: zasada minimalizmu
Data: 2026-10-20. Zakres: jeden zaufany host, AMD Radeon 890M.

## Decyzja
**Nie restartujemy Ollamy ani ComfyUI po każdym zadaniu.**
Używamy istniejących `PriorityScheduler`, `ResourceLeaseRegistry`
i `GPUResidency` w jednym produkcyjnym Gateway. Brak drugiego
koordynatora, brak modyfikacji grup render/video, brak nowego root daemona.

Stan `LLM` / `MEDIA` oznacza **prawo RM do rozpoczęcia następnego
obciążenia**, nie absolutną sprzętową wyłączność wszystkich kontekstów.
Stan `BLOCKED` przy każdej niezweryfikowanej zmianie/timeoutcie.

## Fakty z rzeczywistego hosta
- Ollama, Gateway, Bridge i ComfyUI są aktywne; Gateway: status ok,
  max_concurrency 1, active_count 0, lease_count 0.
- Ollama: brak modeli w /api/ps.
- ComfyUI: queue_running=0, queue_pending=0, loaded_models=0,
  cleanup_pending=false, lecz PID 267058 posiada aktywny kontekst
  KFD i uchwyt DRM. To samo w sobie nie oznacza, że proces
  wykonuje obciążenie ani że GPU jest zwolniony w sensie sterownika.
- Gateway ma `Requires=ollama.service`. Automatyczne zatrzymanie
  Ollamy może zatrzymać Gateway; dlatego to NIE jest ścieżka
  rutynowego przekazania GPU.
- Produkcyjny GPUResidency implementuje już wyładowanie modeli
  Ollamy i czyszczenie ComfyUI przez /free oraz
  /ai-platform/residency. Nie tworzymy zamiennika.

## Minimalna sekwencja
1. Rezerwacja w JEDYNEJ kolejce RM z max_concurrency=1;
   podmiot trzyma tę samą rezerwację aż do zakończenia zadania.
2. Wejście do MEDIA: potwierdź brak równoległego zlecenia,
   wyładuj modele Ollamy (`keep_alive=0`) i sprawdź /api/ps;
   sprawdź stan ComfyUI (/queue oraz /ai-platform/residency).
   Dopiero wtedy autoryzuj wykonanie w ComfyUI.
3. Powrót do LLM: potwierdź puste kolejki, przeprowadź
   /free unload_models+free_memory i sprawdź cleanup_pending=false,
   loaded_models=0 oraz ograniczony allocator. Potwierdź,
   że Ollama nie zaczęła pracy poza RM. Następnie zwolnij lease.
4. Niepewny stan, niedostępny API, znikający właściciel, błąd
   oczekiwania lub timeout: **BLOCKED**, marker i zachowanie
   własności. Nie zwalniać rezerwacji wyłącznie na podstawie
   terminalnego statusu zadania, samej pamięci VRAM ani TTL.
5. Zatrzymanie konkretnej jednostki systemd i ponowny start
   tylko jako osobna procedura recovery podczas kontrolowanego
   okna, po upewnieniu się, że nie odbieramy dostępu Gateway.
   Nie stosować SIGSTOP/SIGCONT ani restartu całego sterownika
   jako zwykłego sposobu przełączania.

## Granice bezpieczeństwa i test odbiorowy
To jest **cooperative scheduling** własnych silników, a nie
host-wide GPU isolation. Nie przyznaje pozytywnego `E_safe` ani
automatycznego fizycznego grantu N1:
`GPU_REUSE_SAFE=NOT_VERIFIED`, `N1_REAL_GPU_GRANT=NOT_ADMITTED`.

Odbiór każdej zmiany produkcyjnej musi sprawdzić:
- LLM→MEDIA→LLM na jednej rezerwacji bez restartów usług;
- brak współbieżnych zadań GPU i brak możliwości wejścia
  przez inne zadanie bez lease;
- odmowę przy błędzie /api/ps, /queue, /free,
  /ai-platform/residency, timeout i przerwaniu klienta;
- kolejkę zadań oczekującą podczas transition/dirty;
- brak awarii sterownika oraz nienaruszone działanie
  Gateway/Bridge/Ollamy po testach.

## Minimalne następne zadanie
Weryfikacja i ewentualne naprawienie **obecnej** implementacji
`GPUResidency` / `ResourceLeaseRegistry` testami negatywnymi
i jednym małym testem integracyjnym, bez tworzenia nowego systemu
i bez nadmiernie częstych restartów usług. Nie zmieniać
produkcyjnego release bez odrębnego odbioru.
