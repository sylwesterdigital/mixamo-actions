## v1.2.2 — 2026-10-15

- Repair Rantlist thumbnail display: preserve the remote JPG/PNG/WebP MIME type, bound requests to three visible thumbnails, and show a clean fallback instead of broken images.
- Make the bottom Model Library vertically resizable by dragging its top handle, with multiple scrollable rows and keyboard resizing support.
- Replace the confusing avatar/model text prompt with a dedicated publish dialog; prefill the filename from the saved GLB name and offer explicit Avatar and Model choices.
- Show upload-in-progress status, elapsed time without fabricated percent-complete, and persistent confirmed success or detailed failure for every Rantlist upload.
- Report a separate Stage-preview upload failure without incorrectly marking a successfully uploaded GLB as failed.
- Preserve local models, private Rantlist identity isolation, Git/SSH publishing, and the static-only Ubuntu deployment boundary; no Rantlist server or Nginx changes.

## v1.2.1 — 2026-10-15

- Fix Rantlist profile login rejected as a legacy chat page: read current Rantlist UI/protocol/hash metadata from its public, same-origin `/version` endpoint before opening the Stage WebSocket.
- Include `uiVersion`, `protocolVersion`, `uiHash`, and `reloadSupport` on the WebSocket handshake URL, as required by the existing Rantlist r630 server.
- If Rantlist redeploys between version lookup and connection, refresh and retry the handshake once; never retry unrelated account/authentication rejections.
- Reject malformed, redirected, oversized or unavailable Rantlist version responses without sending a profile credential.
- Retain the existing private Stage gallery, local model library, Flask token isolation, SSH/Git updater and strictly scoped static homepage deployment. No Ubuntu or Rantlist backend changes.

# Mixamo Studio — update log

## v1.2.0 — Rantlist Stage gallery integration (2026-10-15)
- Import a portable `rantlist-profile` JSON in Mixamo Studio to connect to the same Rantlist account using Rantlist r630's existing WebSocket sign-in and 40-minute owner-bound Stage gallery capability.
- Add Local / Rantlist Stage tabs to the collapsible bottom library; browse owner-private remote avatar and model GLBs, preview thumbnails, load animated GLBs in Three.js, and download remote files.
- Add `↑ R` to each local GLB card to publish it to a chosen Rantlist Stage Avatar or Model library, then upload its captured WebP stage thumbnail when it meets Rantlist's preview limit.
- Use the existing owner-scoped `/stage-private/api/assets` Rantlist API, not server filesystem access; honor Rantlist's 20 MiB-per-GLB limit, 60-item library cap, and profile media quota.
- Keep exported profile JSON, account identity, WebSocket capability and private Rantlist asset URLs out of persistent local storage and all release/deployment files; protect all localhost Rantlist gateway requests with the Studio session token.
- Confine outbound gallery traffic to `wss://rantlist.me/ws` and `https://rantlist.me` with strict remote media path checks; do not modify or deploy any Rantlist server, Nginx, or Ubuntu service configuration.
- Warn explicitly that Rantlist r630 allows only one active session per nickname: connecting via Mixamo may sign out an open Rantlist tab and refresh saved profile fields from the exported JSON.
- Add offline contract tests for Rantlist's portable-profile format, ownership capability, media URL allowlist, gallery listing, GLB upload and WebP thumbnail; keep local Flask installation and rollback tests intact.

## v1.1.3 — 2026-10-15

- Remove the misleading Nginx/HTTPS configuration warning after successful homepage deployment. Existing server configuration is never modified.
- Restrict server deployment to five allowlisted static files in the existing `/var/www/mojoworks/labs/mixamo-actions/` directory; exclude `.htaccess` and all server configuration files.
- Refuse to create a missing destination, follow a symlinked destination/asset, or change remote permissions, ownership, or other applications.

- Correct Ubuntu SSH deployment endpoint from the supplied Rantlist `deploy.sh`: `root@yolo.cx` on port `18021`, replacing the mistaken `root@mail:22` defaults.
- Automatically map only the previously shipped legacy `root@mail:22` pair when publishing, without changing an existing private `mixamo-watch.env` or overriding customized endpoints.
- Add `./ops/deploy-homepage.sh --show-target` to verify the effective SSH host, port and remote folder without opening a network connection.
- Preserve environment-variable priority over the private config and retain automatic retry of homepage publication without reinstalling Flask or republishing the Git tag.
- Preserve the existing Flask Studio, model gallery and single combined animation GLB exporter unchanged.


## v1.1.2 — 2026-10-15

