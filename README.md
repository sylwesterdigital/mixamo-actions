# Mixamo Actions · Studio

Local Mixamo / Playwright / Blender animation pipeline with one combined GLB, Three.js motion preview and named motion presets.

## Motion list collector (manual Mixamo tab)

The collector is `core/mixamo_motion_collector.js` (also served as a downloadable script
by `http://127.0.0.1:5055/collector.js`, and linked **Collector ↗** in Studio).
Open the authenticated Mixamo **Animations** tab in Brave, open DevTools → Console,
and paste the contents of this script. The draggable collector records selected motions
with exact motion IDs and exports `animations.json`. Import this JSON using Studio's
**Animation collection → Import JSON**, or use a saved preset. The downloader uses the
resulting list. **The pipeline does not automatically inject the collector** into its
Playwright-controlled tab; collect motions manually outside a running download job.

## Create or extend animation collections (v1.3.2)

**Directly in Studio:** Animation collection → **+ New collection**. Enter a
name, add each action with a Mixamo search term, title/description and optional
exact numeric `motionId`, then **Save collection**. To add actions to an
existing collection, select it in the preset library and click **Edit selected**.
The editor uses an optimistic SHA-256 check before replacing a saved collection.
You can also import exported `animations.json` as before.

**From the actual Mixamo results:** Open **Collector ↗** from Studio, open the
downloaded JS in the authenticated Mixamo Brave tab's DevTools Console. Select
motion cards; **Save as new** creates a named list and **Update** amends the
selected list. Use **Export animations.json**, then **+ Import JSON file** in
Studio. The collector is deliberately not injected while the download pipeline
is running.

## Extend an existing generated model without finding its source ZIP

1. In the **Local** Model Library, click a model previously built by this Studio.
2. **Use Local model** is selected automatically when you click the generated
   model. Studio shows its name and reuses the saved source/animation evidence;
   no new character ZIP, file-picker, or manual path is needed.
3. Select a saved collection containing new motions, then click **Build avatar**.
   Existing matching motion IDs are filtered out. The original FBX clips are
   SHA-256 verified (or strictly verified against a legacy download manifest).
   Only missing animations are fetched from Mixamo, and the extended combined
   GLB is saved as a new item in the Local gallery.
4. If a download fails, click **Resume** to continue using the same output and
   verified animations.

Extension outputs and their per-build merged preset/checkpoints live in
`~/MixamoLocal/extensions/`; existing generated GLBs/FBXs are never overwritten.
The original character ZIP/FBX must still exist on the Mac; Studio locates it
from the saved build manifest so you do not have to find it in Finder. The
Mixamo browser may need to upload the original rig again for new downloads.
**Imported standalone GLBs and Rantlist remote assets are previewable but
cannot safely acquire Mixamo actions without the original rig/source.**

