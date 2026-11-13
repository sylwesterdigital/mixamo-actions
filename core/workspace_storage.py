#!/usr/bin/env python3
"""Adopt a MANUALLY copied MixamoLocal folder; never copy or delete model data.

Checks a mounted external workspace, safely rebases copied metadata, and
reconstructs an absent/incomplete gallery index from available GLBs. The saved
workspace selection is activated only after verification. The original folder
is never modified. No Ubuntu/server operations are performed here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import uuid

MARKER = '.mixamo-workspace.json'
SCHEMA = 1
IDENTITY_RE = re.compile(r'^[0-9a-f]{32}$')
ID_RE = re.compile(r'^[0-9a-f]{24,32}$')
DATA_DIRS = ('uploads', 'extensions', 'presets', 'library')


class WorkspaceError(RuntimeError):
    pass


def default_config() -> Path:
    value = os.environ.get('MIXAMO_WORKSPACE_CONFIG', '').strip()
    return Path(value).expanduser() if value else Path.home() / 'Library' / 'Application Support' / 'MixamoStudio' / 'workspace.json'


def default_workspace() -> Path:
    return (Path.home() / 'MixamoLocal').resolve()


def _read_json(file: Path):
    try:
        data = json.loads(file.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError) as exc:
        raise WorkspaceError(f'Invalid JSON at {file}: {exc}') from exc
    return data


def configured_workspace():
    override = os.environ.get('MIXAMO_FLASK_WORKSPACE', '').strip()
    if override:
        return Path(override).expanduser().resolve(), None, 'environment'
    config = default_config()
    if config.exists():
        data = _read_json(config)
        if not isinstance(data, dict) or data.get('schema') != SCHEMA or not isinstance(data.get('path'), str) or not IDENTITY_RE.fullmatch(str(data.get('workspaceId', ''))):
            raise WorkspaceError('Saved workspace configuration is invalid; no files were changed.')
        path = Path(data['path']).expanduser()
        if not path.is_absolute():
            raise WorkspaceError('Configured workspace path must be absolute.')
        return path.resolve(), data['workspaceId'], 'config'
    return default_workspace(), None, 'default'


def _external_volume(path: Path) -> Path | None:
    parts = Path(path).expanduser().parts
    if len(parts) >= 3 and parts[:2] == ('/', 'Volumes') and parts[2] not in ('', '.', '..'):
        return Path('/Volumes') / parts[2]
    return None


def check_volume(path: Path, *, mount_check=None):
    volume = _external_volume(path)
    if volume:
        test = mount_check or os.path.ismount
        if volume.is_symlink() or not volume.is_dir() or not test(str(volume)):
            raise WorkspaceError(f'External drive is not mounted at {volume}. Reconnect it; Studio will NOT use internal storage instead.')
    return volume


def verify_workspace(path: Path, workspace_id: str | None, *, mount_check=None) -> Path:
    path = Path(path).expanduser()
    check_volume(path, mount_check=mount_check)
    if workspace_id:
        if path.is_symlink() or not path.is_dir():
            raise WorkspaceError(f'Configured Mixamo workspace is unavailable: {path}')
        meta = _read_json(path / MARKER)
        if not isinstance(meta, dict) or meta.get('schema') != SCHEMA or meta.get('workspaceId') != workspace_id:
            raise WorkspaceError('Workspace drive identity mismatch. Refusing to create or overwrite any files.')
    elif _external_volume(path) and (path.is_symlink() or not path.is_dir()):
        raise WorkspaceError(f'External workspace does not exist: {path}. Copy your MixamoLocal folder to the drive first.')
    return path.resolve()


def open_workspace() -> tuple[Path, str]:
    path, identity, origin = configured_workspace()
    return verify_workspace(path, identity), origin


def _check_tree(root: Path):
    """Avoid following copied symlinks into unrelated locations."""
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            candidate = Path(base) / name
            if candidate.is_symlink():
                raise WorkspaceError(f'Unsafe symlink in Mixamo workspace: {candidate}')
            if not (candidate.is_file() or candidate.is_dir()):
                raise WorkspaceError(f'Unsupported filesystem object in workspace: {candidate}')


def _replace_paths(value, old: str, new: str):
    if isinstance(value, str):
        if value == old:
            return new
        if value.startswith(old + '/'):
            return new + value[len(old):]
        return value
    if isinstance(value, list):
        return [_replace_paths(item, old, new) for item in value]
    if isinstance(value, dict):
        return {k: _replace_paths(v, old, new) for k, v in value.items()}
    return value


def _stamp(path: Path):
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec='seconds')


def _valid_glb(file: Path):
    try:
        if file.stat().st_size < 20:
            return False
        with file.open('rb') as f:
            header = f.read(12)
        return header[:4] == b'glTF' and int.from_bytes(header[4:8], 'little') == 2 and int.from_bytes(header[8:12], 'little') == file.stat().st_size
    except OSError:
        return False


def _glb_files(root: Path):
    """Discover managed imports, generated builds and model extensions."""
    for parent in (root / 'uploads', root / 'extensions', root / 'library' / 'files'):
        if parent.is_dir():
            for candidate in sorted(parent.rglob('*.glb')):
                if candidate.is_file() and _valid_glb(candidate):
                    yield candidate


def _canonical_entry(file: Path, root: Path, origin_root: Path):
    rel = file.relative_to(root)
    if len(rel.parts) >= 2 and rel.parts[:2] == ('library', 'files') and ID_RE.fullmatch(file.stem):
        key = file.stem
        source = 'imported'   # cannot infer optimization/source provenance safely
        name = file.stem
    else:
        old_path = str(origin_root / rel)
        old_key = hashlib.sha256(('generated:' + old_path).encode('utf-8')).hexdigest()[:24]
        new_key = hashlib.sha256(('generated:' + str(file)).encode('utf-8')).hexdigest()[:24]
        thumbs = root / 'library' / 'thumbnails'
        key = old_key if (thumbs / (old_key + '.webp')).is_file() else new_key
        # Only mark generated if a corresponding build manifest exists. This
        # prevents exposing unsafe Extend actions for unknown GLB files.
        exports = file.parent.parent
        source = 'generated' if file.parent.name == 'glb' and (exports / 'manifest.json').is_file() and file.name == exports.name + '-anims.glb' else 'imported'
        name = exports.name.removesuffix('-exports') if source == 'generated' else file.stem
    return dict(id=key, path=str(file), name=name[:140], source=source,
                created=_stamp(file), size=file.stat().st_size, mtime=file.stat().st_mtime_ns, clips=None)


def _metadata_files(root: Path):
    known = [root / 'library' / 'catalog.json', root / '.mixamo-last-job.json']
    for base in (root / 'uploads', root / 'extensions'):
        if base.is_dir():
            known.extend(base.rglob('manifest.json'))
            known.extend(base.rglob('.mixamo-resume.json'))
    return sorted({p for p in known if p.is_file()})


def _write_json_safely(file: Path, value):
    """Atomic metadata edits, keeping the manually copied original once."""
    if file.is_symlink():
        raise WorkspaceError(f'Symlinked metadata is unsafe: {file}')
    backup = file.with_name(file.name + '.before-workspace-adoption')
    if file.exists() and not backup.exists():
        backup.write_bytes(file.read_bytes())
    temp = file.with_name(file.name + '.workspace-tmp')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp, file)
    finally:
        temp.unlink(missing_ok=True)


def inspect(source: Path, destination: Path, *, mount_check=None, require_complete=True):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser()
    if not destination.is_absolute() or destination == source or source in destination.parents or destination in source.parents:
        raise WorkspaceError('Source and destination must be different, non-nested absolute folders.')
    volume = check_volume(destination, mount_check=mount_check)
    if volume and destination == volume:
        raise WorkspaceError('Select the copied MixamoLocal folder inside the mounted drive, not the volume root.')
    if destination.is_symlink() or not destination.is_dir():
        raise WorkspaceError(f'No copied MixamoLocal directory at {destination}. Copy it manually first.')
    _check_tree(destination)
    present = {folder: (destination / folder).is_dir() for folder in DATA_DIRS}
    if not present['uploads'] and not present['library'] and not present['extensions']:
        raise WorkspaceError('This folder has no uploads, extensions, or library directory; refusing to select an empty workspace.')
    missing = []
    mismatched = []
    if require_complete and source.is_dir() and source != destination:
        for folder in DATA_DIRS:
            old = source / folder
            if not old.exists():
                continue
            for file in old.rglob('*'):
                if not file.is_file():
                    continue
                rel = file.relative_to(source)
                # A lost gallery index can be reconstructed; no separate copy required.
                if rel == Path('library/catalog.json'):
                    continue
                newer = destination / rel
                if not newer.is_file():
                    missing.append(rel)
                elif newer.stat().st_size != file.stat().st_size:
                    # Idempotent activation: known JSON manifests were safely
                    # rebased after the first adoption and differ in length.
                    matches_rebased = False
                    if file.suffix.lower() == '.json' and (file.name == 'manifest.json' or file.name == '.mixamo-resume.json'):
                        try:
                            matches_rebased = (_read_json(newer) == _replace_paths(_read_json(file), str(source), str(destination)))
                        except WorkspaceError:
                            pass
                    if not matches_rebased:
                        mismatched.append(rel)
                if len(missing) + len(mismatched) >= 12:
                    break
            if len(missing) + len(mismatched) >= 12:
                break
        if (source / '.mixamo-last-job.json').is_file() and not (destination / '.mixamo-last-job.json').is_file():
            missing.append(Path('.mixamo-last-job.json'))
    if missing or mismatched:
        items = ', '.join(str(p) for p in (missing + mismatched)[:8])
        raise WorkspaceError(f'Manual copy appears incomplete or changed ({items}). Copy the missing files before activating. Original remains untouched.')
    glbs = list(_glb_files(destination))
    existing = destination / 'library' / 'catalog.json'
    return dict(root=str(destination), folders=present, glbCount=len(glbs), catalogExists=existing.is_file(),
                sizeGiB=round(sum(p.stat().st_size for p in glbs)/1024**3, 3), volume=str(volume) if volume else None)


def adopt(source: Path, destination: Path, *, activate=False, config: Path | None = None,
          mount_check=None, check_server=True):
    """Validate an existing copy and rebase/reindex it; copy NO media."""
    destination = Path(destination).expanduser()
    source = Path(source).expanduser().resolve()
    details = inspect(source, destination, mount_check=mount_check)
    print('[workspace] MANUAL COPY MODE — no media will be copied, moved or deleted.')
    print(f'[workspace] Copied folder: {destination}')
    print('[workspace] Found: ' + ', '.join(f'{k}={"yes" if v else "missing"}' for k, v in details['folders'].items()))
    print(f'[workspace] Valid GLBs found: {details["glbCount"]}; gallery catalogue: {"present" if details["catalogExists"] else "missing"}')
    if not activate:
        print('[workspace] Checked only; to rebuild metadata and switch storage, rerun with --activate (Studio/watchers stopped).')
        return details
    if os.environ.get('MIXAMO_FLASK_WORKSPACE', '').strip():
        raise WorkspaceError('MIXAMO_FLASK_WORKSPACE override is set. Unset it before activating persistent configuration.')
    if check_server:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(('127.0.0.1', 5055)) == 0:
                raise WorkspaceError('Stop Mixamo Studio on port 5055 before switching the storage folder.')
        # Watcher can restart Flask mid-adoption; require it to be stopped.
        pid_file = Path(__file__).resolve().parents[1] / 'updates' / '.state' / 'watch.lock' / 'pid'
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text().strip()), 0)
            except (OSError, ValueError):
                pass
            else:
                raise WorkspaceError('Stop the continuous update watcher before switching storage.')
    destination = destination.resolve(strict=True)
    catalog_file = destination / 'library' / 'catalog.json'
    # Validate catalog BEFORE making any writes. A missing/unreadable index is
    # rebuildable; malformed structured metadata must not be silently lost.
    catalog = []
    if catalog_file.is_file():
        try:
            catalog = _read_json(catalog_file)
            if not isinstance(catalog, list):
                raise ValueError('not a list')
        except (WorkspaceError, ValueError, TypeError):
            catalog = []
            print('[workspace] Invalid catalogue; rebuilding from discovered GLBs. Original copied file will be backed up.')
    # Rewrite only known Mixamo metadata files. Presets and user JSON stay untouched.
    for path in _metadata_files(destination):
        if path == catalog_file:
            continue
        if path.stat().st_size > 16*1024*1024:
            continue
        try:
            payload = _read_json(path)
        except WorkspaceError:
            continue
        rewritten = _replace_paths(payload, str(source), str(destination))
        if rewritten != payload:
            _write_json_safely(path, rewritten)
    # Preserve all catalogue IDs, titles, originalId and existing screenshots.
    indexed = []
    indexed_paths = set()
    taken_ids = set()
    for entry in catalog:
        if not isinstance(entry, dict) or not ID_RE.fullmatch(str(entry.get('id', ''))):
            continue
        revised = _replace_paths(entry, str(source), str(destination))
        file = Path(str(revised.get('path', '')))
        if not file.is_file() or not _valid_glb(file) or revised['id'] in taken_ids:
            continue
        indexed.append(revised)
        indexed_paths.add(str(file.resolve()))
        taken_ids.add(revised['id'])
    for file in _glb_files(destination):
        resolved = str(file.resolve())
        if resolved in indexed_paths:
            continue
        entry = _canonical_entry(file, destination, source)
        # Avoid ID collisions (e.g. copied managed imports with same file stem).
        while entry['id'] in taken_ids:
            entry['id'] = uuid.uuid4().hex
        indexed.append(entry)
        indexed_paths.add(resolved)
        taken_ids.add(entry['id'])
    if not indexed and details['glbCount']:
        raise WorkspaceError('Could not build a valid catalogue from copied GLBs; storage was not switched.')
    catalog_file.parent.mkdir(parents=True, exist_ok=True)
    if not catalog_file.is_file() or indexed != catalog:
        _write_json_safely(catalog_file, indexed)
    # Register an identity marker so a disconnected external drive is never
    # silently replaced by a newly created empty folder on the laptop.
    marker_file = destination / MARKER
    if marker_file.exists():
        marker = _read_json(marker_file)
        if not isinstance(marker, dict) or not IDENTITY_RE.fullmatch(str(marker.get('workspaceId', ''))):
            raise WorkspaceError('Existing workspace marker has an invalid identity; configuration unchanged.')
        identity = marker['workspaceId']
    else:
        identity = uuid.uuid4().hex
        _write_json_safely(marker_file, {'schema':SCHEMA, 'workspaceId':identity, 'original':str(source),
                                         'created':datetime.now(timezone.utc).isoformat()})
    config_file = config or default_config()
    if config_file.is_symlink():
        raise WorkspaceError('Refusing to replace symlinked workspace configuration.')
    config_file.parent.mkdir(parents=True, exist_ok=True)
    _write_json_safely(config_file, {'schema':SCHEMA, 'path':str(destination), 'workspaceId':identity})
    os.chmod(config_file, 0o600)
    print(f'[workspace] READY: {len(indexed)} gallery entries. Storage switched to {destination}.')
    print(f'[workspace] Original remains untouched: {source}')
    return dict(details, galleryCount=len(indexed), activated=True)


def main():
    parser = argparse.ArgumentParser(description='Validate a MANUALLY copied workspace and repair gallery paths; never copy media.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='Show current configured workspace and mounted-drive status')
    action = commands.add_parser('adopt', aliases=['migrate'], help='Validate copied folder; optionally reindex and activate it')
    action.add_argument('--source', default=str(default_workspace()), help='Previous MixamoLocal folder')
    action.add_argument('--destination', required=True, help='ALREADY COPIED folder, e.g. /Volumes/SSD/MixamoLocal')
    action.add_argument('--activate', action='store_true', help='Repair copied metadata/gallery and select this folder for future builds')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            path, identity, origin = configured_workspace()
            checked = verify_workspace(path, identity)
            print(f'Workspace: {checked}\nConfiguration: {origin}\nStatus: AVAILABLE')
        else:
            adopt(Path(args.source), Path(args.destination), activate=args.activate)
    except (WorkspaceError, OSError, ValueError) as exc:
        parser.exit(2, f'[workspace ERROR] {exc}\n')


if __name__ == '__main__':
    main()
