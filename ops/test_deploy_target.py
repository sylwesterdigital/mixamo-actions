"""Regression tests for the Mixamo homepage deployment target (offline)."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HomepageTargetTests(unittest.TestCase):
    def show(self, **overrides):
        env = os.environ.copy()
        env.pop('MIXAMO_DEPLOY_TARGET', None)
        env.pop('MIXAMO_DEPLOY_PORT', None)
        env.update(overrides)
        result = subprocess.run(
            ['bash', str(ROOT / 'ops/deploy-homepage.sh'), '--show-target'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=10, check=True,
        )
        return result.stdout

    def test_documented_rantlist_endpoint_is_default(self):
        self.assertIn('SSH target: root@yolo.cx', self.show())
        self.assertIn('SSH port: 18021', self.show())

    def test_migrate_only_legacy_pair(self):
        result = self.show(MIXAMO_DEPLOY_TARGET='root@mail', MIXAMO_DEPLOY_PORT='22')
        self.assertIn('SSH target: root@yolo.cx', result)
        self.assertIn('SSH port: 18021', result)

    def test_explicit_custom_endpoint_is_preserved(self):
        result = self.show(MIXAMO_DEPLOY_TARGET='deploy@my-test.example', MIXAMO_DEPLOY_PORT='2233')
        self.assertIn('SSH target: deploy@my-test.example', result)
        self.assertIn('SSH port: 2233', result)

    def test_remote_directory_is_exact(self):
        self.assertIn('Remote path: /var/www/mojoworks/labs/mixamo-actions', self.show())

    def test_success_only_uploads_five_static_files_and_no_nginx_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp)
            audit = fake_bin / 'audit.txt'
            for name in ('ssh', 'rsync'):
                shim = fake_bin / name
                shim.write_text('#!/bin/sh\nprintf "%s:%s\\n" "' + name + '" "$*" >> "$MIXAMO_DEPLOY_TEST_AUDIT"\n')
                shim.chmod(0o755)
            env = os.environ.copy()
            env.pop('MIXAMO_DEPLOY_TARGET', None)
            env.pop('MIXAMO_DEPLOY_PORT', None)
            env['MIXAMO_DEPLOY_TEST_AUDIT'] = str(audit)
            env['PATH'] = temp + os.pathsep + env['PATH']
            result = subprocess.run(['bash', str(ROOT / 'ops/deploy-homepage.sh')],
                                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(),
                'Homepage files deployed to root@yolo.cx:/var/www/mojoworks/labs/mixamo-actions/')
            log = audit.read_text()
            self.assertIn('ssh:', log)
            self.assertIn('rsync:', log)
            self.assertIn("[ ! -d", log)
            self.assertIn('pwd -P', log)
            self.assertNotIn('mkdir', log)
            self.assertNotIn('nginx', log.lower())
            self.assertNotIn('--delete', log)
            self.assertIn("--include=/index.html", log)
            self.assertIn("--include=/release.json", log)
            self.assertIn("--exclude=*", log)
            self.assertNotIn("--include=/.htaccess", log)
            self.assertNotIn(' --perms', log)

    def test_failed_remote_safety_check_blocks_rsync(self):
        with tempfile.TemporaryDirectory() as temp:
            fake_bin = Path(temp)
            audit = fake_bin / 'audit.txt'
            ssh = fake_bin / 'ssh'
            ssh.write_text('#!/bin/sh\nprintf "ssh\\n" >> "$MIXAMO_DEPLOY_TEST_AUDIT"\nexit 12\n')
            ssh.chmod(0o755)
            rsync = fake_bin / 'rsync'
            rsync.write_text('#!/bin/sh\nprintf "rsync\\n" >> "$MIXAMO_DEPLOY_TEST_AUDIT"\n')
            rsync.chmod(0o755)
            env = os.environ.copy()
            env['PATH'] = temp + os.pathsep + env['PATH']
            env['MIXAMO_DEPLOY_TEST_AUDIT'] = str(audit)
            result = subprocess.run(['bash', str(ROOT / 'ops/deploy-homepage.sh')],
                                    cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(audit.read_text().strip(), 'ssh')


if __name__ == '__main__':
    unittest.main()
