# Magazyn V1 — drugi YubiKey 5C, fizyczne odzyskiwanie PASS

Data: 29.10.2026. Wynik: REAL SECOND YUBIKEY RECOVERY DRILL = PASS.

Operator wykonał rzeczywisty test z drugim fizycznym YubiKeyiem po przyłożeniu palca do sensora. Dostarczony wynik:
- TWO_INDEPENDENT_CIPHERTEXT_FILES_ON_GLOBALNAS=PASS
- SECOND_YUBIKEY_PHYSICAL_DECRYPT=PASS
- SECOND_YUBIKEY_RECOVERED_MASTER_AES_MATCH=PASS
- SECOND_YUBIKEY_REAL_NAS_ARCHIVE_VERIFY=PASS
- SECOND_YUBIKEY_REAL_NAS_RESTORE_IN_RAM=PASS
- SECOND_YUBIKEY_DRILL_EVIDENCE_SAVED_PRIVATELY=PASS
- SECOND_YUBIKEY_REAL_PRODUCTION_RECOVERY_DRILL=PASS
- PRODUCTION_DATABASE_AND_STAGE_K_PIV_UNCHANGED=PASS
- TEMPORARY_RAM_SECRETS_REMOVED=PASS

Raport maszynowy zapisany na rzeczywistym serwerze: /srv/ai-data/magazyn-v1/reports/yubikey-spare-real-drill-20261029.json (0600).
Jego status PASS, typ zdarzenia i siedem wymaganych podtestów zostały odczytane. Porównanie SHA-256 obu odbiorców PIV, drugiego ciphertextu oraz historycznego archiwum testowego z rzeczywistymi plikami zakończyło się PASS. W raporcie potwierdzono brak zmian produkcyjnej bazy.

Pierwszy YubiKey: historyczny fizyczny decrypt/restore PASS z 27.10.2026, odbiór udokumentowany w MAGAZYN_YUBIKEY_RECOVERY_2026-10-27_PL.md. Klucz AES produkcyjny nie był rotowany podczas migracji.
Drugi YubiKey: oddzielny klucz sprzętowy PIV ECC P-256 i oddzielny ciphertext na GlobalNAS, fizyczny decrypt/restore PASS 29.10.2026.
Konfiguracja Tailscale pracownika: wcześniej odebrana PASS.
Bieżący Stage K daily PASS 29.10.2026; weekly PASS; bridge Magazyn PASS bez zaległych problemów.

W lokalnym worktree przygotowano zmienioną bramkę recovery, zastępującą odrzucony wariant pendrive/age X25519 kontrolą dwóch niezależnych YubiKeyów. Testy ukierunkowanej bramki: 13/13 PASS, w tym przypadki odmowy przy braku raportu, niespójnych hashach i braku poświadczenia pierwszego testu.

Formalny pełny GO należy zapisać dopiero po ponownym uruchomieniu całej regresji i końcowej read-only bramki produkcyjnej. Nie wolno fałszywie oznaczać statusu release_gate na PASS bez wykonania. Nowej bramki nie podmieniano w zamrożonym runtime aplikacji, a działające WebGUI, Telegram i zasady backupu pozostają nienaruszone.
