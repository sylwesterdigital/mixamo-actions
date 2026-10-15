#!/usr/bin/env python3
"""Local-only Flask control panel for Mixamo Playwright + Blender pipeline.

No browser credentials are requested or stored. The app attaches to a separately
signed-in Brave profile. It is deliberately a single-job LOCAL desktop app.
"""
from __future__ import annotations

from collections import deque
from io import BytesIO
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlsplit
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import uuid

from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename
from rantlist_bridge import RantlistBridge, RantlistError, MAX_MODEL

ROOT = Path(__file__).resolve().parent
RELEASE_FILE = ROOT.parent / "release.json"
WORKSPACE = Path(os.environ.get('MIXAMO_FLASK_WORKSPACE', str(Path.home() / 'MixamoLocal'))).expanduser().resolve()
UPLOADS = WORKSPACE / 'uploads'
PRESETS = WORKSPACE / 'presets'
LOGS = WORKSPACE / 'logs'
LIBRARY = WORKSPACE / 'library'
LIBRARY_FILES = LIBRARY / 'files'
LIBRARY_THUMBS = LIBRARY / 'thumbnails'
LIBRARY_INDEX = LIBRARY / 'catalog.json'
LIBRARY_LOCK = Lock()
for folder in (UPLOADS, PRESETS, LOGS, LIBRARY, LIBRARY_FILES, LIBRARY_THUMBS):
    folder.mkdir(parents=True, exist_ok=True)

APP_TOKEN = secrets.token_urlsafe(32)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1250 * 1024 * 1024
app.config['JSON_SORT_KEYS'] = False
STATE_LOCK = Lock()
STATE = {'job': None}
RANTLIST_BRIDGE = RantlistBridge()  # No imported profiles/tokens written to disk.


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def respond_error(message, code=400):
    return jsonify(error=str(message)), code


@app.before_request
def local_access_only():
    host = request.host.split(':')[0].lower()
    if host not in {'127.0.0.1', 'localhost', '[::1]'}:
        abort(403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') or request.path.startswith('/api/rantlist/'):
        if request.headers.get('X-Local-Token') != APP_TOKEN:
            abort(403)


def saved_presets():
    items = []
    for file in sorted(PRESETS.glob('*.json'), key=lambda x: x.name.casefold()):
        try:
            payload = json.loads(file.read_text(encoding='utf-8'))
            entries = payload.get('animations') if isinstance(payload, dict) else payload
            if isinstance(entries, list):
                items.append({'filename': file.name, 'name': payload.get('presetName', file.stem) if isinstance(payload, dict) else file.stem, 'count': len(entries)})
        except (ValueError, OSError):
            continue
    return items


def validate_preset(path):
    raw = json.loads(path.read_text(encoding='utf-8'))
    seq = raw.get('animations') if isinstance(raw, dict) else raw
    if not isinstance(seq, list) or not seq:
        raise ValueError('Preset needs a non-empty "animations" array')
    for item in seq:
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict) and (item.get('search') or item.get('title')):
            continue
        raise ValueError(f'Invalid animation entry: {str(item)[:120]}')
    return len(seq)


def safe_file_name(original, extension):
    basename = secure_filename(Path(original or '').name)
    if not basename or Path(basename).suffix.lower() not in extension:
        raise ValueError(f'Expected file extension: {", ".join(sorted(extension))}')
    return basename


def browser_executable():
    supplied = os.environ.get('MIXAMO_BRAVE_BIN') or os.environ.get('BRAVE_BIN')
    candidates = [supplied] if supplied else []
    candidates += ['/Applications/Brave Browser.app/Contents/MacOS/Brave Browser']
    for command in ('brave-browser', 'brave', 'brave-browser-stable'):
        found = shutil.which(command)
        if found:
            candidates.append(found)
    return next((str(candidate) for candidate in candidates if candidate and Path(candidate).is_file()), None)


def blender_executable():
    supplied = os.environ.get('BLENDER_BIN')
    candidates = [supplied, '/Applications/Blender.app/Contents/MacOS/Blender', shutil.which('blender'), '/usr/bin/blender']
    return next((str(c) for c in candidates if c and Path(c).is_file()), '/Applications/Blender.app/Contents/MacOS/Blender' if sys.platform == 'darwin' else '/usr/bin/blender')


def port_ready(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.4):
            return True
    except OSError:
        return False