To process a genuinely new character, click **Upload new ZIP / FBX** once and
choose the file using your Mac's native picker. The file input is hidden; the
selected filename appears below the button. The Studio no longer asks users
to type the character's file path. The existing backend path API is retained
only for compatibility with scripts that already use it.

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
│   ├── mixamo-actions-v1.3.2.zip # all new release ZIPs go HERE
│   ├── .backups/                 # automatic rollback snapshots
│   └── .state/                   # PID, service log, installed version
├── core/                         # running Flask + Playwright + Blender application
├── site/                         # WORKWORK.FUN public homepage
└── updates-log.md
```

Save the downloaded `mixamo-actions-v1.3.2.zip` **directly into the repository's `updates/` folder**, using your browser's Save As destination. No `cp ~/Downloads/...` step is needed.

If your watcher is already running, simply save the new versioned ZIP in `updates/`; no command is needed. If the watcher is not running, start **continuous monitoring** once:

```zsh
cd /Users/smielniczuk/Documents/works/mixamo-actions
./mixamo-studio-watch.sh
```

Leave that terminal open. Do **not** pass `--once`: that flag performs one check and exits.

The updater verifies manifest hashes, tests the code, installs dependencies in `core/.venv`, backs up overwritten files, and restarts the managed Flask app on port 5055. It preserves local browser profiles, credentials, uploads, exported GLBs, and the Git directory.

**If the installer reports an unmanaged process on port 5055**, it will not overwrite code or stop that process. Inspect the listener:

```zsh
lsof -nP -iTCP:5055 -sTCP:LISTEN
ps -p PID -o command=   # replace PID with the actual listener PID
```

Stop only the old instance after verifying its command and let the continuous watcher retry. The permanent watcher automatically notices later higher-version ZIPs in `updates/`.

Open the local Studio at http://127.0.0.1:5055. The browser tab reports new versions after its local server restarts.

## Configuration

```zsh
cp mixamo-watch.env.example mixamo-watch.env
```

This defaults to `MIXAMO_DEPLOY_TARGET=root@yolo.cx` and `MIXAMO_DEPLOY_PORT=18021`, as specified in the supplied Rantlist `deploy.sh`. The updater also recognizes the previous mistaken `root@mail:22` configuration without changing private local settings. Repository push uses the *existing* `origin` remote, `main` branch, and your local Git credentials; no password or token is placed in source.

**Continuous watcher with GitHub publishing enabled (from the repo root):**

```zsh
cd /Users/smielniczuk/Documents/works/mixamo-actions
./mixamo-studio-watch.sh
```

`--once` is a deliberate single pass and exits. `MIXAMO_AUTO_GIT_PUSH=0` and
`MIXAMO_AUTO_DEPLOY=0` intentionally disable publishing; do not use these for
normal automatic operation. The watcher reads `mixamo-watch.env` (which should
remain ignored by Git). Git push needs a working `origin`, branch `main`, and
an authorized GitHub SSH key. The updater automatically pushes to `git@github.com:...`
when `origin` is HTTPS and does not change the existing fetch remote. This is
non-interactive: SSH authentication errors are logged and retried later. Run
`ssh -T git@github.com` once on this Mac to verify GitHub authorization (GitHub
returns a greeting, often with exit status 1). If you use a custom SSH destination,
set `MIXAMO_GIT_PUSH_URL` in the untracked `mixamo-watch.env`. The Rantlist
server deploy also uses SSH, but GitHub must separately authorize the key.  Homepage deployment also needs SSH access to the configured
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
./ops/deploy-homepage.sh --show-target
./ops/deploy-homepage.sh --dry-run
./ops/deploy-homepage.sh
```

The existing server site mapping is left untouched. Deployment copies only five static assets into the already-provisioned directory, never modifies Nginx/HTTPS or any server service, and does **not** expose Flask, Playwright, Adobe login sessions or character uploads to the Internet.

## Health and test commands

```zsh
python3 ops/install_release.py updates/mixamo-actions-v1.3.2.zip --repo . --verify-only
curl -fsS http://127.0.0.1:5055/api/release
cd core && .venv/bin/python -m unittest discover -s tests -v
```

## Security

The local control panel listens on `127.0.0.1` and requires a token for mutating calls. Do not expose the Flask app or Brave CDP port `9222` on the public Ubuntu host. Do not put browser profiles, session cookies, large models, `.venv`, `.env`, or private keys into release archives. The updater rejects directory traversal, symlinks and corrupt manifests; it does not execute arbitrary shell hooks from ZIPs.

## Release publication recovery

The watcher records **installation**, **Git publication**, and **homepage publication** separately under `updates/.state/`. A failed Git push or remote deploy never changes the successful installation marker. The persistent watcher retries pending publication without reinstalling the app (with a short retry cooldown). Run `./mixamo-studio-watch.sh --once` to attempt a single immediate publish cycle.

Git requires `origin`, `main`, and your configured user identity. The watcher stages only files listed by `release.json` and checks their SHA-256 hashes. The homepage requires `MIXAMO_DEPLOY_TARGET` and an existing SSH/rsync connection; the existing website routing is left unchanged. No push or remote deploy occurs unless the corresponding settings are enabled.

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
bootstrap the updated installer using `unzip -o updates/mixamo-actions-v1.3.2.zip ops/install_release.py`,
and restart the watcher from the repository root.

### Rantlist Stage integration (v1.2.0)

Mixamo Studio runs locally at `http://127.0.0.1:5055`. In the collapsible **Model Library**, choose **Rantlist Stage**, then **Connect profile** and select the **JSON exported from your own Rantlist profile**. The JSON is parsed and used only in process memory, never saved to the Mixamo workspace, never committed to GitHub, and never uploaded to the static homepage. Treat the exported JSON like a sensitive sign-in credential: Rantlist r630 signs users in by their exported identity UUID.

**Important Rantlist compatibility detail:** Rantlist r630 maintains only one active WebSocket session for each nickname. Connecting Mixamo can sign out your Rantlist browser tab; close/sign out that tab first if you need an uninterrupted Mixamo session. Rantlist also persists profile metadata when signing in, so **use a fresh exported JSON** to avoid replacing newer profile fields with stale backup metadata. This is a limitation of the existing Rantlist authentication protocol, not an OAuth flow.

