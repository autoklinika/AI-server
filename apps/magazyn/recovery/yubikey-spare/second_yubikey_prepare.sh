#!/usr/bin/env bash
# Interactive provisioning of the SECOND YubiKey 5C for Magazyn V1.
# PIN/PUK are entered only into the user's own SSH terminal.
set -Eeuo pipefail
set +x
umask 077

ROOT=/srv/ai-data/magazyn-v1
DIR="$ROOT/private/yubikey-spare"
PLUGIN=/srv/ai-data/tools/age/usr/bin/age-plugin-yubikey
PRIMARY_RECIPIENT_FILE=/srv/ai-data/platform/recovery/stage-k/age-recipients.txt
PRIMARY_CIPHER=/mnt/AI_Platform/Magazyn/recovery/magazyn-v1-aes256-key-yubikey.age
MODE="$1"
TEMP=""
fail(){ echo "SECOND_YUBIKEY_BLOCKED: $*" >&2; exit 2; }
cleanup(){ if [[ -n "$TEMP" && -f "$TEMP" && ! -L "$TEMP" ]]; then rm -f -- "$TEMP"; fi; }
trap cleanup EXIT
[[ "$MODE" == --check || "$MODE" == --prepare ]] || fail "Uruchom --check albo --prepare."
[[ "$(id -un)" == harrypotter ]] || fail "Korzystaj z konta harrypotter, bez sudo."
[[ -x "$PLUGIN" && -r "$PRIMARY_RECIPIENT_FILE" && -s "$PRIMARY_CIPHER" ]] || fail "Brak starego, sprawdzonego recovery."
[[ -f "$ROOT/private/backup-keys/magazyn.key" ]] || fail "Nie ma klucza AES Magazynu."
[[ "$(stat -c %s "$ROOT/private/backup-keys/magazyn.key")" == 32 ]] || fail "Rozmiar AES jest nieprawidłowy."
CURRENT_SERIAL="$(ykman list --serials)"
[[ "$CURRENT_SERIAL" =~ ^[0-9]+$ ]] || fail "Podłącz DOKŁADNIE JEDEN YubiKey 5C."
FIRST="$(grep -E '^age1yubikey1[a-z0-9]+$' "$PRIMARY_RECIPIENT_FILE" | head -n 1 || true)"
[[ "$FIRST" == age1yubikey1* ]] || fail "Nie rozpoznano pierwszego recipienta."
EXISTING="$("$PLUGIN" --list 2>/dev/null || true)"
if grep -Fqx -- "$FIRST" <<< "$EXISTING"; then
  fail "Podłączono PIERWSZY YubiKey — nie zmieniam go."
fi
INFO="$(ykman piv info 2>/dev/null)" || fail "Nie udało się odczytać PIV."
[[ "$INFO" != *"Slot 82 (RETIRED1):"* ]] || fail "Slot PIV 0x82 jest już zajęty — nie nadpisujemy."
[[ ! -e "$DIR/identity.txt" && ! -e "$DIR/recipient.txt" ]] || fail "Zapasowa identity już istnieje — nie nadpisujemy."
has_pin_default(){ [[ "$INFO" == *"Using default PIN"* ]]; }
has_puk_default(){ [[ "$INFO" == *"Using default PUK"* ]]; }
has_mgmt_default(){ [[ "$INFO" == *"Using default Management key"* ]]; }
echo "SECOND_YUBIKEY_NOT_PRIMARY=PASS"
echo "SECOND_PIV_SLOT_0X82_EMPTY=PASS"
if has_pin_default; then echo "PIN_STATUS=FACTORY"; else echo "PIN_STATUS=CHANGED"; fi
if has_puk_default; then echo "PUK_STATUS=FACTORY"; else echo "PUK_STATUS=CHANGED"; fi
if has_mgmt_default; then echo "MANAGEMENT_KEY_STATUS=FACTORY"; else echo "MANAGEMENT_KEY_STATUS=CHANGED"; fi
if [[ "$MODE" == --check ]]; then
  echo "SECOND_YUBIKEY_SETUP_PREFLIGHT=PASS"
  echo "NEXT: uruchom --prepare w swoim interaktywnym terminalu SSH."
  exit 0
