#!/usr/bin/env python3
"""One-command Mixamo -> original rig/materials -> Blender NLA -> Three.js GLB.

Uses the user's signed-in Brave CDP session, not Adobe/Google cookies exported
from the browser. All outputs live BESIDE the character ZIP/FBX, not beside
this script. `--skip-download` reuses FBXs from the pipeline output directory.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.tga', '.exr'}
MAX_MEMBER = 1024 * 1024 * 1024
MAX_TOTAL = 3 * 1024 * 1024 * 1024
ROOT = Path(__file__).resolve().parent


def prepare_source(path: Path, dest: Path) -> tuple[Path, list[Path]]:
    """Extract rigged FBX + nearby textures, preserving ZIP subdirectories safely.

    No arbitrary files are unpacked. ZIP members cannot escape dest.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == '.fbx':
        output = dest / path.name
        if path.resolve() != output.resolve():
            shutil.copy2(path, output)
        textures = []
        # Keep likely sidecar texture directories available to Blender.
        for item in path.parent.iterdir():
            if item.is_file() and item.suffix.lower() in IMAGE_EXTS:
                target = dest / item.name
                if item.resolve() != target.resolve():
                    shutil.copy2(item, target)
                textures.append(target)
        return output, textures
    if path.suffix.lower() != '.zip':
        raise ValueError('Character must be a rigged .fbx or a .zip containing exactly one .fbx')
    with zipfile.ZipFile(path) as archive:
        members = []
        for info in archive.infolist():
            name = info.filename.replace('\\', '/')
            rel = Path(name)
            if info.is_dir() or name.startswith('/') or '..' in rel.parts or '__MACOSX' in rel.parts:
                continue
            if rel.name.startswith('._') or rel.suffix.lower() not in IMAGE_EXTS | {'.fbx'}:
                continue
            members.append((info, rel))
        fbxs = [(i, rel) for i, rel in members if rel.suffix.lower() == '.fbx']
        if len(fbxs) != 1:
            raise ValueError(f'Expected exactly one .fbx in character ZIP, found {len(fbxs)}')
        if sum(info.file_size for info, _ in members) > MAX_TOTAL:
            raise ValueError('Character archive exceeds 3 GiB decompression limit')
        paths = []
        for info, rel in members:
            if info.file_size > MAX_MEMBER:
                raise ValueError(f'ZIP member too large: {rel}')
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Defense in depth against traversal or symlinks.
            if not target.resolve().is_relative_to(dest.resolve()):
                raise ValueError(f'Unsafe ZIP path: {rel}')
            with archive.open(info) as reader, target.open('wb') as writer:
                shutil.copyfileobj(reader, writer)
            paths.append(target)
        base = dest / fbxs[0][1]
        return base, [f for f in paths if f.suffix.lower() in IMAGE_EXTS]


def inspect_glb(path: Path) -> dict:
    """Read GLB's JSON chunk without importing any third-party libraries."""
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError(f'{path.name}: truncated GLB')
        magic, version, length = struct.unpack('<4sII', header)
        if magic != b'glTF' or version != 2 or length != path.stat().st_size:
            raise ValueError(f'{path.name}: invalid GLB header/length')
        chunk_header = stream.read(8)
        if len(chunk_header) != 8:
            raise ValueError(f'{path.name}: no GLB JSON chunk')
        chunk_length, chunk_type = struct.unpack('<I4s', chunk_header)
        if chunk_type != b'JSON':
            raise ValueError(f'{path.name}: invalid GLB JSON chunk type')
        content = stream.read(chunk_length)
        if len(content) != chunk_length:
            raise ValueError(f'{path.name}: truncated JSON chunk')
        obj = json.loads(content.decode('utf-8'))
    data = {key: len(obj.get(key, [])) for key in ('scenes', 'nodes', 'skins', 'meshes', 'materials', 'textures', 'images', 'animations')}
    data['file'] = path.name
    data['bytes'] = path.stat().st_size
    data['animation_names'] = [item.get('name', '(unnamed)') for item in obj.get('animations', [])]
    data['extensionsUsed'] = obj.get('extensionsUsed', [])
    if not data['meshes'] or not data['skins'] or not data['animations']:
        raise ValueError(f'{path.name}: expected skinned meshes AND animations; got {data}')
    return data


