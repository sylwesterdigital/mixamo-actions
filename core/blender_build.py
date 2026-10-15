"""Run via Blender -b --factory-startup -P blender_build.py -- --source-fbx ...

Builds a brand-new textured base scene directly from the original rigged FBX,
combines Mixamo FBX actions as separate NLA tracks, saves a .blend and exports
combined/per-action Three.js GLBs. Blender 4.x/5.x glTF parameters are detected.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import bpy

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.tga', '.exr'}


def log(message):
    print(f'[BLENDER] {message}', flush=True)


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('--source-fbx', required=True, type=Path)
    p.add_argument('--actions-dir', required=True, type=Path)
    p.add_argument('--output-dir', required=True, type=Path)
    p.add_argument('--base-armature', default='Base')
    p.add_argument('--ignore', nargs='*', default=[])
    p.add_argument('--draco-level', type=int, default=6)
    p.add_argument('--webp-quality', type=int, default=30)
    p.add_argument('--no-draco', action='store_true')
    p.add_argument('--no-webp', action='store_true')
    p.add_argument('--per-action', action='store_true')
    p.add_argument('--require-textures', action='store_true')
    args = p.parse_args(argv)
    args.source_fbx = args.source_fbx.resolve()
    args.actions_dir = args.actions_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    args.ignore = {x.casefold() for x in args.ignore}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'glb').mkdir(parents=True, exist_ok=True)
    return args


def snapshot():
    return set(bpy.data.objects), set(bpy.data.actions)


def import_fbx(file):
    before_objects, before_actions = snapshot()
    # Image search can work for both embedded media and relative sidecars.
    bpy.ops.import_scene.fbx(filepath=str(file), use_image_search=True)
    new_objects = [x for x in bpy.data.objects if x not in before_objects]
    new_actions = [x for x in bpy.data.actions if x not in before_actions]
    armatures = [x for x in new_objects if x.type == 'ARMATURE']
    meshes = [x for x in new_objects if x.type == 'MESH']
    if not armatures:
        raise RuntimeError(f'FBX contains no armature: {file.name}')
    main_arm = max(armatures, key=lambda obj: len(obj.data.bones))
    return {'objects': new_objects, 'actions': new_actions, 'armature': main_arm, 'meshes': meshes}


def bone_match(a, b):
    left = set(a.data.bones.keys())
    right = set(b.data.bones.keys())
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def remove_objects(objects):
    for obj in list(objects):
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)


def resolve_images(folder):
    """Repair missing FBX image paths from sidecar files extracted with ZIP."""
    candidates = {}
    for f in folder.rglob('*'):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            candidates.setdefault(f.name.casefold(), []).append(f)
    patched = []
    missing = []
    for image in bpy.data.images:
        if image.source != 'FILE' or image.packed_file:
            continue
        path = Path(bpy.path.abspath(image.filepath)) if image.filepath else None
        if path and path.is_file():
            continue
        # FBX paths may be Windows-like (C:\\foo\\img.png) on macOS.
        names = [Path(str(image.filepath).replace('\\', '/')).name, image.name]
        matches = next((candidates.get(n.casefold(), []) for n in names
                        if candidates.get(n.casefold())), [])
        if len(matches) == 1:
            image.filepath = str(matches[0])
            try:
                image.reload()
            except Exception as exc:
                log(f'Warning: could not reload texture {image.name}: {exc}')
            patched.append(image.name)
        else:
            missing.append(image.name)
    if patched:
        log(f'Relinked {len(patched)} texture(s) from character ZIP')
    if missing:
        log('WARNING: Missing image file(s): ' + ', '.join(missing))
    return missing


def texture_stats(meshes):
    mats = {slot.material for mesh in meshes for slot in mesh.material_slots if slot.material}
    images = set()
    for mat in mats:
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and getattr(node, 'image', None):
                    images.add(node.image)
    return len(mats), images


def mesh_material_transfer(original_meshes, animation_meshes):
    """Transfer source materials ONLY when mesh correspondence is unambiguous.

    Geometry counts + unique mesh name match are checked. For a single mesh,
    matching vertex/polygon counts are sufficient. This is not UV retargeting.
    """
    if not original_meshes or not animation_meshes:
        return 0, 0
    available = list(original_meshes)
    transferred = 0
    unmatched = 0
    for target in animation_meshes:
        topology = lambda o: (len(o.data.vertices), len(o.data.polygons))
        compatible = [src for src in available if topology(src) == topology(target)]
        tname = re.sub(r'\.\d{3}$', '', target.name).casefold()
        named = [src for src in compatible if re.sub(r'\.\d{3}$', '', src.name).casefold() == tname]
        source = named[0] if len(named) == 1 else compatible[0] if len(compatible) == 1 else None
        if source is None:
            unmatched += 1
            continue
        source_mats = [slot.material for slot in source.material_slots]
        if source_mats and any(source_mats):
            target.data.materials.clear()
            for mat in source_mats:
                target.data.materials.append(mat)
            transferred += 1
        available.remove(source)
    return transferred, unmatched


def action_for_import(item):
    arm = item['armature']
    ad = arm.animation_data
    act = ad.action if ad else None
    if act:
        return act
    if len(item['actions']) == 1:
        return item['actions'][0]
    raise RuntimeError('Could not uniquely identify armature action after import: ' +
                       ', '.join(a.name for a in item['actions']))


def attach_action(base, action, name):
    """Create NLA track from imported action while preserving its data-block."""
    action.name = name
    action.use_fake_user = True
    base.animation_data_create()
    ad = base.animation_data
    track = ad.nla_tracks.new()
    track.name = name
    strip = track.strips.new(name=name, start=0, action=action)
    # Slotted Actions in Blender 4.4+ may require an explicit slot.
    if getattr(action, 'slots', None) and hasattr(strip, 'action_slot') and strip.action_slot is None:
        slots = list(action.slots)
        if slots:
            strip.action_slot = slots[0]
    low, high = map(float, action.frame_range)
    strip.action_frame_start = low
    strip.action_frame_end = max(low + 1, high)
    strip.frame_start = 0
    strip.frame_end = max(1, int(round(high - low)))
    return track


def clear_active_animation(obj):
    if obj.animation_data:
        obj.animation_data.action = None


def options_for_export(args, animation_mode):
    op = bpy.ops.export_scene.gltf
    props = {p.identifier: p for p in op.get_rna_type().properties}
    kwargs = {
        'export_format': 'GLB', 'export_animations': True,
        'export_skins': True,
    }
    # Newer Blender glTF exporter uses an explicit NLA export mode.
    if 'export_animation_mode' in props:
        kwargs['export_animation_mode'] = animation_mode
    else:
        if animation_mode == 'NLA_TRACKS':
            kwargs['export_nla_strips'] = True
            kwargs['export_all_actions'] = False
        else:
            kwargs['export_nla_strips'] = False
            kwargs['export_all_actions'] = False
    if not args.no_draco:
        if 'export_draco_mesh_compression_enable' not in props:
            raise RuntimeError('This Blender glTF exporter does not offer Draco; rerun with --no-draco')
        kwargs['export_draco_mesh_compression_enable'] = True
        kwargs['export_draco_mesh_compression_level'] = args.draco_level
    if not args.no_webp:
        if 'export_image_format' not in props:
            raise RuntimeError('This Blender glTF exporter does not offer image format setting; use --no-webp')
        available = [i.identifier for i in props['export_image_format'].enum_items]
        if 'WEBP' not in available:
            raise RuntimeError('This Blender does not support exporting WebP; use --no-webp')
        kwargs['export_image_format'] = 'WEBP'
        if 'export_image_quality' in props:
            kwargs['export_image_quality'] = args.webp_quality
        elif 'export_webp_quality' in props:
            kwargs['export_webp_quality'] = args.webp_quality
    kwargs['export_texcoords'] = True
    kwargs['export_materials'] = 'EXPORT'
    # Some older bpy versions omit one or more settings above.
    return {key: val for key, val in kwargs.items() if key in props}


def export_glb(path, args, *, mode):
    settings = options_for_export(args, mode)
    settings['filepath'] = str(path)
    log(f'GLB export: {path.name} [mode={mode}]')
    result = bpy.ops.export_scene.gltf(**settings)
    if 'FINISHED' not in result or not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f'Blender GLB export did not finish: {path.name}')


def main():
    args = parse_args()
    clip_files = sorted(f for f in args.actions_dir.glob('*.fbx') if f.name.casefold() not in args.ignore)
    if not clip_files:
        raise RuntimeError('No FBX animation clips found')
    log(f'Blender {bpy.app.version_string} | original rig: {args.source_fbx.name}')
    log(f'Animation FBXs: {len(clip_files)}')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    source = import_fbx(args.source_fbx)
    original_arm = source['armature']
    original_meshes = source['meshes']
    if not original_meshes:
        raise RuntimeError('Original character FBX has no meshes, cannot produce textured character')
    resolve_images(args.source_fbx.parent)
    original_mats, original_image_nodes = texture_stats(original_meshes)
    log(f'Original character: {len(original_meshes)} mesh(es), {original_mats} material(s), '
        f'{len(original_image_nodes)} image texture(s)')
    if not original_mats:
        raise RuntimeError('Original character FBX has no materials; cannot preserve character appearance')

    # Read first WITH SKIN clip, which provides a skeleton guaranteed compatible
    # with subsequent Mixamo exports for the same uploaded character.
    first = import_fbx(clip_files[0])
    first_action = action_for_import(first)
    match = bone_match(original_arm, first['armature'])
    log(f'Original vs Mixamo skeleton agreement: {match:.0%}')
    if match >= 0.98:
        base = original_arm
        base_meshes = original_meshes
        log('Keeping original rig and ALL original mesh materials.')
    else:
        base = first['armature']
        base_meshes = first['meshes']
        if not base_meshes:
            raise RuntimeError('Mixamo first animation has no skin/mesh! Ensure With Skin is enabled.')
        transferred, unmatched = mesh_material_transfer(original_meshes, base_meshes)
        log(f'Using Mixamo-compatible rig; matched {transferred} original material mesh(es), '
            f'{unmatched} unmatched mesh(es)')
        if transferred < len(base_meshes):
            # A mismatch may yield white or wrong-looking GLBs; reject rather than silently shipping.
            raise RuntimeError('Cannot unambiguously transfer all original materials to the Mixamo meshes. '
                               'Check that the uploaded FBX and downloaded With Skin FBX represent the same mesh. '
                               'No GLB was exported.')
        remove_objects(source['objects'])
    base.name = args.base_armature
    if base.animation_data:
        clear_active_animation(base)
    tracks = []
    action_names = set()

    for index, clip in enumerate(clip_files):
        imported = first if index == 0 else import_fbx(clip)
        arm = imported['armature']
        similarity = bone_match(base, arm)
        if similarity < .98:
            raise RuntimeError(f'Animation {clip.name} has incompatible bones ({similarity:.0%}). '
                               'Make sure every animation was exported from the same Mixamo character.')
        action = first_action if index == 0 else action_for_import(imported)
        name = clip.stem
        if name.casefold() in action_names:
            raise RuntimeError(f'Duplicate animation name: {name}')
        action_names.add(name.casefold())
        track = attach_action(base, action, name)
        tracks.append((name, action, track))
        # Unlink animation from imported armature object before deleting it.
        # The NLA track and fake-user preserve the Action datablock.
        if arm != base:
            remove_objects(imported['objects'])
        else:
            clear_active_animation(base)
        log(f'Added NLA: {name} ({len(tracks)}/{len(clip_files)})')

    # NLA strips should be individual clips, not simultaneously blended.
    # Only NLA_TRACKS mode is used for combined GLB; no need for playable scene playback.
    mats, images = texture_stats(base_meshes)
    if not mats:
        raise RuntimeError('Output character has no materials')
    missing = resolve_images(args.source_fbx.parent)
    if args.require_textures and (not images or missing):
        raise RuntimeError('Original source lacks resolved image texture nodes. '
                           'Textures may not be embedded or FBX references may be broken.')
    material_report = {'base_meshes': len(base_meshes), 'material_count': mats,
                       'image_texture_nodes': len(images), 'missing_image_files': missing,
                       'source_material_count': original_mats,
                       'source_image_texture_nodes': len(original_image_nodes),
                       'source_rig_bone_agreement': match}
    report_path = args.output_dir / 'material_report.json'
    report_path.write_text(json.dumps(material_report, indent=2), encoding='utf-8')
    try:
        bpy.ops.file.pack_all()
    except Exception as exc:
        log(f'WARNING: Could not pack all images into .blend: {exc}')
    clear_active_animation(base)
    bpy.context.scene.frame_set(0)
    blend_path = args.output_dir / (args.output_dir.name + '-rework.blend')
    log(f'Saving generated Blender project: {blend_path.name}')
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path), compress=True)

    combined = args.output_dir / 'glb' / (args.output_dir.name + '-anims.glb')
    export_glb(combined, args, mode='NLA_TRACKS')

    if args.per_action:
        # ACTIVE_ACTIONS uses the single active action and avoids the old script's
        # issue where each per-action export could include all animations.
        for name, action, track in tracks:
            for _, _, t in tracks:
                t.mute = True
            base.animation_data.action = action
            # New slot-based Actions need a selected compatible slot.
            if getattr(action, 'slots', None) and hasattr(base.animation_data, 'action_slot'):
                slots = list(action.slots)
                if slots and base.animation_data.action_slot is None:
                    base.animation_data.action_slot = slots[0]
            path = args.output_dir / 'glb' / (name + '.glb')
            export_glb(path, args, mode='ACTIVE_ACTIONS')
        clear_active_animation(base)
        for _, _, t in tracks:
            t.mute = False

    log(f'Done: {len(tracks)} clip(s), {len(base_meshes)} mesh(es), '
        f'{mats} material(s), {len(images)} texture node(s)')


if __name__ == '__main__':
    main()
