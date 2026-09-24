#!/usr/bin/env bash
set -Eeuo pipefail

NAS_HOST="globalnas.local"
SHARE="AI_Platform"
SMB_USER="ai_backup"
MOUNTPOINT="/mnt/AI_Platform"
CONFIG_DIR="/etc/ai-platform/stage-k"
CREDENTIALS="$CONFIG_DIR/globalnas.credentials"
MARKER="$MOUNTPOINT/.ai-platform-backup-target.json"
FSTAB="/etc/fstab"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FSTAB_BACKUP="/etc/fstab.stage-k-pre-globalnas-$STAMP"
MOUNTED_BY_SCRIPT=0
FSTAB_CHANGED=0
CREDENTIALS_CREATED=0
TMP_CRED=""

fail() {
  echo "STAGE_K_GLOBALNAS_FAIL=$*" >&2
  exit 1
}

rollback() {
  rc=$?
  if (( rc == 0 )); then
    return
  fi
  echo "Stage K GlobalNAS setup failed; applying rollback..." >&2
  if (( FSTAB_CHANGED == 1 )) && [[ -f "$FSTAB_BACKUP" ]]; then
    cp -a "$FSTAB_BACKUP" "$FSTAB"
    systemctl daemon-reload || true
  fi
  if (( MOUNTED_BY_SCRIPT == 1 )) && mountpoint -q "$MOUNTPOINT"; then
    umount "$MOUNTPOINT" || true
  fi
  if [[ -n "$TMP_CRED" && -e "$TMP_CRED" ]]; then
    rm -f "$TMP_CRED"
  fi
  if (( CREDENTIALS_CREATED == 1 )); then
    rm -f "$CREDENTIALS"
  fi
}
trap rollback EXIT

[[ $EUID -eq 0 ]] || fail "run with sudo"
getent hosts "$NAS_HOST" >/dev/null || fail "GlobalNAS DNS resolution failed"

if ! command -v mount.cifs >/dev/null 2>&1; then
  echo "Installing cifs-utils..."
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y cifs-utils
fi

install -d -m 0700 "$CONFIG_DIR"
install -d -m 0755 "$MOUNTPOINT"

if mountpoint -q "$MOUNTPOINT"; then
  current_source="$(findmnt -T "$MOUNTPOINT" -n -o SOURCE)"
  current_type="$(findmnt -T "$MOUNTPOINT" -n -o FSTYPE)"
  [[ "$current_source" == "//$NAS_HOST/$SHARE" && "$current_type" == "cifs" ]] \
    || fail "mountpoint already used by unexpected source: $current_source ($current_type)"
  echo "GlobalNAS share already mounted correctly."
else
  TMP_CRED="$CONFIG_DIR/.globalnas.credentials.$$"
  umask 077
  read -r -s -p "SMB password for $SMB_USER@GlobalNAS: " SMB_PASSWORD
  echo
  [[ -n "$SMB_PASSWORD" ]] || fail "empty SMB password"
  printf 'username=%s\npassword=%s\n' "$SMB_USER" "$SMB_PASSWORD" > "$TMP_CRED"
  unset SMB_PASSWORD
  chmod 0600 "$TMP_CRED"

  echo "Testing SMB 3.1.1 mount..."
  mount -t cifs "//$NAS_HOST/$SHARE" "$MOUNTPOINT" \
    -o "credentials=$TMP_CRED,vers=3.1.1,iocharset=utf8,uid=1000,gid=1000,file_mode=0600,dir_mode=0700,noserverino,_netdev"
  MOUNTED_BY_SCRIPT=1

  install -m 0600 -o root -g root "$TMP_CRED" "$CREDENTIALS"
  CREDENTIALS_CREATED=1
  rm -f "$TMP_CRED"
  TMP_CRED=""
fi

[[ "$(findmnt -T "$MOUNTPOINT" -n -o FSTYPE)" == "cifs" ]] \
  || fail "mounted target is not CIFS"

probe="$MOUNTPOINT/.stage-k-probe-$$"
payload="stage-k-$STAMP-$RANDOM-$RANDOM"
printf '%s' "$payload" > "$probe"
sync "$probe" 2>/dev/null || sync
[[ "$(cat "$probe")" == "$payload" ]] || fail "SMB write/read probe mismatch"
rm -f "$probe"

cat > "$MARKER" <<EOF_MARKER
{
  "schema_version": 1,
  "purpose": "ai-platform-stage-k",
  "nas": "GlobalNAS",
  "host": "$NAS_HOST",
  "share": "$SHARE"
}
EOF_MARKER
chmod 0600 "$MARKER"

if ! grep -Fq "//$NAS_HOST/$SHARE $MOUNTPOINT cifs " "$FSTAB"; then
  cp -a "$FSTAB" "$FSTAB_BACKUP"
  FSTAB_LINE="//$NAS_HOST/$SHARE $MOUNTPOINT cifs credentials=$CREDENTIALS,vers=3.1.1,iocharset=utf8,uid=1000,gid=1000,file_mode=0600,dir_mode=0700,noserverino,_netdev,nofail,x-systemd.automount,x-systemd.idle-timeout=600,x-systemd.device-timeout=10 0 0"
  printf '\n# AI Platform Stage K - GlobalNAS\n%s\n' "$FSTAB_LINE" >> "$FSTAB"
  FSTAB_CHANGED=1
  systemctl daemon-reload
fi

umount "$MOUNTPOINT"
MOUNTED_BY_SCRIPT=0
mount "$MOUNTPOINT"
MOUNTED_BY_SCRIPT=1

[[ "$(findmnt -T "$MOUNTPOINT" -n -o SOURCE)" == "//$NAS_HOST/$SHARE" ]] \
  || fail "persistent mount source mismatch"
[[ "$(findmnt -T "$MOUNTPOINT" -n -o FSTYPE)" == "cifs" ]] \
  || fail "persistent mount type mismatch"
[[ -f "$MARKER" ]] || fail "Stage K target marker missing after remount"

echo "STAGE_K_GLOBALNAS_PASS=1"
echo "MOUNTPOINT=$MOUNTPOINT"
echo "SOURCE=//$NAS_HOST/$SHARE"
echo "CREDENTIALS=$CREDENTIALS"
echo "FSTAB_BACKUP=$FSTAB_BACKUP"
trap - EXIT
