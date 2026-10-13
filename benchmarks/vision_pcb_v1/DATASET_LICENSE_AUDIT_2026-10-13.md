# Vision PCB — audyt pochodzenia i praw danych (2026-10-13)

Status: **weryfikacja publicznych źródeł**, nie prawna gwarancja i nie zgoda na publikowanie zbiorów dalej.

| Dataset | Status | Źródło | Warunek |
|---|---|---|---|
| VisA PCB1–PCB4 | CC BY 4.0 | https://github.com/amazon-science/spot-diff | Podawać autorów i licencję. Zachować oryginały, sumy SHA-256 |
| PCB-IND | CC BY 4.0 | https://www.nature.com/articles/s41597-026-07684-4 | Atrybucja; kontrola duplikatów i przygotowania splitów |
| DeepPCB | **RESEARCH HOLD** | https://github.com/tangsanli5201/DeepPCB | README mówi research-only; nie wykorzystywać automatycznie do treningu komercyjnego |
| PCB-SAID | **ACCESS HOLD** | https://openaccess.thecvf.com/content/ICCV2025W/VISION%2725/html/Mineo_PCB-SAID_A_Low-Cost_Camera-Based_Dataset_for_Few-Shot_SMD_Assembly_Inspection_ICCVW_2025_paper.html | Autorzy udostępniają na żądanie; brak potwierdzonych praw i kompletu plików |

## Zasady integracji danych

1. Prawdziwe archiwa są umieszczane **wyłącznie na NVMe**, poza repo GitHub; brak danych w produkcyjnym runtime.
2. Nie przyjmujemy historycznych splitów bez audytu specimen_id, source_id, hash obrazu; obrazy jednego fizycznego PCB nie mogą przejść między splitami.
3. Benchmark **B3** ma zawierać nieznane rodziny PCB. Test leave-one-PCB-family-out może być realizowany dla czterech kategorii VisA, ale nie stanowi dowodu generalizacji do napraw ECU.
4. Oryginalne maski VisA powinny być oceniane dodatkowo odrębnym silnikiem pikselowym; obecny scorer liczy bounding-box IoU, a **nie AUPRO**.
5. Na bieżącej AI Platform test HEAD oficjalnego archiwum VisA zwrócił HTTP 200, Content-Length **1,929,840,640 B**. Test 1 MiB przez HTTP Range zwrócił 206, ale transfer rzędu **0.62 MB/s**, dlatego nie rozpoczęto pobierania całości podczas pracy użytkownika.
6. Licencje checkpointów modeli, tokenizerów, wag CLIP, YOLO i zestawów treningowych wymagają oddzielnego audytu przed użyciem komercyjnym.

## Kolejny gate

DATA-01: wersjonowany manifest obrazu + harmonogram kontrolowanego importu i atrybucji.
MODEL-01: wybór checkpointów i sprawdzenie sprzętowego backendu (CPU/GPU; nie zakładać CUDA).
