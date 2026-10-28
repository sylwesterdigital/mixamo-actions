"""Self-contained GLB optimizer invariants: preserve geometry and animations."""
import json
import random
import struct
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from texture_optimize import _unpack, optimize_glb, OptimizationError


def build_glb_fixture(path: Path, *, with_images=True):
    rng = random.Random(4201)
    geometry = bytes(range(256)) * 3
    animation = (b'animation-frames-' * 67)
    images = []
    views = []
    bin_data = bytearray()

    def append(payload):
        bin_data.extend(b'\0' * ((-len(bin_data)) % 4))
        idx = len(views)
        views.append({'buffer': 0, 'byteOffset': len(bin_data), 'byteLength': len(payload)})
        bin_data.extend(payload)
        return idx

    vertex_view = append(geometry)
    animation_view = append(animation)
    if with_images:
        for kind in ('PNG', 'JPEG', 'WEBP'):
            image = Image.new('RGBA' if kind == 'PNG' else 'RGB', (192, 256))
            pixel_data = bytearray(rng.getrandbits(8) for _ in range(192*256*(4 if kind == 'PNG' else 3)))
            image.frombytes(bytes(pixel_data))
            raw = BytesIO()
            image.save(raw, format=kind, quality=95) if kind != 'PNG' else image.save(raw, format='PNG')
            image_view = append(raw.getvalue())
            images.append({'bufferView': image_view, 'mimeType': {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[kind], 'name': kind})
    doc = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(bin_data)}],
           'bufferViews': views,
           'accessors': [{'bufferView': vertex_view, 'componentType': 5121, 'count': 10, 'type': 'SCALAR'},
                         {'bufferView': animation_view, 'componentType': 5121, 'count': 10, 'type': 'SCALAR'}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
           'animations': [{'name': 'Walk', 'channels': [{'sampler': 0, 'target': {'node': 0, 'path': 'translation'}}],
                           'samplers': [{'input': 1, 'output': 1}]}],
           'images': images, 'materials': [{'name': 'Outfit', 'pbrMetallicRoughness': {'baseColorFactor': [1,1,1,1]}}],
           'skins': [{'joints': [0]}], 'nodes': [{'name': 'Rig'}]}
    json_bytes = json.dumps(doc, separators=(',', ':')).encode()
    json_bytes += b' ' * ((-len(json_bytes)) % 4)
    bin_data.extend(b'\0' * ((-len(bin_data)) % 4))
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, total) + struct.pack('<I4s', len(json_bytes), b'JSON') + json_bytes +
                     struct.pack('<I4s', len(bin_data), b'BIN\0') + bytes(bin_data))
    return doc


def view_bytes(doc, binary, idx):
    view = doc['bufferViews'][idx]
    return binary[view['byteOffset']:view['byteOffset'] + view['byteLength']]


class TextureOptimizationTests(unittest.TestCase):
    def test_scale_three_formats_and_preserve_geometry_animations_and_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base/'original.glb'
            build_glb_fixture(source)
            input_bytes = source.read_bytes()
            before, source_bin = _unpack(source)
            for percent in (75, 50, 25):
                output = base/f'model-o{percent}.glb'
                report = optimize_glb(source, output, percent)
                after, new_bin = _unpack(output)
                self.assertEqual(report['optimizedCount'], 3)
                self.assertLess(output.stat().st_size, source.stat().st_size)
                for property in ('meshes', 'animations', 'materials', 'skins', 'nodes', 'accessors'):
                    self.assertEqual(after[property], before[property])
                for idx in (0, 1):
                    self.assertEqual(view_bytes(before, source_bin, idx), view_bytes(after, new_bin, idx))
                for image in after['images']:
                    idx = image['bufferView']
                    payload = view_bytes(after, new_bin, idx)
                    with Image.open(BytesIO(payload)) as loaded:
                        self.assertEqual(loaded.size, (round(192*percent/100), round(256*percent/100)))
                self.assertEqual(source.read_bytes(), input_bytes)

    def test_png_alpha_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'a.glb', Path(tmp)/'b.glb'
            build_glb_fixture(src)
            optimize_glb(src, out, 50)
            doc, blob = _unpack(out)
            png_view = doc['images'][0]['bufferView']
            with Image.open(BytesIO(view_bytes(doc, blob, png_view))) as image:
                self.assertIn('A', image.getbands())

    def test_invalid_percent_and_no_images_fail_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'a.glb', Path(tmp)/'b.glb'
            build_glb_fixture(src, with_images=False)
            for value in (None, '50', 15, 100, True):
                with self.assertRaises(OptimizationError):
                    optimize_glb(src, out, value)
            with self.assertRaisesRegex(OptimizationError, 'no embedded'):
                optimize_glb(src, out, 50)
            self.assertFalse(out.exists())

    def test_rejects_file_overwrite_and_malformed_glb(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)/'a.glb'
            build_glb_fixture(src)
            with self.assertRaisesRegex(OptimizationError, 'new GLB'):
                optimize_glb(src, src, 75)
            missing = Path(tmp)/'b.glb'
            missing.write_bytes(b'glTF' + bytes(30))
            with self.assertRaisesRegex(OptimizationError, 'Invalid GLB'):
                optimize_glb(missing, Path(tmp)/'output.glb', 75)

    def test_rejects_external_textures(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'a.glb', Path(tmp)/'b.glb'
            build_glb_fixture(src, with_images=False)
            # Recreate valid image metadata pointing outside GLB.
            import struct
            raw = src.read_bytes()
            doc, blob = _unpack(src)
            doc['images'] = [{'uri':'texture.png'}]
            j = json.dumps(doc).encode(); j += b' ' * ((-len(j)) % 4)
            total=12+8+len(j)+8+len(blob)
            src.write_bytes(struct.pack('<4sII',b'glTF',2,total)+struct.pack('<I4s',len(j),b'JSON')+j+
                            struct.pack('<I4s',len(blob),b'BIN\0')+blob)
            with self.assertRaisesRegex(OptimizationError, 'external textures'):
                optimize_glb(src, out, 75)
            self.assertFalse(out.exists())


if __name__ == '__main__': unittest.main()
