# Mixamo Local Studio — Flask Edition

A one-page, **local-only** interface for the existing Mixamo Playwright → Blender → single combined GLB pipeline. The original Python scripts and the draggable Motion Collector are included. No Adobe credentials are requested by the Flask app.

## Start on macOS / Ubuntu

```bash
cd mixamo_flask_local
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./start.sh
```

The launcher usually opens **http://127.0.0.1:5055** automatically; otherwise open it manually. The web page has Brave login/automation controls, preset JSON importing, character selection/upload, and a Start button. You no longer have to type the lengthy pipeline command.

Brave and Blender must be installed. To override auto-detection when needed:

```bash
export MIXAMO_BRAVE_BIN="/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
export BLENDER_BIN="/Applications/Blender.app/Contents/MacOS/Blender"
./start.sh
```

On Ubuntu, Brave is typically `brave-browser` and Blender `/usr/bin/blender`. `BLENDER_BIN=/usr/bin/blender ./start.sh` works as well.

## First-time Mixamo sign-in

1. Click **Open Brave to sign in**. This opens the dedicated `~/.mixamo-brave-profile` using ordinary Brave, *without debugging*. Sign in manually with Adobe/Google and confirm Mixamo loads.
2. **Quit that dedicated Brave instance fully** (not just a tab).
3. Click **Start automated Brave**. It reuses the signed-in profile and enables CDP on **localhost port 9222**.
4. Choose a preset, select a character, and click **Start processing**.

If Playwright reports an authentication or CDP error, use the same troubleshooting steps as the console pipeline. `localhost:9222` must stay private. The Flask UI only confirms the port is open, **not** that Mixamo has accepted the session.

## Character selection: Local model or new upload

- **Use Local model** (default): click a previously generated model card in the
  Local Model Library. Choose a preset with additional motion actions and click
  **Build avatar**. Studio resolves the saved source and verified old FBXs,
  downloads only missing motions, then creates a new combined GLB in
  `~/MixamoLocal/extensions/` without changing the original model or exports.
- **Upload new ZIP / FBX**: one button opens the Mac's native file picker.
  The underlying file input is hidden; no other "Choose file" or path input
  is displayed. A new upload is copied to `~/MixamoLocal/uploads/<unique-id>/`.

An imported GLB lacking the original rig's generated export manifest is
preview-only for this extension workflow. The backend retains local-path
support for legacy CLI clients, but Studio does not expose that input.

Presets exported by the draggable JS collector can be uploaded to the local
preset library at `~/MixamoLocal/presets/`. Local JSON files can be imported
through the Studio preset picker.

## Processing / results

The one-page UI runs the original `mixamo_pipeline.py` **as a subprocess**, so all Playwright, Blender, material-preservation and GLB validation logic remains unchanged. The user sees live logs and can cancel a job. Only one job runs at once because the Brave browser session is shared.

At the Auto-Rigger **Review** stage, Playwright attempts automatic **Next**. If Mixamo requires **Orient** or manual marker placement, the automation waits and you finish rigging **in Brave**, then it resumes. Even if you select **Confirm character manually**, the pipeline waits for your click in Brave without asking for terminal input. The web page calls attention to this stage when logs indicate manual rigging.

Default output: **one GLB containing the textured character, rig, and all named animation actions**, plus Blender project, source FBXs and a final ZIP. The Flask page offers direct downloads of the combined GLB and ZIP after successful completion.

## Additional notes

- Server listens on **127.0.0.1:5055 only**. No exposure to LAN/public networks or production multi-user use is intended. POST actions require a random per-launch token and job execution does not invoke a shell.
- Job logs are written to `~/MixamoLocal/logs/`; status/log display remembers the most recent job **until Flask restarts**, while exported files remain on disk.
- For browser file upload the maximum request size is 1.25 GiB. Source ZIP extraction and validation is performed by the existing pipeline.
- The app does not manage Adobe accounts, bypass Google login security, or scrape cookies from your everyday Brave browser.
- Playwright selectors are dependent on Mixamo's interface and still require **live testing with your authenticated account**. Blender output/material correctness should be verified visually in Three.js.
- Existing code is included for convenience: `mixamo_pipeline.py`, `mixamo_browser.py`, `blender_build.py`, `mixamo_motion_collector.js` and `brave_session.sh`.

## One-page API (local)

`GET /` — UI, `GET /api/status` — job/Brave status, `POST /api/presets` — upload a JSON preset, `POST /api/jobs` — start pipeline, `POST /api/jobs/cancel` — request stop, `POST /api/brave/login|automate` — open the dedicated Brave profile, `GET /api/jobs/<id>/file/glb|zip` — download results.

## Full-window Three.js studio interface (updated version)

The Flask page now uses a fixed-height **desktop-style workbench**:

- **Left dock — Build / Activity:** character ZIP or FBX, local path, Motion Collector JSON presets, Draco/WebP settings, job Start/Cancel, and a scrollable log panel. Advanced controls are collapsed by default; the dock can be hidden using the top-right menu for more viewer room. On narrow screens the dock slides over the viewer.
- **Main stage — Three.js:** display the last successfully generated **combined GLB** automatically, or click **Open GLB** to preview an existing local `.glb` directly in the browser (without uploading that GLB to Flask). Click **Latest export** to reload the current session's completed build.
- **lil-gui stage controls:** choose any named GLB animation clip, Play / Pause / Stop / Next / Previous, animation speed (0.1–3×), **Repeat or Once**, timed crossfades (0–2 seconds), key/fill/rim/ambient lighting, ACES exposure, shadow toggle, floor/grid/background colors, orbit rotation and camera framing.
- **Transport bar and logs drawer:** lightweight controls overlay the viewport. Pipeline logs can open over the scene without a full-page scroll.

