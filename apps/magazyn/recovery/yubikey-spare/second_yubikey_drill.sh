#!/usr/bin/env bash
# Second YubiKey 5C: real production AES decrypt and restore drill in RAM.
# Run locally via SSH. The PIN never enters ChatGPT or command arguments.
set -Eeuo pipefail
set +x
umask 077

ROOT=/srv/ai-data/magazyn-v1
PIV_ID="$ROOT/private/yubikey-spare/identity.txt"
PIV_PUB="$ROOT/private/yubikey-spare/recipient.txt"
PIV_FIRST=/srv/ai-data/platform/recovery/stage-k/age-recipients.txt
APP="$ROOT/releases/529af02029e1/apps/magazyn"
PY="$ROOT/runtime/py314/bin/python"
AGE=/srv/ai-data/tools/age/usr/bin/age
PLUGIN=/srv/ai-data/tools/age/usr/bin/age-plugin-yubikey
LOCAL_AES="$ROOT/private/backup-keys/magazyn.key"
CIPHER=/mnt/AI_Platform/Magazyn/recovery/magazyn-v1-aes256-key-yubikey-spare.age
FIRST_CIPHER=/mnt/AI_Platform/Magazyn/recovery/magazyn-v1-aes256-key-yubikey.age
NAS=/mnt/AI_Platform
EVIDENCE="$ROOT/reports/yubikey-spare-real-drill-20261029.json"
MODE="$1"
TMP=""
fail(){ echo "SECOND_YUBIKEY_DRILL_BLOCKED: $*" >&2; exit 2; }
cleanup(){
  if [[ -n "$TMP" && "$TMP" == /dev/shm/magazyn-spare-drill-* && -d "$TMP" && ! -L "$TMP" ]]; then
    rm -rf -- "$TMP"
    echo "TEMPORARY_RAM_SECRETS_REMOVED=PASS"
  fi
}
trap cleanup EXIT
[[ "$MODE" == --check || "$MODE" == --run ]] || fail "Użyj --check albo --run"
[[ "$(id -un)" == harrypotter ]] || fail "Uruchom jako harrypotter, bez sudo."
[[ -x "$PY" && -x "$AGE" && -x "$PLUGIN" ]] || fail "Brak narzędzi."
[[ -f "$LOCAL_AES" && "$(stat -c %s "$LOCAL_AES")" == 32 && "$(stat -c %a "$LOCAL_AES")" == 600 ]] || fail "Błędny AES produkcyjny."
[[ -f "$PIV_ID" && -f "$PIV_PUB" && -f "$PIV_FIRST" ]] || fail "Brak plików drugiego klucza."
[[ "$(stat -c %a "$PIV_ID")" == 600 && "$(stat -c %a "$PIV_PUB")" == 600 ]] || fail "Brak prywatnych uprawnień tożsamości."
[[ "$(grep -c '^AGE-PLUGIN-YUBIKEY-' "$PIV_ID" || true)" == 1 ]] || fail "Niepoprawne identity."
SECOND="$(grep -E '^age1yubikey1[a-z0-9]+$' "$PIV_PUB" || true)"
FIRST="$(grep -E '^age1yubikey1[a-z0-9]+$' "$PIV_FIRST" | head -n 1 || true)"
[[ "$SECOND" == age1yubikey1* && "$FIRST" == age1yubikey1* && "$SECOND" != "$FIRST" ]] || fail "Niezależność kluczy niepotwierdzona."
[[ "$(ykman list --serials | wc -l)" == 1 ]] || fail "Podłącz dokładnie DRUGI YubiKey."
CURRENT="$("$PLUGIN" --list 2>/dev/null || true)"
grep -Fqx -- "$SECOND" <<< "$CURRENT" || fail "Wykryty YubiKey NIE odpowiada drugiemu recipientowi."
if grep -Fqx -- "$FIRST" <<< "$CURRENT"; then fail "Podłączony jest pierwszy YubiKey, przerwij."; fi
INFO="$(ykman piv info 2>/dev/null)" || fail "Brak PIV."
[[ "$INFO" == *"Slot 82 (RETIRED1):"* && "$INFO" == *ECCP256* ]] || fail "Nie ma oczekiwanego PIV ECC P-256 w 0x82."
[[ "$INFO" != *"Using default PIN"* && "$INFO" != *"Using default PUK"* && "$INFO" != *"Using default Management key"* ]] || fail "PIV ma nadal fabryczne zabezpieczenia."
TRIES="$(printf '%s\n' "$INFO" | sed -nE 's/^[[:space:]]*PIN tries remaining:[[:space:]]*([0-9]+)\/[0-9]+.*$/\1/p' | head -n 1)"
[[ "$TRIES" =~ ^[0-9]+$ && "$TRIES" -ge 2 ]] || fail "Za mało prób PIN, nie ryzykujemy."
[[ -f "$CIPHER" && ! -L "$CIPHER" && -f "$FIRST_CIPHER" && ! -L "$FIRST_CIPHER" ]] || fail "Brakuje dwóch zaszyfrowanych escrow."
[[ "$(findmnt -n -T /dev/shm -o FSTYPE | tail -n1)" == tmpfs ]] || fail "/dev/shm nie jest tmpfs."
export PYTHONPATH="$APP"
"$PY" - "$NAS" "$CIPHER" "$FIRST_CIPHER" "$LOCAL_AES" <<'PY'
import hashlib,sys
from pathlib import Path
from magazyn import backup
mount,spare,first,key=map(Path,sys.argv[1:])
root=backup._nas_target(mount)
assert spare.parent==root/"recovery"
assert spare.read_bytes().startswith(b"age-encryption.org/v1\n")
assert first.read_bytes().startswith(b"age-encryption.org/v1\n")
assert 120<=spare.stat().st_size<=4096
assert backup.read_key(key)
print("TWO_INDEPENDENT_CIPHERTEXT_FILES_ON_GLOBALNAS=PASS")
PY
ARCHIVE="$(find "$NAS/Magazyn/daily" -maxdepth 1 -type f -name '*.mgzb' -print | sort | tail -n1)"
[[ -n "$ARCHIVE" && -f "$ARCHIVE" && ! -L "$ARCHIVE" ]] || fail "Brak aktualnego backupu."
echo "SECOND_YUBIKEY_PIV_AND_NAS_PREFLIGHT=PASS"
echo "PIN_ATTEMPTS_REMAINING=$TRIES"
if [[ "$MODE" == --check ]]; then
  echo "NEXT=Uruchom --run we własnym interaktywnym terminalu SSH."
  exit 0
