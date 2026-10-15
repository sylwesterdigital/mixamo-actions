"""Crash/retry safety tests, no live Mixamo/Adobe/Flask connection required."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from resume_state import ResumePlan, planned, verify_fbx, digest, valid_resume_command

SPEC = [{'search': 'standing', 'title': 'Standing Idle', 'filename': 'Standing Idle__131220901'},
        {'search': 'swim', 'title': 'Swimming', 'filename': 'Swimming__110800901'},
        {'search': 'walk', 'title': 'Walking', 'filename': 'Walking__117660901'}]
BINARY_FBX = b'Kaydara FBX Binary  \x00\x1a\x00' + bytes(2048)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.out = self.dir / 'fbx'
        self.source = self.dir / 'original.zip'
        self.source.write_bytes(b'original source')
        self.preset = self.dir / 'preset.json'
        self.preset.write_text(json.dumps({'animations': SPEC}))

    def tearDown(self):
        self.temp.cleanup()

    def state(self, specs=None):
        return ResumePlan(self.out, SPEC if specs is None else specs,
                          source_sha256=digest(self.source), preset_sha256=digest(self.preset))

    def test_saved_python_unbuffered_command_can_resume(self):
        """Flask launches -u, so the recovery validator must accept it."""
        executable = sys.executable
        pipeline = self.dir / 'mixamo_pipeline.py'
        original = [executable, '-u', str(pipeline), '--cdp', 'http://127.0.0.1:9222',
                    '--character', str(self.source), '--animations', str(self.preset),
                    '--draco-level', '6', '--skip-upload']
        self.assertTrue(valid_resume_command(original, executable=executable,
                                             pipeline=pipeline, character=self.source, preset=self.preset))
        self.assertTrue(valid_resume_command([executable, str(pipeline),
                                              '--character', str(self.source), '--animations', str(self.preset)],
                                             executable=executable, pipeline=pipeline,
                                             character=self.source, preset=self.preset))
        for invalid in ([executable, '-u', '-m', 'subprocess', '--character', str(self.source),
                         '--animations', str(self.preset)],
                        original + ['--unexpected-option'],
                        original + ['--character', '/tmp/other'],
                        original[:-1] + ['--animations', '/tmp/other'],
                        original[:original.index('--character') + 1] + ['/tmp/different.zip'] +
                        original[original.index('--character') + 2:],
                        [executable, '-u', str(pipeline), '--character', str(self.source)]):
            self.assertFalse(valid_resume_command(invalid, executable=executable,
                                                 pipeline=pipeline, character=self.source, preset=self.preset))

    def test_record_resume_complete_and_corrupted_file(self):
        one = self.state()
        self.assertEqual(one.missing(), [x for _, x in planned(SPEC)])
        names = [name for _, name in planned(SPEC)]
        (self.out / names[0]).write_bytes(BINARY_FBX)
        one.record(SPEC[0], names[0])
        self.assertEqual(one.completed(), 1)
        restart = self.state()
        self.assertEqual(restart.completed(), 1)
        self.assertEqual(restart.missing(), names[1:])
        (self.out / names[0]).write_bytes(b'<html>error</html>' + bytes(3000))
        self.assertEqual(self.state().completed(), 0)
        self.assertIn(names[0], self.state().missing())

    def test_complete_downloads_skip_browser_phase(self):
        plan = self.state()
        for spec, filename in plan.expected:
            (self.out / filename).write_bytes(BINARY_FBX)
            plan.record(spec, filename)
        self.assertFalse(self.state().missing())
        self.assertEqual(self.state().completed(), 3)

    def test_change_source_or_preset_refuses_old_files(self):
        plan = self.state()
        filename = plan.expected[0][1]
        (self.out / filename).write_bytes(BINARY_FBX)
        plan.record(SPEC[0], filename)
        before = (self.out / filename).read_bytes()
        self.source.write_bytes(b'a different model')
        with self.assertRaisesRegex(ValueError, 'different character'):
            self.state()
        self.assertEqual((self.out / filename).read_bytes(), before)
        self.source.write_bytes(b'original source')
        with self.assertRaisesRegex(ValueError, 'animation preset'):
            self.state(SPEC[:2])

    def test_staged_part_is_not_a_completed_download(self):
        plan = self.state()
        name = plan.expected[0][1]
        (self.out / (name + '.part')).write_bytes(BINARY_FBX)
        self.assertEqual(plan.completed(), 0)
        self.assertEqual(len(plan.missing()), 3)
        self.assertFalse(verify_fbx(self.out / name))
        self.assertFalse(verify_fbx(self.out / (name + '.part') ) is False)

    def test_legacy_manifest_adopts_only_valid_matching_files(self):
        self.out.mkdir()
        file = self.out / planned(SPEC)[0][1]
        file.write_bytes(BINARY_FBX)
        manifest = {'successful': [{'requested': SPEC[0], 'file': file.name, 'status': 'downloaded'}],
                    'failed': [{'requested': SPEC[1], 'error': 'timeout'}]}
        (self.out / 'manifest.json').write_text(json.dumps(manifest))
        plan = self.state()
        self.assertEqual(plan.completed(), 1)
        self.assertTrue((self.out / '.mixamo-resume.json').is_file())
        self.assertEqual(self.state().missing(), [planned(SPEC)[1][1], planned(SPEC)[2][1]])

    def test_untracked_legacy_file_is_not_silently_reused(self):
        self.out.mkdir()
        file = self.out / planned(SPEC)[0][1]
        file.write_bytes(BINARY_FBX)
        with self.assertRaisesRegex(ValueError, 'unverified legacy'):
            self.state()
        self.assertTrue(file.is_file())

    def test_checkpoint_manifest_cannot_include_extra_fbx(self):
        plan = self.state()
        (self.out / 'unrelated.fbx').write_bytes(BINARY_FBX)
        with self.assertRaisesRegex(ValueError, 'unrelated clips'):
            plan.ensure_no_untracked()

    def test_duplicate_titles_produce_distinct_files(self):
        names = [n for _, n in planned([{'search': 'jump'}, {'search': 'jump'}, {'search': 'jump'}])]
        self.assertEqual(names, ['jump.fbx','jump-2.fbx','jump-3.fbx'])


if __name__ == '__main__':
    unittest.main()
