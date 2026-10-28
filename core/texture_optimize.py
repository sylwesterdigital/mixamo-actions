"""Non-destructive glTF 2.0 GLB texture downscaling.

Rebuild bufferViews instead of appending images (which would leave bulky source
textures in the file). All accessor and animation bufferView indices are retained.
No external tools, Blender, network connections, or input-file modifications.
"""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import struct

from PIL import Image, ImageOps, UnidentifiedImageError

GLB_MAGIC = b'glTF'
JSON_CHUNK = b'JSON'
BIN_CHUNK = b'BIN\0'
MAX_GLB = 256 * 1024 * 1024
SCALES = {75, 50, 25}
MIME_FORMAT = {'image/png': 'PNG', 'image/jpeg': 'JPEG', 'image/webp': 'WEBP'}


class OptimizationError(ValueError):
    pass


def _pad(data: bytes, fill: bytes = b'\0') -> bytes:
    return data + fill * ((-len(data)) % 4)


def _unpack(path: Path):
    if path.stat().st_size > MAX_GLB:
        raise OptimizationError('GLB exceeds the 256 MiB optimization limit')
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != GLB_MAGIC:
        raise OptimizationError('Not a valid GLB file')
    magic, version, length = struct.unpack_from('<4sII', data)
    if version != 2 or length != len(data):
        raise OptimizationError('Invalid GLB version or file length')
    chunks = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise OptimizationError('Truncated GLB chunk header')
        size, kind = struct.unpack_from('<I4s', data, offset)
        offset += 8
        if offset + size > len(data):
            raise OptimizationError('Truncated GLB chunk')
        chunks.append((kind, data[offset:offset + size]))
        offset += size
    if len(chunks) != 2 or [k for k, _ in chunks] != [JSON_CHUNK, BIN_CHUNK]:
        raise OptimizationError('Only standard self-contained GLBs with JSON and BIN chunks are supported')
    try:
        document = json.loads(chunks[0][1].decode('utf-8').rstrip(' \t\r\n\x00'))
    except (ValueError, UnicodeDecodeError) as exc:
        raise OptimizationError('Invalid GLB JSON') from exc
    if not isinstance(document, dict) or document.get('asset', {}).get('version') != '2.0':
        raise OptimizationError('Invalid glTF 2.0 asset metadata')
    if 'EXT_meshopt_compression' in document.get('extensionsUsed', []):
        raise OptimizationError('Meshopt-compressed GLBs are not supported by this optimizer')
    buffers = document.get('buffers', [])
    if len(buffers) != 1 or buffers[0].get('uri'):
        raise OptimizationError('The GLB must have one embedded binary buffer')
    binary = chunks[1][1]
    declared = buffers[0].get('byteLength')
    if type(declared) is not int or declared < 0 or declared > len(binary):
        raise OptimizationError('GLB binary buffer length is invalid')
    return document, binary


def _encode_image(data: bytes, mime: str, percent: int):
    try:
        with Image.open(BytesIO(data)) as picture:
            if getattr(picture, 'n_frames', 1) != 1:
                raise OptimizationError('Animated textures are unsupported')
            old = picture.size
            if old[0] * old[1] > 67_108_864:
                raise OptimizationError('Texture exceeds the safe 64-megapixel optimization limit')
            picture.load()
            if old[0] < 1 or old[1] < 1:
                raise OptimizationError('Texture has invalid dimensions')
            new_size = (max(1, round(old[0] * percent / 100)),
                        max(1, round(old[1] * percent / 100)))
            # Do not silently recompress tiny 1x1 images.
            if new_size == old:
                return data, old, new_size
            if picture.mode not in ('RGBA', 'RGB', 'LA', 'L'):
                picture = picture.convert('RGBA' if 'A' in picture.getbands() or 'transparency' in picture.info else 'RGB')
            resized = picture.resize(new_size, Image.Resampling.LANCZOS)
            kwargs = {}
            if mime == 'image/jpeg':
                if resized.mode not in ('RGB', 'L'):
                    resized = resized.convert('RGB')
                kwargs.update(quality=88, optimize=True)
            elif mime == 'image/png':
                kwargs.update(optimize=True, compress_level=8)
            elif mime == 'image/webp':
                kwargs.update(quality=85, method=5)
            if picture.info.get('icc_profile'):
                kwargs['icc_profile'] = picture.info['icc_profile']
            out = BytesIO()
            resized.save(out, format=MIME_FORMAT[mime], **kwargs)
            return out.getvalue(), old, new_size
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        if isinstance(exc, OptimizationError):
            raise
        raise OptimizationError(f'Texture could not be decoded or resized: {exc}') from exc


