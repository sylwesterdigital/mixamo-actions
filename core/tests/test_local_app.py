"""Run with `python -m unittest discover -s tests -v` after installing requirements."""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FlaskLocalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ['MIXAMO_FLASK_WORKSPACE'] = str(Path(cls.temp.name) / 'workspace')
        import flask_app
        cls.mod = flask_app
        cls.client = flask_app.app.test_client()
        cls.headers = {'X-Local-Token': flask_app.APP_TOKEN, 'Host': '127.0.0.1:5055'}

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_home(self):
        response = self.client.get('/', headers={'Host': '127.0.0.1:5055'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'MIXAMO', response.data)
        self.assertIn(b'sceneCanvas', response.data)
        self.assertIn(b'guiMount', response.data)

    def test_release_information(self):
        response = self.client.get('/api/release', headers={'Host': '127.0.0.1:5055'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['version'], json.loads((ROOT.parent / 'release.json').read_text())['version'])
        self.assertTrue(response.json['changes'])
        notification = self.client.get('/static/release-watch.js', headers={'Host': '127.0.0.1:5055'})
        self.assertEqual(notification.status_code, 200)
        self.assertIn(b'Reload studio', notification.data)

    def test_rantlist_gallery_routes_are_token_protected(self):
        forbidden = self.client.get('/api/rantlist/assets',headers={'Host':'127.0.0.1:5055'})
        self.assertEqual(forbidden.status_code,403)
        self.assertEqual(self.client.post('/api/rantlist/connect',data=b'{}',
            headers={'Host':'127.0.0.1:5055'}).status_code,403)

    def test_rantlist_remote_listing_and_upload_from_local_library(self):
        with patch.object(self.mod.RANTLIST_BRIDGE,'list_assets',return_value={'items':[], 'maxItems':60}):
            result=self.client.get('/api/rantlist/assets',headers=self.headers)
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json['items'],[])
        import hashlib
        uid=hashlib.sha256(b'test').hexdigest()[:24]
        source=Path(self.temp.name)/'combined.glb'
        source.write_bytes(b'glTF'+b'\0'*128)
        with self.mod.LIBRARY_LOCK:
            original=self.mod._load_library()
            self.mod._save_library(original+[{'id':uid,'name':'Test dancer','path':str(source),'source':'generated','created':'now'}])
        try:
            with patch.object(self.mod.RANTLIST_BRIDGE,'publish',return_value={'id':'a'*32,'kind':'avatar','thumbnailSaved':False}) as publish:
                result=self.client.post('/api/rantlist/publish/'+uid,json={'kind':'avatar'},headers=self.headers)
                self.assertEqual(result.status_code,200)
                self.assertEqual(publish.call_args.kwargs['glb'][:4],b'glTF')
                self.assertEqual(publish.call_args.kwargs['name'],'Test dancer')
        finally:
            with self.mod.LIBRARY_LOCK:self.mod._save_library(original)

    def test_post_requires_token(self):
        response = self.client.post('/api/jobs', headers={'Host': '127.0.0.1:5055'})
        self.assertEqual(response.status_code, 403)

    def test_json_preset_and_dry_run(self):
        source = Path(self.temp.name) / 'avatar.zip'
        with zipfile.ZipFile(source, 'w') as z:
            z.writestr('model.fbx', b'placeholder FBX')
            z.writestr('textures/diffuse.png', b'fake texture')
        preset = {'presetName': 'Test Pack', 'animations': [
            {'search': 'Jump', 'title': 'Jump', 'description': 'Female Forward Running Jump',
             'motionId': '124620901', 'filename': 'Jump__124620901'}]}
        response = self.client.post('/api/presets',
             data={'file': (io.BytesIO(json.dumps(preset).encode()), 'pack.json')},
             content_type='multipart/form-data', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        form = {'source_mode': 'path', 'character_path': str(source), 'preset_mode': 'saved',
                'preset': response.json['filename'], 'blender': sys.executable,
                'dry_run': 'true', 'draco': '6', 'webp': '30', 'timeout': '900', 'port': '9222'}
        response = self.client.post('/api/jobs', data=form, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        for _ in range(100):
            time.sleep(0.05)
            result = self.client.get('/api/status', headers={'Host': '127.0.0.1:5055'}).json['job']
            if result['status'] not in ('starting', 'running'):
                break
        self.assertEqual(result['status'], 'completed', result)
        self.assertTrue(Path(result['output']).is_dir())
        # macOS resolves /var/... to /private/var/...; compare canonical paths.
        self.assertEqual(Path(result['output']).parent.resolve(), source.parent.resolve())

    def test_library_persistence_screenshot_download_and_safe_delete(self):
        # Generated GLB remains at its original export path after card deletion.
        character = Path(self.temp.name) / 'test-character.zip'
        character.write_bytes(b'test')
        output = Path(self.temp.name) / 'test-character-exports'
        glb_dir = output / 'glb'
        glb_dir.mkdir(parents=True, exist_ok=True)
        original = glb_dir / (output.name + '-anims.glb')
        original.write_bytes(b'glTF' + b'generated-export')
        job = {'id': 'job-gallery-001', 'character': character, 'output': output}
        key = self.mod.register_generated(job)
        self.assertTrue(key)
        listed = self.client.get('/api/library', headers={'Host':'127.0.0.1:5055'})
        self.assertEqual(listed.status_code, 200)
        self.assertIn(key, [model['id'] for model in listed.json['models']])
        self.assertEqual(next(m for m in listed.json['models'] if m['id'] == key)['jobId'], job['id'])
        self.assertTrue(self.mod.LIBRARY_INDEX.is_file())
        response = self.client.get(f'/api/library/{key}/download', headers={'Host':'127.0.0.1:5055'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        shot = b'RIFF' + (28).to_bytes(4, 'little') + b'WEBP' + b'fake-studio-screenshot-content'
        response = self.client.post(f'/api/library/{key}/thumbnail', data=shot,
             content_type='image/webp', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.patch(f'/api/library/{key}', json={'clips': 27}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        listed = self.client.get('/api/library', headers={'Host':'127.0.0.1:5055'}).json['models']
        self.assertEqual(next(m for m in listed if m['id'] == key)['clips'], 27)
        response = self.client.get(f'/api/library/{key}/thumbnail', headers={'Host':'127.0.0.1:5055'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, shot)
        response = self.client.delete(f'/api/library/{key}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(original.is_file(), 'Deleting card must not delete original generated GLB')
        self.assertEqual(self.client.get(f'/api/library/{key}/glb', headers={'Host':'127.0.0.1:5055'}).status_code, 404)

    def test_local_glb_import_and_delete_managed_copy(self):
        upload = self.client.post('/api/library/import', data={'file': (io.BytesIO(b'glTF' + bytes(40)), 'my-model.glb')},
            content_type='multipart/form-data', headers=self.headers)
        self.assertEqual(upload.status_code, 201, upload.data)
        model = upload.json['model']
        managed = self.mod.LIBRARY_FILES / (model['id'] + '.glb')
        self.assertTrue(managed.exists())
        response = self.client.delete('/api/library/' + model['id'], headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(managed.exists())
        bad = self.client.post('/api/library/import', data={'file': (io.BytesIO(b'not-a-glb'), 'bad.glb')},
            content_type='multipart/form-data', headers=self.headers)
        self.assertEqual(bad.status_code, 400)

    def test_static_viewer_and_preview_route(self):
        response = self.client.get('/static/viewer.mjs', headers={'Host': '127.0.0.1:5055'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'AnimationMixer', response.data)
        response = self.client.get('/api/jobs/nonexistent/preview', headers={'Host': '127.0.0.1:5055'})
        self.assertEqual(response.status_code, 404)
        job = self.mod.STATE['job']
        if job and job['status'] == 'completed':
            glb_dir = job['output'] / 'glb'
            glb_dir.mkdir(parents=True, exist_ok=True)
            path = glb_dir / (job['output'].name + '-anims.glb')
            path.write_bytes(b'glTF-testing')
            response = self.client.get(f"/api/jobs/{job['id']}/preview", headers={'Host': '127.0.0.1:5055'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content_type.startswith('model/gltf-binary'))
            self.assertNotIn('attachment', response.headers.get('Content-Disposition', ''))
            path.unlink()


if __name__ == '__main__':
    unittest.main()
