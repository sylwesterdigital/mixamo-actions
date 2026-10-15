#!/bin/bash
# Mixamo Actions release watcher. Compatible with macOS Bash 3.2 and Zsh invocation.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATES="$ROOT/updates"
STATE="$UPDATES/.state"
LOCK="$STATE/watch.lock"
POLL_SECONDS="${MIXAMO_POLL_SECONDS:-5}"
RUN_ONCE=0
[[ "${1:-}" == '--once' ]] && RUN_ONCE=1
[[ "${1:-}" == '--status' ]] && { cat "$STATE/installed-version" 2>/dev/null || echo unversioned; exit 0; }
mkdir -p "$STATE" "$UPDATES"
# Explicit Zsh environment overrides the local config file. Environment values
# must be exported to the installer subprocess (e.g. MIXAMO_ALLOW_DIRTY_CORE).
OVERRIDE_AUTO_GIT_PUSH="${MIXAMO_AUTO_GIT_PUSH-}"
OVERRIDE_AUTO_DEPLOY="${MIXAMO_AUTO_DEPLOY-}"
OVERRIDE_POLL_SECONDS="${MIXAMO_POLL_SECONDS-}"
if [[ -f "$ROOT/mixamo-watch.env" ]]; then
  set -a
  source "$ROOT/mixamo-watch.env"
  set +a
