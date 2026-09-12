# Hermes: Discord voice — wdrożenie i odtworzenie, 12.09.2026

## Wynik i granice potwierdzenia

Uruchomiono prywatnego bota Discord z odbiorem mowy z telefonu, polskim STT
i polskim TTS. Po końcowych poprawkach użytkownik potwierdził poprawną,
zrozumiałą odpowiedź na „Hermes, powtórz: napięcie wynosi dwanaście przecinek
sześć wolta”. Zapis i rzeczywisty odczyt lokalnego protokołu również przeszły.
Bot pozostał w kanale głosowym „Ogólne” serwera „Serwer AI”. Jest to stan
zakończenia próby, nie deklaracja bieżącej dostępności usługi.

Nie sprawdzono długiej sesji po poprawkach. Nie ustalono jednej przyczyny
wcześniejszych błędów modelu i zapętlenia JSON. Nie wdrożono automatycznego
dziennika sesji ani generatora raportów napraw. Telegram ponownie się połączył,
ale nie wykonano pełnej nowej wymiany wiadomości w aplikacji Telegram.

Nie konfigurowano, nie montowano ani nie zapisywano niczego na NAS-ie.
Nie sterowano ECU, CAN, testerami ani programatorami. Nie przełączono globalnie
LLM na CPU. Rozpoznawanie mowy na CPU jest osobnym, docelowym ustawieniem STT.

Ten dokument archiwizuje wykonane działania. Dołączone parametryzowane skrypty
są rekonstrukcją do odtworzenia, przygotowaną później i sprawdzoną lokalnie;
nie były ponownie wdrażane na serwerze w ramach przygotowania repozytorium.
Nie zawiera tokenów, prywatnych identyfikatorów, nagrań ani pełnych rozmów.

## Punkt wyjścia i zachowane elementy

- Hermes 0.21.0, commit `79445a496c86a19332ad786494b8384d2167e2d0`.
- Ollama 0.32.14, model Qwen 35B Q4_K_M, kontekst 65536.
- AMD Radeon 890M / RADV STRIX1; używany backend Vulkan.
- Istniejący `hermes-gateway.service` użytkownika uruchamia
  `venv/bin/python -m hermes_cli.main gateway run` z katalogu Hermes.
  Włączone uruchamianie usługi i linger; restart automatyczny już istniał.
- Domyślny model nadal `qwen3.6:35b-hermes64k`, provider `custom`,
  `http://127.0.0.1:11435/clients/hermes/v1`, API `chat_completions`.
- Zachowano `agent.max_turns=500`, `verbose=false`, `reasoning_effort="none"`.
- Zachowano konfigurację Telegrama i jego zestaw narzędzi. Wcześniejsze patche
  `agent/turn_api_request.py` (wspólna kolejka zasobów) i `gateway/run_inbound.py`
  (argumenty szybkich poleceń/media) istniały przed tą pracą i nie były edytowane.
  Ich wcześniejsze skrypty odtworzenia są już w `tools/` tego repozytorium.
- Nie zmieniono kodu rdzenia Hermesa ani ai-gateway podczas tej integracji.
- Ollama już miała `OLLAMA_VULKAN=1`, `OLLAMA_IGPU_ENABLE=1`,
  `OLLAMA_MAX_LOADED_MODELS=1`. Usługa preload była w stanie failed przed pracą.

Przed zmianami wykonano prywatną kopię `.env`, `config.yaml`, definicji usługi,
pełnego venv i listy pakietów. Katalog kopii miał tryb 0700, pliki konfiguracyjne
0600. Sprawdzono, że wersje wcześniej zainstalowanych pakietów nie zmieniły się.
Kopie pozostają na serwerze; nie są materiałem do publicznego repozytorium.

## Zmiany wdrożone

### Discord i zależności

Utworzono prywatną aplikację/bota, instalowaną wyłącznie na serwerze właściciela.
Włączono Message Content Intent; Members i Presence pozostawiono wyłączone.
Właściciela ograniczono przez numeryczny `DISCORD_ALLOWED_USERS`.
Nie ustawiano kanału domowego. `bot_public=false`; brak publicznego linku instalacji.

Uprawnienia bota: View Channels, Send Messages, Embed Links, Attach Files,
Read Message History, Add Reactions, Connect, Speak, Use Voice Activity
(suma bitowa 36817984). Bez Administrator. Użytkownik sam zatwierdził regulamin,
CAPTCHA, weryfikację e-mail i reset/skopiowanie tokenu. Automatyzacja nie
zastępowała tych czynności.

