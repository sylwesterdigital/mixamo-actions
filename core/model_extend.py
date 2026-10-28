"""Safe action-extension plan for an existing locally generated character.

Never edits the original export folder or glb. Existing FBXs are reused only
when their recorded Mixamo download checkpoint validates byte-for-byte.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from resume_state import ResumePlan, digest, planned, verify_fbx


def animation_identity(spec):
    if isinstance(spec, str):
        return ('text', spec.strip().casefold())
    if spec.get('motionId'):
        return ('motion', str(spec['motionId']).strip())
    return ('label', str(spec.get('filename') or spec.get('title') or spec.get('search') or '').strip().casefold())


def extend_generated_model(entry: dict, new_preset: Path, workspace: Path) -> dict:
    """Prepare an isolated, resumable extension and return its pipeline inputs.

    This function writes only under the local Mixamo workspace. It does not
    touch original FBXs, GLBs, the Rantlist API, or any remote machine.
    """
    if entry.get('source') != 'generated':
        raise ValueError('This GLB has no verified Mixamo source. Use the original character ZIP/FBX to add animations.')
    workspace = Path(workspace).resolve()
    glb = Path(entry['path']).resolve(strict=True)
    exports = glb.parent.parent
    if glb.parent.name != 'glb' or glb.name != exports.name + '-anims.glb':
        raise ValueError('Generated model has no recognized export folder.')
    try:
        manifest = json.loads((exports / 'manifest.json').read_text(encoding='utf-8'))
        character = Path(manifest['original_character']).expanduser().resolve(strict=True)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise ValueError('Original Mixamo source manifest is unavailable. The GLB was not changed.') from exc
    if not character.is_file() or character.suffix.lower() not in {'.fbx', '.zip'}:
        raise ValueError('Original character ZIP/FBX is unavailable.')
    original_hash = digest(character)
    fbx_source = exports / 'fbx'
    checkpoint_file = fbx_source / '.mixamo-resume.json'
    if checkpoint_file.is_file():
        try:
            info = json.loads(checkpoint_file.read_text(encoding='utf-8'))
            old_specs = info['requested']
            if info.get('schema') != 1 or info.get('source_sha256') != original_hash:
                raise ValueError('Original character file changed. Existing animation files will not be reused.')
            completed = info['completed']
            if not isinstance(completed, dict):
                raise ValueError('Invalid original animation checkpoint.')
            old_files = planned(old_specs)
            if any(not verify_fbx(fbx_source / name) or
                   not isinstance(completed.get(name),dict) or
                   completed[name].get('spec') != spec or
                   completed[name].get('size') != (fbx_source/name).stat().st_size or
                   completed[name].get('sha256') != digest(fbx_source/name)
                   for spec,name in old_files):
                raise ValueError('Original animation downloads are incomplete or damaged; resume the original build first.')
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f'Cannot safely reuse old animation downloads: {exc}') from exc
    else:
        # Pre-1.2.6 exports use a Mixamo download manifest. First verify the
        # original extracted FBX matches the source archive (no source mix-ups).
        from mixamo_pipeline import verify_legacy_source
        try:
            verify_legacy_source(character, exports / 'source_character')
            legacy = json.loads((fbx_source / 'manifest.json').read_text(encoding='utf-8'))
            successful = legacy['successful']
            old_specs = [row['requested'] for row in successful]
            old_files = planned(old_specs)
            evidence = {(row['file'], json.dumps(row['requested'],sort_keys=True)) for row in successful}
            if not old_files or not all(isinstance(s,dict) and
                    (name,json.dumps(s,sort_keys=True)) in evidence and verify_fbx(fbx_source/name)
                    for s,name in old_files):
                raise ValueError('Legacy animation download manifest does not match the saved FBXs.')
            if set(p.name for p in fbx_source.glob('*.fbx')) != set(name for _,name in old_files):
                raise ValueError('Legacy export contains untracked animation FBXs.')
        except (OSError,KeyError,TypeError,ValueError) as exc:
            raise ValueError(f'Cannot safely reuse legacy animations: {exc}') from exc
    if not isinstance(old_specs,list) or not old_specs or not all(isinstance(s,dict) for s in old_specs):
        raise ValueError('Original animation checkpoint is invalid.')
    original_files = {json.dumps(s,sort_keys=True):name for s,name in old_files}
    raw = json.loads(Path(new_preset).read_text(encoding='utf-8'))
    additions = raw.get('animations') if isinstance(raw, dict) else raw
    if not isinstance(additions, list) or not additions:
        raise ValueError('Select a nonempty animation preset.')
    # Maintain exact original entries, their order and file names.
    seen = {animation_identity(s) for s in old_specs}
    all_specs = list(old_specs)
    added = 0
    for spec in additions:
        if not isinstance(spec, dict) or not (spec.get('search') or spec.get('title')):
            raise ValueError('Animation preset contains an invalid entry.')
        key = animation_identity(spec)
        if key not in seen:
            all_specs.append(spec)
            seen.add(key)
            added += 1
    if not added:
        raise ValueError('Every animation in this preset is already in the model. No new clips to download.')
    # Stable, isolated output path for the same source + requested extension.
    raw_combined = json.dumps({'animations':all_specs}, sort_keys=True, ensure_ascii=False).encode('utf-8')
    key = hashlib.sha256((str(glb) + ':' + original_hash + ':').encode() + raw_combined).hexdigest()[:12]
    destination = workspace / 'extensions' / f'{exports.name}-extended-{key}'
    if not destination.resolve().is_relative_to(workspace / 'extensions'):
        raise ValueError('Extension destination is outside the local workspace.')
    destination.mkdir(parents=True, exist_ok=True)
    preset = destination / 'animations-merged.json'
    if preset.exists():
        if preset.read_bytes() != raw_combined + b'\n':
            raise ValueError('Existing extension preset differs. Original files were preserved.')
    else:
        preset.write_bytes(raw_combined + b'\n')
    fbx_dir = destination / 'fbx'
    fbx_dir.mkdir(exist_ok=True)
    target = ResumePlan(fbx_dir, all_specs, source_sha256=original_hash, preset_sha256=digest(preset))
    target.ensure_no_untracked()
    # A filename collision between different specs must never create a bad reuse.
    old_by_spec = original_files
    reused = 0
    for spec, dest_name in target.expected:
        old_name = old_by_spec.get(json.dumps(spec, sort_keys=True))
        if not old_name:
            continue
        dest = fbx_dir / dest_name
        if target.valid(spec, dest_name):
            reused += 1
            continue
        if dest.exists():
            raise ValueError('Existing extension FBX failed validation: ' + dest.name)
        # Copy, never hard-link: later modification must not damage base exports.
        shutil.copyfile(exports / 'fbx' / old_name, dest)
        target.record(spec, dest_name)
        reused += 1
    return dict(character=character, preset=preset, output=destination,
                previous=len(old_specs), added=added, reused=reused, total=len(all_specs),
                remaining=len(target.missing()))