The viewer imports **Three.js 0.180** and **lil-gui 0.20** from jsDelivr, with a matching Three.js Draco decoder path. An internet connection is required the first time those front-end modules are downloaded. The existing pipeline itself is unchanged. If a restrictive network blocks jsDelivr, the Flask build controls still work but the 3D viewer will not initialize until dependencies are available. In that case, vendor the pinned Three.js, addons, Draco decoder, and lil-gui files locally and adjust the `importmap` and decoder path in `templates/index.html` / `static/viewer.mjs`.

### Preview endpoint

`GET /api/jobs/<job_id>/preview` serves the most recent **completed** job's combined GLB *inline* as `model/gltf-binary` for GLTFLoader. The existing `/api/jobs/<job_id>/file/glb|zip` remains a download endpoint. Preview is not allowed until the pipeline reports success. Local GLB opening uses a browser object URL and does not require any server-side file-upload handler.

### Files modified (compared with the prior Flask edition)

- `flask_app.py` — added a read-only GLB preview endpoint.
- `templates/index.html` — replaced the long page with a viewport-first layout.
- `static/studio.css` — responsive, no document-level scrolling.
- `static/studio.js` — pre-existing Flask API/UI flow, logs, state restore, preview integration.
- `static/viewer.mjs` — Three.js renderer, GLTFLoader+DRACOLoader, AnimationMixer, OrbitControls, lil-gui.

All `mixamo_pipeline.py`, `mixamo_browser.py`, `blender_build.py`, `mixamo_motion_collector.js`, and Brave-session scripts are retained from the last Flask package.


### Rantlist Stage (v1.2.0)

From the Model Library dock, choose **Rantlist Stage** → **Connect profile** and select your Rantlist v1 portable-profile JSON. The file is not saved to disk. Connecting may replace another open session of the same nickname and save imported profile metadata on Rantlist, so use a recent backup. Local GLB card **↑ R** publishes via `/stage-private/api/assets` to the private Avatar or Model gallery, limited by the Rantlist account storage quota and 20 MiB per GLB. Remote gallery cards can preview/load/download/delete their GLBs. Browser–localhost gateway operations use the Studio session token, and only fixed `rantlist.me` HTTPS/WSS destinations are permitted.

#### Rantlist compatibility (v1.2.1)

Before profile login, the local bridge reads the public `https://rantlist.me/version` endpoint and passes current UI/protocol/hash values in the Rantlist WebSocket connection URL, preventing Rantlist r630 from misidentifying Mixamo as a legacy client. This request sends no profile credential and neither changes nor deploys Rantlist server files.

### Model gallery reliability and publishing (v1.2.3)

The bottom gallery can be resized by dragging its top grip (or focusing it and using the up/down arrows). Cards reflow into scrollable rows. Remote thumbnails load only when visible, up to three simultaneous requests, preserve their original image MIME types, and display a placeholder on failure rather than broken alt text. Local `↑ R` opens a modal prefilled with the saved model name, offers Avatar/Model radio buttons, shows an indeterminate upload status with elapsed time, and keeps explicit success/failure results until dismissed. The remote API does not provide byte-level upload progress; no fake percentages are shown. Model publication is never rolled back if an optional screenshot fails; its error is reported separately.

### Transparent model thumbnails (v1.2.5)

The **Capture** action now creates a portrait WebP thumbnail with a transparent
background, no floor or grid, and framing specific to the loaded avatar. It
does not change the appearance of the live stage. Previously captured opaque
thumbnails (including assets already on Rantlist) are **not** overwritten.
Load a local model and choose **Capture** to replace its local thumbnail.

The gallery CSS uses independent, content-sized rows so dragging the gallery's
top edge only reveals more rows and never changes a card's aspect ratio.

The Mixamo Motion Collector is available in `mixamo_motion_collector.js` and
through the **Collector ↗** link. Open Mixamo Animations in Brave, open its
DevTools Console and paste the script there; export `animations.json` and
import it into Studio. For safety it is not injected into an active Playwright
download session automatically.


### Resumable builds (v1.2.6)

Failed or interrupted builds expose a **↻ Resume** button in Studio (including after an app restart). The last validated job's source path, preset and safe CLI options are stored locally; upload bytes are never copied again. `resume_state.py` validates per-animation FBX hashes and only downloads missing/invalid clips. Browser search timeouts get two bounded retries. Download-button timeouts are not retried automatically, because Mixamo may still be producing a file. Once all clips are present, Blender builds the combined GLB without revisiting Mixamo.

For builds started with an older Studio that did not persist job details, select **File path** with the *original* upload ZIP path from Logs, choose the unchanged preset and click Build. Older `fbx/manifest.json` and saved original source are verified before any legacy FBXs are reused.


Animation collection: Use **+ Import JSON file** to upload a collector JSON into
`MIXAMO_FLASK_WORKSPACE/presets`; the UI selects it immediately. A Finder
`file:///...` URL is also accepted in JSON path mode. No browser filesystem
permissions are required for server-side path access.

## Non-destructive texture optimization

The Local gallery's ◈ button calls `POST /api/library/<id>/optimize` with JSON `{"percent": 75|50|25}` (local token required). The service resizes embedded PNG/JPEG/WebP textures from the already-built GLB into a new managed GLB under `~/MixamoLocal/library/files/`, preserving skinning, mesh and animation buffer data. The original input and provenance are not rewritten; thumbnail and clip metadata are inherited.