def bundle(outdir: Path, manifest: dict):
    archive = outdir / 'character_bundle.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        # Do not double-pack previous archives or the source rig ZIP.
        for root in ('fbx', 'glb'):
            d = outdir / root
            if d.exists():
                for f in sorted(d.rglob('*')):
                    relative = f.relative_to(outdir)
                    if not f.is_file() or any(part.startswith('.') for part in relative.parts):
                        continue  # Never bundle quarantined, replaced animations.
                    if root == 'fbx' and f.suffix.lower() not in ('.fbx', '.json'):
                        continue
                    if f.suffix.lower() in ('.zip', '.blend1'):
                        continue
                    z.write(f, relative)
        for f in sorted(outdir.glob('*.blend')):
            z.write(f, f.relative_to(outdir))
        if (outdir / 'material_report.json').exists():
            z.write(outdir / 'material_report.json', 'material_report.json')
        z.writestr('manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False))
    return archive


def main(argv=None):
    p = argparse.ArgumentParser(description='Mixamo (Brave/Playwright) + Blender -> Three.js GLBs, one command')
    p.add_argument('--character', required=True, type=Path, help='Original rigged FBX or ZIP containing one FBX')
    p.add_argument('--animations', default=ROOT / 'animations.json', type=Path)
    p.add_argument('--cdp', default='http://127.0.0.1:9222', help='Existing signed-in Brave CDP endpoint')
    p.add_argument('--out', type=Path, help='Default: <character folder>/<character filename>-exports')
    p.add_argument('--blender', type=Path, default=Path('/Applications/Blender.app/Contents/MacOS/Blender'))
    p.add_argument('--skip-download', action='store_true', help='Build from already downloaded FBXs in <out>/fbx')
    p.add_argument('--skip-upload', action='store_true', help='Reuse the current character in signed-in Mixamo')
    p.add_argument('--confirm-upload', action='store_true', help='Pause for manual character-preview confirmation')
    p.add_argument('--continue-on-error', action='store_true', help='Allow missing downloads and build successes')
    p.add_argument('--manual-rig-timeout', type=int, default=900, help='Seconds allowed for manual rigging if Mixamo requires it')
    p.add_argument('--ignore', nargs='*', default=[], help='FBX filenames to ignore for Blender import')
    p.add_argument('--draco-level', type=int, default=6)
    p.add_argument('--webp-quality', type=int, default=30)
    p.add_argument('--no-draco', action='store_true')
    p.add_argument('--no-webp', action='store_true')
    p.add_argument('--per-action', action='store_true', help='Additional GLB for each action')
    p.add_argument('--require-textures', action='store_true', help='Fail if original has image textures but output does not')
    p.add_argument('--dry-run', action='store_true', help='Prepare source and show commands without launching browser or Blender')
    args = p.parse_args(argv)
    character = args.character.expanduser().resolve()
    if not character.is_file():
        p.error(f'Character does not exist: {character}')
    if not args.animations.expanduser().is_file():
        p.error(f'Animation list not found: {args.animations}')
    if not (0 <= args.draco_level <= 6 and 0 <= args.webp_quality <= 100):
        p.error('--draco-level must be 0..6 and --webp-quality 0..100')
    outdir = (args.out or character.parent / (character.stem + '-exports')).expanduser().resolve()
    fbx_dir, glb_dir, source_dir = outdir / 'fbx', outdir / 'glb', outdir / 'source_character'
    fbx_dir.mkdir(parents=True, exist_ok=True)
    glb_dir.mkdir(parents=True, exist_ok=True)
    source_fbx, textures = prepare_source(character, source_dir)
    print(f'[paths] Original character: {character}')
    print(f'[paths] All exports:       {outdir}')
    print(f'[source] Blender base:    {source_fbx} ({len(textures)} extracted texture(s))')
    browser_cmd = [sys.executable, str(ROOT / 'mixamo_browser.py'), '--character', str(source_fbx),
                   '--animations', str(args.animations.expanduser().resolve()), '--out', str(fbx_dir), '--cdp', args.cdp,
                   '--manual-rig-timeout', str(args.manual_rig_timeout)]
    if args.skip_upload:
        browser_cmd.append('--skip-upload')
    if args.continue_on_error:
        browser_cmd.append('--continue-on-error')
    if not args.confirm_upload:
        browser_cmd.append('--auto-confirm-character')
    blender_cmd = [str(args.blender.expanduser()), '-b', '--factory-startup', '-P', str(ROOT / 'blender_build.py'), '--',
                   '--source-fbx', str(source_fbx), '--actions-dir', str(fbx_dir), '--output-dir', str(outdir),
                   '--base-armature', 'Base', '--draco-level', str(args.draco_level),
                   '--webp-quality', str(args.webp_quality)]
    if args.no_draco:
        blender_cmd.append('--no-draco')
    if args.no_webp:
        blender_cmd.append('--no-webp')
    if args.per_action:
        blender_cmd.append('--per-action')
    if args.require_textures:
        blender_cmd.append('--require-textures')
    if args.ignore:
        blender_cmd.extend(['--ignore', *args.ignore])
    if args.dry_run:
        print('[dry-run] Browser command:', ' '.join(map(shlex_quote, browser_cmd)))
        print('[dry-run] Blender command:', ' '.join(map(shlex_quote, blender_cmd)))
        return 0
    if not args.skip_download:
        print('[phase 1/3] Mixamo download')
        ret = subprocess.run(browser_cmd, check=False).returncode
        if ret and not args.continue_on_error:
            raise RuntimeError(f'Mixamo downloader exited {ret}; Blender stage not started. Rerun to resume.')
    else:
        print('[phase 1/3] Using existing FBX downloads (--skip-download)')
    clips = sorted(p for p in fbx_dir.glob('*.fbx') if p.is_file() and p.stat().st_size)
    if not clips:
        raise RuntimeError(f'No FBX animation files in {fbx_dir}; nothing to build')
    if not args.blender.expanduser().is_file():
        raise FileNotFoundError(f'Blender executable not found: {args.blender}. Use --blender /path/to/Blender')
    print(f'[phase 2/3] Blender: {len(clips)} FBX files')
    # Remove old generated GLBs so the next validation cannot report stale files.
    for previous in glb_dir.glob('*.glb'):
        previous.unlink()
    subprocess.run(blender_cmd, check=True)
    glbs = sorted(glb_dir.glob('*.glb'))
    if not glbs:
        raise RuntimeError(f'Blender produced no GLBs in {glb_dir}')
    print('[phase 3/3] Verify GLB + archive')
    reports = [inspect_glb(f) for f in glbs]
    combined_name = outdir.name + '-anims.glb'
    combined_report = next((r for r in reports if r['file'] == combined_name), None)
    expected_animations = sum(f.name.casefold() not in {x.casefold() for x in args.ignore} for f in clips)
    if not combined_report or combined_report['animations'] != expected_animations:
        raise RuntimeError(f'Combined GLB should contain {expected_animations} animations, '
                           f'but contains {combined_report["animations"] if combined_report else "none"}. '
                           'Check NLA export mode and source FBX actions.')
    if args.per_action:
        wrong = [r['file'] for r in reports if r['file'] != combined_name and r['animations'] != 1]
        if wrong:
            raise RuntimeError(f'Per-action GLBs must contain exactly one clip; invalid: {wrong}')
    material_report_path = outdir / 'material_report.json'
    material_report = json.loads(material_report_path.read_text(encoding='utf-8')) if material_report_path.exists() else {}
    expects_image = bool(textures or material_report.get('source_image_texture_nodes', 0))
    if expects_image and any(not r['images'] or not r['textures'] for r in reports):
        raise RuntimeError('Source character contains image textures but one or more GLBs lack embedded textures. '
                           'Inspect original FBX texture paths and material_report.json. No final bundle created.')
    if args.require_textures and (not material_report.get('image_texture_nodes') or not all(r['images'] for r in reports)):
        raise RuntimeError('--require-textures: No resolved image textures on the base character or inside GLB')
    for r in reports:
        print(f"[glb] {r['file']}: {r['animations']} animation(s), {r['meshes']} mesh(es), "
              f"{r['materials']} material(s), {r['textures']} texture(s)")
    manifest = {
        'created': datetime.now(timezone.utc).isoformat(), 'original_character': str(character),
        'outputs': str(outdir), 'fbx_count': len(clips), 'glbs': reports, 'materials': material_report,
        'warnings': (['Source ZIP had textures but one or more GLBs lack embedded images; inspect original FBX material links.']
                     if textures and any(not r['images'] for r in reports) else []),
        'notes': 'Materials come from the original source rig when skeletons match; downloaded animation meshes are discarded. '
                 'When skeletons differ, compatible animation mesh/rig is used and material slots are transferred only on confident mesh matches.'
    }
    (outdir / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    archive = bundle(outdir, manifest)
    print(f'[done] {archive}')
    return 0


def shlex_quote(s):
    import shlex
    return shlex.quote(str(s))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(1)
