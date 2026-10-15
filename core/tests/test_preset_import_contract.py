"""Preset import behavior without Flask dependencies, plus source-contract checks.

Flask route behavior is exercised by test_local_app when the updater runs on Mac.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

# Isolate the unprivileged pure path resolver without running the Flask server.
module=ast.parse((ROOT/'flask_app.py').read_text(encoding='utf-8'))
resolver=next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name=='preset_local_path')
namespace={'Path':Path}
from urllib.parse import unquote,urlsplit
namespace.update(unquote=unquote,urlsplit=urlsplit)
exec(compile(ast.Module(body=[resolver],type_ignores=[]),'<preset_local_path>','exec'),namespace)
preset_local_path=namespace['preset_local_path']

class PresetImportTests(unittest.TestCase):
    def test_absolute_path_and_finder_file_url_are_equivalent(self):
        with tempfile.TemporaryDirectory(prefix='preset file url ') as tmp:
            file=Path(tmp)/'animations males.json'
            file.write_text(json.dumps({'animations':[{'search':'idle'}]}))
            from urllib.parse import quote
            plain=preset_local_path(str(file))
            finder=preset_local_path('file://'+quote(str(file)))
            localhost=preset_local_path('file://localhost'+quote(str(file)))
            self.assertEqual(plain,finder)
            self.assertEqual(plain,localhost)
    def test_other_schemes_and_network_hosts_rejected(self):
        bad=['https://example.test/motion.json','file://malicious.example/tmp/foo.json',
             'file:///etc/passwd?ignored','file:///etc/passwd#fragment',
             'animations-males.json','']
        for x in bad:
            with self.subTest(value=x), self.assertRaises(ValueError):preset_local_path(x)
    def test_import_remains_visible_and_auto_selects_saved_file(self):
        html=(ROOT/'templates/index.html').read_text()
        script=(ROOT/'static/studio.js').read_text()
        self.assertLess(html.index('id="presetPath"'),html.index('id="presetFile"'))
        self.assertIn('presetImportStatus',html)
        self.assertIn("$('presetFile').addEventListener('change'",script)
        self.assertIn("send('/api/presets'",script)
        self.assertIn("setMode('preset','saved')",script)
        self.assertIn("$('presetSelect').value=response.filename",script)
        self.assertNotIn("$('savePreset')",script)
    def test_server_stages_validates_and_does_not_clobber_other_presets(self):
        code=(ROOT/'flask_app.py').read_text()
        self.assertIn('file.save(staged)',code)
        self.assertIn('count = validate_preset(staged)',code)
        self.assertIn('os.replace(staged, output)',code)
        self.assertIn('if hashlib.sha256(output.read_bytes()).hexdigest() == incoming_hash:',code)
        self.assertIn('staged.unlink(missing_ok=True)',code)
