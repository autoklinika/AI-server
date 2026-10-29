# Magazyn V1 — dwa YubiKey 5C, przygotowanie escrow

Data: 29.10.2026. Status: DWA OSOBNE ZASZYFROWANE ESCROW NA GLOBALNAS — PASS. FIZYCZNY DRILL DRUGIEGO KLUCZA — PENDING.

## Faktycznie wykonane

- Drugi YubiKey otrzymał niezależny, niewyeksportowalny klucz ECC P-256 w PIV 0x82, z PIN policy ONCE i Touch ALWAYS. Certyfikat ręcznie dokończony dla tego samego klucza, bez ponownego generowania. Tożsamość age i publiczny recipient przechodzą kontrole.
- Skrypt second_yubikey_seal.py --check: SECOND_YUBIKEY_RECIPIENT_AND_NAS_PREFLIGHT=PASS.
- Skrypt second_yubikey_seal.py --seal: PRODUCTION_AES_AND_ORIGINAL_YUBIKEY_ESCROW_VERIFIED=PASS, SECOND_YUBIKEY_AES_ESCROW_WRITTEN_TO_GLOBALNAS=PASS oraz ORIGINAL_ESCROW_MASTER_AES_AND_BACKUPS_UNCHANGED=PASS.
- GlobalNAS Magazyn/recovery zawiera dwa osobne pliki 242 bajty: magazyn-v1-aes256-key-yubikey.age i magazyn-v1-aes256-key-yubikey-spare.age.
- Nie przeprowadzano rotacji AES ani zmian w bazie, Stage K, pierwszym YubiKeyu lub harmonogramie backupów.
- Skrypt second_yubikey_drill.sh --check: TWO_INDEPENDENT_CIPHERTEXT_FILES_ON_GLOBALNAS=PASS, SECOND_YUBIKEY_PIV_AND_NAS_PREFLIGHT=PASS, PIN_ATTEMPTS_REMAINING=3.
- Produkcyjne WebGUI i Telegram pozostają active, HTTPS Magazynu 200 i poprawny TLS, SQLite quick_check ok.

## Kolejna wymagana czynność

W interaktywnym terminalu SSH użytkownika harrypotter z podłączonym tylko drugim YubiKeyiem:

    bash /srv/ai-data/magazyn-v1/config/second_yubikey_drill.sh --run

PIN wpisuje wyłącznie użytkownik do swojego terminala, a po monicie dotyka YubiKeya. Skrypt odszyfrowuje istniejący klucz AES do prywatnego katalogu RAM, porównuje z aktualnym AES produkcji, weryfikuje rzeczywisty backup GlobalNAS, odtwarza bazę wyłącznie do pamięci RAM i sprząta. Nie nadpisuje produkcyjnej SQLite ani pierwszego escrow.

Oczekiwane zakończenie:
- SECOND_YUBIKEY_PHYSICAL_DECRYPT=PASS
- SECOND_YUBIKEY_RECOVERED_MASTER_AES_MATCH=PASS
- SECOND_YUBIKEY_REAL_NAS_ARCHIVE_VERIFY=PASS
- SECOND_YUBIKEY_REAL_NAS_RESTORE_IN_RAM=PASS
- SECOND_YUBIKEY_REAL_PRODUCTION_RECOVERY_DRILL=PASS
- TEMPORARY_RAM_SECRETS_REMOVED=PASS

W razie błędu nie próbuj PIN-u wielokrotnie. Zweryfikuj przyczynę bez odtwarzania bazy na produkcji.

## Formalna bramka

Dopiero po rzeczywistym fizycznym PASS obu niezależnych YubiKeyów można zamknąć dual-key offsite_recovery. Dotychczasowy wydany magazyn.release_gate wciąż ma starszą kontrolę offline.age, odrzuconą na rzecz dwóch YubiKeyów — nie należy oznaczać jej sztucznie jako PASS.
