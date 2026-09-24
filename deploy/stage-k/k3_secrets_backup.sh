#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_ROOT="${1:-/mnt/AI_Platform}"
TIER="${2:-manual}"
AGE_BIN="/srv/ai-data/tools/age/usr/bin/age"
RECIPIENTS="/srv/ai-data/platform/recovery/stage-k/age-recipients.txt"
EXPECTED_RECIPIENT_FINGERPRINT="SHA256:BVPwRUzB0IbP/6QVNsy9/XbIxs8MxHxbvFJ6soFNUPM"
MARKER="$TARGET_ROOT/.ai-platform-backup-target.json"

fail() {
  echo "STAGE_K_K3_SECRETS_FAIL=$*" >&2
  exit 1
}

[[ $EUID -eq 0 ]] || fail "run with sudo"
[[ "$TIER" =~ ^(daily|weekly|manual)$ ]] || fail "invalid tier"
[[ -d "$TARGET_ROOT" ]] || fail "target root missing"
[[ "$(basename "$TARGET_ROOT")" == "AI_Platform" ]] || fail "target root must be AI_Platform"
[[ "$(findmnt -T "$TARGET_ROOT" -n -o FSTYPE)" == "cifs" ]] || fail "target is not CIFS"
[[ -f "$MARKER" ]] || fail "Stage K target marker missing"
[[ -x "$AGE_BIN" ]] || fail "age binary missing"
[[ -s "$RECIPIENTS" ]] || fail "age recipients missing"
ACTUAL_RECIPIENT_FINGERPRINT="$(ssh-keygen -lf "$RECIPIENTS" | awk '{print $2}')"
[[ "$ACTUAL_RECIPIENT_FINGERPRINT" == "$EXPECTED_RECIPIENT_FINGERPRINT" ]] \
  || fail "age recipient fingerprint mismatch"

python3 - "$MARKER" <<'PY'
import json, sys
d=json.load(open(sys.argv[1]))
assert d.get("purpose")=="ai-platform-stage-k"
assert d.get("nas")=="GlobalNAS"
assert d.get("share")=="AI_Platform"
PY

mapfile -t SOURCES <<'EOF'
etc/ai-bridge/ai-bridge.env
etc/ai-gateway/ai-gateway.env
srv/ai-data/hermes/.env
srv/ai-data/hermes/auth.json
etc/ai-platform/stage-k/globalnas.credentials
EOF

for rel in "${SOURCES[@]}"; do
  [[ -f "/$rel" ]] || fail "required secret missing: /$rel"
done

if [[ -d /srv/ai-data/hermes/pairing ]]; then
  SOURCES+=("srv/ai-data/hermes/pairing")
fi

BACKUP_ID="$(date -u +%Y%m%dT%H%M%SZ)"
STAGING="$TARGET_ROOT/.incomplete/k3-secrets-$BACKUP_ID.$$"
FINAL="$TARGET_ROOT/Platform/secrets/$TIER/$BACKUP_ID"
BUNDLE="$STAGING/secrets.tar.gz.age"
mkdir -p "$STAGING"
chmod 0700 "$STAGING"
[[ ! -e "$FINAL" ]] || fail "backup ID collision"
umask 077
echo "Encrypting secrets directly to age bundle..."
tar --numeric-owner -C / -czf - "${SOURCES[@]}" |   "$AGE_BIN" -R "$RECIPIENTS" -o "$BUNDLE"

[[ -s "$BUNDLE" ]] || fail "encrypted bundle is empty"
[[ "$(head -1 "$BUNDLE")" == "age-encryption.org/v1" ]] || fail "invalid age bundle header"

cp "$RECIPIENTS" "$STAGING/recipients.txt"
chmod 0600 "$STAGING/recipients.txt"

export STAGE_K_SECRET_BACKUP_ID="$BACKUP_ID"
export STAGE_K_SECRET_TIER="$TIER"
export STAGE_K_SECRET_BUNDLE="$BUNDLE"
export STAGE_K_SECRET_RECIPIENTS="$RECIPIENTS"
export STAGE_K_SECRET_STAGING="$STAGING"
python3 - <<'PY'
import hashlib, json, os, pathlib, stat, subprocess
backup_id=os.environ["STAGE_K_SECRET_BACKUP_ID"]
tier=os.environ["STAGE_K_SECRET_TIER"]
bundle=pathlib.Path(os.environ["STAGE_K_SECRET_BUNDLE"])
recipients=pathlib.Path(os.environ["STAGE_K_SECRET_RECIPIENTS"])
staging=pathlib.Path(os.environ["STAGE_K_SECRET_STAGING"])
sources=[
    pathlib.Path("/etc/ai-bridge/ai-bridge.env"),
    pathlib.Path("/etc/ai-gateway/ai-gateway.env"),
    pathlib.Path("/srv/ai-data/hermes/.env"),
    pathlib.Path("/srv/ai-data/hermes/auth.json"),
    pathlib.Path("/etc/ai-platform/stage-k/globalnas.credentials"),
]
pairing=pathlib.Path("/srv/ai-data/hermes/pairing")
if pairing.is_dir():
    sources.append(pairing)

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()

fp=subprocess.check_output(
    ["ssh-keygen","-lf",str(recipients)], text=True
).strip()
entries=[]
for p in sources:
    st=p.stat()
    entries.append({
        "path": str(p),
        "type": "directory" if p.is_dir() else "file",
        "bytes": st.st_size if p.is_file() else None,
        "mode": oct(stat.S_IMODE(st.st_mode)),
    })
manifest={
    "manifest_schema_version": 1,
    "status": "COMPLETE",
    "domain": "PlatformSecrets",
    "backup_id": backup_id,
    "tier": tier,
    "encryption": {
        "format": "age",
        "recipient_type": "ssh-ed25519",
        "recipient_fingerprint": fp,
        "private_key_stored_on_ai_server": False,
        "private_key_stored_on_nas": False,
    },
    "bundle": {
        "path": "secrets.tar.gz.age",
        "bytes": bundle.stat().st_size,
        "sha256": sha256(bundle),
    },
    "sources": entries,
    "plaintext_written_to_nas": False,
    "plaintext_temp_bundle_created": False,
}
text=json.dumps(manifest,indent=2,sort_keys=True)+"\n"
mp=staging/"manifest.json"
mp.write_text(text)
os.chmod(mp,0o600)
(staging/"manifest.sha256").write_text(
    sha256(mp)+"  manifest.json\n"
)
os.chmod(staging/"manifest.sha256",0o600)
(staging/"COMPLETE").write_text(backup_id+"\n")
os.chmod(staging/"COMPLETE",0o600)
PY
mkdir -p "$(dirname "$FINAL")"
mv "$STAGING" "$FINAL"

echo "STAGE_K_K3_SECRETS_PASS=1"
echo "BACKUP_ID=$BACKUP_ID"
echo "BUNDLE=$FINAL/secrets.tar.gz.age"
echo "MANIFEST=$FINAL/manifest.json"
