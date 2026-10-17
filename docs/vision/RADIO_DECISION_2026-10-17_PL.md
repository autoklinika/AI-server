# Vision PCB — decyzja o AnomalyVFM RADIO (17.10.2026)

**Status:** `SELECTED / FROZEN_UNTIL_STATION_READY / NOT_PRODUCTION`.
**Projekt:** AI Platform / Vision, zdjęcia PCB i sterowników ECU.

## Decyzja

1. **AnomalyVFM RADIO** pozostaje jedynym wybranym kandydatem do dalszego rozwoju i specjalizacji Vision.
2. **Trening i kolejne benchmarki są wstrzymane** do czasu ukończenia stanowiska fotograficzno-inspekcyjnego. Nie uruchamiać automatycznie GPU.
3. Oryginalny checkpoint zachować bez zmian. Przyszły LoRA/DoRA, nowa głowica lub kalibracja otrzymają osobne wersje i benchmark.
4. Usunąć z dysku inne eksperymentalne modele Vision i ich dedykowane składniki. Nie naruszać modeli AI Platform używanych do innych zadań ani wspólnych danych VisA/Resource Managera.
5. Nie promować RADIO do produkcji bez niezależnej walidacji na rzeczywistych sterownikach ECU.

## Uzasadnienie i ograniczenia

RADIO uzyskał najwyższe image AUROC i pixel AUROC na VisA PCB3/PCB4 spośród modeli posiadających pełne porównywalne benchmarki. W małych pilotażach AnomalyVFM DINOv3 oraz GeneralAD nie uzyskały przewagi uzasadniającej pełne testy.

To **nie oznacza dostatecznej skuteczności detekcyjnej**: przy globalnym progu wybranym na PCB2 (docelowe 5% FPR) RADIO wykryło 21/100 uszkodzeń na PCB3 i 40/100 na PCB4; na obu splitach było 0 FP, lecz kosztem dużej liczby przeoczeń. Obniżenie progu przy zwiększonej czułości na PCB3 powoduje liczne fałszywe alarmy. Brakujące elementy PCB3: 0/20 przy bazowym progu.

RADIO wykrywa **odstępstwo obrazu**, ale nie jest modelem rozumienia elektroniki. Nie potrafi z samej anomalii wiarygodnie wyprowadzać identyfikacji uszkodzonego elementu, konsekwencji elektrycznych ani brakującej obsady nieznanego PCB. Docelowo należy oddzielić:
- detektor anomalii i mapę ROI (RADIO);
- rozpoznanie rodzaju usterki i opis techniczny przez osobny model, zasoby wiedzy i człowieka;
- opcjonalny wzorzec znanego ECU (referencja/BOM/schemat), jeśli jest dostępny.

Nie mieszać adaptera Vision z ogólnym adapterem automotive ani osobnym adapterem wentylatora **WVC**.

## Warunki dalszego rozwoju

Po ukończeniu stanowiska (Sony A6100, stabilny import zdjęć, podgląd, kontrolowane oświetlenie, mechanika i ramię robota) przygotować **Vision PCB Dataset v1**, w tym:
- obrazy poprawne i uszkodzone z identyfikacją rodziny ECU, oznaczeniem rzeczywistych defektów, maskami i kontrolą źródła;
- powtarzalny protokół ekspozycji, ostrości, skali, oświetlenia i wycinania ROI;
- zestaw kalibracyjny odrębny od **nowego ślepego zbioru testowego** (PCB3/PCB4 VisA są już przeanalizowane);
- metryki recall vs FPR, Image AUROC/AP, Pixel AUROC/AP, region recall, liczba fałszywych alarmów na PCB, czas inferencji i niezawodność GPU.

Kolejność: najpierw poprawa wejścia/ROI i kalibracji **bez treningu**, potem dopiero izolowany LoRA/DoRA lub specjalizacja głowicy, na końcu walidacja na nieznanych ECU fotografowanych Sony A6100. Nie zastępować pomiarów jakości oceną samego AUROC.

## Fizycznie usunięte eksperymentalne modele Vision

PatchCore (usunięty wcześniej), WinCLIP, AnomalyCLIP, AnomalyVFM DINOv3, GeneralAD, MiniCPM-V 4.7 1B oraz Qwen3-VL 8B wraz z dedykowanymi wagami, środowiskami, predykcjami i skryptami testowymi. W końcowej operacji porządkowania z 17.10.2026 odzyskano **ok. 30,7 GB** miejsca na NVMe; wcześniejsze usunięcie PatchCore było osobną operacją.

Wyjątki: 10 małych JSON-ów WinCLIP/AnomalyCLIP pozostaje jako niezmienne referencje dla benchmarku RADIO. Pakiet `anomalib` zawiera także implementacje innych architektur, gdyż jest biblioteką współdzieloną, a repozytorium Git zachowuje historię zmian. Nie oznacza to aktywnej instalacji konkurencyjnych modeli.

Produkcja AI Platform, Gateway, Bridge, Resource Manager, Ollama/Hermes i niezależne projekty pozostały bez zmian. Nie scalać tej dokumentacji do `main` bez oddzielnej decyzji.

## Dokumenty

- [Benchmarki i analiza progów](RADIO_BENCHMARKS_2026-10-17_PL.md)
- [Retencja, sumy kontrolne, wznawianie i raport czyszczenia](RADIO_RETENTION_RESUME_2026-10-17_PL.md)
- Rejestr aktywnego wyboru: `benchmarks/vision_pcb_v1/models.json` — wyłącznie `anomalyvfm-radio`.

**Stan końcowy: model wybrany i zachowany, dalsze prace wstrzymane do ukończenia stanowiska Vision.**