fi
[[ -t 0 && -t 1 && -c /dev/tty ]] || fail "Potrzebny Twój interaktywny terminal SSH."
[[ -d "$ROOT/private" && "$(stat -c %a "$ROOT/private")" == 700 ]] || fail "Nieprawidłowe uprawnienia katalogu."
install -d -m 0700 "$DIR"
echo "Wybierz 8-cyfrowy PIN oraz INNY 8-cyfrowy PUK; zapisz PUK poza serwerem."
echo "Przy błędnym PIN/PUK przerwij, nie ponawiaj automatycznie."
if has_pin_default; then
  echo "ETAP 1/4: zmiana fabrycznego PIN-u."
  ykman piv access change-pin || fail "Zmiana PIN-u nieudana. Przerwano."
  INFO="$(ykman piv info 2>/dev/null)" || fail "Błąd urządzenia."
  ! has_pin_default || fail "Nadal PIN fabryczny."
  echo "SECOND_YUBIKEY_PIN_CHANGED=PASS"
fi
if has_puk_default; then
  echo "ETAP 2/4: zmiana fabrycznego PUK-u, innego od PIN-u."
  ykman piv access change-puk || fail "Zmiana PUK-u nieudana. Przerwano."
  INFO="$(ykman piv info 2>/dev/null)" || fail "Błąd urządzenia."
  ! has_puk_default || fail "Nadal PUK fabryczny."
  echo "SECOND_YUBIKEY_PUK_CHANGED=PASS"
fi
if has_mgmt_default; then
  echo "ETAP 3/4: losowy klucz zarządzający PIV chroniony PIN-em."
  ykman piv access change-management-key --generate --protect || fail "Zmiana management key nieudana."
  INFO="$(ykman piv info 2>/dev/null)" || fail "Błąd urządzenia."
  ! has_mgmt_default || fail "Nadal management key fabryczny."
  echo "SECOND_YUBIKEY_MANAGEMENT_KEY_CHANGED=PASS"
fi
! has_pin_default && ! has_puk_default && ! has_mgmt_default || fail "PIV nadal ma fabryczne zabezpieczenia."
[[ "$(ykman list --serials)" == "$CURRENT_SERIAL" ]] || fail "Podłączony YubiKey został zamieniony."
INFO="$(ykman piv info 2>/dev/null)" || fail "Nie wykryto urządzenia."
[[ "$INFO" != *"Slot 82 (RETIRED1):"* ]] || fail "Slot 0x82 jest już zajęty."
echo "ETAP 4/4: generowanie niewyeksportowalnego klucza ECC P-256 w slocie PIV 0x82."
echo "Dostęp wymaga PIN-u; przy odszyfrowaniu trzeba będzie dotknąć klucza."
TEMP="$(mktemp "$DIR/.tmp-age-identity-XXXXXXXX")"
"$PLUGIN" --generate --slot 1 --name "Magazyn-V1-Spare-2026" \
  --pin-policy once --touch-policy always > "$TEMP" || fail "Generowanie identity nieudane."
[[ "$(grep -c '^AGE-PLUGIN-YUBIKEY-' "$TEMP" || true)" == 1 ]] || fail "Zły format identity."
SECOND="$( "$PLUGIN" --list 2>/dev/null | grep -E '^age1yubikey1[a-z0-9]+$' || true )"
[[ "$SECOND" == age1yubikey1* && "$SECOND" != "$FIRST" ]] || fail "Nowy recipient nieprawidłowy."
[[ "$(printf '%s\n' "$SECOND" | wc -l)" == 1 ]] || fail "Nieoczekiwana liczba recipientów."
mv -T -- "$TEMP" "$DIR/identity.txt"
TEMP=""
chmod 0600 "$DIR/identity.txt"
( set -C; printf '%s\n' "$SECOND" > "$DIR/recipient.txt" ) || fail "Zapis publicznego recipienta nieudany."
chmod 0600 "$DIR/recipient.txt"
echo "SECOND_YUBIKEY_INDEPENDENT_PIV_KEY=PASS"
echo "SECOND_YUBIKEY_PUBLIC_RECIPIENT_STORED=PASS"
echo "PRIMARY_YUBIKEY_AND_PRODUCTION_AES_UNCHANGED=PASS"
echo "Dane PIN/PUK ani AES nie zostały zapisane w tym skrypcie."