def session_status():
    return {'port': 9222, 'portOpen': port_ready(9222), 'braveFound': browser_executable() is not None,
            'browser': browser_executable(), 'profile': str(Path(os.environ.get('MIXAMO_BRAVE_PROFILE', str(Path.home() / '.mixamo-brave-profile'))).expanduser())}


def public_job(job, cursor=0):
    if job is None:
        return None
    cursor = max(0, cursor)
    first = job['first_index']
    lines = [line for i, line in job['lines'] if i >= cursor]
    return {'id': job['id'], 'status': job['status'], 'phase': job['phase'], 'started': job['started'],
            'finished': job.get('finished'), 'returncode': job.get('returncode'), 'error': job.get('error'),
            'character': str(job['character']), 'output': str(job['output']),
            'lines': lines, 'logCursor': job['next_index'], 'oldestLine': first,
            'combinedGlb': (job['output'] / 'glb' / (job['output'].name + '-anims.glb')).is_file(),
            'bundle': (job['output'] / 'character_bundle.zip').is_file()}


def log_job(job, message):
    line = str(message).rstrip('\r\n')
    with STATE_LOCK:
        i = job['next_index']
        job['next_index'] += 1
        if len(job['lines']) == job['lines'].maxlen:
            job['first_index'] += 1
        job['lines'].append((i, line))
        lowered = line.lower()
        if '[phase 1/3]' in lowered:
            job['phase'] = 'Mixamo download'
        elif '[phase 2/3]' in lowered:
            job['phase'] = 'Blender conversion'
        elif '[phase 3/3]' in lowered:
            job['phase'] = 'GLB validation & archive'
        elif '[done]' in lowered:
            job['phase'] = 'Completed'
        elif '[action required]' in lowered or ('manual' in lowered and ('rigger' in lowered or 'orient' in lowered or 'marker' in lowered)):
            job['phase'] = 'Manual rigging required in Brave'
        elif '[character] character editor ready' in lowered:
            job['phase'] = 'Downloading animations'




def _load_library():
    try:
        payload = json.loads(LIBRARY_INDEX.read_text(encoding='utf-8'))
        return payload if isinstance(payload, list) else []
    except (ValueError, OSError):
        return []


def _save_library(items):
    temp = LIBRARY_INDEX.with_suffix('.json.tmp')
    temp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(LIBRARY_INDEX)


def _library_public(entry):
    item = dict(id=entry['id'], name=entry['name'], source=entry['source'],
                created=entry['created'], clips=entry.get('clips'),
                glbUrl=f"/api/library/{entry['id']}/glb",
                downloadUrl=f"/api/library/{entry['id']}/download",
                jobId=entry.get('jobId'),
                thumbnailUrl=f"/api/library/{entry['id']}/thumbnail" if (LIBRARY_THUMBS / (entry['id'] + '.webp')).is_file() else None)
    return item


def library_entries():
    with LIBRARY_LOCK:
        entries = _load_library()
    return [_library_public(e) for e in reversed(entries) if Path(e['path']).is_file()]


def register_generated(job):
    folder = job['output']
    file = folder / 'glb' / (folder.name + '-anims.glb')
    if not file.is_file() or not file.stat().st_size:
        return None
    canonical = str(file.resolve())
    key = hashlib.sha256(('generated:' + canonical).encode()).hexdigest()[:24]
    with LIBRARY_LOCK:
        entries = _load_library()
        previous = next((e for e in entries if e['id'] == key), None)
        size = file.stat().st_size
        modified = file.stat().st_mtime_ns
        if previous and (previous.get('size') != size or previous.get('mtime') != modified):
            (LIBRARY_THUMBS / (key + '.webp')).unlink(missing_ok=True)
        entries = [e for e in entries if e['id'] != key]
        entries.append(dict(id=key, path=canonical, name=job['character'].stem,
                            source='generated', created=now(), size=size, mtime=modified, clips=None, jobId=job['id']))
        _save_library(entries)
    return key


def library_lookup(item_id):
    if not re.fullmatch(r'[a-f0-9]{24,32}', item_id):
        abort(404)
    with LIBRARY_LOCK:
        entry = next((e for e in _load_library() if e['id'] == item_id), None)
    if entry is None or not Path(entry['path']).is_file():
        abort(404)
    return entry


@app.get('/api/library')
def get_library():
    return jsonify(models=library_entries())


