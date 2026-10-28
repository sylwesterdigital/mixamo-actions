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

    def test_texture_optimization_creates_managed_variant_with_no_source_mutation(self):
        from test_texture_optimize import build_glb_fixture, _unpack
        uid='f'*24
        source=self.mod.LIBRARY_FILES/(uid+'.glb')
        build_glb_fixture(source)
        before=source.read_bytes()
        with self.mod.LIBRARY_LOCK:
            old=self.mod._load_library()
            self.mod._save_library(old+[{'id':uid,'name':'Avatar','path':str(source),
                                        'source':'imported','created':'today','clips':3}])
        variants=[]
        try:
            unauthorized=self.client.post(f'/api/library/{uid}/optimize',json={'percent':75},headers={'Host':'127.0.0.1:5055'})
            self.assertEqual(unauthorized.status_code,403)
            bad=self.client.post(f'/api/library/{uid}/optimize',json={'percent':77},headers=self.headers)
            self.assertEqual(bad.status_code,400)
            for percent in (75,50,25):
                response=self.client.post(f'/api/library/{uid}/optimize',json={'percent':percent},headers=self.headers)
                self.assertEqual(response.status_code,201,response.data)
                model=response.json['model']
                variants.append(model['id'])
                self.assertEqual(model['name'],f'Avatar-o{percent}')
                self.assertEqual(model['source'],'optimized')
                self.assertEqual(model['originalId'],uid)
                self.assertFalse(model['canExtend'])
                self.assertEqual(model['clips'],3)
                self.assertEqual(response.json['report']['optimizedCount'],3)
                download=self.client.get(model['glbUrl'],headers=self.headers)
                self.assertEqual(download.status_code,200)
                self.assertTrue(download.data.startswith(b'glTF'))
                self.assertNotEqual(download.data,before)
            self.assertEqual(source.read_bytes(),before)
            # Re-optimization of a variant always uses the base instead of
            # compounding a 50% scale into another 50% conversion.
            variant_response=self.client.post(f'/api/library/{variants[0]}/optimize',json={'percent':25},headers=self.headers)
            self.assertEqual(variant_response.status_code,409,variant_response.data)
            self.assertIn('already exists', variant_response.json['error'])
            for variant in variants:
                deleted=self.client.delete(f'/api/library/{variant}',headers=self.headers)
                self.assertEqual(deleted.status_code,200)
                self.assertFalse((self.mod.LIBRARY_FILES/(variant+'.glb')).exists())
            self.assertEqual(source.read_bytes(),before)
        finally:
            with self.mod.LIBRARY_LOCK:
                self.mod._save_library(old)
            source.unlink(missing_ok=True)
            for variant in variants:
                (self.mod.LIBRARY_FILES/(variant+'.glb')).unlink(missing_ok=True)
                (self.mod.LIBRARY_THUMBS/(variant+'.webp')).unlink(missing_ok=True)

    def test_edit_motion_collection_create_update_and_concurrent_reject(self):
        name='new_collection_for_route_test'
        file=self.mod.PRESETS/(name+'.json')
        file.unlink(missing_ok=True)
        motions=[{'search':'walk','title':'Walk','motionId':'117660901'}]
        try:
            denied=self.client.post('/api/presets/edit',json={'name':name,'animations':motions},
                      headers={'Host':'127.0.0.1:5055'})
            self.assertEqual(denied.status_code,403)
            created=self.client.post('/api/presets/edit',json={'name':name,'animations':motions},headers=self.headers)
            self.assertEqual(created.status_code,200,created.data)
            self.assertEqual(created.json['count'],1)
            read=self.client.get('/api/presets/'+name+'.json',headers=self.headers)
            self.assertEqual(read.status_code,200)
            self.assertEqual(read.json['content']['animations'],motions)
            conflict=self.client.post('/api/presets/edit',json={'name':name,'animations':motions},headers=self.headers)
            self.assertEqual(conflict.status_code,409)
            updated=self.client.post('/api/presets/edit',json={
                'name':name,'animations':motions+[{'search':'run','title':'Running'}],
                'original':read.json['filename'],'sha256':read.json['sha256']},headers=self.headers)
            self.assertEqual(updated.status_code,200,updated.data)
            self.assertEqual(updated.json['count'],2)
            self.assertEqual(self.client.post('/api/presets/edit',json={'name':name,'animations':[]},
                             headers=self.headers).status_code,400)
        finally:
            file.unlink(missing_ok=True)

    def test_extend_generated_gallery_model_reuses_existing_fbx(self):
        from resume_state import ResumePlan, digest
        base=self.mod.UPLOADS/'test-extend'
        base.mkdir(parents=True,exist_ok=True)
        original=base/'model.fbx'
        original.write_bytes(b'Kaydara FBX Binary  \x00\x1a\x00'+bytes(1200))
        out=base/'model-exports'
        (out/'fbx').mkdir(parents=True,exist_ok=True)
        (out/'glb').mkdir(exist_ok=True)
        (out/'source_character').mkdir(exist_ok=True)
        (out/'manifest.json').write_text(json.dumps({'original_character':str(original)}))
        glb=out/'glb'/'model-exports-anims.glb'
        glb.write_bytes(b'glTF'+bytes(100))
        old=[{'search':'idle','title':'Idle','filename':'Idle__117780901','motionId':'117780901'}]
        preset=base/'old.json'
        preset.write_text(json.dumps({'animations':old}))
        cp=ResumePlan(out/'fbx',old,source_sha256=digest(original),preset_sha256=digest(preset))
        spec,filename=cp.expected[0]
        (out/'fbx'/filename).write_bytes(original.read_bytes())
        cp.record(spec,filename)
        saved_preset=self.mod.PRESETS/'extension-route-test.json'
        saved_preset.write_text(json.dumps({'animations':[
            {'search':'idle','title':'Idle','filename':'Idle__117780901','motionId':'117780901'},
            {'search':'walk','title':'Walk','filename':'Walk__118080901','motionId':'118080901'}]}))
        uid='c'*24
        with self.mod.LIBRARY_LOCK:
            saved_catalog=self.mod._load_library()
            self.mod._save_library(saved_catalog+[{'id':uid,'name':'Base model','path':str(glb),'source':'generated','created':'today'}])
        with self.mod.STATE_LOCK:
            saved_state=self.mod.STATE['job']
            self.mod.STATE['job']=None
        previous=self.mod.LAST_JOB_FILE.read_bytes() if self.mod.LAST_JOB_FILE.exists() else None
        try:
            with patch.object(self.mod,'Thread') as thread:
                response=self.client.post('/api/jobs',data={
                    'source_mode':'library','library_id':uid,'preset_mode':'saved',
                    'preset':saved_preset.name,'blender':sys.executable,
                },headers=self.headers)
                self.assertEqual(response.status_code,200,response.data)
                self.assertEqual(response.json['extension']['reused'],1)
                self.assertEqual(response.json['extension']['remaining'],1)
                self.assertEqual(response.json['extension']['total'],2)
                self.assertIn('--out',self.mod.STATE['job']['command'])
                thread.return_value.start.assert_called_once()
                self.assertTrue(glb.exists())
                self.assertEqual((out/'fbx'/filename).read_bytes(),original.read_bytes())
        finally:
            saved_preset.unlink(missing_ok=True)
            with self.mod.LIBRARY_LOCK:self.mod._save_library(saved_catalog)
            with self.mod.STATE_LOCK:self.mod.STATE['job']=saved_state
            if previous is None:self.mod.LAST_JOB_FILE.unlink(missing_ok=True)
            else:self.mod.LAST_JOB_FILE.write_bytes(previous)

    def test_diagnostics_require_token_and_log_safe_routes(self):
        denied=self.client.get('/api/diagnostics',headers={'Host':'127.0.0.1:5055'})
        self.assertEqual(denied.status_code,403)
        ok=self.client.get('/api/diagnostics',headers=self.headers)
        self.assertEqual(ok.status_code,200)
        self.assertTrue(any(row['route']=='/api/diagnostics' for row in ok.json['events']))
        self.assertFalse(any('Authorization' in str(e) or 'token' in str(e).lower() for e in ok.json['events']))

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
        # Keep the private-gallery fixture active for BOTH listing and upload.
        # Previously it ended after the GET; POST then hit the real Rantlist
        # connector, which correctly returned 401 in an unauthenticated test.
        catalogue = {'items': [], 'maxItems': 60, 'usedItems': 0, 'capacityKnown': True}
        import hashlib
        uid=hashlib.sha256(b'test').hexdigest()[:24]
        source=Path(self.temp.name)/'combined.glb'
        source.write_bytes(b'glTF'+b'\0'*128)
        with self.mod.LIBRARY_LOCK:
            original=self.mod._load_library()
            self.mod._save_library(original+[{'id':uid,'name':'Test dancer','path':str(source),'source':'generated','created':'now'}])
        try:
            with patch.object(self.mod.RANTLIST_BRIDGE, 'list_assets', return_value=catalogue) as listing, \
                 patch.object(self.mod.RANTLIST_BRIDGE, 'publish', return_value={'id':'a'*32,'kind':'avatar','thumbnailSaved':False}) as publish:
                response = self.client.get('/api/rantlist/assets', headers=self.headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json['items'], [])
                result=self.client.post('/api/rantlist/publish/'+uid,json={'kind':'avatar'},headers=self.headers)
                self.assertEqual(result.status_code,200)
                self.assertEqual(publish.call_args.kwargs['glb'][:4],b'glTF')
                self.assertEqual(publish.call_args.kwargs['name'],'Test dancer')
                changed=self.client.post('/api/rantlist/publish/'+uid,json={'kind':'model','name':'blad3'},headers=self.headers)
                self.assertEqual(changed.status_code,200)
                self.assertEqual(publish.call_args.kwargs['name'],'blad3')
                self.assertEqual(publish.call_args.kwargs['kind'],'model')
                invalid=self.client.post('/api/rantlist/publish/'+uid,json={'name':''},headers=self.headers)
                self.assertEqual(invalid.status_code,400)
                self.assertEqual(publish.call_count,2)
                self.assertEqual(listing.call_count, 3)  # GET + two valid uploads
        finally:
            with self.mod.LIBRARY_LOCK:self.mod._save_library(original)

    def test_resume_preserves_original_upload_and_rejects_changes(self):
        from resume_state import digest
        from collections import deque
        character = Path(self.temp.name) / 'resume-upload.zip'
        character.write_bytes(b'a saved upload')
        preset = Path(self.temp.name) / 'resume-anims.json'
        preset.write_text(json.dumps({'animations':[{'search':'swim'}]}))
        out = character.parent / 'resume-upload-exports'
        command = [sys.executable, '-u', str(self.mod.ROOT / 'mixamo_pipeline.py'),
                   '--character', str(character), '--animations', str(preset)]
        # Fake only thread scheduling: never launch a live Mixamo or Blender job.
        record = dict(schema=1, command=command, character=str(character),
                      output=str(out), preset=str(preset), characterSha256=digest(character),
                      presetSha256=digest(preset), animations=1, status='failed',
                      id='previous-job', started='yesterday', finished='today')
        with self.mod.STATE_LOCK:
            prior = self.mod.STATE['job']
            self.mod.STATE['job'] = None
        previous = self.mod.read_last_job()
        try:
            self.mod.LAST_JOB_FILE.write_text(json.dumps(record))
            recovered = self.client.get('/api/status', headers=self.headers).json['job']
            self.assertTrue(recovered['resumable'])
            self.assertEqual(recovered['character'], str(character))
            no_token = self.client.post('/api/jobs/resume', headers={'Host':'127.0.0.1:5055'})
            self.assertEqual(no_token.status_code, 403)
            with patch.object(self.mod, 'Thread') as thread:
                resumed = self.client.post('/api/jobs/resume', headers=self.headers)
                self.assertEqual(resumed.status_code, 200, resumed.data)
                self.assertTrue(thread.called)
                args = thread.call_args.kwargs['args']
                self.assertIn(str(character), args[1])
                self.assertIn(str(preset), args[1])
                self.assertNotIn('--skip-download', args[1])
                self.assertEqual(resumed.json['job']['character'], str(character))
            with self.mod.STATE_LOCK:
                self.mod.STATE['job'] = None
            self.mod.LAST_JOB_FILE.write_text(json.dumps(record))
            preset.write_text('changed preset')
            denied = self.client.post('/api/jobs/resume', headers=self.headers)
            self.assertEqual(denied.status_code, 409)
        finally:
            with self.mod.STATE_LOCK:
                self.mod.STATE['job'] = prior
            if previous:
                self.mod.LAST_JOB_FILE.write_text(json.dumps(previous))
            else:
                self.mod.LAST_JOB_FILE.unlink(missing_ok=True)

    def test_rantlist_publish_quota_preflight_never_uploads(self):
        # A full account must fail locally without touching the upload API.
        import hashlib
        key = hashlib.sha256(b'quota-test').hexdigest()[:24]
        source = Path(self.temp.name) / 'quota-example.glb'
        source.write_bytes(b'glTF' + bytes(40))
        local_item = {'id': key, 'name': 'Quota example', 'path': str(source), 'source': 'generated'}
        full = {'items': [], 'usedItems': 60, 'maxItems': 60, 'capacityKnown': True}
        with patch.object(self.mod, '_load_library', return_value=[local_item]), \
             patch.object(self.mod.RANTLIST_BRIDGE, 'list_assets', return_value=full), \
             patch.object(self.mod.RANTLIST_BRIDGE, 'publish') as upload:
            response = self.client.post('/api/rantlist/publish/' + key,
                                        json={'kind': 'avatar'}, headers=self.headers)
            self.assertEqual(response.status_code, 409, response.data)
            self.assertIn('60/60', response.json['error'])
            upload.assert_not_called()

    def test_rantlist_publish_disconnected_session_is_unauthorized(self):
        # Verify an authentication failure is correctly returned, not masked.
        from rantlist_bridge import RantlistError
        import hashlib
        key = hashlib.sha256(b'not-connected').hexdigest()[:24]
        source = Path(self.temp.name) / 'not-connected.glb'
        source.write_bytes(b'glTF' + bytes(40))
        local_item = {'id': key, 'name': 'Not connected', 'path': str(source), 'source': 'generated'}
        with patch.object(self.mod, '_load_library', return_value=[local_item]), \
             patch.object(self.mod.RANTLIST_BRIDGE, 'list_assets',
                          side_effect=RantlistError('Sign in required', 401)), \
             patch.object(self.mod.RANTLIST_BRIDGE, 'publish') as upload:
            response = self.client.post('/api/rantlist/publish/' + key,
                                        json={'kind': 'avatar'}, headers=self.headers)
            self.assertEqual(response.status_code, 401, response.data)
            upload.assert_not_called()

    def test_remote_thumbnail_keeps_actual_mime_type_and_rejects_html(self):
        with patch.object(self.mod.RANTLIST_BRIDGE,'asset',return_value=(b'\xff\xd8\xff'+b'x'*64,'image/jpeg')):
            image=self.client.get('/api/rantlist/assets/'+'a'*32+'/thumbnail',headers=self.headers)
            self.assertEqual(image.status_code,200)
            self.assertEqual(image.mimetype,'image/jpeg')
        with patch.object(self.mod.RANTLIST_BRIDGE,'asset',return_value=(b'<html>error</html>','text/html')):
            image=self.client.get('/api/rantlist/assets/'+'a'*32+'/thumbnail',headers=self.headers)
            self.assertEqual(image.status_code,502)

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

    def test_import_multiple_motion_packs_and_file_url_build(self):
        from urllib.parse import quote
        source = Path(self.temp.name) / 'second-preset-avatar.zip'
        with zipfile.ZipFile(source, 'w') as z:
            z.writestr('model.fbx', b'placeholder FBX')
        # 24 actions: same shape as the user-supplied animations-males.json.
        male = {'animations': [dict(search=f'action-{i}', title=f'Action {i}',
                                    motionId=str(100000000+i), filename=f'Action_{i}')
                               for i in range(24)]}
        first = self.client.post('/api/presets',
            data={'file':(io.BytesIO(json.dumps(male).encode()), 'animations-males.json')},
            headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.json['count'], 24)
        again = self.client.post('/api/presets',
            data={'file':(io.BytesIO(json.dumps(male).encode()), 'animations-males.json')},
            headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(again.status_code, 200, again.data)
        self.assertEqual(again.json['filename'], first.json['filename'])
        self.assertTrue(again.json['alreadySaved'])
        another = {'animations':[{'search':'new animation'}]}
        different = self.client.post('/api/presets',
            data={'file':(io.BytesIO(json.dumps(another).encode()), 'animations-males.json')},
            headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(different.status_code, 200, different.data)
        self.assertNotEqual(different.json['filename'], first.json['filename'])
        self.assertEqual(json.loads((self.mod.PRESETS / first.json['filename']).read_text()), male)
        invalid = self.client.post('/api/presets',
            data={'file':(io.BytesIO(b'not-json'), 'invalid-motions.json')},
            headers=self.headers, content_type='multipart/form-data')
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse((self.mod.PRESETS / 'invalid-motions.json').exists())
        form = {'source_mode':'path','character_path':str(source), 'preset_mode':'path',
                'preset_path':'file://'+quote(str(self.mod.PRESETS / first.json['filename'])),
                'blender':sys.executable,'dry_run':'true', 'draco':'6', 'webp':'30',
                'timeout':'900','port':'9222'}
        response = self.client.post('/api/jobs', data=form, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.data)
        for _ in range(100):
            time.sleep(.05)
            result=self.client.get('/api/status',headers=self.headers).json['job']
            if result['status'] not in ('starting','running'):break
        self.assertEqual(result['status'],'completed',result)

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
