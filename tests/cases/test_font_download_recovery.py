"""Local fault injection; network transport is mocked or isolated in killable children."""
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import setup_fonts as fonts


class FontDownloadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / 'cache'
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.project = self.root / 'project'
        self.raw = b'fixture verified font\x00\x01'
        self.source = self.bundle / 'Tiny.otf'
        self.source.write_bytes(self.raw)
        self.font = {'file': 'Tiny.otf', 'family': 'Tiny', 'style': 'Regular',
                     'postscript_name': 'Tiny-Regular', 'sha256': hashlib.sha256(self.raw).hexdigest()}
        self.entries = [dict(self.font, file='fandol/Tiny.otf', distribution='download', package='fandol')]
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('fandol/Tiny.otf', self.raw)
            archive.writestr('fandol/COPYING', b'fixture license')
        self.archive_bytes = stream.getvalue()
        self.package = {'sha256': hashlib.sha256(self.archive_bytes).hexdigest(), 'bytes': len(self.archive_bytes),
                        'urls': sorted(fonts.FANDOL_URLS)[:2], 'archive_root': 'fandol', 'license_files': ['COPYING']}
        self.manifest = self.bundle / 'fonts.json'
        self.write_manifest([self.font])

    def write_manifest(self, entries, packages=None):
        self.data = {'schema_version': 1, 'fonts': entries,
                     'roles': {r: {'regular': entries[0]['file']} for r in fonts.ROLE_COMMANDS},
                     'packages': packages or {}}
        self.manifest.write_text(json.dumps(self.data), encoding='utf-8')
        self.runtime = self.cache / ('myppt-' + fonts.digest(self.manifest)[:16])

    def archive_path(self):
        return self.cache / 'archives' / ('fandol-' + self.package['sha256'] + '.zip')

    def transport(self, url, destination, size, timeout):
        Path(destination).write_bytes(self.archive_bytes)

    def test_incomplete_read_recovers_via_next_pinned_mirror(self):
        attempts = []
        def transfer(url, destination, size, timeout):
            attempts.append(url)
            if len(attempts) == 1:
                Path(destination).write_bytes(b'partial')
                raise http.client.IncompleteRead(b'partial', 100)
            self.transport(url, destination, size, timeout)
        with patch.object(fonts, '_download_to_file', side_effect=transfer):
            archive = fonts.download_package(self.package, self.cache)
        self.assertEqual(fonts.digest(archive), self.package['sha256'])
        self.assertEqual(len(attempts), 2)
        self.assertFalse(list(archive.parent.glob('.myppt-download-*')))

    def test_http_exception_is_actionable_and_cleans_partial_files(self):
        with patch.object(fonts, '_download_to_file', side_effect=http.client.BadStatusLine('broken header')):
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts.download_package(self.package, self.cache)
        self.assertEqual(caught.exception.code, 'font_download_failed')
        self.assertIn('BadStatusLine', str(caught.exception))
        self.assertTrue(caught.exception.recovery)
        self.assertFalse(self.archive_path().exists())
        self.assertFalse(list(self.archive_path().parent.glob('.myppt-download-*')))

    def test_worker_catches_incomplete_read_without_traceback(self):
        prefix = '''import urllib.request, http.client
class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return 'https://mirrors.ctan.org/fonts/fandol.zip'
    def read(self, size): raise http.client.IncompleteRead(b'partial', 50)
urllib.request.urlopen = lambda *args, **kwargs: Response()
'''
        with patch.object(fonts, 'DOWNLOAD_WORKER', prefix + fonts.DOWNLOAD_WORKER):
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts._download_to_file(self.package['urls'][0], self.root / 'transfer.tmp', len(self.raw), timeout=4)
        self.assertIn('IncompleteRead', str(caught.exception))
        self.assertNotIn('Traceback', str(caught.exception))

    def test_hung_dns_is_killed_by_parent_deadline(self):
        prefix = '''import socket, time, urllib.request
socket.getaddrinfo = lambda *args, **kwargs: time.sleep(30)
urllib.request.urlopen = lambda *args, **kwargs: socket.getaddrinfo('no-network.invalid', 443)
'''
        started = time.monotonic()
        with patch.object(fonts, 'DOWNLOAD_WORKER', prefix + fonts.DOWNLOAD_WORKER):
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts._download_to_file(self.package['urls'][0], self.root / 'dns.tmp', 10, timeout=0.4)
        self.assertEqual(caught.exception.code, 'font_download_timeout')
        self.assertLess(time.monotonic() - started, 3)

    def test_hung_body_read_is_killed_by_parent_deadline(self):
        prefix = '''import urllib.request, time
class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def geturl(self): return 'https://mirrors.ctan.org/fonts/fandol.zip'
    def read(self, size): time.sleep(30); return b'x'
urllib.request.urlopen = lambda *args, **kwargs: Response()
'''
        started = time.monotonic()
        with patch.object(fonts, 'DOWNLOAD_WORKER', prefix + fonts.DOWNLOAD_WORKER):
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts._download_to_file(self.package['urls'][0], self.root / 'body.tmp', 10, timeout=0.4)
        self.assertEqual(caught.exception.code, 'font_download_timeout')
        self.assertLess(time.monotonic() - started, 3)

    def test_transport_diagnostics_are_utf8_in_isolated_process(self):
        worker = "import sys; print(sys.flags.utf8_mode, '\\u4e2d\\u6587\\u8def\\u5f84', file=sys.stderr); sys.exit(1)"
        with patch.object(fonts, 'DOWNLOAD_WORKER', worker):
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts._download_to_file(self.package['urls'][0], self.root/'unicode.tmp', 10, timeout=4)
        self.assertIn('1 中文路径', str(caught.exception))

    def test_total_budget_covers_all_mirrors(self):
        with patch.object(fonts, 'DOWNLOAD_TOTAL_TIMEOUT', 0.5), \
             patch.object(fonts, 'DOWNLOAD_ATTEMPT_TIMEOUT', 0.3), \
             patch.object(fonts, 'DOWNLOAD_WORKER', 'import time; time.sleep(30)'):
            started = time.monotonic()
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts.download_package(self.package, self.cache)
        self.assertEqual(caught.exception.code, 'font_download_timeout')
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(list(self.archive_path().parent.glob('.myppt-download-*')))

    def test_bad_archive_is_preserved_and_automatically_replaced(self):
        archive = self.archive_path()
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b'interrupted archive')
        diagnostics = []
        with patch.object(fonts, '_download_to_file', side_effect=self.transport) as transport:
            result = fonts.download_package(self.package, self.cache, diagnostics=diagnostics)
        self.assertEqual(fonts.digest(result), self.package['sha256'])
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(Path(diagnostics[0]['preserved']).read_bytes(), b'interrupted archive')
        self.assertTrue(Path(diagnostics[0]['preserved']).with_name('recovery.json').is_file())
        transport.assert_called_once()

    def test_offline_bad_archive_has_recovery_and_no_repeated_corrupt_retry(self):
        archive = self.archive_path()
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b'bad')
        with patch.object(fonts, '_download_to_file') as transport:
            with self.assertRaises(fonts.FontPreparationError) as first:
                fonts.download_package(self.package, self.cache, offline=True)
            with self.assertRaises(fonts.FontPreparationError) as second:
                fonts.download_package(self.package, self.cache, offline=True)
        self.assertEqual(first.exception.code, 'font_offline_unavailable')
        self.assertEqual(len(first.exception.diagnostics), 1)
        self.assertEqual(second.exception.diagnostics, [])
        self.assertIn('without --offline', first.exception.recovery)
        transport.assert_not_called()

    def test_corrupt_extracted_font_repairs_offline_from_verified_archive(self):
        archive = self.archive_path()
        archive.parent.mkdir(parents=True)
        archive.write_bytes(self.archive_bytes)
        target = self.cache / 'packages' / self.package['sha256'] / 'fandol/Tiny.otf'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'half font')
        diagnostics = []
        directory = fonts.extract_package(archive, self.package, self.entries, self.cache, diagnostics)
        self.assertEqual((directory / 'fandol/Tiny.otf').read_bytes(), self.raw)
        self.assertEqual(Path(diagnostics[0]['preserved']).read_bytes(), b'half font')

    def test_runtime_partial_font_recovers_and_user_font_stays_untouched(self):
        self.runtime.mkdir(parents=True)
        (self.runtime / 'Tiny.otf').write_bytes(b'partial runtime')
        user_font = self.root / 'OS-user-fonts/Tiny.otf'
        user_font.parent.mkdir()
        user_font.write_bytes(b'user font other version')
        data = fonts.load_manifest(self.manifest, self.cache, offline=True)
        self.assertEqual((self.runtime / 'Tiny.otf').read_bytes(), self.raw)
        self.assertEqual(user_font.read_bytes(), b'user font other version')
        self.assertEqual(len(data['_cache_recovery']), 1)
        self.assertEqual(Path(data['_cache_recovery'][0]['preserved']).read_bytes(), b'partial runtime')

    def test_corrupt_license_archive_and_cached_manifest_recover(self):
        license_file = self.bundle / 'licenses/NOTICE'
        license_file.parent.mkdir()
        license_file.write_bytes(b'original license')
        upstream = self.bundle / 'upstream/lm.zip'
        upstream.parent.mkdir()
        upstream.write_bytes(b'upstream fixture')
        self.write_manifest([self.font], {'lm': {'local_archive': 'upstream/lm.zip', 'sha256': fonts.digest(upstream)}})
        for relative in ['licenses/NOTICE', 'upstream/lm.zip', 'fonts.json']:
            target = self.runtime / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'\xff interrupted')
        report = fonts.setup_fonts(self.manifest, self.project, install=False, cache_dir=self.cache, offline=True)
        self.assertEqual(report['exit_status'], 2, report)
        self.assertEqual((self.runtime / 'licenses/NOTICE').read_bytes(), license_file.read_bytes())
        self.assertEqual((self.runtime / 'upstream/lm.zip').read_bytes(), upstream.read_bytes())
        self.assertEqual(json.loads((self.runtime / 'fonts.json').read_text())['schema_version'], 1)
        self.assertEqual(len(list((self.cache / 'quarantine').glob('*/recovery.json'))), 3)

    def test_complete_runtime_cache_ignores_bad_archive_without_network(self):
        self.write_manifest(self.entries, {'fandol': self.package})
        self.runtime.mkdir(parents=True)
        (self.runtime / 'Tiny.otf').write_bytes(self.raw)
        archive = self.archive_path()
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b'bad but unused archive')
        with patch.object(fonts, '_download_to_file') as network, patch.object(fonts, 'existing_exact_font') as local:
            data = fonts.load_manifest(self.manifest, self.cache, offline=True)
        self.assertEqual(data['_cache_recovery'], [])
        network.assert_not_called()
        local.assert_not_called()
        self.assertEqual(archive.read_bytes(), b'bad but unused archive')

    def test_verified_extracted_cache_works_without_archive(self):
        self.write_manifest(self.entries, {'fandol': self.package})
        target = self.cache / 'packages' / self.package['sha256'] / 'fandol/Tiny.otf'
        target.parent.mkdir(parents=True)
        target.write_bytes(self.raw)
        with patch.object(fonts, '_download_to_file') as network, patch.object(fonts, 'existing_exact_font') as local:
            data = fonts.load_manifest(self.manifest, self.cache, offline=True)
        self.assertEqual((self.runtime / 'Tiny.otf').read_bytes(), self.raw)
        network.assert_not_called()
        local.assert_not_called()

    def test_unsafe_cache_link_is_preserved_without_recovery_mutation(self):
        archive = self.archive_path()
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b'user data')
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == archive or original(path)), \
             patch.object(fonts, '_download_to_file') as network:
            with self.assertRaises(fonts.FontPreparationError) as caught:
                fonts.download_package(self.package, self.cache)
        self.assertEqual(caught.exception.code, 'font_cache_unsafe')
        self.assertEqual(archive.read_bytes(), b'user data')
        self.assertFalse((self.cache / 'quarantine').exists())
        network.assert_not_called()

    def test_interrupted_copy_leaves_no_half_user_font(self):
        target = self.root / 'OS-user-fonts/Tiny.otf'
        def fail(source, destination):
            destination.write(b'partial')
            raise OSError('simulated disk full')
        with patch.object(fonts.shutil, 'copyfileobj', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'disk full'):
                fonts.copy_unchanged(self.source, target, self.font['sha256'])
        self.assertFalse(target.exists())
        self.assertEqual(list(target.parent.iterdir()), [])

    def test_atomic_publish_preserves_racing_existing_user_font(self):
        target = self.root / 'OS-user-fonts/Tiny.otf'
        def collision(*args):
            target.write_bytes(b'existing user font')
            raise FileExistsError('racing writer')
        primitive = 'rename' if os.name == 'nt' else 'link'
        with patch.object(fonts.os, primitive, side_effect=collision):
            with self.assertRaisesRegex(ValueError, 'preserved'):
                fonts.copy_unchanged(self.source, target, self.font['sha256'])
        self.assertEqual(target.read_bytes(), b'existing user font')
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_existing_different_user_font_is_never_replaced(self):
        target = self.root / 'user.otf'
        target.write_bytes(b'user version')
        with patch.object(fonts.shutil, 'copyfileobj') as copy:
            with self.assertRaisesRegex(ValueError, 'preserved'):
                fonts.copy_unchanged(self.source, target, self.font['sha256'])
        self.assertEqual(target.read_bytes(), b'user version')
        copy.assert_not_called()

    def test_local_tex_lookup_is_bounded_and_failure_falls_through(self):
        with patch.object(fonts.shutil, 'which', return_value='kpsewhich'), \
             patch.object(fonts.subprocess, 'run', side_effect=subprocess.TimeoutExpired('kpsewhich', 0.2)) as run:
            self.assertIsNone(fonts.existing_exact_font('Tiny.otf', self.font['sha256'], timeout=0.2))
        self.assertEqual(run.call_args.kwargs['timeout'], 0.2)


if __name__ == '__main__':
    unittest.main()