@app.post('/api/library/import')
def import_library_model():
    upload = request.files.get('file')
    if not upload or not upload.filename or Path(upload.filename).suffix.lower() != '.glb':
        return respond_error('Choose a .glb file')
    uid = uuid.uuid4().hex
    file = LIBRARY_FILES / (uid + '.glb')
    try:
        upload.save(file)
        if not file.stat().st_size:
            raise ValueError('Empty GLB file')
        # Validate the GLB magic, not a filename extension alone.
        with file.open('rb') as source:
            if source.read(4) != b'glTF':
                raise ValueError('Invalid GLB header')
        entry = dict(id=uid, name=Path(upload.filename).stem[:140], path=str(file.resolve()),
                     source='imported', created=now(), size=file.stat().st_size, clips=None)
        with LIBRARY_LOCK:
            entries = _load_library()
            entries.append(entry)
            _save_library(entries)
        return jsonify(ok=True, model=_library_public(entry)), 201
    except (OSError, ValueError) as exc:
        file.unlink(missing_ok=True)
        return respond_error(exc)


@app.get('/api/library/<item_id>/glb')
def library_glb(item_id):
    entry = library_lookup(item_id)
    return send_file(entry['path'], mimetype='model/gltf-binary', as_attachment=False, conditional=True)


@app.get('/api/library/<item_id>/download')
def library_download(item_id):
    entry = library_lookup(item_id)
    return send_file(entry['path'], mimetype='model/gltf-binary', as_attachment=True,
                     download_name=secure_filename(entry['name']) + '.glb', conditional=True)


@app.get('/api/library/<item_id>/thumbnail')
def library_thumbnail(item_id):
    library_lookup(item_id)
    path = LIBRARY_THUMBS / (item_id + '.webp')
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype='image/webp', conditional=True)


@app.post('/api/library/<item_id>/thumbnail')
def save_library_thumbnail(item_id):
    library_lookup(item_id)
    if request.content_length is not None and request.content_length > 1_500_000:
        return respond_error('Screenshot exceeds 1.5 MB', 413)
    data = request.stream.read(1_500_001)
    if len(data) > 1_500_000 or len(data) < 20 or not (data[:4] == b'RIFF' and data[8:12] == b'WEBP'):
        return respond_error('A WebP stage screenshot smaller than 1.5 MB is required')
    with LIBRARY_LOCK:
        path = LIBRARY_THUMBS / (item_id + '.webp')
        temp = LIBRARY_THUMBS / (item_id + '.' + uuid.uuid4().hex + '.tmp')
        temp.write_bytes(data)
        temp.replace(path)
    return jsonify(ok=True, thumbnailUrl=f'/api/library/{item_id}/thumbnail')


@app.patch('/api/library/<item_id>')
def patch_library_item(item_id):
    data = request.get_json(silent=True) or {}
    clips = data.get('clips')
    if type(clips) is not int or not 0 <= clips <= 10000:
        return respond_error('Clip count must be an integer between 0 and 10000')
    with LIBRARY_LOCK:
        entries = _load_library()
        match = next((entry for entry in entries if entry['id'] == item_id), None)
        if match is None:
            abort(404)
        match['clips'] = clips
        _save_library(entries)
    return jsonify(ok=True)


@app.delete('/api/library/<item_id>')
def delete_library_item(item_id):
    entry = library_lookup(item_id)
    with LIBRARY_LOCK:
        entries = [e for e in _load_library() if e['id'] != item_id]
        _save_library(entries)
        (LIBRARY_THUMBS / (item_id + '.webp')).unlink(missing_ok=True)
        # Only remove GLBs explicitly copied into the application-managed library.
        managed = LIBRARY_FILES / (item_id + '.glb')
        if entry.get('source') == 'imported' and Path(entry['path']).resolve() == managed.resolve():
            managed.unlink(missing_ok=True)
    return jsonify(ok=True)