fi
[[ -t 0 && -t 1 && -c /dev/tty ]] || fail "PIN wprowadzaj wyłącznie w swoim terminalu SSH."
[[ ! -e "$EVIDENCE" ]] || fail "Test fizyczny ma już raport. Nie nadpisujemy."
TMP="$(mktemp -d /dev/shm/magazyn-spare-drill-XXXXXXXX)"
[[ "$(stat -c %a "$TMP")" == 700 ]] || fail "Katalog RAM nie jest prywatny."
RECOVERED="$TMP/recovered.key"
RESTORED="$TMP/restore.sqlite3"

export PATH="$(dirname "$PLUGIN"):$PATH"
echo "SECOND_YUBIKEY_PHYSICAL_DECRYPT=START"
echo "Wpisz PIN tylko tutaj; dotknij YubiKeya, gdy poprosi."
echo "Jeśli PIN będzie nieprawidłowy, NIE próbuj go wielokrotnie."
if ! "$AGE" --decrypt -i "$PIV_ID" -o "$RECOVERED" "$CIPHER"; then
  fail "Odszyfrowanie nieudane. Przerwano bez ponawiania PIN-u."
fi
echo "SECOND_YUBIKEY_PHYSICAL_DECRYPT=PASS"
"$PY" - "$RECOVERED" "$LOCAL_AES" "$ARCHIVE" "$RESTORED" "$EVIDENCE" "$PIV_PUB" "$PIV_FIRST" <<'PY'
import hashlib,hmac,json,os,sqlite3,sys
from pathlib import Path
from datetime import datetime,timezone
from magazyn import backup
recovered,original,archive,restored,evidence,second,first=map(Path,sys.argv[1:])
try:
    key=backup.read_key(recovered)
    real=backup.read_key(original)
    assert len(key)==32 and hmac.compare_digest(key,real)
    print("SECOND_YUBIKEY_RECOVERED_MASTER_AES_MATCH=PASS")
    result=backup.verify_archive(archive,recovered)
    assert result["status"]=="PASS"
    print("SECOND_YUBIKEY_REAL_NAS_ARCHIVE_VERIFY=PASS")
    result=backup.restore_archive(archive,restored,recovered)
    assert result["status"]=="PASS"
    con=sqlite3.connect("file:"+str(restored)+"?mode=ro",uri=True)
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert con.execute("PRAGMA foreign_key_check").fetchall()==[]
        assert con.execute("PRAGMA user_version").fetchone()[0]==3
        n=con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        assert n>=2
        for body,digest in con.execute("SELECT content,sha256 FROM item_documents"):
            assert hashlib.sha256(body).hexdigest()==digest
    finally:con.close()
    print("SECOND_YUBIKEY_REAL_NAS_RESTORE_IN_RAM=PASS")
    primary=first.read_text().strip()
    spare=second.read_text().strip()
    assert primary!=spare and spare.startswith("age1yubikey1")
    record={
        "event":"PHYSICAL_SECOND_YUBIKEY_RECOVERY_DRILL",
        "status":"PASS",
        "at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "primary_recipient_sha256":hashlib.sha256(primary.encode()).hexdigest(),
        "secondary_recipient_sha256":hashlib.sha256(spare.encode()).hexdigest(),
        "secondary_ciphertext_sha256":hashlib.sha256(Path("/mnt/AI_Platform/Magazyn/recovery/magazyn-v1-aes256-key-yubikey-spare.age").read_bytes()).hexdigest(),
        "source_archive_sha256":hashlib.sha256(archive.read_bytes()).hexdigest(),
        "checks":["recipient_distinct","piv_nondefault","physical_age_decrypt",
                  "master_aes_identical","nas_archive_verified","sqlite_restored_in_ram",
                  "document_hashes_valid"],
        "production_sqlite_modified":False
    }
    fd=os.open(evidence,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,"w") as out:
        json.dump(record,out,sort_keys=True,indent=2);out.write("\n")
    print("SECOND_YUBIKEY_DRILL_EVIDENCE_SAVED_PRIVATELY=PASS")
except Exception:
    print("SECOND_YUBIKEY_DRILL_VERIFICATION_FAILED",file=sys.stderr)
    raise SystemExit(3)
PY
echo "SECOND_YUBIKEY_REAL_PRODUCTION_RECOVERY_DRILL=PASS"
echo "PRODUCTION_DATABASE_AND_STAGE_K_PIV_UNCHANGED=PASS"
