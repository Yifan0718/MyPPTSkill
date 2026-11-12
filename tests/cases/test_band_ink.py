"""Real PDF geometry and PNG pixels for optional band-ink diagnosis."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pymupdf
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas

import audit_band_ink as ink
from audit_beamer_layout import audit_pdf


class BandInkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='band-ink-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.build_path = self.base / 'build.json'

    def write_json(self, path, value):
        path.write_text(json.dumps(value), encoding='utf8')

    def fixture(self, baseline=3, background_alpha=1, text_alpha=1, blank=False, complex_background=False, pages=1):
        pdf = self.base / 'deck.pdf'
        c = canvas.Canvas(str(pdf), pagesize=(300, 255.12))
        colors = [(.64, 0, 0), (.925, .925, .925), (.85, .85, .85)]
        for page in range(pages):
            for index, fill in enumerate(colors):
                c.saveState()
                c.setFillAlpha(background_alpha)
                c.setFillColorRGB(*fill)
                c.rect(index * 100, 0, 100, 9.12, stroke=0, fill=1)
                c.restoreState()
                if not blank:
                    c.saveState()
                    c.setFillAlpha(text_alpha)
                    c.setFillColorRGB(*( (1, 1, 1) if index == 0 else (.64, 0, 0)))
                    c.setFont('Helvetica', 5)
                    c.drawString(index * 100 + 25, baseline, ('Author', 'Title', '20/20')[index])
                    c.restoreState()
            if complex_background:
                c.setFillColorRGB(0, 0, 1)
                c.rect(10, 1, 10, 7, stroke=0, fill=1)
            c.setFillColorRGB(.96, .96, .96)
            c.rect(0, 232.16, 300, 22.96, stroke=0, fill=1)
            c.setFillColorRGB(.64, 0, 0)
            c.setFont('Helvetica', 12)
            c.drawString(20, 240, 'Actual title band')
            c.showPage()
        c.save()
        layout = audit_pdf(pdf)
        layout_path = self.base / 'layout.json'
        self.write_json(layout_path, layout)
        render_dir = self.base / 'renders'
        render_dir.mkdir(exist_ok=True)
        renders = []
        with pymupdf.open(pdf) as document:
            for number, page in enumerate(document, 1):
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                image = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
                # Model the known Poppler fractional-height canvas behavior:
                # rows 492..509 are band, row 510 is white canvas, not padding.
                ImageDraw.Draw(image).line((0, 510, image.width - 1, 510), fill='white')
                png = render_dir / f'page-{number}.png'
                image.save(png)
                renders.append({'page': number, 'path': str(png), 'sha256': ink.sha(png),
                                'width_px': image.width, 'height_px': image.height, 'pdf_sha256': ink.sha(pdf)})
        build = {'schema': 'beamer-build/v1', 'physical_page_count': pages, 'dpi': 144,
                 'pdf_path': str(pdf), 'pdf_sha256': ink.sha(pdf),
                 'layout_audit': {'path': str(layout_path), 'sha256': ink.sha(layout_path)},
                 'pages': [{'page': number, 'display_width_pt': 300, 'display_height_pt': 255.12}
                           for number in range(1, pages + 1)], 'renders': renders}
        self.write_json(self.build_path, build)
        return build

    def footers(self, report):
        return [row for row in report['pages'][0]['containers'] if row['kind'] == 'footer']

    def test_white_rounding_row_is_excluded_from_all_multicolor_band_margins(self):
        self.fixture()
        result = ink.diagnose(self.build_path)
        footers = self.footers(result)
        self.assertEqual(len(footers), 3)
        for row in footers:
            self.assertEqual(row['band_bounds_px'][1], 492)
            self.assertEqual(row['band_bounds_px'][3], 510)
            self.assertIn(510, row['excluded_non_band_rows_px'])
            self.assertEqual(row['bottom_margin_px'], 510 - row['foreground_bounds_px'][3])
            self.assertTrue(row['requires_visual_review'])
        self.assertEqual(footers[0]['expected_fill_rgb'], [163, 0, 0])
        self.assertEqual(footers[1]['expected_fill_rgb'], [236, 236, 236])
        self.assertFalse(result['signed_off'])
        self.assertEqual(result['visual_review'], 'pending')

    def test_white_on_red_and_red_on_gray_have_visible_core_and_antialias_extent(self):
        self.fixture()
        rows = self.footers(ink.diagnose(self.build_path))
        for row in rows:
            self.assertIsNotNone(row['foreground_bounds_px'])
            self.assertGreater(row['foreground_pixel_count'], 0)
            self.assertIn('foreground_core_rgb_distance', row['thresholds'])
            self.assertLessEqual(row['antialiased_extent_bounds_px'][1], row['foreground_bounds_px'][1])
            self.assertGreaterEqual(row['antialiased_extent_bounds_px'][3], row['foreground_bounds_px'][3])

    def test_biased_ink_is_candidate_and_balanced_ink_still_needs_visual_review(self):
        self.fixture(baseline=1)
        report = ink.diagnose(self.build_path)
        self.assertTrue(any(row['candidate'] for row in self.footers(report)))
        self.assertTrue(any(f['category'] == 'footer_ink_balance_candidate' for f in report['findings']))
        self.fixture(baseline=3)
        rows = self.footers(ink.diagnose(self.build_path))
        self.assertTrue(all(not row['candidate'] for row in rows))
        self.assertTrue(all(row['requires_visual_review'] for row in rows))

    def test_title_band_is_diagnosed_without_becoming_visual_signoff(self):
        self.fixture()
        result = ink.diagnose(self.build_path)
        row = next(row for row in result['pages'][0]['containers'] if row['kind'] == 'title')
        self.assertIsNotNone(row['foreground_bounds_px'])
        self.assertEqual(row['band_bounds_px'][1], 0)
        self.assertTrue(row['requires_visual_review'])

    def test_low_alpha_background_and_text_require_manual_inspection(self):
        for options, reason in (({'background_alpha': .5}, 'translucent_or_unknown_background_alpha'),
                                ({'text_alpha': .3}, 'low_or_unknown_text_alpha')):
            with self.subTest(options=options):
                self.fixture(**options)
                for row in self.footers(ink.diagnose(self.build_path)):
                    self.assertEqual(row['confidence'], 'requires_manual_review')
                    self.assertIn(reason, row['reasons'])
                    self.assertIsNone(row['candidate'])

    def test_complex_background_is_not_misidentified_as_glyphs(self):
        self.fixture(complex_background=True)
        row = self.footers(ink.diagnose(self.build_path))[0]
        self.assertIn('overlapping_graphics_or_complex_background', row['reasons'])
        self.assertEqual(row['confidence'], 'requires_manual_review')

    def test_empty_colored_bands_are_retained_without_empty_pass(self):
        self.fixture(blank=True)
        rows = self.footers(ink.diagnose(self.build_path))
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertIn('no_visible_foreground_glyphs_found', row['reasons'])
            self.assertIsNone(row['candidate'])
            self.assertTrue(row['requires_visual_review'])

    def test_antialias_tail_sensitivity_is_disclosed_for_manual_review(self):
        build = self.fixture()
        png = Path(build['renders'][0]['path'])
        with Image.open(png) as source:
            image = source.convert('RGB')
        image.putpixel((60, 509), (180, 40, 40))
        image.save(png)
        build['renders'][0]['sha256'] = ink.sha(png)
        self.write_json(self.build_path, build)
        row = self.footers(ink.diagnose(self.build_path))[0]
        self.assertEqual(row['antialiased_extent_bounds_px'][3], 510)
        self.assertLess(row['foreground_bounds_px'][3], 510)
        self.assertIn('balance_candidate_changes_with_antialias_threshold', row['reasons'])
        self.assertEqual(row['confidence'], 'requires_manual_review')

    def test_transparent_png_does_not_silently_assume_compositing(self):
        build = self.fixture()
        png = Path(build['renders'][0]['path'])
        with Image.open(png) as source:
            image = source.convert('RGBA')
        image.putpixel((60, 500), (255, 255, 255, 100))
        image.save(png)
        build['renders'][0]['sha256'] = ink.sha(png)
        self.write_json(self.build_path, build)
        row = self.footers(ink.diagnose(self.build_path))[0]
        self.assertIn('transparent_png_requires_compositing_review', row['reasons'])
        self.assertIsNone(row['candidate'])

    def test_stale_render_and_missing_page_fail_with_recovery_json(self):
        for failure in ('stale', 'coverage'):
            with self.subTest(failure=failure):
                build = self.fixture(pages=2)
                if failure == 'stale':
                    Path(build['renders'][0]['path']).write_bytes(b'changed')
                else:
                    build['renders'].pop()
                    self.write_json(self.build_path, build)
                output = self.base / (failure + '.json')
                with contextlib.redirect_stdout(io.StringIO()):
                    code = ink.main([str(self.build_path), '--output', str(output)])
                self.assertEqual(code, 3)
                report = json.loads(output.read_text(encoding='utf8'))
                self.assertEqual(report['status'], 'failed')
                self.assertIn('recovery', report)

    def test_layout_hash_dpi_and_container_links_are_checked(self):
        for failure in ('layout_hash', 'dpi', 'container'):
            with self.subTest(failure=failure):
                build = self.fixture()
                if failure == 'layout_hash':
                    build['layout_audit']['sha256'] = '0' * 64
                elif failure == 'dpi':
                    build['dpi'] = 72
                else:
                    path = Path(build['layout_audit']['path'])
                    layout = json.loads(path.read_text(encoding='utf8'))
                    layout['pages'][0]['measurements']['footer_containers'][0]['container_id'] = 'absent'
                    self.write_json(path, layout)
                    build['layout_audit']['sha256'] = ink.sha(path)
                self.write_json(self.build_path, build)
                with self.assertRaises(ValueError):
                    ink.diagnose(self.build_path)

    def test_cli_preserves_existing_outputs_and_all_input_evidence(self):
        build = self.fixture()
        for output in (self.build_path, Path(build['layout_audit']['path']), Path(build['renders'][0]['path'])):
            before = output.read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                code = ink.main([str(self.build_path), '--output', str(output)])
            self.assertEqual(code, 3)
            self.assertEqual(output.read_bytes(), before)
        output = self.base / 'renders' / 'unsafe.json'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = ink.main([str(self.build_path), '--output', str(output)])
        self.assertEqual(code, 3)
        self.assertFalse(output.exists())

    def test_all_pages_are_covered_and_success_writes_new_diagnostic(self):
        self.fixture(pages=2)
        output = self.base / 'diagnostic.json'
        with contextlib.redirect_stdout(io.StringIO()):
            code = ink.main([str(self.build_path), '--output', str(output)])
        self.assertEqual(code, 0)
        result = json.loads(output.read_text(encoding='utf8'))
        self.assertEqual([row['page'] for row in result['pages']], [1, 2])
        self.assertEqual(result['status'], 'completed_pending_visual_review')
        self.assertTrue(all(row['requires_visual_review'] for page in result['pages'] for row in page['containers']))

    def test_missing_pillow_in_fresh_process_retains_structured_failure(self):
        self.fixture()
        output = self.base / 'missing-pillow.json'
        runner = '''
import importlib.abc, runpy, sys
from pathlib import Path
class MissingPillow(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PIL' or fullname.startswith('PIL.'):
            raise ModuleNotFoundError('Simulated missing Pillow runtime')
sys.meta_path.insert(0, MissingPillow())
script, build, output = sys.argv[1:]
sys.path.insert(0, str(Path(script).parent))
sys.argv = [script, build, '--output', output]
runpy.run_path(script, run_name='__main__')
'''
        child = subprocess.run([sys.executable, '-B', '-c', runner, str(Path(ink.__file__).resolve()),
                                str(self.build_path), str(output)], capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 3, child.stderr)
        report = json.loads(output.read_text(encoding='utf8'))
        self.assertEqual(report['schema'], 'beamer-band-ink/v1')
        self.assertEqual(report['status'], 'failed')
        self.assertIn('missing Pillow', report['error'])
        self.assertIn('existing Python runtime containing Pillow', report['recovery'])
        self.assertIn('independent real local plus full-page', report['recovery'])
        self.assertEqual(json.loads(child.stdout), report)
        self.assertNotIn('Traceback', child.stderr)

    def test_argument_errors_exit_three_with_structured_stderr_recovery(self):
        for arguments in ([], ['--output'], ['--unknown-option']):
            with self.subTest(arguments=arguments):
                child = subprocess.run([sys.executable, '-B', str(Path(ink.__file__).resolve()), *arguments],
                                       capture_output=True, text=True, timeout=30)
                self.assertEqual(child.returncode, 3)
                report = json.loads(child.stderr)
                self.assertEqual(report['schema'], 'beamer-band-ink/v1')
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['stage'], 'arguments')
                self.assertIn('--help', report['recovery'])
                self.assertEqual(child.stdout, '')

    def test_invalid_json_shapes_retain_failure_report_in_fresh_process(self):
        values = [[], None, 'wrong report', 7, {'renders': [None, {'path': []}]},
                  {'renders': None}]
        for index, value in enumerate(values):
            with self.subTest(value=value):
                self.write_json(self.build_path, value)
                before = self.build_path.read_bytes()
                output = self.base / ('invalid-shape-%d.json' % index)
                child = subprocess.run([sys.executable, '-B', '-X', 'utf8',
                                        str(Path(ink.__file__).resolve()), str(self.build_path),
                                        '--output', str(output)], capture_output=True,
                                       text=True, encoding='utf8', timeout=30)
                self.assertEqual(child.returncode, 3, child.stderr)
                report = json.loads(output.read_text(encoding='utf8'))
                self.assertEqual(report['status'], 'failed')
                self.assertFalse(report['signed_off'])
                self.assertIn('recovery', report)
                self.assertEqual(json.loads(child.stdout), report)
                self.assertNotIn('Traceback', child.stderr)
                self.assertEqual(self.build_path.read_bytes(), before)

    def test_recovery_does_not_freeze_cwd_for_invalid_render_paths(self):
        existing = self.base / 'existing.png'
        existing.write_bytes(b'preserved render placeholder')
        paths = ['missing-relative.png', existing.name,
                 str(self.base / 'missing-absolute.png'), str(self.base)]
        for index, path in enumerate(paths):
            with self.subTest(path=path):
                self.write_json(self.build_path, {'schema': 'beamer-build/v1',
                                                 'renders': [{'path': path}]})
                before = self.build_path.read_bytes()
                output = self.base / ('invalid-render-path-%d.json' % index)
                child = subprocess.run([sys.executable, '-B', '-X', 'utf8',
                                        str(Path(ink.__file__).resolve()), str(self.build_path),
                                        '--output', str(output)], cwd=self.base, capture_output=True,
                                       text=True, encoding='utf8', timeout=30)
                self.assertEqual(child.returncode, 3, child.stderr)
                report = json.loads(output.read_text(encoding='utf8'))
                self.assertEqual(report['status'], 'failed')
                self.assertFalse(report['signed_off'])
                self.assertEqual(json.loads(child.stdout), report)
                self.assertEqual(self.build_path.read_bytes(), before)
                self.assertEqual(existing.read_bytes(), b'preserved render placeholder')
                self.assertNotIn('Traceback', child.stderr)
