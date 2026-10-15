"""Non-interactive Git publication target selection."""
import os
import tempfile
import unittest
import subprocess
from pathlib import Path
from ops.git_transport import choose_push_url, resolve_from_repo

class GitTransportTests(unittest.TestCase):
    def test_github_https_becomes_ssh_without_changing_origin(self):
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(['git','init','-q',temp],check=True)
            subprocess.run(['git','-C',temp,'remote','add','origin',
                'https://github.com/sylwesterdigital/mixamo-actions.git'], check=True)
            expected = 'git@github.com:sylwesterdigital/mixamo-actions.git'
            self.assertEqual(resolve_from_repo(Path(temp)), expected)
            actual = subprocess.check_output(['git','-C',temp,'remote','get-url','origin'],text=True).strip()
            self.assertEqual(actual,'https://github.com/sylwesterdigital/mixamo-actions.git')

    def test_existing_ssh_unchanged(self):
        self.assertEqual(choose_push_url('git@github.com:user/repo.git'), 'git@github.com:user/repo.git')

    def test_existing_local_remote_unchanged(self):
        self.assertEqual(choose_push_url('/tmp/bare.git'), '/tmp/bare.git')

    def test_no_https_authentication_fallback(self):
        with self.assertRaisesRegex(ValueError, 'Refusing interactive HTTPS'):
            choose_push_url('https://example.org/some/repo.git')

    def test_explicit_override(self):
        self.assertEqual(choose_push_url('https://github.com/org/repo.git', 'git@somehost:team/repo.git'), 'git@somehost:team/repo.git')

    def test_bad_url(self):
        with self.assertRaises(ValueError): choose_push_url('https://user:secret@github.com/org/repo.git')
        with self.assertRaises(ValueError): choose_push_url('')

if __name__ == '__main__': unittest.main()