def optimize_glb(source: Path, destination: Path, percent: int) -> dict:
    """Write a new GLB, never overwrite `source`. Return optimization statistics."""
    if type(percent) is not int or percent not in SCALES:
        raise OptimizationError('Select a texture size of 75%, 50%, or 25%')
    source = Path(source).resolve()
    destination = Path(destination)
    if source == destination.resolve() or destination.exists():
        raise OptimizationError('Output must be a new GLB file')
    doc, binary = _unpack(source)
    views = doc.get('bufferViews', [])
    images = doc.get('images', [])
    if not isinstance(views, list) or not isinstance(images, list):
        raise OptimizationError('Invalid GLB image or bufferView table')
    replacements = {}
    report = []
    external = 0
    # Reject ambiguous bufferViews shared by images and mesh accessors.
    used_by_accessor = {obj.get('bufferView') for obj in doc.get('accessors', []) if isinstance(obj, dict)}
    used_by_accessor.update(obj.get('indices', {}).get('bufferView') for obj in doc.get('accessors', []) if isinstance(obj, dict) and isinstance(obj.get('indices'), dict))
    used_by_accessor.update(obj.get('values', {}).get('bufferView') for obj in doc.get('accessors', []) if isinstance(obj, dict) and isinstance(obj.get('values'), dict))
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            raise OptimizationError('Invalid image metadata')
        if 'bufferView' not in image:
            external += 1
            continue
        mime = image.get('mimeType', '').lower()
        if mime not in MIME_FORMAT:
            raise OptimizationError(f'Unsupported embedded texture format: {mime or "unknown"}')
        idx = image['bufferView']
        if type(idx) is not int or not 0 <= idx < len(views) or idx in used_by_accessor:
            raise OptimizationError('Texture shares a bufferView with mesh data or references an invalid view')
        view = views[idx]
        if view.get('buffer') != 0:
            raise OptimizationError('Texture is not in the GLB binary buffer')
        offset, length = view.get('byteOffset', 0), view.get('byteLength', -1)
        if (type(offset) is not int or type(length) is not int or offset < 0 or
                length < 1 or offset + length > len(binary)):
            raise OptimizationError('Texture bufferView is out of bounds')
        if idx not in replacements:
            original = binary[offset:offset + length]
            encoded, old, new = _encode_image(original, mime, percent)
            replacements[idx] = encoded
        else:
            # Same bufferView can be referenced by more than one image, with identical MIME only.
            original = binary[offset:offset + length]
            with Image.open(BytesIO(original)) as picture:
                old = picture.size
            new = (max(1, round(old[0] * percent / 100)), max(1, round(old[1] * percent / 100)))
            encoded = replacements[idx]
        report.append({'image': image.get('name') or f'Texture {index + 1}', 'before': list(old), 'after': list(new), 'bytesBefore': length, 'bytesAfter': len(encoded)})
    if external:
        raise OptimizationError('This GLB references external textures. Import a self-contained GLB with embedded textures.')
    if not replacements:
        raise OptimizationError('This GLB has no embedded PNG, JPEG, or WebP textures to optimize')
    # All original bufferViews (geometry, Draco, skinning and animation) keep
    # their indices and raw payload; only their byteOffsets are recomputed.
    # The old image buffers are omitted, which actually reduces the output.
    repacked = bytearray()
    for index, view in enumerate(views):
        if not isinstance(view, dict) or view.get('buffer') != 0:
            raise OptimizationError('Only embedded bufferViews are supported')
        offset, length = view.get('byteOffset', 0), view.get('byteLength')
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0 or offset + length > len(binary):
            raise OptimizationError('Invalid GLB bufferView')
        payload = replacements.get(index, binary[offset:offset + length])
        repacked.extend(b'\0' * ((-len(repacked)) % 4))
        view['byteOffset'] = len(repacked)
        view['byteLength'] = len(payload)
        repacked.extend(payload)
    doc['buffers'][0]['byteLength'] = len(repacked)
    json_bytes = _pad(json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), b' ')
    bin_bytes = _pad(bytes(repacked))
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    if total > 0xFFFFFFFF or total > MAX_GLB:
        raise OptimizationError('Optimized GLB exceeds the supported size limit')
    output = (struct.pack('<4sII', GLB_MAGIC, 2, total) +
              struct.pack('<I4s', len(json_bytes), JSON_CHUNK) + json_bytes +
              struct.pack('<I4s', len(bin_bytes), BIN_CHUNK) + bin_bytes)
    # A write failure must not leave a partial, gallery-visible GLB.
    tmp = destination.with_name(destination.name + '.part')
    try:
        with tmp.open('xb') as handle:
            handle.write(output)
            handle.flush()
        tmp.replace(destination)
    finally:
        tmp.unlink(missing_ok=True)
    return {'percent': percent, 'textures': report, 'optimizedCount': len(replacements),
            'externalTextures': external, 'beforeBytes': source.stat().st_size,
            'afterBytes': destination.stat().st_size}
