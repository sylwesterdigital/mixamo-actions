"""End-to-end resume validation with fake local Blender and no browser/network."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mixamo_pipeline
from resume_state import ResumePlan, planned, digest

FBX = b'Kaydara FBX Binary  \x00\x1a\x00' + b'\0' * 2048
SPEC = [{'search':'stand','filename':'Standing Idle__131220901'},
        {'search':'swim','filename':'Swimming__110800901'}]


def glb(path, count):
    payload = {'meshes':[{}], 'skins':[{}], 'animations':[{'name':f'A{i}'} for i in range(count)]}
    content = json.dumps(payload).encode()
    content += b' ' * ((4 - (len(content) % 4)) % 4)
    path.write_bytes(struct.pack('<4sII',b'glTF',2,12+8+len(content)) +
                     struct.pack('<I4s',len(content),b'JSON') + content)


class ResumePipelineTests(unittest.TestCase):
    def test_complete_checkpoint_skips_mixamo_and_runs_blender(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            character = root / 'rig.fbx'
            character.write_bytes(FBX)
            preset = root / 'animations.json'
            preset.write_text(json.dumps({'animations':SPEC}))
            out = root / 'rig-exports'
            fbx = out / 'fbx'
            state = ResumePlan(fbx, SPEC, source_sha256=digest(character),preset_sha256=digest(preset))
            for spec, name in planned(SPEC):
                (fbx / name).write_bytes(FBX)
                state.record(spec, name)
            calls = []
            def fake_run(command, **kwargs):
                calls.append(command)
                self.assertTrue(any(str(part).endswith('/blender_build.py') for part in command))
                combined = out / 'glb' / (out.name + '-anims.glb')
                glb(combined, 2)
                return SimpleNamespace(returncode=0)
            with patch.object(mixamo_pipeline.subprocess,'run',side_effect=fake_run):
                result = mixamo_pipeline.main(['--character',str(character),
                    '--animations',str(preset),'--out',str(out),'--blender',sys.executable])
            self.assertEqual(result, 0)
            self.assertEqual(len(calls), 1, 'Should not launch the Mixamo browser again')
            self.assertTrue((out/'character_bundle.zip').is_file())
            self.assertEqual(json.loads((out/'manifest.json').read_text())['fbx_count'], 2)

    def test_v125_legacy_zip_recovers_completed_fbx_and_checks_source(self):
        import zipfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            character = root / 'frenchi1.zip'
            with zipfile.ZipFile(character, 'w') as z:
                z.writestr('tripo/model.fbx', FBX)
            preset = root / 'anim.json'
            preset.write_text(json.dumps({'animations': SPEC}))
            out = root / 'frenchi1-exports'
            staged = out / 'source_character/tripo/model.fbx'
            staged.parent.mkdir(parents=True)
            staged.write_bytes(FBX)
            fbxs = out / 'fbx'
            fbxs.mkdir()
            file = fbxs / planned(SPEC)[0][1]
            file.write_bytes(FBX)
            (fbxs/'manifest.json').write_text(json.dumps({
                'successful':[{'requested':SPEC[0], 'file':file.name}],
                'failed':[{'requested':SPEC[1], 'error':'Mixamo search timeout'}]}))
            with patch.object(mixamo_pipeline.subprocess, 'run',return_value=SimpleNamespace(returncode=1)) as runner:
                with self.assertRaisesRegex(RuntimeError, 'Mixamo downloader exited'):
                    mixamo_pipeline.main(['--character',str(character), '--animations',str(preset),
                                          '--out',str(out), '--blender',sys.executable])
                self.assertEqual(runner.call_count,1)
            from resume_state import ResumePlan
            checkpoint = ResumePlan(fbxs, SPEC, source_sha256=digest(character), preset_sha256=digest(preset))
            self.assertEqual(checkpoint.completed(), 1)
            self.assertEqual(checkpoint.missing(), [planned(SPEC)[1][1]])
            self.assertEqual(file.read_bytes(), FBX)

    def test_missing_clip_stops_before_blender_without_browser(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            character=root/'rig.fbx'; character.write_bytes(FBX)
            preset=root/'anims.json'; preset.write_text(json.dumps({'animations':SPEC}))
            out=root/'rig-exports'
            state=ResumePlan(out/'fbx', SPEC,source_sha256=digest(character),preset_sha256=digest(preset))
            (out/'fbx'/state.expected[0][1]).write_bytes(FBX)
            state.record(*state.expected[0])
            with patch.object(mixamo_pipeline.subprocess,'run') as runner:
                with self.assertRaisesRegex(RuntimeError,'1/2 animations still missing'):
                    mixamo_pipeline.main(['--character',str(character),'--animations',str(preset),
                        '--out',str(out),'--blender',sys.executable,'--skip-download'])
                runner.assert_not_called()

if __name__ == '__main__':unittest.main()
