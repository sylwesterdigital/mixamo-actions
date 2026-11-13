"""Manual-copy workspace adoption: never copy/delete media, preserve gallery."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from workspace_storage import (WorkspaceError, adopt, inspect, configured_workspace,
                               verify_workspace, _external_volume, _replace_paths, MARKER)


class ManualWorkspaceTests(unittest.TestCase):
    def setUp(self):
        # A workspace override is a legitimate production safety check,
        # but a separate Flask test may set one while testing in-process.
        # These fixtures must be independent of that inherited environment.
        env = patch.dict(os.environ, {'MIXAMO_FLASK_WORKSPACE': ''})
        env.start()
        self.addCleanup(env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'mac' / 'MixamoLocal'
        self.dest = self.root / 'external' / 'MixamoLocal'
        self.source.mkdir(parents=True)
        self.config = self.root / 'settings' / 'workspace.json'
        self.glb = self.source / 'uploads' / 'job' / 'avatar-exports' / 'glb' / 'avatar-exports-anims.glb'
        self.glb.parent.mkdir(parents=True)
        # Minimal structurally correct binary GLB header, 20 bytes total.
        self.glb.write_bytes(b'glTF' + (2).to_bytes(4,'little') + (20).to_bytes(4,'little') + b'0'*8)
        self.fbx = self.source / 'uploads' / 'job' / 'avatar-exports' / 'fbx' / 'Idle.fbx'
        self.fbx.parent.mkdir(parents=True)
        self.fbx.write_bytes(b'Kaydara FBX Binary  \x00\x1a\x00' + b'0'*100)
        self.preset = self.source / 'presets' / 'male.json'
        self.preset.parent.mkdir(parents=True)
        self.preset.write_text('{"animations":[{"search":"idle"}]}')
        self.catalog = self.source / 'library' / 'catalog.json'
        self.catalog.parent.mkdir()
        self.original_id = 'cafebeef' * 3
        self.catalog.write_text(json.dumps([{'id':self.original_id, 'name':'Custom Model', 'path':str(self.glb),
                                            'source':'generated', 'created':'2026-01-01T00:00:00+00:00', 'clips':25}]))
        self.thumb = self.source / 'library' / 'thumbnails' / (self.original_id + '.webp')
        self.thumb.parent.mkdir()
        self.thumb.write_bytes(b'RIFF'+b'0'*8+b'WEBP')
        self.manifest = self.source / 'uploads' / 'job' / 'avatar-exports' / 'manifest.json'
        self.manifest.write_text(json.dumps({'original_character':str(self.source/'uploads/job/avatar.zip')}))
        self.job = self.source / '.mixamo-last-job.json'
        self.job.write_text(json.dumps({'schema':1, 'character':str(self.source/'uploads/job/avatar.zip'),
                                        'preset':str(self.preset), 'output':str(self.glb.parent.parent),
                                        'command':['python3','-u','pipeline.py',str(self.source/'uploads/job/avatar.zip')]}))
        (self.source/'library'/'files').mkdir()
        self.before = {str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}

    def copy_manually(self):
        self.dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(self.source,self.dest)

    def test_dry_run_checks_existing_copy_but_does_not_mutate(self):
        with self.assertRaisesRegex(WorkspaceError, 'Copy it manually first'):
            inspect(self.source,self.dest)
        self.copy_manually()
        checked = adopt(self.source,self.dest,config=self.config,check_server=False)
        self.assertEqual(checked['glbCount'],1)
        self.assertFalse(self.config.exists())
        self.assertFalse((self.dest/MARKER).exists())
        self.assertEqual((self.dest/'library/catalog.json').read_bytes(),self.catalog.read_bytes())

    def test_adopt_manual_copy_preserves_gallery_metadata_and_original(self):
        self.copy_manually()
        result = adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        self.assertEqual(result['galleryCount'],1)
        models=json.loads((self.dest/'library/catalog.json').read_text())
        self.assertEqual(models[0]['id'],self.original_id)
        self.assertEqual(models[0]['name'],'Custom Model')
        self.assertEqual(models[0]['clips'],25)
        self.assertEqual(models[0]['path'],str(self.dest/self.glb.relative_to(self.source)))
        self.assertEqual((self.dest/self.thumb.relative_to(self.source)).read_bytes(),self.thumb.read_bytes())
        job=json.loads((self.dest/'.mixamo-last-job.json').read_text())
        self.assertEqual(job['preset'],str(self.dest/self.preset.relative_to(self.source)))
        self.assertEqual(job['command'][-1],str(self.dest/'uploads/job/avatar.zip'))
        self.assertEqual(json.loads((self.dest/self.manifest.relative_to(self.source)).read_text())['original_character'],
                         str(self.dest/'uploads/job/avatar.zip'))
        self.assertEqual({str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()},self.before)
        cfg = json.loads(self.config.read_text())
        self.assertEqual(verify_workspace(self.dest,cfg['workspaceId']),self.dest)
        self.assertTrue((self.dest/'library/catalog.json.before-workspace-adoption').exists())
        self.assertEqual(self.glb.stat().st_size,(self.dest/self.glb.relative_to(self.source)).stat().st_size)
        # Idempotent on a repeat activation, no new entries.
        self.assertEqual(adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)['galleryCount'],1)

    def test_rebuild_missing_gallery_from_glbs(self):
        self.copy_manually()
        (self.dest/'library/catalog.json').unlink()
        result = adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        self.assertEqual(result['galleryCount'],1)
        model=json.loads((self.dest/'library/catalog.json').read_text())[0]
        self.assertEqual(model['source'],'generated')
        self.assertEqual(model['path'],str(self.dest/self.glb.relative_to(self.source)))
        # Rebuilt ID matches the previous generated key when original thumbnail is available.
        self.assertTrue(Path(model['path']).is_file())
        self.assertTrue(self.config.is_file())

    def test_rebuild_missing_catalog_with_managed_import(self):
        self.copy_manually()
        managed=self.dest/'library/files'/('b'*32+'.glb')
        managed.write_bytes(self.glb.read_bytes())
        (self.dest/'library/catalog.json').unlink()
        result=adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        self.assertEqual(result['galleryCount'],2)
        models=json.loads((self.dest/'library/catalog.json').read_text())
        self.assertIn('b'*32,{m['id'] for m in models})

    def test_incomplete_copy_is_rejected_without_changing_config(self):
        self.copy_manually()
        (self.dest/self.fbx.relative_to(self.source)).unlink()
        with self.assertRaisesRegex(WorkspaceError,'incomplete'):
            adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        self.assertFalse(self.config.exists())
        self.assertFalse((self.dest/MARKER).exists())
        self.assertTrue(self.fbx.exists())

    def test_source_unmodified_on_invalid_catalog_and_rebuild(self):
        self.copy_manually()
        (self.dest/'library/catalog.json').write_text('{invalid')
        result=adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        self.assertEqual(result['galleryCount'],1)
        self.assertEqual((self.dest/'library/catalog.json.before-workspace-adoption').read_text(),'{invalid')
        self.assertEqual(self.catalog.read_bytes(),self.before['library/catalog.json'])

    def test_drive_identity_prevents_silent_fallback(self):
        self.copy_manually()
        adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        saved=json.loads(self.config.read_text())
        (self.dest/MARKER).unlink()
        with self.assertRaisesRegex(WorkspaceError,'Invalid JSON|identity'):
            verify_workspace(self.dest,saved['workspaceId'])

    def test_env_priority_and_missing_mount(self):
        self.copy_manually()
        adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        with patch.dict(os.environ,{'MIXAMO_WORKSPACE_CONFIG':str(self.config),'MIXAMO_FLASK_WORKSPACE':''}):
            p, ident, origin=configured_workspace()
            self.assertEqual(origin,'config')
            self.assertEqual(verify_workspace(p,ident),self.dest)
        with patch.dict(os.environ,{'MIXAMO_FLASK_WORKSPACE':str(self.source)}):
            self.assertEqual(configured_workspace()[2],'environment')
        disk=Path('/Volumes/AbsentTestDrive')
        with self.assertRaisesRegex(WorkspaceError,'not mounted'):
            verify_workspace(disk/'MixamoLocal',None,mount_check=lambda name:False)
        self.assertEqual(_external_volume(disk/'MixamoLocal'),disk)

    def test_explicit_override_still_blocks_activation(self):
        """Real user-supplied overrides are never silently displaced."""
        self.copy_manually()
        with patch.dict(os.environ, {'MIXAMO_FLASK_WORKSPACE': str(self.source)}):
            with self.assertRaisesRegex(WorkspaceError, 'override is set'):
                adopt(self.source, self.dest, activate=True, config=self.config,
                      check_server=False)
        self.assertFalse(self.config.exists())
        self.assertFalse((self.dest / MARKER).exists())

    def test_reject_destination_symlink_and_nested(self):
        self.copy_manually()
        (self.dest/'out').symlink_to(self.source,target_is_directory=True)
        with self.assertRaisesRegex(WorkspaceError,'Unsafe symlink'):
            adopt(self.source,self.dest,activate=True,config=self.config,check_server=False)
        (self.dest/'out').unlink()
        with self.assertRaisesRegex(WorkspaceError,'different, non-nested'):
            adopt(self.source,self.source/'child',activate=True,config=self.config,check_server=False)

    def test_only_rebase_paths_anchored_to_old_root(self):
        old=str(self.source)
        self.assertEqual(_replace_paths('prefix '+old+'/abc',old,str(self.dest)),'prefix '+old+'/abc')
        self.assertEqual(_replace_paths(old+'/abc',old,str(self.dest)),str(self.dest)+'/abc')

if __name__=='__main__': unittest.main()
