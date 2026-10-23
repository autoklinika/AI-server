# RTX 5060 Ti / eGPU — komplet materiałów odbioru

Zbiór z dnia 23.10.2026 z rzeczywistego hosta AI Platform.
[Raport główny](../RTX_5060_TI_EGPU_CONFIGURATION_AND_STABILITY_2026-10-23_PL.md).

- installed/boot-gate — zainstalowany kod ai_egpu_boot.py, module_guard
- installed/systemd — rzeczywista usługa i zależności producentów pracy GPU
- installed/modprobe.d — konfiguracja modułów i blokady uruchamiania
- installed/ollama.service.d — rzeczywiste pliki konfiguracji Ollama
- installed/ai-gateway.service.d — drop-iny Gateway i RM
- installed/effective-hardware-and-runtime-snapshot.json — audyt odczytowy hosta
- reports/ — BGE-M3, wysoka VRAM/moc, dwugodzinny soak
- results/ — oryginalne wyniki JSON
- results/long-soak/telemetry.csv — wszystkie 7621 próbek ~1 Hz
- results/long-soak/ — status, zdarzenia, wyniki i logi
- tests/ — kod uruchomionych prób, tylko do archiwizacji
- history/ — raporty wcześniejszych etapów; nie wszystkie były wdrożone

**Nie należy bezpośrednio uruchamiać skryptów z tego archiwum ani
instalować plików na innym hoście.** Boot gate ma sprzętowo
specyficzne identyfikatory i zabezpieczenia.

Repozytorium jest publiczne. Nie umieszczono tokenów, haseł, plików
.env, prywatnych danych komunikatorów, danych klientów, wag modeli ani
pełnych dzienników systemowych.

Kontrola integralności (po wejściu do tego katalogu):

~~~shell
sha256sum -c SHA256SUMS.txt
~~~

Poprzednie NOT_DEPLOYED / NOT_REBOOT_VERIFIED z historycznych raportów
dotyczą wcześniejszego stanu i nie unieważniają późniejszego
odbioru produkcyjnego z 19:24 CEST.
