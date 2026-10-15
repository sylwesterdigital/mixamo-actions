"""Validation tests that require only Python stdlib."""
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops'))
from install_release import load_release, version_parts, get_old_version, install, still_matches_previous_release

class ReleaseTests(unittest.TestCase):
    def test_version_comparison(self):
        self.assertTrue(version_parts('1.10.0') > version_parts('1.9.9'))
        self.assertTrue(version_parts('2.0.0') > version_parts('1.99.99'))

    def test_old_version_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(get_old_version(Path(temp)), '0.0.0')

    def test_zip_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            zip_path = Path(temp) / 'invalid.zip'
            with zipfile.ZipFile(zip_path,'w') as z:
                z.writestr('release.json', json.dumps({'version':'1.0.0','files':{'../bad':'x'*64}}))
                z.writestr('../bad','bad')
            with self.assertRaisesRegex(RuntimeError, 'Unsafe ZIP path'):
                load_release(zip_path, Path(temp) / 'stage')

    def test_invalid_hash_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            zip_path = Path(temp) / 'invalid.zip'
            with zipfile.ZipFile(zip_path,'w') as z:
                z.writestr('release.json', json.dumps({'version':'1.0.0','files':{'VERSION':'0'*64}}))
                z.writestr('VERSION','1.0.0')
            with self.assertRaisesRegex(RuntimeError, 'Hash mismatch'):
                load_release(zip_path, Path(temp) / 'stage')

    def test_previous_release_manifest_allows_unpublished_clean_files(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / 'core').mkdir()
            (repo / 'VERSION').write_text('1.0.1\n')
            clean = b'installed by v1.0.1'
            source = repo / 'core/flask_app.py'
            source.write_bytes(clean)
            (repo / 'release.json').write_text(json.dumps({
                'version': '1.0.1',
                'files': {'core/flask_app.py': hashlib.sha256(clean).hexdigest()}
            }))
            self.assertTrue(still_matches_previous_release(repo, 'core/flask_app.py'))
            source.write_bytes(b'user changed this')
            self.assertFalse(still_matches_previous_release(repo, 'core/flask_app.py'))

    def test_disabled_publish_does_not_write_success_markers(self):
        import os, shutil, subprocess
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / 'updates/.state').mkdir(parents=True)
            shutil.copyfile(ROOT / 'mixamo-studio-watch.sh', repo / 'mixamo-studio-watch.sh')
            release = repo / 'updates/mixamo-actions-v1.0.2.zip'
            release.write_bytes(b'fixture for watcher state')
            import hashlib
            sha = hashlib.sha256(release.read_bytes()).hexdigest()
            (repo / 'updates/.state/last-successful-sha').write_text(sha)
            env = os.environ.copy()
            env.update(MIXAMO_AUTO_GIT_PUSH='0', MIXAMO_AUTO_DEPLOY='0')
            proc = subprocess.run(['bash', str(repo/'mixamo-studio-watch.sh'), '--once'],
                                  cwd=repo, env=env, capture_output=True, text=True, timeout=15)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertFalse((repo/'updates/.state/published-git-sha').exists())
            self.assertFalse((repo/'updates/.state/published-site-sha').exists())

    def test_git_push_and_failed_homepage_remain_independent(self):
        """Regression: successful Git commit/tag must not imply homepage deployment."""
        import hashlib, os, shutil, subprocess
        if shutil.which('git') is None:
            self.skipTest('Git not installed')
        with tempfile.TemporaryDirectory(prefix='mixamo-publish-test-') as temp:
            repo = Path(temp) / 'repo'
            repo.mkdir()
            payload = json.loads((ROOT / 'release.json').read_text())['files']
            for name in [*payload, 'release.json']:
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / name, target)
            package = ROOT / 'updates' / f'mixamo-actions-v{(ROOT / "VERSION").read_text().strip()}.zip'
            state = repo / 'updates/.state'
            state.mkdir(parents=True)
            dest = repo / 'updates' / package.name
            shutil.copy2(package, dest)
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            (state / 'last-successful-sha').write_text(digest)
            def git(*args):
                return subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, check=True)
            git('init', '-b', 'main')
            git('config', 'user.name', 'Mixamo Test')
            git('config', 'user.email', 'mixamo-test@example.test')
            (repo / 'keep-user-file.txt').write_text('unrelated work')
            git('add', 'keep-user-file.txt')
            git('commit', '-m', 'bootstrap')
            remote = Path(temp) / 'remote.git'
            subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
            git('remote', 'add', 'origin', str(remote))
            git('push', '-u', 'origin', 'main')
            env = os.environ.copy()
            env.update(MIXAMO_AUTO_GIT_PUSH='1', MIXAMO_AUTO_DEPLOY='1', MIXAMO_DEPLOY_TARGET='')
            process = subprocess.run(['bash', 'mixamo-studio-watch.sh', '--once'], cwd=repo,
                                     env=env, capture_output=True, text=True, timeout=25)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            self.assertEqual((state / 'published-git-sha').read_text().strip(), digest)
            self.assertFalse((state / 'published-site-sha').exists())
            self.assertIn('MIXAMO_DEPLOY_TARGET is empty', process.stdout)
            self.assertTrue(git('ls-remote', '--tags', 'origin', 'v'+(ROOT / 'VERSION').read_text().strip()).stdout.strip())
            self.assertIn('keep-user-file.txt', git('ls-files').stdout)

    def test_installer_success_and_rollback(self):
        version = (ROOT / 'VERSION').read_text().strip()
        archive = ROOT / 'updates' / f'mixamo-actions-v{version}.zip'
        if not archive.is_file():
            self.skipTest('Build ZIP first')
        for should_fail in (False, True):
            with self.subTest(fails=should_fail), tempfile.TemporaryDirectory() as temp:
                repo = Path(temp)
                (repo / 'core').mkdir()
                (repo / 'VERSION').write_text('0.9.0\n')
                old = repo / 'core/flask_app.py'
                old.write_text('old app')
                expected_version = version
                def fake_start(root, version):
                    if should_fail and version == expected_version:
                        raise RuntimeError('simulated healthcheck failure')
                with patch('install_release.preflight_service_ownership'), \
                     patch('install_release.wait_until_idle'), \
                     patch('install_release.ensure_dependencies'), \
                     patch('install_release.stop_studio'), \
                     patch('install_release.start_studio', side_effect=fake_start):
                    if should_fail:
                        with self.assertRaisesRegex(RuntimeError, 'simulated healthcheck'):
                            install(archive, repo)
                        self.assertEqual((repo / 'VERSION').read_text(), '0.9.0\n')
                        self.assertEqual(old.read_text(), 'old app')
                    else:
                        self.assertTrue(install(archive, repo))
                        self.assertEqual((repo / 'VERSION').read_text(), expected_version + '\n')
                        self.assertTrue((repo / 'core/static/release-watch.js').is_file())
                        self.assertEqual((repo / 'updates/.state/installed-version').read_text(), expected_version + '\n')

if __name__ == '__main__': unittest.main()
