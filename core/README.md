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

## Character selection: two modes

- **Existing local file** (recommended on the same machine): paste the absolute path to your ZIP/FBX. Exports go next to it in `<filename>-exports/` as before.
- **Upload ZIP**: use the browser's file picker. Uploaded copy is saved in `~/MixamoLocal/uploads/<unique-id>/<original-filename>` and its exports are generated in the *same uploaded copy folder*. A web file input cannot reveal its original local directory to Flask. The resulting combined GLB and ZIP can be downloaded directly from the page.

Presets exported by the draggable JS collector can be uploaded to the local preset library. The library lives in `~/MixamoLocal/presets/`. You may also paste a local existing `animations.json` path instead.

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

### Model gallery reliability and publishing (v1.2.2)

The bottom gallery can be resized by dragging its top grip (or focusing it and using the up/down arrows). Cards reflow into scrollable rows. Remote thumbnails load only when visible, up to three simultaneous requests, preserve their original image MIME types, and display a placeholder on failure rather than broken alt text. Local `↑ R` opens a modal prefilled with the saved model name, offers Avatar/Model radio buttons, shows an indeterminate upload status with elapsed time, and keeps explicit success/failure results until dismissed. The remote API does not provide byte-level upload progress; no fake percentages are shown. Model publication is never rolled back if an optional screenshot fails; its error is reported separately.