def worker(job, command):
    logfile = LOGS / (job['id'] + '.log')
    try:
        with logfile.open('w', encoding='utf-8') as sink:
            if job.get('cancel_requested'):
                with STATE_LOCK:
                    job['status'] = 'cancelled'
                    job['finished'] = now()
                return
            log_job(job, '[local] Running Mixamo pipeline')
            process = subprocess.Popen(command, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
            with STATE_LOCK:
                job['process'] = process
                job['status'] = 'running'
                cancel_now = job.get('cancel_requested', False)
            if cancel_now:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            assert process.stdout is not None
            for line in process.stdout:
                sink.write(line)
                sink.flush()
                log_job(job, line)
            code = process.wait()
            # Register the output BEFORE reporting the job as complete. The UI
            # can then immediately load it and capture the stage thumbnail.
            if code == 0 and not job.get('cancel_requested'):
                try:
                    model_id = register_generated(job)
                    if model_id:
                        log_job(job, f'[library] Added finished model {model_id}')
                except Exception as ex:
                    log_job(job, f'[library WARNING] Failed to register output: {ex}')
            with STATE_LOCK:
                job['returncode'] = code
                job['finished'] = now()
                job['status'] = 'cancelled' if job.get('cancel_requested') else ('completed' if code == 0 else 'failed')
                if code != 0 and not job.get('cancel_requested'):
                    job['error'] = f'Pipeline exited with code {code}. Check logs for details.'
            log_job(job, f'[local] Finished with exit code {code}')
    except Exception as exc:
        with STATE_LOCK:
            job['status'] = 'failed'
            job['finished'] = now()
            job['error'] = str(exc)
        log_job(job, f'[local ERROR] {exc}')


@app.get('/')
def index():
    return render_template('index.html', token=APP_TOKEN, session=session_status(), presets=saved_presets(), blender=blender_executable(), workspace=str(WORKSPACE))


@app.get('/api/release')
def release_info():
    """Version metadata for already-open browser tabs; intentionally read-only."""
    try:
        info = json.loads(RELEASE_FILE.read_text(encoding='utf-8'))
        return jsonify(version=info['version'], changes=info.get('changes', []),
                       published=info.get('date', ''), name='Mixamo Studio')
    except (OSError, KeyError, ValueError):
        return jsonify(version='unversioned', changes=[], published='', name='Mixamo Studio')


@app.get('/api/update-readiness')
def update_readiness():
    """Watcher waits for the single local pipeline job before restarting."""
    with STATE_LOCK:
        current = STATE.get('job')
        status_value = current.get('status', '') if current else ''
    return jsonify(ready=status_value not in ('running', 'queued', 'cancelling'), status=status_value)


@app.get('/api/status')
def status():
    try:
        since = int(request.args.get('since', '0'))
    except ValueError:
        since = 0
    with STATE_LOCK:
        job = public_job(STATE['job'], since)
    return jsonify(job=job, session=session_status(), presets=saved_presets())


@app.post('/api/presets')
def add_preset():
    file = request.files.get('file')
    if not file or not file.filename:
        return respond_error('Select a JSON preset file')
    try:
        filename = safe_file_name(file.filename, {'.json'})
        output = PRESETS / filename
        if output.exists():
            output = PRESETS / f'{Path(filename).stem}_{uuid.uuid4().hex[:6]}.json'
        file.save(output)
        count = validate_preset(output)
        return jsonify(ok=True, filename=output.name, count=count, presets=saved_presets())
    except Exception as exc:
        if 'output' in locals():
            output.unlink(missing_ok=True)
        return respond_error(exc)


@app.post('/api/brave/<mode>')
def launch_brave(mode):
    if mode not in {'login', 'automate'}:
        return respond_error('Unknown Brave mode')
    browser = browser_executable()
    if not browser:
        return respond_error('Brave executable not found. Set MIXAMO_BRAVE_BIN to its path.')
    if port_ready(9222):
        return respond_error('Port 9222 is already listening. Close the automation Brave instance before starting login.' if mode == 'login'
                             else 'Debug port 9222 is already open; use the existing Brave session.', 409)
    profile = Path(os.environ.get('MIXAMO_BRAVE_PROFILE', str(Path.home() / '.mixamo-brave-profile'))).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    args = [browser, '--user-data-dir=' + str(profile), '--no-first-run']
    if mode == 'automate':
        args += ['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9222']
    args.append('https://www.mixamo.com/')
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        return respond_error(exc)
    text = ('Sign in manually using the opened Brave window. When finished, quit that dedicated Brave instance completely, then select Start automated Brave.'
            if mode == 'login' else 'Dedicated Brave launched. Check that your Mixamo session is signed in before starting the pipeline.')
    return jsonify(ok=True, message=text)


def field_bool(name):
    return request.form.get(name) in {'true', 'on', '1', 'yes'}


def int_value(name, default, low, high):
    number = int(request.form.get(name, str(default)))
    if not low <= number <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return number


@app.post('/api/jobs')
def start_job():
    with STATE_LOCK:
        if STATE['job'] and STATE['job']['status'] in ('starting', 'running'):
            return respond_error('Another pipeline job is already running.', 409)
    try:
        source_mode = request.form.get('source_mode', 'path')
        if source_mode == 'path':
            value = request.form.get('character_path', '').strip()
            character = Path(value).expanduser().resolve()
            if not value or character.suffix.lower() not in {'.zip', '.fbx'} or not character.is_file():
                raise ValueError('Provide a valid local .zip or .fbx path')
        elif source_mode == 'upload':
            file = request.files.get('character_file')
            if not file or not file.filename:
                raise ValueError('Select a character ZIP or FBX')
            filename = safe_file_name(file.filename, {'.zip', '.fbx'})
            character = UPLOADS / uuid.uuid4().hex[:10] / filename
            character.parent.mkdir(parents=True, exist_ok=True)
            file.save(character)
            if character.stat().st_size == 0:
                raise ValueError('Uploaded character is empty')
        else:
            raise ValueError('Invalid character source mode')

        preset_mode = request.form.get('preset_mode', 'saved')
        if preset_mode == 'saved':
            selection = request.form.get('preset', '')
            preset = (PRESETS / selection).resolve()
            if not selection or not preset.is_relative_to(PRESETS) or not preset.is_file():
                raise ValueError('Choose a saved preset, or upload a JSON preset first')
        elif preset_mode == 'path':
            selection = request.form.get('preset_path', '').strip()
            preset = Path(selection).expanduser().resolve()
            if not selection or not preset.is_file() or preset.suffix.lower() != '.json':
                raise ValueError('Provide an existing animations.json path')
        else:
            raise ValueError('Invalid animation preset mode')
        count = validate_preset(preset)
        draco = int_value('draco', 6, 0, 6)
        webp = int_value('webp', 30, 0, 100)
        timeout = int_value('timeout', 900, 60, 7200)
        blender = Path(request.form.get('blender', blender_executable())).expanduser().resolve()
        if not blender.is_file():
            raise ValueError(f'Blender executable not found: {blender}')
        port = int_value('port', 9222, 1024, 65535)
        output = character.parent / f'{character.stem}-exports'
        command = [sys.executable, '-u', str(ROOT / 'mixamo_pipeline.py'),
                   '--cdp', f'http://127.0.0.1:{port}', '--character', str(character),
                   '--animations', str(preset), '--draco-level', str(draco), '--webp-quality', str(webp),
                   '--manual-rig-timeout', str(timeout), '--blender', str(blender)]
        for field, flag in [('skip_download', '--skip-download'), ('skip_upload', '--skip-upload'),
                            ('confirm_upload', '--confirm-upload'), ('require_textures', '--require-textures'),
                            ('no_draco', '--no-draco'), ('no_webp', '--no-webp'),
                            ('continue_on_error', '--continue-on-error'), ('dry_run', '--dry-run')]:
            if field_bool(field):
                command.append(flag)
        jid = uuid.uuid4().hex[:12]
        job = {'id': jid, 'status': 'starting', 'phase': 'Preparing', 'started': now(), 'finished': None,
               'character': character, 'output': output, 'lines': deque(maxlen=2000), 'next_index': 0,
               'first_index': 0, 'process': None, 'returncode': None, 'error': None,
               'cancel_requested': False, 'animations': count}
        with STATE_LOCK:
            if STATE['job'] and STATE['job']['status'] in ('starting', 'running'):
                return respond_error('Another pipeline job is already running', 409)
            STATE['job'] = job
        Thread(target=worker, args=(job, command), daemon=True).start()
        with STATE_LOCK:
            snapshot = public_job(job)
        return jsonify(ok=True, job=snapshot, animations=count)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return respond_error(exc)


@app.post('/api/jobs/cancel')
def cancel_job():
    import signal
    with STATE_LOCK:
        job = STATE['job']
        if not job or job['status'] not in ('starting', 'running'):
            return respond_error('No running job', 409)
        job['cancel_requested'] = True
        process = job.get('process')
    if process and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return jsonify(ok=True)


@app.get('/api/jobs/<job_id>/file/<kind>')
def download_result(job_id, kind):
    with STATE_LOCK:
        job = STATE['job']
        if not job or job['id'] != job_id or job['status'] != 'completed':
            abort(404)
        out = job['output']
    options = {'glb': out / 'glb' / (out.name + '-anims.glb'), 'zip': out / 'character_bundle.zip',
               'manifest': out / 'manifest.json'}
    path = options.get(kind)
    if path is None or not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.get('/api/jobs/<job_id>/preview')
def preview_result(job_id):
    """Serve the finished combined GLB inline for Three.js GLTFLoader."""
    with STATE_LOCK:
        job = STATE['job']
        if not job or job['id'] != job_id or job['status'] != 'completed':
            abort(404)
        path = job['output'] / 'glb' / (job['output'].name + '-anims.glb')
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype='model/gltf-binary', as_attachment=False,
                     conditional=True)


