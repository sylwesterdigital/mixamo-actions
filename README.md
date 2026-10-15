# Mixamo Actions · Studio

Local Mixamo / Playwright / Blender animation pipeline with one combined GLB, Three.js motion preview and named motion presets.

## Repository layout

| Path | Responsibility |
|---|---|
| `core/` | Flask UI, Mixamo browser automation, Blender processing, Three.js studio |
| `updates/mixamo-actions-vX.Y.Z.zip` | Versioned full source release packages |
| `mixamo-studio-watch.sh` | macOS/Zsh-compatible Bash watcher + release supervisor |
| `ops/install_release.py` | Manifest verifier, guarded installer, backup, tests, health checks, rollback |
| `ops/build_release.py` | Builder for complete versioned ZIP with SHA-256 hashes |
| `ops/deploy-homepage.sh` | SSH/rsync publisher for *static files only* |
| `site/` | Public WORKWORK.FUN project homepage |
| `updates-log.md` | Release notes and version history |

## Repository-only update workflow (macOS Zsh)

The watcher **always runs from this repository**, not from `~/Downloads`. The path is derived from the location of `mixamo-studio-watch.sh` and is not affected by the current shell directory.

```text
/Users/smielniczuk/Documents/works/mixamo-actions/
├── mixamo-studio-watch.sh         # start this watcher from the repo root
├── updates/
│   ├── mixamo-actions-v1.1.1.zip # all new release ZIPs go HERE
│   ├── .backups/                 # automatic rollback snapshots
│   └── .state/                   # PID, service log, installed version
├── core/                         # running Flask + Playwright + Blender application
├── site/                         # WORKWORK.FUN public homepage
└── updates-log.md
```

Save the downloaded `mixamo-actions-v1.1.1.zip` **directly into the repository's `updates/` folder**, using your browser's Save As destination. No `cp ~/Downloads/...` step is needed.

For systems where the **v1.0.0 update failed** (its old tests and installer are still present), apply the updater fix once from the already-saved versioned release ZIP. Then start the normal watcher:

```zsh
cd /Users/smielniczuk/Documents/works/mixamo-actions
unzip -o updates/mixamo-actions-v1.1.1.zip ops/install_release.py mixamo-studio-watch.sh
chmod +x mixamo-studio-watch.sh
./mixamo-studio-watch.sh --once
./mixamo-studio-watch.sh
```

The updater verifies manifest hashes, tests the code, installs dependencies in `core/.venv`, backs up overwritten files, and restarts the managed Flask app on port 5055. It preserves local browser profiles, credentials, uploads, exported GLBs, and the Git directory.

**If the installer reports an unmanaged process on port 5055**, it will not overwrite code or stop that process. Inspect the listener:

```zsh
lsof -nP -iTCP:5055 -sTCP:LISTEN
ps -p PID -o command=   # replace PID with the actual listener PID
```

Stop only the old instance after verifying its command and retry `./mixamo-studio-watch.sh --once`. The permanent watcher automatically notices later higher-version ZIPs in `updates/`.

Open the local Studio at http://127.0.0.1:5055. The browser tab reports new versions after its local server restarts.

## Configuration

```zsh
cp mixamo-watch.env.example mixamo-watch.env
```

This sets `MIXAMO_DEPLOY_TARGET=root@mail`. Ensure your SSH keys allow access and `root@mail` is reachable. Repository push uses the *existing* `origin` remote, `main` branch, and your local Git credentials; no password or token is placed in source.

**Continuous watcher with GitHub publishing enabled (from the repo root):**

```zsh
cd /Users/smielniczuk/Documents/works/mixamo-actions
./mixamo-studio-watch.sh
```

`--once` is a deliberate single pass and exits. `MIXAMO_AUTO_GIT_PUSH=0` and
`MIXAMO_AUTO_DEPLOY=0` intentionally disable publishing; do not use these for
normal automatic operation. The watcher reads `mixamo-watch.env` (which should
remain ignored by Git). Git push needs a working `origin`, branch `main`, and
Git credentials. Homepage deployment also needs SSH access to the configured
`MIXAMO_DEPLOY_TARGET`; failed publishing is retried without reinstalling.