- Fix `Username for https://github.com`: GitHub HTTPS `origin` is converted to a GitHub SSH push target without modifying the configured fetch remote.
- Set `GIT_TERMINAL_PROMPT=0` and SSH `BatchMode=yes` for unattended release publishing; authentication failures produce actionable errors instead of blocking the watcher.
- Preserve previously committed-but-unpushed releases: retry `main` and version tag pushes independently of local installation, using the configured SSH agent/key.
- Support `MIXAMO_GIT_PUSH_URL` to override the push destination for custom authorized SSH remotes; keep existing local/bare repositories valid for tests.
- Add Git transport tests and preserve current Flask Studio, Model Library, Blender pipeline, and Ubuntu homepage deployment.

## v1.1.1 — 2026-10-15

- Prevent locally edited release-managed README.md from blocking a newer version: save original bytes in `updates/.backups/before-vX.Y.Z-*/README.md` before replacing the release copy.
- Record preserved tracked changes in `updates/.backups/.../local-edits.json`, and restore them automatically if installation or health checks fail.
- Refuse updates when release-managed Git changes are staged, so automatic publication never mixes pending user commits into a release.
- Reject existing release target symlinks to avoid writes outside the repository.
- Preserve v1.1.0 Model Library, authenticated Mixamo pipeline, and combined GLB export.

## v1.1.0 — 2026-10-15

- Added a full-window collapsible bottom Model Library with scene-screenshot preview cards, load/download/delete controls, and no page-level scrolling.
- Finished combined GLB exports are automatically registered in a persistent library at `~/MixamoLocal/library` (or `MIXAMO_FLASK_WORKSPACE/library`).
- Added Save to Library for manually opened GLB files and Capture to refresh thumbnails from the current Three.js stage.
- Library API includes safe model streaming, GLB downloads, thumbnail uploads, and removals; deleting generated cards leaves original exports intact.
- Preserved Mixamo/Brave/Blender automation, NLA animation export and v1.0.2 Git/Ubuntu watcher behavior.

## v1.0.2 — 2026-10-15

- Fixed Git and homepage publish markers: disabled actions no longer count as successful publishing, so later enabling them processes the already-installed version.
- The permanent watcher keeps checking `updates/`; `--once` is explicitly documented as a one-pass diagnostic/install mode.
- Corrected installer conflict detection to accept verified source files from the last installed release when Git publishing was previously disabled, while still rejecting manual edits.
- Preserved automatic commit, `vX.Y.Z` tag, and `origin main` push with the workstation's existing Git credentials.
- Added regression tests covering publish-marker behavior and preserving locally edited files.
- Only manifest-verified release files are staged for Git, never unrelated user files; existing release tags must point to the correct commit.
- Missing SSH deployment configuration is a publish failure, not a successful homepage release.
- `--once` retries pending publication immediately, without a cooldown after a previous disabled or failed run, and exits nonzero if any enabled publication fails.

## v1.0.1 — 2026-10-15

- Fixed macOS `/var` versus `/private/var` canonical-path mismatch in the Flask dry-run test.
- Removed the hard-coded release version in tests so future version bumps work without test rewrites.
- Added a port-5055 preflight before source installation; refuses to disrupt unrelated processes and reports PID/command for diagnosis.
- Updated local Studio and public homepage version labels to v1.0.1.
- Fixed watcher precedence so explicit Zsh environment overrides `mixamo-watch.env` and is passed to install subprocesses.
- Clarified repository-only update workflow: ZIP packages live in `updates/`; watcher starts from repository root, never from Downloads.
- Preserved the existing Flask/Three.js, Brave/Mixamo/Blender pipeline and single combined animation GLB export.

## v1.0.0 — 2026-10-15

- Established `mixamo-actions-vMAJOR.MINOR.PATCH.zip` as the full-release format.
- Added `mixamo-studio-watch.sh`: watches `updates/`, verifies safe ZIP paths, installs to `core/`, runs checks, restarts Flask and rolls back failures.
- Added safe deployment scripts, release status API and update overlay in existing tabs.
- Added a project homepage for `/var/www/mojoworks/labs/mixamo-actions`.
- Added optional Git commit/tag/push using the workstation's existing credentials, with no credentials stored in the package.
- Preserved the existing Mixamo/Brave/Blender pipeline and combined animation GLB export.

### Release policy

- PATCH: bug fixes. MINOR: backwards-compatible features. MAJOR: breaking changes.
- Every package includes its `release.json`, this log, complete `core/` source, homepage and deployment scripts.
- Watcher refuses downgrades, duplicate releases, unsafe archives and failed health checks.
- Releases are never installed while a Mixamo/Blender job is running.
