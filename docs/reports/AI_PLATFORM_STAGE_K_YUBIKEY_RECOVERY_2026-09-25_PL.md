# AI Platform — Stage K YubiKey Recovery — 2026-09-25

## Cel

Migracja szyfrowania backupów sekretów Stage K z pojedynczego recipienta `ssh-ed25519` na sprzętowy recovery key YubiKey, bez wiązania odzyskania z konkretnym laptopem.

## Skonfigurowany klucz

- model: YubiKey 5C;
- firmware: 5.4.3;
- aplikacja: PIV;
- slot: `RETIRED1` / `0x82`;
- algorytm: ECC P-256;
- `PIN policy`: `ONCE`;
- `Touch policy`: `NEVER`;
- klucz prywatny wygenerowany na YubiKeyu i niewyeksportowany.
Fabryczny PIN/PUK/management key zostały wykryte przed konfiguracją. `age-plugin-yubikey` wymusił zmianę PIN-u oraz zastąpił domyślny management key losowym kluczem przechowywanym w metadanych YubiKeya chronionych PIN-em.

## Runtime hosta

Zainstalowano/zweryfikowano `age`, `yubikey-manager`, `pcscd`, `libccid`, Rust/Cargo, `libpcsclite-dev`, `pkg-config` oraz `age-plugin-yubikey 0.5.1`.

Plugin runtime Stage K znajduje się obok platformowego `age`:
`/srv/ai-data/tools/age/usr/bin/age-plugin-yubikey`.

Dla zdalnej sesji wymagane były lokalne reguły Polkit i udev. Reguła udev ogranicza dostęp do urządzeń Yubico smart-card do grupy `pcscd` (`0660`).
## Testy

- wykrycie YubiKey przez `ykman`: PASS;
- odczyt PIV i slotu 82: PASS;
- potwierdzenie `PIN ONCE / Touch NEVER`: PASS;
- szyfrowanie testowe publicznym recipientem: PASS;
- odszyfrowanie testowe YubiKey + PIN: `YUBIKEY_DECRYPT_TEST=PASS`;
- platformowy `age 1.2.1` + `age-plugin-yubikey 0.5.1`: PASS;
- weryfikacja historycznego bundle SSH `20260924T164644Z`: PASS;
- syntetyczny manifest schema v2 / YubiKey: PASS;
- testy `test_stage_k_yubikey_recipients.py`: 4/4 PASS.
## Zmiany architektury Stage K

Dodano centralną politykę recipientów `k3_recipients.py`. Nowy manifest secrets ma `manifest_schema_version = 2`, typ `age-plugin-yubikey`, liczbę recipientów, ich listę oraz SHA-256 kanonicznego zestawu.

`k3_secrets_verify.py` pozostaje kompatybilny ze starymi bundle `ssh-ed25519`, dzięki czemu historyczne backupy nie wymagają ponownego szyfrowania.

Polityka jest przygotowana na wiele YubiKeyów. Dodanie drugiego 5C wymaga dopisania jego publicznego recipienta do zaakceptowanej i aktywnej listy; prywatne klucze pozostają niezależne.
## Stan i następny gate

Aktywny historyczny `/srv/ai-data/platform/recovery/stage-k/age-recipients.txt` nie został jeszcze podmieniony. Nowy recipient jest przygotowany osobno jako `age-recipients-yubikey.txt`, aby przed merge nie zepsuć starego skryptu z `main`.

Następny gate: wykonać rzeczywisty `k3_secrets_backup.sh` z worktree migracji i `STAGE_K_AGE_RECIPIENTS=.../age-recipients-yubikey.txt`, najlepiej przy odłączonym YubiKeyu. Potwierdzi to, że produkcyjny backup szyfruje się wyłącznie publicznym recipientem bez obecności tokena.