Token odczytano bez wypisywania ze schowka Windows, sprawdzono zgodność aplikacji
i tożsamość przez Discord `/users/@me`, przesłano przez stdin/SSH i atomowo
dopisano do prywatnego `.env` (0600). Schowek wyczyszczono tylko, jeśli nie
zmienił się od odczytu. Publiczny helper przyjmuje stdin i identyfikatory operatora;
nie zawiera prywatnych danych z pierwotnego skryptu.

Dodano bez zmiany istniejących wersji: discord.py 2.7.1, PyNaCl 1.6.2,
davey 0.1.4, faster-whisper 1.2.1, brotlicffi 1.2.0.1. Edge TTS 7.2.7 już istniał.
Dołączony plik requirements zapisuje bezpośrednie zależności, nie pełny lock
transytywny. Nie używano `discord.py[voice]`, którego ograniczenie PyNaCl
kolidowało z wybraną wersją. Sprawdzono dostępność FFmpeg i Opus.
Wbudowany VoiceReceiver Hermesa obsługiwał odbiór i DAVE przez davey;
nie instalowano discord-ext-voice-recv.

### Końcowa konfiguracja

- STT: `enabled=true`, `provider=local`, `language=pl`, lokalnie `model=small`,
  `device=cpu`, `compute_type=int8`. Istniejące ustawienia OpenAI STT zachowano.
- TTS: `provider=edge`, `edge.voice=pl-PL-MarekNeural`. To usługa sieciowa;
  lokalny jest STT, nie cały tor audio.
- Discord: timeout bezczynności voice 0, `auto_thread=false`, tekstowy kanał
  ogólny w `free_response_channels`, polski prompt protokolanta.
- `platform_toolsets.discord=[terminal,file,web]`. To realny dostęp do narzędzi
  na uprawnieniach procesu; prompt nie stanowi izolacji systemowej.
- Nadpisania modelu dla kanału tekstowego i głosowego: model
  `qwen3.6:35b-hermes64k-gpu`, provider `custom`.
- Dodatkowy custom provider „Hermes Discord Qwen GPU”: ten sam lokalny URL
  ai-gateway, `api_mode=chat_completions`, kontekst aliasu 65536,
  `extra_body={reasoning_effort: "none", temperature: 0, presence_penalty: 0}`.
- `auxiliary.title_generation.enabled=false`. **Jest to zmiana globalna Hermesa,
  również dla Telegrama**; eliminuje dodatkowe wywołania tytułów ze wspólnej kolejki.

Alias GPU utworzono z istniejącego modelu przez `/api/create`, zmieniając tylko
`num_gpu=99`. Zachowuje wagi, renderer/parser qwen3.5 i kontekst 64K. Modelfile
w `deploy/` odtwarza tę samą zmianę. Template `{{ .Prompt }}` jest prawidłowy
przy tym rendererze/parserze i nie został zastąpiony ręcznym szablonem.

## Dziennik diagnozy i testów

Poniższe czasy są obserwacjami pojedynczych prób, nie gwarancją wydajności.
Czas odpowiedzi tekstowej nie jest pełnym opóźnieniem rozmowy głosowej.

