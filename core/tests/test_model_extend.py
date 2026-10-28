"""Regression tests for safe, offline model augmentation and source isolation."""
import json
import sys
import tempfile
import zipfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_extend import extend_generated_model
from resume_state import ResumePlan, digest, valid_resume_command

FBX = b'Kaydara FBX Binary  \x00\x1a\x00' + bytes(1500)
BASE = [{'search':'idle','title':'Idle','motionId':'123456789','filename':'Idle__123456789'},
        {'search':'walk','title':'Walk','motionId':'123456788','filename':'Walk__123456788'}]
EXTRA = [{'search':'walk','title':'Walk','motionId':'123456788','filename':'Walk__123456788'},
         {'search':'dance','title':'Dance','motionId':'123456787','filename':'Dance__123456787'}]

class ExtendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.workspace=Path(self.tmp.name)
        self.home=self.workspace/'uploads'/'abcd1234'
        self.home.mkdir(parents=True)
        self.character=self.home/'rig.zip'
        self.character.write_bytes(b'still-the-original')
        self.exports=self.home/'rig-exports'
        (self.exports/'glb').mkdir(parents=True)
        (self.exports/'fbx').mkdir()
        self.glb=self.exports/'glb'/'rig-exports-anims.glb'
        self.glb.write_bytes(b'glTF' + bytes(1200))
        (self.exports/'manifest.json').write_text(json.dumps({'original_character':str(self.character)}))
        self.old_preset=self.home/'old.json'
        self.old_preset.write_text(json.dumps({'animations':BASE}))
        old=ResumePlan(self.exports/'fbx',BASE,source_sha256=digest(self.character),preset_sha256=digest(self.old_preset))
        for spec,name in old.expected:
            (self.exports/'fbx'/name).write_bytes(FBX)
            old.record(spec,name)
        self.new_preset=self.home/'new.json'
        self.new_preset.write_text(json.dumps({'animations':EXTRA}))
        self.entry={'source':'generated','path':str(self.glb),'name':'rig'}
    def tearDown(self):self.tmp.cleanup()
    def test_reuses_verified_originals_without_overwriting_base(self):
        before={p.name:p.read_bytes() for p in (self.exports/'fbx').glob('*.fbx')}
        result=extend_generated_model(self.entry,self.new_preset,self.workspace)
        self.assertEqual((result['previous'],result['added'],result['reused'],result['remaining']), (2,1,2,1))
        self.assertNotEqual(result['output'],self.exports)
        # tempfile uses /var/... on macOS, whereas Path.resolve() returns
        # /private/var/...; compare physical locations rather than spellings.
        self.assertEqual(result['output'].parent.resolve(),
                         (self.workspace/'extensions').resolve())
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.exports/'fbx').glob('*.fbx')})
        second=extend_generated_model(self.entry,self.new_preset,self.workspace)
        self.assertEqual(second['output'],result['output'])
        self.assertEqual(second['remaining'],1)
    def test_symlinked_workspace_alias_uses_canonical_extension_directory(self):
        # Exercise the same path-alias situation as macOS /var -> /private/var
        # on all platforms, without depending on the host OS's temp layout.
        with tempfile.TemporaryDirectory() as parent:
            alias = Path(parent) / 'workspace-alias'
            alias.symlink_to(self.workspace, target_is_directory=True)
            result = extend_generated_model(self.entry, self.new_preset, alias)
            self.assertEqual(result['output'].parent.resolve(),
                             (alias / 'extensions').resolve())
            self.assertTrue(result['output'].is_dir())
            self.assertTrue(self.glb.exists())
            self.assertEqual(len(list((self.exports / 'fbx').glob('*.fbx'))), 2)

    def test_rejects_unverified_models_and_changes(self):
        with self.assertRaisesRegex(ValueError,'no verified Mixamo source'):
            extend_generated_model({**self.entry,'source':'imported'},self.new_preset,self.workspace)
        self.character.write_bytes(b'changed model')
        with self.assertRaisesRegex(ValueError,'changed'):
            extend_generated_model(self.entry,self.new_preset,self.workspace)
    def test_damaged_existing_fbx_does_not_get_copied(self):
        clip=next((self.exports/'fbx').glob('*.fbx'))
        clip.write_bytes(b'garbage')
        with self.assertRaisesRegex(ValueError,'incomplete or damaged'):
            extend_generated_model(self.entry,self.new_preset,self.workspace)
    def test_duplicate_preset_is_noop(self):
        self.new_preset.write_text(json.dumps({'animations':[BASE[0]]}))
        with self.assertRaisesRegex(ValueError,'already in the model'):
            extend_generated_model(self.entry,self.new_preset,self.workspace)
    def test_legacy_export_reuses_verified_downloads_without_writing_original(self):
        # Releases predating the SHA-256 checkpoint wrote stage1 manifest.json.
        with zipfile.ZipFile(self.character,'w') as z:
            z.writestr('tripo/model.fbx', FBX)
        source=self.exports/'source_character'/'tripo'/'model.fbx'
        source.parent.mkdir(parents=True)
        source.write_bytes(FBX)
        checkpoint=self.exports/'fbx'/'.mixamo-resume.json'
        checkpoint.unlink()
        old_files={p.name:p.read_bytes() for p in (self.exports/'fbx').glob('*.fbx')}
        old_specs=BASE
        old_names=[x.name for x in (self.exports/'fbx').glob('*.fbx')]
        manifest={'successful':[
          {'requested':spec,'file':name,'status':'downloaded'}
          for spec,name in __import__('resume_state').planned(old_specs)
        ],'failed':[]}
        (self.exports/'fbx'/'manifest.json').write_text(json.dumps(manifest))
        result=extend_generated_model(self.entry,self.new_preset,self.workspace)
        self.assertEqual((result['reused'],result['remaining']), (2,1))
        self.assertFalse(checkpoint.exists(), 'Legacy source checkpoint must not be created or modified')
        self.assertEqual(old_files,{p.name:p.read_bytes() for p in (self.exports/'fbx').glob('*.fbx')})

    def test_resume_command_allows_only_matched_output(self):
        pipeline=self.workspace/'pipeline.py'
        args=[sys.executable,'-u',str(pipeline),'--character',str(self.character),
              '--animations',str(self.new_preset),'--out',str(self.home/'output')]
        self.assertTrue(valid_resume_command(args,executable=sys.executable,pipeline=pipeline,
          character=self.character,preset=self.new_preset,output=self.home/'output'))
        self.assertFalse(valid_resume_command(args,executable=sys.executable,pipeline=pipeline,
          character=self.character,preset=self.new_preset,output=self.home/'elsewhere'))
        self.assertFalse(valid_resume_command(args,executable=sys.executable,pipeline=pipeline,
          character=self.character,preset=self.new_preset))

if __name__=='__main__':unittest.main()