After connection, the **Rantlist Stage** gallery shows your private Avatar and Model GLBs. Load a remote model into Three.js, download it, or delete the remote asset (after confirmation). In the **Local** gallery, click **↑ R** on a model card and choose `avatar` or `model` to publish the combined GLB to the respective Rantlist Stage library. Thumbnail upload is attempted if the captured local WebP is 192 KiB or smaller. Rantlist limits each GLB to **20 MiB**, uses a shared Stage gallery limit of **60 items**, and applies the account's ordinary upload quota. Oversize GLBs need optimizing before publishing. New Rantlist assets remain **owner-private**; they are available to others in Stage only when used as an explicitly shared/selected Stage asset, not as a public asset directory.

The integration reuses the already deployed Rantlist r630 API, `wss://rantlist.me/ws` and `https://rantlist.me/stage-private/api/assets`. Its WebSocket capability is kept in local Flask process memory and expires when the session disconnects. It opens the Rantlist socket without a cross-origin browser WebSocket, since Rantlist r630 rejects foreign WebSocket origins. The local gateway is protected by the ephemeral `X-Local-Token`. A Flask restart requires importing the profile again. **No Rantlist source, Ubuntu files, Nginx, services, or static deploy destination are changed.**

### Rantlist connection compatibility fix (v1.2.1)

Rantlist r630 requires WebSocket connection query parameters matching its current server-served browser UI. Mixamo Studio now checks the public `https://rantlist.me/version` JSON immediately before connecting and includes `uiVersion`, `protocolVersion`, `uiHash` and `reloadSupport=1` in the `wss://rantlist.me/ws` handshake URL. A deployment race retries once; an unrelated sign-in denial is never retried. The imported portable profile is not stored or sent during version discovery. No Rantlist server edits, SSH operations, or Nginx changes are required for this fix.


## Resume an interrupted Mixamo build (v1.2.6)

Studio now shows **↻ Resume** after a failed, cancelled, or interrupted build. It reuses the original uploaded ZIP/FBX, exact animation preset, and output folder — no second upload. The resume command is persisted locally in `~/MixamoLocal/.mixamo-last-job.json` (owner-only file), so it remains available after Flask restarts. No tokens, cookies, Rantlist identities or credentials are stored.

The `fbx/.mixamo-resume.json` checkpoint is written atomically. Each completed FBX is validated and bound to a SHA-256 digest, original character fingerprint, preset fingerprint, and animation spec. Partial downloads remain `.part` files until verified. Download search timeouts are retried up to three times with a controlled page reload. A duplicate browser download is **never** triggered on an ambiguous download event timeout. If all expected animations already exist and validate, the Mixamo stage is skipped and Blender runs directly.

**For a build that failed before v1.2.6:** earlier versions did not save the Flask job configuration. Copy the original ZIP path from the failed job's Logs (the `[paths] Original character` line), select **File path** and the **same animation preset**, then click **Build avatar**. The new pipeline checks the older `fbx/manifest.json` and `source_character/` before adopting verified existing FBXs. Your 17 completed clips should be reused; only the missing eight should be downloaded. Do not re-upload that ZIP as a new file, as this creates a separate output directory.

Resume never deletes original output files; mismatched or unverified legacy exports stop with an explicit error.

## Watcher log boundaries (v1.2.7)

Every release attempt now prints dated START INSTALL and END INSTALL banners and
explicit separate GitHub and homepage START/END status. The watcher keeps a
compact event-only history at `updates/.state/update-events.log`; your original
terminal output still shows all installer, dependency and test lines between them.
A failed release prints a FAILED boundary before the next attempt. The watcher
remains a foreground process; leave it running without `--once`. When upgrading
from an older watcher version, restart the watcher once to run the newly installed
shell code rather than the previous copy held by the existing Bash process.

## Importing animation JSON presets (v1.3.2)

In Studio's **Animation collection** section, click **+ Import JSON file** and
select any Motion Collector export (e.g. `animations-males.json`). Import runs
immediately: a validated copy is saved in `~/MixamoLocal/presets/`, selected in
the Library dropdown, and reusable for future characters and resumed jobs.
No filesystem path or second Save click is required. The import is visible even
when the JSON path tab is selected. Importing the exact same filename and bytes
again reuses the existing preset; different contents never overwrite it.

The **JSON path** alternative accepts `/Users/.../animations-males.json` or
`file:///Users/.../animations-males.json` for a file already on the Mac running
Flask, but the Import button is recommended for normal usage.