fi
[[ -n "$OVERRIDE_AUTO_GIT_PUSH" ]] && export MIXAMO_AUTO_GIT_PUSH="$OVERRIDE_AUTO_GIT_PUSH"
[[ -n "$OVERRIDE_AUTO_DEPLOY" ]] && export MIXAMO_AUTO_DEPLOY="$OVERRIDE_AUTO_DEPLOY"
[[ -n "$OVERRIDE_POLL_SECONDS" ]] && export MIXAMO_POLL_SECONDS="$OVERRIDE_POLL_SECONDS"
AUTO_GIT_PUSH="${MIXAMO_AUTO_GIT_PUSH:-1}"
AUTO_DEPLOY="${MIXAMO_AUTO_DEPLOY:-1}"
POLL_SECONDS="${MIXAMO_POLL_SECONDS:-5}"
if ! mkdir "$LOCK" 2>/dev/null; then
  old_pid="$(cat "$LOCK/pid" 2>/dev/null || true)"
  if [[ "$old_pid" =~ ^[0-9]+$ ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Watcher already running (PID $old_pid)."; exit 1
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK" 2>/dev/null || { echo "Watcher lock occupied: $LOCK"; exit 1; }
  mkdir "$LOCK" || exit 1
fi
printf '%s\n' "$$" > "$LOCK/pid"
cleanup() { if [[ "$(cat "$LOCK/pid" 2>/dev/null || true)" == "$$" ]]; then rm -f "$LOCK/pid";rmdir "$LOCK" 2>/dev/null || true;fi; }
trap cleanup EXIT
trap 'exit 0' INT TERM

latest_release() {
  python3 - "$UPDATES" <<'PY'
import pathlib,re,sys
root=pathlib.Path(sys.argv[1]); matches=[]
for p in root.glob('mixamo-actions-v*.zip'):
    m=re.fullmatch(r'mixamo-actions-v(\d+)\.(\d+)\.(\d+)\.zip',p.name)
    if m: matches.append((tuple(map(int,m.groups())),p))
print(max(matches,key=lambda a:a[0])[1] if matches else '')
PY
}
checksum() { shasum -a 256 "$1" | awk '{print $1}'; }

publish_git() {
  # Stage ONLY manifest-verified release files, never unrelated local work.
  if ! git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1;then echo 'ERROR: Not a Git repository';return 1;fi
  if [[ "$(git -C "$ROOT" branch --show-current)" != main ]];then
    echo 'ERROR: Not on main; refusing automatic GitHub push.';return 1
  fi
  if ! git -C "$ROOT" diff --cached --quiet;then
    echo 'ERROR: Git index contains staged changes; refusing to mix them into the release.';return 1
  fi
  if ! git -C "$ROOT" remote get-url origin >/dev/null 2>&1;then
    echo 'ERROR: Git origin is missing.';return 1
  fi
  local version
  version="$(cat "$ROOT/VERSION")"
  local release_listing
  if ! release_listing="$(python3 - "$ROOT/release.json" "$ROOT" <<'PYRELEASE'
import hashlib,json,pathlib,sys
meta=json.loads(pathlib.Path(sys.argv[1]).read_text())
root=pathlib.Path(sys.argv[2])
if meta.get('version') != (root/'VERSION').read_text().strip():
    raise SystemExit('Release version and manifest disagree')
for name,sha in sorted(meta['files'].items()):
    file=root/name
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=sha:
        raise SystemExit('Release source modified or missing: '+name)
    print(name)
print('release.json')
PYRELEASE
  )";then
    echo 'ERROR: Installed files no longer match release.json; Git publish canceled.'
    return 1
  fi
  local -a release_files=()
  while IFS= read -r file;do
    [[ -n "$file" ]] && release_files+=("$file")
  done <<< "$release_listing"
  [[ ${#release_files[@]} -gt 1 ]] || return 1
  git -C "$ROOT" add -- "${release_files[@]}" || return 1
  if ! git -C "$ROOT" diff --cached --quiet;then
    git -C "$ROOT" commit -m "release: mixamo-actions v$version" || return 1
  fi
  git -C "$ROOT" push origin main || return 1
  if git -C "$ROOT" rev-parse -q --verify "refs/tags/v$version" >/dev/null;then
    local target current
    target="$(git -C "$ROOT" rev-list -n 1 "v$version")"
    current="$(git -C "$ROOT" rev-parse HEAD)"
    if [[ "$target" != "$current" ]];then
      echo "ERROR: existing tag v$version points to a different commit.";return 1
    fi
  else
    git -C "$ROOT" tag "v$version" || return 1
  fi
  git -C "$ROOT" push origin "v$version" || return 1
  echo "Git commit and v$version tag published."
}

publish_site() {
  if [[ -z "${MIXAMO_DEPLOY_TARGET:-}" ]];then
    echo 'ERROR: MIXAMO_DEPLOY_TARGET is empty; homepage is NOT published.'
    return 1
  fi
  "$ROOT/ops/deploy-homepage.sh" || return 1
}

echo "Mixamo Studio watcher: $ROOT"
echo "Watching: $UPDATES/mixamo-actions-vMAJOR.MINOR.PATCH.zip"
echo "Install target: $ROOT/core"
echo "Git: $AUTO_GIT_PUSH | Homepage deploy: $AUTO_DEPLOY"
PUBLISH_FAILURE=0
while true; do
  package="$(latest_release)"
  if [[ -n "$package" && -f "$package" ]];then
    first="$(stat -f '%z:%m' "$package" 2>/dev/null || stat -c '%s:%Y' "$package" 2>/dev/null || true)"
    sleep 3
    second="$(stat -f '%z:%m' "$package" 2>/dev/null || stat -c '%s:%Y' "$package" 2>/dev/null || true)"
    if [[ -n "$first" && "$first" == "$second" ]];then
      sha="$(checksum "$package")"
      installed_sha="$(cat "$STATE/last-successful-sha" 2>/dev/null || true)"
      if [[ "$sha" != "$installed_sha" ]];then
        echo "Installing $(basename "$package")"
        if [[ -f "$ROOT/ops/install_release.py" ]] && python3 "$ROOT/ops/install_release.py" "$package" --repo "$ROOT";then
          printf '%s\n' "$sha" > "$STATE/last-successful-sha"
          rm -f "$STATE/published-git-sha" "$STATE/published-site-sha"
        else
          echo 'ERROR: Update failed or postponed. Will retry after interval.'
          [[ "$RUN_ONCE" == 1 ]] && exit 1
          sleep 20
        fi
      fi
      if [[ "$(cat "$STATE/last-successful-sha" 2>/dev/null || true)" == "$sha" ]];then
        now_epoch="$(date +%s)"
        last_retry="$(cat "$STATE/last-publish-at" 2>/dev/null || echo 0)"
        if [[ "$RUN_ONCE" != 1 && "$last_retry" =~ ^[0-9]+$ ]] && (( now_epoch - last_retry < 60 )); then
          [[ "$RUN_ONCE" == 1 ]] && break
          sleep "$POLL_SECONDS"
          continue
        fi
        # Disabled publishing is not a successful publish. Leave its marker
        # absent so enabling it later publishes the already installed release.
        if [[ "$AUTO_GIT_PUSH" == 1 && "$(cat "$STATE/published-git-sha" 2>/dev/null || true)" != "$sha" ]];then
          printf '%s\n' "$now_epoch" > "$STATE/last-publish-at"
          if publish_git;then printf '%s\n' "$sha" > "$STATE/published-git-sha";else
            PUBLISH_FAILURE=1
            echo 'WARNING: Git publish failed. Installed app remains healthy; will retry.';fi
        fi
        if [[ "$AUTO_DEPLOY" == 1 && "$(cat "$STATE/published-site-sha" 2>/dev/null || true)" != "$sha" ]];then
          printf '%s\n' "$now_epoch" > "$STATE/last-publish-at"
          if publish_site;then printf '%s\n' "$sha" > "$STATE/published-site-sha";else
            PUBLISH_FAILURE=1
            echo 'WARNING: Homepage deploy failed; will retry without reinstalling.';fi
        fi
      fi
    fi
  fi
  [[ "$RUN_ONCE" == 1 ]] && break
  sleep "$POLL_SECONDS"
done
if [[ "$RUN_ONCE" == 1 && "$PUBLISH_FAILURE" != 0 ]]; then
  echo 'ERROR: Local install may be successful, but one or more remote publications failed.'
  exit 1
fi
