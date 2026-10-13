# Vision Resource Manager — rozdzielenie poświadczeń po obserwatorze GPU

**Status: DEV / audyt otwarty do czasu wdrożenia i testu wykonawcy bez sekretu kontrolnego.**
Data: 2026-10-13. PR #163 zależny od PR #161, audyt PR #162.

## Potwierdzony stan wejściowy

Administrator uruchomił instalację. Odczytowe testy systemowe potwierdziły:
- GPU_CLIENTS_VISIBLE=2 dla ai-vision i ai-gateway-rm;
- brak połączenia socket dla harrypotter;
- SYSTEM_SECURITY_VERIFY=PASS, observer/production Ollama/ai-gateway active;
- **problem:** stary root:ai-vision-rm 0640 bearer jest dostępny obu kontom serwisowym przez współdzieloną grupę.

## Migracja kontrolowanego uprawnienia

Administrator uruchamia wyłącznie po sprawdzeniu syntax + SHA:
`sudo bash deploy/vision-rm-security/separate-control-credential.sh --apply`.

Ten krok:
1. Zakłada wyłączną grupę **ai-vision-rm-control**, tylko dla ai-gateway-rm.
2. Przenosi /etc/ai-platform/vision-rm i executor.token na root:ai-vision-rm-control.
3. Rotuje poprzedni sekret ONCE atomowo, z fsync pliku i katalogu; nie wypisuje nowego sekretu. Odtąd stary sekret jest nieważny.
4. Ustawia /var/lib/ai-gateway-rm jako 0700, prywatny dla kontrolera.
5. Dowodzi testem runuser, że **ai-vision nie może odczytać tokenu**, a ai-gateway-rm może.
6. Nie restartuje usług, nie zmienia ai-gateway/main/Ollama, nie zmienia root-own observer socket group ai-vision-rm.

Po akcji administrator uruchamia weryfikator:
`sudo bash deploy/vision-rm-security/verify-system-security.sh --verify`.

Wymagane: SYSTEM_SECURITY_VERIFY=PASS,
VISION_MODEL_CONTROL_SECRET=DENIED,
VISION_MODEL_CONTROLLER_STATE=DENIED,
GATEWAY_CONTROL_SECRET=READABLE,
OBSERVER_2_USER_SNAPSHOTS=PASS.

## Co jeszcze blokuje produkcję mimo wyniku PASS

Obecny `ScopedVisionExecutor` z PR #161 łączy przywileje kontrolera (POST/DELETE ResourceLease) z uruchamianiem modelu jako ten sam UID. Po rozdzieleniu poświadczenia **celowo nie może** wykonywać obu operacji jako ai-vision. To jest pożądany fail-closed, nie wolno przywracać shared-group sekretu jako skrótu.

Konieczny osobny, root-owned controller/broker z własnością ai-gateway-rm oraz ściśle ograniczonym AF_UNIX protokołem do uruchamiania zaufanych zadań:
- controlling process posiada sekret, bez przekazywania go do ai-vision;
- worker pod UID ai-vision uruchamia zaufany skrypt/checkpoint w systemd cgroup;
- worker może wykonać **wyłącznie bezstronny, odczytowy GET potwierdzający przydział** z osobną ograniczoną capability, nie pełnym RM bearer;
- broker odrzuca nieznane programy/scope/UID, wiąże lease z jednym zatwierdzonym jobem i sprawdza cgroup terminal + read-only GPU observer;
- żaden proces modelu nie może wykonywać mutacji lease (POST, DELETE, heartbeat) ani odczytać sekretu;
- heartbeat loss / crash controller => fail-closed, bez auto-unblock.

Wymagane następnie: testy negatywne pod obiema UID, realny WinCLIP + ROCm, pełne CI, niezależny security gate i jawna zgoda na merge/cutover.

**Nigdy nie włączaj AI_BRIDGE_GATEWAY_VISION_EXTERNAL_ENABLED w produkcji przed pełnym gate.**