To disable remote actions on a particular run:

```zsh
MIXAMO_AUTO_GIT_PUSH=0 MIXAMO_AUTO_DEPLOY=0 ./mixamo-studio-watch.sh --once
```

## Version bump for future updates

For the *next* release, increment `VERSION` (e.g. `1.0.3`) and add its notes to `updates-log.md`, then run:

```zsh
python3 ops/build_release.py
```

The builder writes the ZIP directly into this repository’s `updates/` directory; the running watcher detects it. The watcher rejects same/older versions by default.

## Deploy the homepage

The static homepage lives in `site/`; by default the deploy script publishes into `/var/www/mojoworks/labs/mixamo-actions` over SSH:

```zsh
./ops/deploy-homepage.sh --dry-run
./ops/deploy-homepage.sh
```

An existing Nginx server block must map the website URL to that directory; see `ops/nginx-location.example.conf`. The site does **not** expose Flask, Playwright, Adobe login sessions or character uploads to the Internet.

## Health and test commands

```zsh
python3 ops/install_release.py updates/mixamo-actions-v1.1.1.zip --repo . --verify-only
curl -fsS http://127.0.0.1:5055/api/release
cd core && .venv/bin/python -m unittest discover -s tests -v
```

## Security

The local control panel listens on `127.0.0.1` and requires a token for mutating calls. Do not expose the Flask app or Brave CDP port `9222` on the public Ubuntu host. Do not put browser profiles, session cookies, large models, `.venv`, `.env`, or private keys into release archives. The updater rejects directory traversal, symlinks and corrupt manifests; it does not execute arbitrary shell hooks from ZIPs.

## Release publication recovery

The watcher records **installation**, **Git publication**, and **homepage publication** separately under `updates/.state/`. A failed Git push or remote deploy never changes the successful installation marker. The persistent watcher retries pending publication without reinstalling the app (with a short retry cooldown). Run `./mixamo-studio-watch.sh --once` to attempt a single immediate publish cycle.

Git requires `origin`, `main`, and your configured user identity. The watcher stages only files listed by `release.json` and checks their SHA-256 hashes. The homepage requires `MIXAMO_DEPLOY_TARGET` and an existing SSH/rsync connection; the optional Nginx route must be configured on Ubuntu. No push or remote deploy occurs unless the corresponding settings are enabled.

## Model Library (v1.1.0)

The bottom dock in the Flask Studio can collapse into a 36px header. Every successful
combined GLB pipeline export is added to the library. Click a card to load its GLB;
the stage captures a WebP preview automatically. Cards offer **Download** and
**Remove from Library**. Choose **Open GLB → Save** to import an existing GLB.

Library records and thumbnails are persisted outside the source checkout in
`~/MixamoLocal/library/` by default, or under `$MIXAMO_FLASK_WORKSPACE/library/`.
A removal only deletes a generated model's library entry and snapshot; its original
`*-exports/glb/*-anims.glb` file remains intact. Removing a manually imported
library GLB deletes only the managed library copy, not the file it came from.
Models built before this release can be added using Open GLB and Save.

## Local README edits during updates (v1.1.1)

The repository is release-managed. If a tracked README or other release file was locally
modified but **not staged**, the watcher installs the verified release after saving the
original bytes under `updates/.backups/before-v<version>-<timestamp>/`. See the matching
`local-edits.json` for preserved paths. These edits are not auto-merged into new code.
Git-staged changes to release files still require a manual commit/unstage first.

For first upgrade from v1.1.0, stop the old watcher, save this package to `updates/`,
bootstrap the updated installer using `unzip -o updates/mixamo-actions-v1.1.1.zip ops/install_release.py`,
and restart the watcher from the repository root.