@app.errorhandler(RantlistError)
def rantlist_error(exc):
    return respond_error(str(exc), exc.status)


@app.post('/api/rantlist/connect')
def rantlist_connect():
    """Import a portable profile only into transient memory; never store its JSON."""
    from rantlist_bridge import parse_portable_profile
    if request.content_length is None or request.content_length > 2 * 1024 * 1024:
        return respond_error('Profile JSON must be smaller than 2 MiB.', 413)
    try:
        payload = request.get_json(force=True)
    except Exception:
        return respond_error('Invalid profile JSON.')
    return jsonify(RANTLIST_BRIDGE.connect(parse_portable_profile(payload)))


@app.get('/api/rantlist/status')
def rantlist_status():
    return jsonify(RANTLIST_BRIDGE.status())


@app.post('/api/rantlist/disconnect')
def rantlist_disconnect():
    RANTLIST_BRIDGE.close()
    return jsonify(ok=True)


@app.get('/api/rantlist/assets')
def rantlist_assets():
    return jsonify(RANTLIST_BRIDGE.list_assets())


@app.get('/api/rantlist/assets/<asset_id>/<format>')
def rantlist_asset(asset_id, format):
    if format not in ('glb','download','thumbnail'):
        abort(404)
    payload, _mime = RANTLIST_BRIDGE.asset(asset_id, 'thumbnail' if format=='thumbnail' else 'glb')
    mimetype = 'image/webp' if format=='thumbnail' else 'model/gltf-binary'
    return send_file(BytesIO(payload), mimetype=mimetype,
                     as_attachment=format=='download',
                     download_name=f'rantlist-{asset_id}.glb' if format=='download' else None,
                     max_age=0)