| Próba / działanie | Wynik i znaczenie |
| --- | --- |
| Syntetyczna polska fraza o silniku, napięciu 12,6 V i masie | Edge TTS ~4,75 s; STT ~11,25 s z pierwszym ładowaniem, następnie ~2,57 s i ~1,16 s na ciepło; sens rozpoznany poprawnie |
| Pierwszy odczyt pliku przez Hermes API | Rzeczywisty read_file i poprawny marker; ~56 s, odpowiedź po angielsku |
| Krótka odpowiedź na bazowym modelu | ~104 s i błędne „user”; Discord ~100 s i „user/Otwiera” |
| Pierwsza rozmowa głosowa | Mapowanie SSRC, odbiór mowy, STT i odtwarzanie działały; treść modelu błędna, m.in. angielskie fragmenty i znaczniki |
| Bezpośredni test ai-gateway | Błędna chińska treść przy krótkim polskim zadaniu; minimalne oczekiwanie w kolejce wskazywało też na problem poniżej warstwy Hermes |
| Porównanie CPU, num_gpu=0, mały kontekst | Poprawne „Głos gotowy”, ~20 s głównie ładowania. Powstał testowy alias CPU, ale nie wybrano go globalnie ani jako końcowego modelu Discorda |
| GPU auto-fit vs num_gpu=99 | Auto-fit częściowo dzielił obliczenia CPU/GPU (41/42 warstwy). Wymuszenie pełnego GPU: 42/42, size_vram=size ok. 23,94 GB; próby 4K i 64K |
| Hermes API zapis/odczyt na GPU | Plik poprawny, ale klient przekroczył 240 s; serwer dokończył po ok. 7 min 36 s. Timeout klienta nie anulował wszystkich prac w kolejce |
| Jawne reasoning_effort=none w extra_body | Generic custom endpoint na 11435 nie korzystał z rozpoznania Ollama po standardowym porcie; samo ustawienie agenta nie wystarczało w badanej ścieżce |
| Wyłączenie automatycznych tytułów | Dodatkowe zadania tytułów zajmowały wspólną kolejkę; zmiana globalna, restart przy braku aktywnych agentów, oczekiwanie na opróżnienie kolejki |
| Arytmetyka przed temperature=0 | Błędne 46 i nieprawidłowe wywołanie narzędzia; ustawiono temperature=0 i presence_penalty=0 dla providera GPU |
| Discord: zapis oraz ponowny odczyt protokołu | Potwierdzone write_file i read_file; ~32,3 s czasu całkowitego (~30,6 s modelu) |
| Zapętlenie title | Po początkowo dobrych odpowiedziach model wielokrotnie emitował JSON z tytułem, odczytywany przez TTS; nie uznano tego za poprawne działanie |
| Diagnostyczny proxy na loopback 11436 | Tymczasowo przechwycono prywatnie body żądania bez nagłówków; brak response_format i wymuszenia tytułu; 33 wiadomości, 10 definicji narzędzi, max_tokens 65536 |
| Porównanie surowych żądań | Bez narzędzi odpowiedzi poprawne nawet z historią; z narzędziami wystąpiło nieoczekiwane tool_call mimo tool_choice=none. Surowa próba nie miała executora, niczego nie wykonała |
| Zakończenie diagnostyki | Wycofano URL 11436 do 11435, zatrzymano wyłącznie własny proxy, usunięto prywatne przechwycone body; nie zmieniano kodu ai-gateway |
| Opróżnienie pamięci modelu | Dopiero po sprawdzeniu braku agentów, kolejki i leases użyto keep_alive=0 dla załadowanego modelu; nie usunięto wag ani konfiguracji |
| Nowa sesja po przeładowaniu GPU | Powtórzenie „napięcie wynosi 12,6 V.” poprawne ~27,1 s z ładowaniem; 17+28 →45 ~2,34 s na ciepło |
| Odczyt po wcześniejszym podaniu wartości | Odpowiedź poprawna, ale bez read_file; **nie zaliczono jako test odczytu** |
| Odczyt w nowej sesji bez podpowiedzi wartości | Potwierdzone read_file i 12,6 V, ~7,68 s |
| „Dzień dobry. Słucham.” | Poprawne ~2,85 s, audio uruchomione bez błędu |
| Końcowa próba mikrofonu telefonu | Użytkownik potwierdził poprawną i zrozumiałą odpowiedź głosową |

Nie dowiedziono konkretnego błędu sterownika ani szablonu. Zmiana GPU,
parametrów generowania, tytułów i wyczyszczenie sesji/pamięci występowały w jednej
serii diagnostycznej; nie da się przypisać całej poprawy jednemu czynnikowi.

Podczas testów mikrofon telefonu przechwytywał również głos drugiego asystenta
z głośnika komputera. Te wypowiedzi nie były nowymi poleceniami użytkownika
do zmiany konfiguracji. Do kontrolowanego testu powinna mówić jedna aplikacja naraz.

## Odtworzenie na istniejącej instalacji

1. Ustal lokalne `HERMES_HOME`, venv, jednostkę użytkownika i istniejący endpoint
   ai-gateway. Nie kopiuj konfiguracji całej instalacji z innego hosta.
2. Przy braku aktywnych rozmów i zadań zatrzymaj bramkę i wykonaj prywatną kopię
   `.env`, YAML, jednostki i venv. Zapisz listę wersji pakietów. Katalog kopii 0700.
3. W istniejącym venv wygeneruj constraints (`python -m pip freeze` do prywatnego
   pliku) i zainstaluj `deploy/hermes-discord-voice.requirements.txt` z `-c` wskazującym
   ten plik. W razie konfliktu zatrzymaj wdrożenie zamiast aktualizować cały Hermes.
   Sprawdź `python -m pip check`, importy modułów, FFmpeg i Opus.
