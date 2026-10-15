#!/bin/bash
# Upload only the Mixamo static landing page to its existing dedicated directory.
# This script must not configure nginx, HTTPS, services, ownership, or permissions.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Explicit shell environment wins over private local configuration.
SHELL_TARGET="${MIXAMO_DEPLOY_TARGET-}"
SHELL_PORT="${MIXAMO_DEPLOY_PORT-}"
[[ -f "$ROOT/mixamo-watch.env" ]] && source "$ROOT/mixamo-watch.env"
[[ -n "$SHELL_TARGET" ]] && MIXAMO_DEPLOY_TARGET="$SHELL_TARGET"
[[ -n "$SHELL_PORT" ]] && MIXAMO_DEPLOY_PORT="$SHELL_PORT"
TARGET="${MIXAMO_DEPLOY_TARGET:-root@yolo.cx}"
PORT="${MIXAMO_DEPLOY_PORT:-18021}"
REMOTE_DIR='/var/www/mojoworks/labs/mixamo-actions'

# Legacy placeholder accidentally shipped before 1.1.3. Do not change
# any operator-specified endpoint except this exact known-bad pair.
if [[ "$TARGET" == 'root@mail' && "$PORT" == '22' ]]; then
  echo 'INFO: replacing legacy root@mail:22 default with root@yolo.cx:18021' >&2
  TARGET='root@yolo.cx'
  PORT='18021'
fi
[[ "$TARGET" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$ ]] || {
  echo 'ERROR: Invalid MIXAMO_DEPLOY_TARGET (expected user@hostname).' >&2; exit 2;
}
[[ "$PORT" =~ ^[0-9]+$ ]] && (( 10#$PORT >= 1 && 10#$PORT <= 65535 )) || {
  echo 'ERROR: Invalid MIXAMO_DEPLOY_PORT.' >&2; exit 2;
}

# Fixed, explicit allowlist. No .htaccess, application code, models,
# environment files, uploaded files or arbitrary extra files from site/.
ASSETS=(index.html styles.css release.js release.json favicon.svg)
for asset in "${ASSETS[@]}"; do
  [[ -f "$ROOT/site/$asset" && ! -L "$ROOT/site/$asset" ]] || {
    echo "ERROR: Missing or unsafe local static asset: site/$asset" >&2; exit 2;
  }
done

if [[ "${1:-}" == '--show-target' ]]; then
  printf '%s\n' "SSH target: $TARGET" "SSH port: $PORT" "Remote path: $REMOTE_DIR"
  exit 0
fi
[[ $# -eq 0 || ( $# -eq 1 && "$1" == '--dry-run' ) ]] || {
  echo 'Usage: deploy-homepage.sh [--show-target|--dry-run]' >&2; exit 2;
}

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=12 -p "$PORT")
RSYNC_SSH="ssh -o BatchMode=yes -o ConnectTimeout=12 -p $PORT"
# Recursive transfer is scoped to these five plain files only. No -a, so
# this cannot change remote ownership, permissions or group metadata.
RSYNC_OPTS=(-rz --checksum
  --include='/index.html'
  --include='/styles.css'
  --include='/release.js'
  --include='/release.json'
  --include='/favicon.svg'
  --exclude='*')
if [[ "${1:-}" == '--dry-run' ]]; then
  echo "DRY RUN: $TARGET:$REMOTE_DIR/ (SSH port $PORT)"
  RSYNC_RSH="$RSYNC_SSH" rsync -n --itemize-changes "${RSYNC_OPTS[@]}" "$ROOT/site/" "$TARGET:$REMOTE_DIR/"
  exit 0
fi

# Fail closed if the dedicated directory is missing, resolves somewhere else,
# or if a deployed file is a symlink. Never create, delete or reconfigure
# anything remotely. No other server directories are accessed.
REMOTE_CHECK="
  set -eu
  d='$REMOTE_DIR'
  if [ ! -d \"\$d\" ] || [ -L \"\$d\" ]; then
    echo 'ERROR: Dedicated Mixamo homepage directory must already exist and must not be a symlink.' >&2
    exit 2
  fi
  actual=\$(cd \"\$d\" && pwd -P) || exit 2
  if [ \"\$actual\" != \"\$d\" ]; then
    echo 'ERROR: Mixamo homepage path resolves outside its dedicated directory.' >&2
    exit 2
  fi
  for f in index.html styles.css release.js release.json favicon.svg; do
    if [ -L \"\$d/\$f\" ]; then
      echo 'ERROR: Refusing to replace a symlinked homepage asset.' >&2
      exit 2
    fi
  done
  test -w \"\$d\" || { echo 'ERROR: Dedicated directory is not writable.' >&2; exit 2; }
"
"${SSH[@]}" "$TARGET" "$REMOTE_CHECK"
RSYNC_RSH="$RSYNC_SSH" rsync "${RSYNC_OPTS[@]}" "$ROOT/site/" "$TARGET:$REMOTE_DIR/"
echo "Homepage files deployed to $TARGET:$REMOTE_DIR/"