@app.post('/api/rantlist/publish/<library_id>')
def rantlist_publish(library_id):
    """Publish an existing local-library GLB to the authenticated owner's gallery.

    Never accept arbitrary filenames, server destinations, or arbitrary upload URLs.
    """
    kind = (request.get_json(silent=True) or {}).get('kind','avatar')
    if not re.fullmatch(r'[a-f0-9]{24,32}', library_id):
        abort(404)
    with LIBRARY_LOCK:
        entry = next((e for e in _load_library() if e.get('id')==library_id), None)
    if not entry:
        abort(404)
    candidate = Path(entry['path']).expanduser().resolve()
    if not candidate.is_file() or candidate.suffix.lower()!='.glb':
        return respond_error('The saved GLB is no longer available.',404)
    size = candidate.stat().st_size
    if size > MAX_MODEL:
        return respond_error('Rantlist accepts GLB files no larger than 20 MiB. Optimize the model first.',413)
    glb = candidate.read_bytes()
    thumb = LIBRARY_THUMBS / (library_id+'.webp')
    thumbnail = thumb.read_bytes() if thumb.is_file() and thumb.stat().st_size <= 192 * 1024 else None
    return jsonify(RANTLIST_BRIDGE.publish(glb=glb, name=entry.get('name','Mixamo model'), kind=kind, thumbnail=thumbnail))


@app.delete('/api/rantlist/assets/<asset_id>')
def rantlist_delete_asset(asset_id):
    return jsonify(RANTLIST_BRIDGE.delete(asset_id))


@app.get('/collector.js')
def collector():
    return send_file(ROOT / 'mixamo_motion_collector.js', as_attachment=True,
                     download_name='mixamo_motion_collector.js')


if __name__ == '__main__':
    print('Mixamo Flask control panel: http://127.0.0.1:5055')
    print(f'Local workspace: {WORKSPACE}')
    app.run(host='127.0.0.1', port=5055, debug=False, threaded=True, use_reloader=False)
