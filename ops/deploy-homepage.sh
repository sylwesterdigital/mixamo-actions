#!/bin/bash
# Deploy the public STATIC project homepage only, never the local Flask/Brave app.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "$ROOT/mixamo-watch.env" ]] && source "$ROOT/mixamo-watch.env"
TARGET="${MIXAMO_DEPLOY_TARGET:-}"
PORT="${MIXAMO_DEPLOY_PORT:-22}"
REMOTE_DIR="/var/www/mojoworks/labs/mixamo-actions"
[[ -n "$TARGET" && "$TARGET" =~ ^[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+$ ]] || {
  echo 'Configure MIXAMO_DEPLOY_TARGET=user@hostname in mixamo-watch.env' >&2;exit 2;
}
[[ "$PORT" =~ ^[0-9]+$ ]] || exit 2
[[ -f "$ROOT/site/index.html" && -f "$ROOT/site/release.json" ]] || { echo 'Missing homepage assets';exit 2; }
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=12 -p "$PORT")
RSYNC_SSH="ssh -o BatchMode=yes -o ConnectTimeout=12 -p $PORT"
if [[ "${1:-}" == '--dry-run' ]];then
  echo "DRY RUN: ${TARGET}:${REMOTE_DIR}/ (SSH port $PORT)"
  RSYNC_RSH="$RSYNC_SSH" rsync -azn --itemize-changes "$ROOT/site/" "$TARGET:$REMOTE_DIR/"
  exit 0
fi
"${SSH[@]}" "$TARGET" "mkdir -p '$REMOTE_DIR' && test -w '$REMOTE_DIR'"
# No --delete: preserve pre-existing operator-owned files in the target.
RSYNC_RSH="$RSYNC_SSH" rsync -az --checksum "$ROOT/site/" "$TARGET:$REMOTE_DIR/"
echo "Homepage files deployed to $TARGET:$REMOTE_DIR/"
echo 'Nginx/HTTPS still require a one-time site configuration; this script does not alter nginx or services.'
