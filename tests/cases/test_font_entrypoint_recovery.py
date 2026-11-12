"""Exercise failure/recovery status through real configuration and CLI files."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import setup_fonts as fonts


class FontEntrypointRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.project = self.root / 'project'
        self.cache = self.root / 'cache'
        source = self.bundle / 'Fixture.otf'
        source.write_bytes(b'font fixture bytes')
        self.manifest = self.bundle / 'fonts.json'
        self.manifest.write_text(json.dumps({'schema_version': 1,
            'fonts': [{'file': source.name, 'family': 'Fixture', 'style': 'Regular',
                       'postscript_name': 'Fixture-Regular',
                       'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
            'roles': {r: {'regular': source.name} for r in fonts.ROLE_COMMANDS}}))
        p = patch.object(fonts, 'user_cache_directory', return_value=self.cache)
        p.start()
        self.addCleanup(p.stop)

    def arguments(self):
        return ['--manifest', str(self.manifest), '--project-dir', str(self.project),
                '--cache-dir', str(self.cache), '--no-install']

    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = fonts.main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_argument_errors_never_use_cache_ready_status_two(self):
        for args in ([], ['--unknown'], self.arguments() + ['--install']):
            with self.subTest(args=args):
                code, _, error = self.invoke(args)
                self.assertEqual(code, 1)
                self.assertIn('Invalid', error)
        self.assertFalse(self.project.exists())

    def test_unexpected_resource_failure_has_report_and_recovery(self):
        with patch.object(fonts, 'load_manifest', side_effect=RuntimeError('broken input')):
            code, stdout, _ = self.invoke(self.arguments())
        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report['exit_status'], 1)
        self.assertFalse(report['cache_ready'])
        self.assertIn('RuntimeError', report['errors'][0])
        self.assertTrue(report['recovery'])
        self.assertEqual(json.loads((self.project/'font-setup-report.json').read_text()), report)

    def test_native_exception_retains_exact_cache_and_continues(self):
        with patch.object(fonts, 'user_font_directory', return_value=self.root/'installed'), \
             patch.object(fonts, 'install_native', side_effect=RuntimeError('native API unavailable')):
            result = fonts.setup_fonts(self.manifest, self.project, system='Linux')
        self.assertEqual(result['exit_status'], 2)
        self.assertTrue(result['cache_ready'])
        self.assertTrue(Path(result['tex_file']).is_file())
        self.assertIn('RuntimeError', result['fonts'][0]['error'])

    def test_report_write_failure_propagates_to_json_and_exit(self):
        original = fonts.os.replace
        def fail_report(source, target):
            if Path(target).name == 'font-setup-report.json':
                raise PermissionError('report locked')
            return original(source, target)
        with patch.object(fonts.os, 'replace', side_effect=fail_report):
            code, stdout, stderr = self.invoke(self.arguments())
        report = json.loads(stdout)
        self.assertEqual(code, 1)
        self.assertEqual(report['exit_status'], 1)
        self.assertEqual(report['configuration_exit_status'], 2)
        self.assertEqual(report['stage'], 'report-write')
        self.assertTrue(report['cache_ready'])
        self.assertIn('report locked', stderr)
        self.assertFalse((self.project/'font-setup-report.json').exists())

    def test_atomic_write_retains_prior_valid_configuration(self):
        target = self.root/'existing.tex'
        target.write_text('prior valid contents')
        with patch.object(fonts.os, 'replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                fonts.write_if_changed(target, 'new contents')
        self.assertEqual(target.read_text(), 'prior valid contents')
        self.assertEqual({p.name for p in self.root.iterdir()}, {'bundle', 'existing.tex'})

    def test_invalid_export_manifest_returns_failure_without_traceback(self):
        self.manifest.write_text('[]')
        code, _, stderr = self.invoke(['--manifest', str(self.manifest),
                                       '--project-dir', str(self.project), '--export-bootstrap'])
        self.assertEqual(code, 1)
        self.assertIn('Cannot export', stderr)
        self.assertFalse(self.project.exists())

    def test_bootstrap_process_preserves_argument_failure(self):
        fonts.export_bootstrap(self.manifest, self.project)
        result = subprocess.run([sys.executable, '-B', str(self.project/'prepare-fonts.py'), '--unknown'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.project/'myppt-fonts.tex').exists())

    def test_cancel_is_not_converted_to_recoverable_font_status(self):
        with patch.object(fonts, 'load_manifest', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                fonts.setup_fonts(self.manifest, self.project, install=False)

    def test_repeated_slow_os_registration_stops_and_keeps_tex_ready(self):
        data=json.loads(self.manifest.read_text())
        second=self.bundle/'Second.otf'
        second.write_bytes(b'second font fixture')
        data['fonts'].append(dict(data['fonts'][0],file=second.name,
                                  sha256=hashlib.sha256(second.read_bytes()).hexdigest()))
        self.manifest.write_text(json.dumps(data))
        clock=[0]
        def slow_native(*args):
            clock[0]+=fonts.OS_REGISTRATION_BUDGET+1
            return {'installed':True,'os_available':True,'configured':True}
        with patch.object(fonts.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(fonts,'user_font_directory',return_value=self.root/'installed'), \
             patch.object(fonts,'install_native',side_effect=slow_native) as native:
            result=fonts.setup_fonts(self.manifest,self.project,system='Linux')
        self.assertEqual(native.call_count,1)
        self.assertEqual(result['exit_status'],2)
        self.assertTrue(result['cache_ready'])
        self.assertIn('budget',result['fonts'][1]['error'])