4. Skonfiguruj aplikację Discord według sekcji uprawnień. Dodaj bota do właściwego
   serwera. Sekret przekaż bez historii poleceń do `tools/install_hermes_discord_secret.py`
   przez stdin; argumenty to `--env-file`, `--bot-id`, `--owner-id`. Uruchom na Linux
   jako właściciel bramki. Helper odmawia nadpisania istniejących ustawień Discorda.
   Szablon `.env.example` służy wyłącznie jako dokumentacja kluczy.
5. Utwórz alias: `ollama create qwen3.6:35b-hermes64k-gpu -f deploy/hermes-discord-gpu.Modelfile`.
   Sprawdź `ollama show --modelfile` i kontekst; przy pierwszym uruchomieniu sprawdź
   `ollama ps` oraz użycie GPU. Nie zmieniaj globalnego domyślnego modelu.
6. Przygotuj kandydat konfiguracji w prywatnym katalogu poza checkoutem:

   ```sh
   "$HERMES_PYTHON" tools/prepare_hermes_discord_voice.py \
     --input "$HERMES_HOME/config.yaml" \
     --output "$HERMES_HOME/config.discord-candidate.yaml" \
     --text-channel "$TEXT_CHANNEL_ID" --voice-channel "$VOICE_CHANNEL_ID"
   ```

   Helper nie nadpisuje wejścia, nie restartuje usług i nie łączy się z serwerem.
   Wynik zawiera zachowane ustawienia prywatne z wejścia: nie dodawaj go do Gita.
   Format JSON jest poprawnym YAML. Przejrzyj lokalnie różnicę; potwierdź model
   domyślny, Telegram oraz świadomą globalną zmianę automatycznych tytułów.
7. W oknie bez aktywnych zadań zastąp lokalną konfigurację sprawdzonym kandydatem
   z uprawnieniami 0600 i uruchom bramkę. Sprawdź połączenia i brak błędów importu.
   Nie czyść modelu ani nie restartuj wspólnej infrastruktury przy aktywnych zadaniach.
8. Wybierz natywne `/new`, następnie `/voice` → `mode` → `join` na Discordzie,
   po dołączeniu telefonu do kanału głosowego. Zakończenie: `/voice` → `mode` → `leave`.
   Samo wpisanie tekstu przypominającego slash command nie zawsze je wykonywało.

Skrypty nie wykonują automatycznie montowania NAS, operacji ECU ani przełączenia
globalnego LLM na CPU. Nie tworzą zadań cyklicznych. Odbiór głosu działa przez
istniejącą usługę, bez nowego mechanizmu harmonogramu.

## Test odbiorczy i powrót do kopii

W nowej sesji sprawdź kolejno: polską krótką odpowiedź, 17+28, utworzenie lokalnego
pliku testowego i rzeczywiste wywołania write_file/read_file. Treść testowa:

> Objaw: silnik nie uruchamia się. Pomiar: napięcie zasilania 12,6 V. Hipoteza: przerwa w przewodzie masowym.

Potem rozpocznij nową sesję i poproś o odczyt pliku bez podpowiadania wartości.
Sprawdź ślad read_file; sam poprawny tekst nie dowodzi dostępu do pliku.
Na końcu wykonaj próbę mikrofonu i odsłuchu oraz dłuższą sesję z kilkoma zapisami.
Ostatnia część jest nadal otwartym testem, nie wynikiem tego wdrożenia.

Przy powrocie do kopii najpierw odłącz voice i zaczekaj na brak aktywnych prac,
zatrzymaj bramkę, odtwórz prywatną konfigurację i ewentualnie venv z kopii,
następnie uruchom usługę i sprawdź Telegram. Nie usuwaj protokołów ani modeli
automatycznie. Alias GPU może pozostać nieużywany. Zachowaj lokalne materiały.

## Materiały utrwalone i wyłączone

W repozytorium: ten raport, parametryzowany generator konfiguracji, bezpieczny
helper sekretu, Modelfile, bezpośrednie wersje zależności, wzorzec kluczy `.env`
i testy offline. Zastępują lokalny raport końcowy i jednorazowy skrypt z prywatnymi
identyfikatorami w zakresie informacji potrzebnych do odtworzenia.

Poza publikacją pozostają `.env`, backup venv, identyfikatory kont/kanałów,
nagrania, transkrypcje, logi pełnych rozmów i surowe żądania. Przechwycone body
diagnostyczne usunięto jeszcze przy kończeniu diagnozy. Pozostałych lokalnych
materiałów nie usuwano w ramach przygotowania repozytorium. Starsza kopia raportu
na serwerze nie została zaktualizowana; końcowy opis stanu to niniejszy dokument
i lokalny raport wyników, nie wcześniejszy szkic dotyczący NAS.
