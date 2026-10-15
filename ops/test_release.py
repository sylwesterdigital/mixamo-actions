"""Run locally: python3 -m unittest ops.test_release -v"""
import hashlib
import json
import tempfile
import unittest
import zipfile
import subprocess
from pathlib import Path
from ops.install_release import load_release, version_parts, preflight_service_ownership, install
from unittest.mock import patch


class InstallerVerification(unittest.TestCase):
    def build(self, path, entries):
        manifest={'version':'2.1.0','files':{k:hashlib.sha256(v).hexdigest() for k,v in entries.items()}}
        with zipfile.ZipFile(path,'w') as z:
            for name,data in entries.items(): z.writestr(name,data)
            z.writestr('release.json',json.dumps(manifest))

    def test_good_archive(self):
        with tempfile.TemporaryDirectory() as t:
            z=Path(t)/'good.zip';dst=Path(t)/'dst';dst.mkdir()
            self.build(z,{'core/flask_app.py':b'print(1)','VERSION':b'2.1.0'})
            meta=load_release(z,dst)
            self.assertEqual(meta['version'],'2.1.0')
            self.assertEqual((dst/'VERSION').read_text(),'2.1.0')

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            z=Path(t)/'bad.zip';dst=Path(t)/'dst';dst.mkdir()
            self.build(z,{'../escape.py':b'danger'})
            with self.assertRaises(RuntimeError):load_release(z,dst)

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            z=Path(t)/'bad.zip';dst=Path(t)/'dst';dst.mkdir()
            self.build(z,{'core/flask_app.py':b'original'})
            with zipfile.ZipFile(z,'a') as f:
                f.writestr('core/flask_app.py',b'altered')
            with self.assertRaises(RuntimeError):load_release(z,dst)

    def test_occupied_unmanaged_port_fails_before_code_change(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('ops.install_release.port_available', return_value=False), \
             patch('ops.install_release.managed_pid', return_value=None), \
             patch('ops.install_release.describe_port_5055', return_value='PID 4242: old Flask'):
            with self.assertRaisesRegex(RuntimeError, 'PID 4242'):
                preflight_service_ownership(Path(tmp))

    def test_owned_studio_port_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch('ops.install_release.port_available', return_value=False), \
             patch('ops.install_release.managed_pid', return_value=4242):
            preflight_service_ownership(Path(tmp))

    def test_modified_readme_is_backed_up_and_release_installs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / 'core').mkdir()
            (repo / 'updates').mkdir()
            (repo / 'README.md').write_text('original README\n')
            (repo / 'VERSION').write_text('1.1.0\n')
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-C', str(repo), 'add', '--', 'README.md', 'VERSION'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '-qm', 'base'], check=True)
            local_edit = 'Important local README changes\n'
            (repo / 'README.md').write_text(local_edit)
            archive = repo / 'updates/mixamo-actions-v1.1.1.zip'
            self.build_version(archive, '1.1.1', {
                'README.md': b'updated release README\n',
                'VERSION': b'1.1.1\n',
                'core/flask_app.py': b'print(1)\n',
            })
            with patch('ops.install_release.preflight_service_ownership'), \
                 patch('ops.install_release.wait_until_idle'), \
                 patch('ops.install_release.ensure_dependencies'), \
                 patch('ops.install_release.stop_studio'), \
                 patch('ops.install_release.start_studio'), \
                 patch('ops.install_release.managed_pid', return_value=None):
                self.assertTrue(install(archive, repo))
            self.assertEqual((repo / 'README.md').read_text(), 'updated release README\n')
            backups = list((repo / 'updates/.backups').glob('before-v1.1.1-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / 'README.md').read_text(), local_edit)
            self.assertEqual(json.loads((backups[0] / 'local-edits.json').read_text())[
                'preservedTrackedEdits'], ['README.md'])

    def test_staged_readme_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / 'core').mkdir()
            (repo / 'updates').mkdir()
            (repo / 'README.md').write_text('old\n')
            (repo / 'VERSION').write_text('1.1.0\n')
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-C', str(repo), 'add', 'README.md', 'VERSION'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                            'commit', '-qm', 'base'], check=True)
            (repo / 'README.md').write_text('staged change\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'README.md'], check=True)
            archive = repo / 'updates/mixamo-actions-v1.1.1.zip'
            self.build_version(archive, '1.1.1', {'README.md': b'new\n', 'VERSION': b'1.1.1\n'})
            with self.assertRaisesRegex(RuntimeError, 'Staged Git changes'):
                install(archive, repo)
            self.assertEqual((repo / 'README.md').read_text(), 'staged change\n')

    def test_release_target_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            (repo / 'updates').mkdir()
            outside = Path(tmp) / 'outside'
            outside.write_text('outside is safe')
            (repo / 'README.md').symlink_to(outside)
            archive = repo / 'updates/mixamo-actions-v1.1.1.zip'
            self.build_version(archive, '1.1.1', {'README.md': b'new\n', 'VERSION': b'1.1.1\n'})
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                install(archive, repo)
            self.assertEqual(outside.read_text(), 'outside is safe')

    def build_version(self, path, version, entries):
        manifest={'version':version,'files':{k:hashlib.sha256(v).hexdigest() for k,v in entries.items()}}
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in entries.items(): z.writestr(name, data)
            z.writestr('release.json', json.dumps(manifest))

    def test_numeric_semver(self):
        self.assertGreater(version_parts('2.1.10'),version_parts('2.1.9'))


if __name__ == '__main__':unittest.main()
