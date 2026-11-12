"""Tiny real-file fixtures exercise setup; native font calls are mocked."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import setup_fonts as fonts


class FontSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        cache_patch = patch.object(fonts, 'user_cache_directory', return_value=self.cache)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.project = self.root / 'project with spaces'
        self.destination = self.root / 'user-fonts'
        self.source = self.bundle / 'Fixture-Regular.otf'
        self.source.write_bytes(b'tiny-font-fixture\x00\x01')
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.data = {'schema_version': 1, 'fonts': [{'file': self.source.name,
                     'family': 'Fixture', 'style': 'Regular', 'postscript_name': 'Fixture-Regular',
                     'sha256': self.sha}],
                     'roles': {r: {'regular': self.source.name} for r in fonts.ROLE_COMMANDS}}
        self.manifest = self.bundle / 'fonts.json'
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.data), encoding='utf-8')

    def setup(self, install=True, system='Linux', native=None):
        result = native or {'configured': True, 'installed': True, 'os_available': True,
                            'application_refresh_required': True}
        with patch.object(fonts, 'user_font_directory', return_value=self.destination), \
             patch.object(fonts, 'install_native', return_value=result) as call, \
             patch.object(fonts, 'broadcast_windows_change', return_value=True):
            report = fonts.setup_fonts(self.manifest, self.project, install, system)
        return report, call

    def test_real_copy_tex_and_status(self):
        report, native = self.setup()
        self.assertEqual(report['exit_status'], 0)
        self.assertTrue(report['os_available'])
        self.assertEqual((self.destination / self.source.name).read_bytes(), self.source.read_bytes())
        self.assertEqual((Path(report['font_dir']) / self.source.name).read_bytes(), self.source.read_bytes())
        tex = Path(report['tex_file']).read_text()
        self.assertIn('Path={' + self.cache.as_posix() + '/myppt-', tex)
        self.assertIn('\\setsansfont[', tex)
        self.assertNotIn(str(self.project), tex)
        self.assertFalse(report['project_local'])
        self.assertFalse((self.project / 'fonts').exists())
        self.assertNotIn('RequirePackage{unicode-math}', tex)
        self.assertNotIn('RequirePackage{xeCJK}', tex)
        self.assertIn('ifdefined\\setCJKmainfont', tex)
        self.assertIn('RequirePackage[fontset=none]{ctex}', tex)
        self.assertTrue(tex.startswith(fonts.TEX_MARKER))
        self.assertIn('providecommand{\\MyPPTUseBundledMathFont}', tex)
        native.assert_called_once()

    def test_no_install_reports_local_only(self):
        report, call = self.setup(install=False)
        self.assertEqual(report['exit_status'], 2)
        self.assertTrue(report['cache_ready'])
        self.assertFalse(report['installed'])
        call.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_hash_failure_before_any_install(self):
        self.source.write_bytes(b'corrupted')
        report, call = self.setup()
        self.assertEqual(report['exit_status'], 1)
        self.assertIn('SHA256', report['errors'][0])
        self.assertFalse(self.project.exists())
        call.assert_not_called()

    def test_all_hashes_validated_before_mutation(self):
        self.data['fonts'].append(dict(self.data['fonts'][0], file='Bad.otf', sha256='0' * 64))
        (self.bundle / 'Bad.otf').write_bytes(b'bad')
        self.write_manifest()
        report, call = self.setup()
        self.assertEqual(report['exit_status'], 1)
        self.assertFalse(self.destination.exists())
        call.assert_not_called()

    def test_path_traversal_and_absolute_paths_rejected(self):
        for name in ('../outside.otf', '/outside.otf', 'C:/outside.otf', 'C:outside.otf', '..\\outside.otf'):
            with self.subTest(name=name):
                self.data['fonts'][0]['file'] = name
                self.write_manifest()
                report, call = self.setup()
                self.assertEqual(report['exit_status'], 1)
                call.assert_not_called()

    def test_resolved_source_must_remain_in_bundle(self):
        original = Path.resolve
        outside = self.root / 'outside.otf'
        outside.write_bytes(self.source.read_bytes())
        def resolve(path, *args, **kwargs):
            return outside if path == self.source else original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            report, call = self.setup()
        self.assertEqual(report['exit_status'], 1)
        self.assertIn('escapes bundle', report['errors'][0])
        call.assert_not_called()

    def test_idempotent_files_keep_timestamps(self):
        report, _ = self.setup()
        files = [Path(report['tex_file']), self.destination / self.source.name,
                 Path(report['font_dir']) / self.source.name]
        for path in files:
            os.utime(path, ns=(1234567890000000000, 1234567890000000000))
        before = [p.stat().st_mtime_ns for p in files]
        again, _ = self.setup()
        self.assertEqual(again['exit_status'], 0)
        self.assertEqual(before, [p.stat().st_mtime_ns for p in files])
        self.assertEqual(again['fonts'][0]['copy_status'], 'existing')

    def test_different_user_font_preserved_project_still_ready(self):
        self.destination.mkdir()
        target = self.destination / self.source.name
        target.write_bytes(b'existing-other-version')
        report, call = self.setup()
        self.assertEqual(report['exit_status'], 2)
        self.assertTrue(report['cache_ready'])
        self.assertFalse(report['os_available'])
        self.assertEqual(target.read_bytes(), b'existing-other-version')
        self.assertIn('preserved', report['fonts'][0]['error'])
        call.assert_not_called()

    def test_native_error_keeps_local_fonts(self):
        with patch.object(fonts, 'user_font_directory', return_value=self.destination), \
             patch.object(fonts, 'install_native', side_effect=OSError('native failed')):
            report = fonts.setup_fonts(self.manifest, self.project)
        self.assertEqual(report['exit_status'], 2)
        self.assertTrue(report['cache_ready'])
        self.assertFalse(report['installed'])
        self.assertIn('native failed', report['fonts'][0]['error'])

    def test_copy_success_does_not_imply_os_availability(self):
        report, _ = self.setup(native={'configured': True, 'installed': False, 'os_available': False})
        self.assertEqual(report['exit_status'], 2)
        self.assertTrue((self.destination / self.source.name).exists())
        self.assertFalse(report['os_available'])

    def test_platform_dispatch(self):
        for system, name in [('Windows', 'install_windows'), ('Linux', 'install_linux'), ('Darwin', 'install_macos')]:
            with self.subTest(system=system), patch.object(fonts, name, return_value={'native': system}) as call:
                self.assertEqual(fonts.install_native({}, self.source, system), {'native': system})
                call.assert_called_once_with({}, self.source)

    def test_user_directories(self):
        home = self.root / 'home'
        self.assertEqual(fonts.user_font_directory('Darwin', {}, home), home / 'Library/Fonts')
        self.assertEqual(fonts.user_font_directory('Linux', {}, home), home / '.local/share/fonts/MyPPTSkill')
        self.assertEqual(fonts.user_font_directory('Linux', {'XDG_DATA_HOME': 'relative'}, home), home / '.local/share/fonts/MyPPTSkill')
        self.assertEqual(fonts.user_font_directory('Windows', {'LOCALAPPDATA': str(self.root)}, home), self.root / 'Microsoft/Windows/Fonts')
        with self.assertRaises(ValueError):
            fonts.user_font_directory('Windows', {}, home)

    def test_linux_no_cache_never_claims_installed(self):
        with patch.object(fonts.shutil, 'which', return_value=None):
            result = fonts.install_linux(self.data['fonts'][0], self.source)
        self.assertFalse(result['installed'])
        self.assertFalse(result['os_available'])

    def test_linux_substituted_file_rejected(self):
        wrong = self.root / 'wrong.otf'
        wrong.write_bytes(b'different version')
        with patch.object(fonts.shutil, 'which', side_effect=lambda name: name), \
             patch.object(fonts.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, str(wrong) + '\n', '')) as run:
            result = fonts.install_linux(self.data['fonts'][0], self.source)
        self.assertFalse(result['os_available'])
        self.assertTrue(all('timeout' in c.kwargs for c in run.call_args_list))

    def test_windows_branch_broadcasts_and_reports_refresh(self):
        report, call = self.setup(system='Windows')
        self.assertEqual(report['exit_status'], 0)
        self.assertTrue(report['fontchange_broadcast'])
        self.assertTrue(report['application_refresh_required'])
        self.assertEqual(call.call_args.args[-1], 'Windows')

    def test_cli_exit_and_report(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = fonts.main(['--manifest', str(self.manifest), '--project-dir', str(self.project), '--no-install'])
        self.assertEqual(code, 2)
        report = json.loads((self.project / 'font-setup-report.json').read_text())
        self.assertEqual(report['exit_status'], code)
        self.source.write_bytes(b'corrupt')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(fonts.main(['--manifest', str(self.manifest), '--project-dir', str(self.project), '--no-install']), 1)

    def make_archive(self, extra=None, member_bytes=None):
        stream = io.BytesIO()
        content = self.source.read_bytes() if member_bytes is None else member_bytes
        with zipfile.ZipFile(stream, 'w') as zipped:
            zipped.writestr('fandol/' + self.source.name, content)
            zipped.writestr('fandol/COPYING', b'fixture license')
            if extra:
                info = zipfile.ZipInfo('placeholder')
                info.filename = extra
                zipped.writestr(info, b'unsafe')
        value = stream.getvalue()
        package = {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value),
                   'urls': ['https://mirrors.ctan.org/fonts/fandol.zip'],
                   'archive_root': 'fandol', 'license_files': ['COPYING']}
        entries = [dict(self.data['fonts'][0], file='fandol/' + self.source.name, package='fandol')]
        return value, package, entries

    def response(self, value, url='https://mirrors.ctan.org/fonts/fandol.zip'):
        def transport(request_url, destination, size, timeout):
            if not url.startswith('https://'):
                raise ValueError('Package redirect must remain HTTPS')
            Path(destination).write_bytes(value)
        return transport

    def test_pinned_download_cache_and_safe_extraction(self):
        value, package, entries = self.make_archive()
        with patch.object(fonts, '_download_to_file', side_effect=self.response(value)) as request:
            archive = fonts.download_package(package, self.cache)
            extracted = fonts.extract_package(archive, package, entries, self.cache)
            again = fonts.download_package(package, self.cache, offline=True)
        self.assertEqual(archive, again)
        self.assertEqual((extracted / entries[0]['file']).read_bytes(), self.source.read_bytes())
        request.assert_called_once()
        self.assertLessEqual(request.call_args.kwargs['timeout'], fonts.DOWNLOAD_ATTEMPT_TIMEOUT)

    def test_offline_never_calls_network(self):
        _, package, _ = self.make_archive()
        with patch.object(fonts, '_download_to_file') as request:
            with self.assertRaisesRegex(ValueError, 'offline'):
                fonts.download_package(package, self.cache, offline=True)
        request.assert_not_called()

    def test_download_invalid_hash_size_url_and_redirect_rejected(self):
        value, package, _ = self.make_archive()
        with patch.object(fonts, '_download_to_file', side_effect=self.response(value + b'x')):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                fonts.download_package(package, self.cache)
        with patch.object(fonts, '_download_to_file', side_effect=self.response(b'x' * len(value))):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                fonts.download_package(package, self.cache)
        for url in ['http://mirrors.ctan.org/fonts/fandol.zip', 'https://example.com/other.zip']:
            with self.subTest(url=url), patch.object(fonts, '_download_to_file') as request:
                with self.assertRaisesRegex(ValueError, 'official'):
                    fonts.download_package(dict(package, urls=[url]), self.cache)
                request.assert_not_called()
        with patch.object(fonts, '_download_to_file', side_effect=self.response(value, 'http://example.com/font.zip')):
            with self.assertRaisesRegex(ValueError, 'HTTPS'):
                fonts.download_package(package, self.cache)

    def test_entire_zip_checked_before_any_extraction(self):
        for bad in ['fandol/../outside.otf', '/fandol/abs.otf', 'other/root.otf', 'fandol\\bad.otf', 'C:/fandol/bad.otf']:
            with self.subTest(member=bad):
                value, package, entries = self.make_archive(extra=bad)
                archive = self.root / 'unsafe.zip'
                archive.write_bytes(value)
                with self.assertRaisesRegex(ValueError, 'Unsafe ZIP'):
                    fonts.extract_package(archive, package, entries, self.cache)
                self.assertFalse((self.cache / 'packages').exists())

    def test_zip_member_hash_rejected_before_extract(self):
        value, package, entries = self.make_archive(member_bytes=b'wrong')
        archive = self.root / 'wrong.zip'
        archive.write_bytes(value)
        with self.assertRaisesRegex(ValueError, 'member SHA256'):
            fonts.extract_package(archive, package, entries, self.cache)
        self.assertFalse((self.cache / 'packages').exists())

    def test_external_exact_existing_file_used_offline(self):
        self.data['fonts'][0].update(file='fandol/' + self.source.name, distribution='download', package='fandol')
        self.data['roles'] = {role: {'regular': self.data['fonts'][0]['file']} for role in fonts.ROLE_COMMANDS}
        self.write_manifest()
        with patch.object(fonts, 'existing_exact_font', return_value=self.source), \
             patch.object(fonts, '_download_to_file') as request:
            report = fonts.setup_fonts(self.manifest, self.project, install=False, offline=True)
        self.assertEqual(report['exit_status'], 2)
        self.assertTrue(report['cache_ready'])
        request.assert_not_called()

    def test_download_setup_then_offline_cached_rerun(self):
        value, package, entries = self.make_archive()
        self.data['fonts'] = [dict(entries[0], distribution='download')]
        self.data['packages'] = {'fandol': package}
        self.data['roles'] = {role: {'regular': entries[0]['file']} for role in fonts.ROLE_COMMANDS}
        self.write_manifest()
        with patch.object(fonts, 'existing_exact_font', return_value=None), \
             patch.object(fonts, '_download_to_file', side_effect=self.response(value)) as request:
            report = fonts.setup_fonts(self.manifest, self.project, install=False)
        self.assertTrue(report['cache_ready'])
        self.assertEqual(report['exit_status'], 2)
        request.assert_called_once()
        with patch.object(fonts, '_download_to_file') as request:
            again = fonts.setup_fonts(self.manifest, self.project, install=False, offline=True)
        self.assertTrue(again['cache_ready'])
        request.assert_not_called()

    def test_windows_legacy_family_is_read_from_font_bytes(self):
        value = 'LM Sans 10'.encode('utf-16-be')
        table = struct.pack('>HHH', 0, 1, 18) + struct.pack('>HHHHHH', 3, 1, 0x409, 1, len(value), 0) + value
        header = b'OTTO' + struct.pack('>HHHH', 1, 0, 0, 0)
        self.source.write_bytes(header + struct.pack('>4sIII', b'name', 0, 28, len(table)) + table)
        self.assertEqual(fonts.windows_font_family(self.source, 'Latin Modern Sans'), 'LM Sans 10')

    def test_user_tex_configuration_preserved_before_preparation(self):
        self.project.mkdir()
        target = self.project / 'myppt-fonts.tex'
        target.write_text('% My personal font choices\n', encoding='utf-8')
        with patch.object(fonts, 'load_manifest') as load:
            report = fonts.setup_fonts(self.manifest, self.project)
        self.assertEqual(report['exit_status'], 1)
        self.assertIn('preserved', report['errors'][0])
        self.assertEqual(target.read_text(), '% My personal font choices\n')
        load.assert_not_called()

    def test_managed_tex_can_be_regenerated(self):
        self.project.mkdir()
        target = self.project / 'myppt-fonts.tex'
        target.write_text(fonts.TEX_MARKER + '\n% outdated managed output\n', encoding='utf-8')
        report, _ = self.setup(install=False)
        self.assertEqual(report['exit_status'], 2)
        self.assertIn('setCJKmainfont', target.read_text())

    def test_cli_report_collisions_preserve_inputs_and_skip_setup(self):
        self.project.mkdir()
        main = self.project / 'main.tex'
        main.write_text('user source', encoding='utf-8')
        unrelated = self.project / 'data.json'
        unrelated.write_text('{"user":true}', encoding='utf-8')
        managed = self.project / 'myppt-fonts.tex'
        managed.write_text(fonts.TEX_MARKER + '\n', encoding='utf-8')
        for target in [main, unrelated, self.manifest, self.source, managed, self.cache / 'input.json']:
            with self.subTest(target=target):
                before = target.read_bytes() if target.exists() else None
                with contextlib.redirect_stderr(io.StringIO()), patch.object(fonts, 'setup_fonts') as setup:
                    result = fonts.main(['--manifest', str(self.manifest), '--project-dir', str(self.project), '--report', str(target)])
                self.assertEqual(result, 1)
                setup.assert_not_called()
                self.assertEqual(target.read_bytes() if target.exists() else None, before)

    def test_managed_report_updates_are_allowed(self):
        self.project.mkdir()
        target = self.project / 'previous.json'
        target.write_text(json.dumps({'report_schema': fonts.REPORT_SCHEMA, 'exit_status': 99}), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            result = fonts.main(['--manifest', str(self.manifest), '--project-dir', str(self.project), '--report', str(target), '--no-install'])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(target.read_text())['exit_status'], 2)

    def mocked_windows(self, registry_value=None, add_result=0):
        key = MagicMock()
        registry = types.SimpleNamespace(HKEY_CURRENT_USER=1, KEY_READ=1, KEY_WRITE=2, REG_SZ=1,
                                         CreateKeyEx=MagicMock(return_value=key),
                                         QueryValueEx=MagicMock(), SetValueEx=MagicMock())
        if registry_value is None:
            registry.QueryValueEx.side_effect = FileNotFoundError
        else:
            registry.QueryValueEx.return_value = (str(registry_value), 1)
        gdi = MagicMock()
        gdi.AddFontResourceExW.return_value = add_result
        return registry, gdi

    def test_windows_family_does_not_mask_new_face_failure(self):
        registry, gdi = self.mocked_windows()
        def only_family(*args):
            return len(args) == 1
        with patch.dict(sys.modules, {'winreg': registry}), \
             patch.object(fonts.ctypes, 'WinDLL', return_value=gdi, create=True), \
             patch.object(fonts, 'windows_family_available', side_effect=only_family) as available:
            result = fonts.install_windows(dict(self.data['fonts'][0], style='Bold'), self.source)
        self.assertFalse(result['installed'])
        self.assertFalse(result['os_available'])
        self.assertTrue(all(len(call.args) == 3 for call in available.call_args_list))
        gdi.AddFontResourceExW.assert_called_once()

    def test_windows_existing_registry_requires_exact_face(self):
        registry, gdi = self.mocked_windows(self.source)
        with patch.dict(sys.modules, {'winreg': registry}), \
             patch.object(fonts.ctypes, 'WinDLL', return_value=gdi, create=True), \
             patch.object(fonts, 'windows_family_available', return_value=False):
            result = fonts.install_windows(self.data['fonts'][0], self.source)
        self.assertFalse(result['installed'])
        gdi.AddFontResourceExW.assert_called_once()

    def test_windows_verified_existing_face_is_idempotent(self):
        registry, gdi = self.mocked_windows(self.source)
        with patch.dict(sys.modules, {'winreg': registry}), \
             patch.object(fonts.ctypes, 'WinDLL', return_value=gdi, create=True), \
             patch.object(fonts, 'windows_family_available', return_value=True):
            result = fonts.install_windows(self.data['fonts'][0], self.source)
        self.assertTrue(result['installed'])
        self.assertTrue(result['face_verified'])
        gdi.AddFontResourceExW.assert_not_called()
        registry.SetValueEx.assert_not_called()

    def test_bootstrap_export_public_files_only_no_setup_or_network(self):
        private = self.bundle / 'fandol/Private.otf'
        private.parent.mkdir()
        private.write_bytes(b'private external font')
        self.data['fonts'].append({'file': 'fandol/Private.otf', 'distribution': 'download'})
        self.write_manifest()
        cache = self.bundle / 'cache/private-cache.otf'
        cache.parent.mkdir()
        cache.write_bytes(b'cached font')
        license_path = self.bundle / 'licenses/NOTICE'
        license_path.parent.mkdir()
        license_path.write_text('license text', encoding='utf-8')
        with patch.object(fonts, 'setup_fonts') as setup, \
             patch.object(fonts, '_download_to_file') as network, \
             contextlib.redirect_stdout(io.StringIO()):
            result = fonts.main(['--manifest', str(self.manifest), '--project-dir', str(self.project), '--export-bootstrap'])
        self.assertEqual(result, 0)
        setup.assert_not_called()
        network.assert_not_called()
        self.assertTrue((self.project / 'prepare-fonts.py').is_file())
        self.assertTrue((self.project / 'font-support/scripts/setup_fonts.py').is_file())
        exported = self.project / 'font-support/assets/fonts'
        self.assertTrue((exported / self.source.name).is_file())
        self.assertTrue((exported / 'licenses/NOTICE').is_file())
        self.assertFalse((exported / 'fandol').exists())
        self.assertFalse((exported / 'cache').exists())
        self.assertFalse((self.project / 'myppt-fonts.tex').exists())
        self.assertFalse((self.project / 'font-setup-report.json').exists())

    def test_bootstrap_export_idempotent_and_conflict_preserves_project(self):
        fonts.export_bootstrap(self.manifest, self.project)
        launcher = self.project / 'prepare-fonts.py'
        os.utime(launcher, ns=(1234567890000000000, 1234567890000000000))
        before = launcher.stat().st_mtime_ns
        fonts.export_bootstrap(self.manifest, self.project)
        self.assertEqual(launcher.stat().st_mtime_ns, before)
        launcher.write_text('user launcher', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'preserved'):
            fonts.export_bootstrap(self.manifest, self.project)
        self.assertEqual(launcher.read_text(), 'user launcher')

    def test_bootstrap_preflight_conflict_does_not_partially_export(self):
        self.project.mkdir()
        launcher = self.project / 'prepare-fonts.py'
        launcher.write_text('existing user launcher', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'preserved'):
            fonts.export_bootstrap(self.manifest, self.project)
        self.assertFalse((self.project / 'font-support').exists())

    def test_exported_launcher_runs_independently_with_forwarded_options(self):
        fonts.export_bootstrap(self.manifest, self.project)
        target_cache = self.root / 'portable cache'
        result = subprocess.run([sys.executable, str(self.project / 'prepare-fonts.py'), '--offline',
                                 '--no-install', '--cache-dir', str(target_cache)],
                                cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['cache_ready'])
        self.assertEqual(Path(report['project_dir']), self.project)
        self.assertTrue(Path(report['font_dir']).is_relative_to(target_cache))


if __name__ == '__main__':
    unittest.main()
