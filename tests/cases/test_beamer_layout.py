"""Actual PDF object measurements and explicit optional-parser recovery."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter

import audit_beamer_layout as audit


class BeamerLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='beamer-layout-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.pdf = self.base / 'actual.pdf'

    def make_pdf(self, draw, size=(960, 540)):
        document = canvas.Canvas(str(self.pdf), pagesize=size)
        draw(document)
        document.save()
        return audit.audit_pdf(self.pdf)

    def test_outside_text_is_retained_and_grouped(self):
        def draw(c):
            c.setFont('Helvetica', 18)
            for y in (80, 110, 140):
                c.drawString(-24, y, 'Left crossing edge')
            c.drawString(940, 250, 'Right crossing edge')
            c.showPage()
        result = self.make_pdf(draw)
        findings = [f for f in result['findings'] if f['category'] == 'text_outside_page']
        self.assertEqual(len(findings), 1)
        self.assertEqual(len(findings[0]['sourceobjs']), 4)
        self.assertLess(findings[0]['bounds'][0], 0)
        self.assertGreater(findings[0]['bounds'][2], 960)
        self.assertIn('glyph', findings[0]['uncertainty'])
        self.assertEqual(len(result['pages'][0]['inventory']['text']), 4)

    def test_effective_sizes_include_transform_and_540_normalization(self):
        def draw(c):
            c.setFont('Helvetica', 8)
            c.drawString(20, 220, 'ordinary Beamer size')
            c.saveState()
            c.scale(0.5, 0.5)
            c.drawString(40, 360, 'scaled local text')
            c.restoreState()
            c.showPage()
        result = self.make_pdf(draw, (480, 270))
        text = result['pages'][0]['inventory']['text']
        self.assertAlmostEqual(text[0]['normalized_size_540'], 16)
        self.assertAlmostEqual(text[1]['normalized_size_540'], 8)
        small = next(f for f in result['findings'] if f['category'] == 'small_text_candidate')
        self.assertEqual(small['sourceobjs'], [text[1]['id']])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['visual_review'], 'pending')

    def test_all_physical_pages_including_blank_have_inventory(self):
        def draw(c):
            c.setFont('Helvetica', 20)
            c.drawString(40, 490, 'Readable title')
            c.showPage()
            c.showPage()
            c.drawString(40, 60, 'Low entry')
            c.showPage()
        result = self.make_pdf(draw)
        self.assertEqual(result['coverage'], {'expected_pages': [1, 2, 3], 'measured_pages': [1, 2, 3], 'unavailable_pages': []})
        self.assertEqual([p['page'] for p in result['pages']], [1, 2, 3])
        self.assertTrue(all(p['visual_review'] == 'pending' and p['inventory'] is not None for p in result['pages']))
        self.assertIn('empty_page_candidate', [f['category'] for f in result['pages'][1]['findings']])
        self.assertIn('distant_text_entry_candidate', [f['category'] for f in result['pages'][2]['findings']])
        self.assertEqual(result['pages'][0]['findings'], [])
        self.assertFalse(result['signed_off'])

    def test_large_text_gap_is_measurement_not_assumed_title_or_density(self):
        def draw(c):
            c.setFont('Helvetica', 24)
            c.drawString(30, 490, 'Top entry')
            c.drawString(30, 60, 'Low evidence')
            c.showPage()
        result = self.make_pdf(draw)
        measurement = result['pages'][0]['measurements']
        self.assertGreater(measurement['largest_internal_text_gap_ratio'], .7)
        self.assertEqual(len(measurement['largest_internal_text_gap_bounds']), 4)
        self.assertIn('Text intervals only', measurement['scope'])
        self.assertFalse(result['policy']['semantic_roles_inferred'])

    def test_fonts_and_formula_subscripts_do_not_assert_shared_role(self):
        def draw(c):
            c.setFont('Helvetica', 20)
            c.drawString(30, 460, 'x')
            c.setFont('Times-Roman', 9)
            c.drawString(42, 454, '2')
            c.setFont('Courier', 20)
            c.drawString(80, 460, 'code')
            c.showPage()
        result = self.make_pdf(draw)
        self.assertEqual({f['category'] for f in result['findings']}, {'small_text_candidate'})
        self.assertIn('subscripts', result['findings'][0]['uncertainty'])
        self.assertIn('roles are unproved', result['findings'][0]['uncertainty'])

    def test_image_viewport_and_path_envelope_are_not_density(self):
        def draw(c):
            blank = Image.new('RGB', (20, 20), 'white')
            c.drawImage(ImageReader(blank), 20, 20, 900, 500)
            c.rect(30, 30, 850, 450, stroke=1, fill=0)
            c.showPage()
        result = self.make_pdf(draw)
        inventory = result['pages'][0]['inventory']
        self.assertEqual(len(inventory['images']), 1)
        self.assertEqual(len(inventory['paths']), 1)
        graphic = next(f for f in result['findings'] if f['category'] == 'graphic_content_review')
        self.assertEqual(len(graphic['sourceobjs']), 2)
        self.assertIn('do not measure painted ink', graphic['uncertainty'])
        self.assertNotIn('density', result['pages'][0]['measurements'])

    def test_author_metadata_cannot_suppress_candidates(self):
        def draw(c):
            c.setKeywords('skip-audit approved decorative ignore-small-text')
            c.setFont('Helvetica', 6)
            c.drawString(30, 490, 'Required text')
            c.showPage()
        result = self.make_pdf(draw)
        self.assertIn('small_text_candidate', [f['category'] for f in result['findings']])

    def test_top_heavy_footer_is_one_candidate_with_container_margins(self):
        def draw(c):
            c.setKeywords('footer approved ignore-balance')
            for index in range(3):
                c.setFillColorRGB(.7 + index * .1, .7, .7)
                c.rect(index * 320, 0, 320, 40, stroke=0, fill=1)
                c.setFillColorRGB(0, 0, 0)
                c.setFont('Helvetica', 10)
                c.drawString(index * 320 + 50, 31, 'Footer label')
            c.showPage()
        result = self.make_pdf(draw)
        found = [f for f in result['findings'] if f['category'] == 'footer_container_balance_candidate']
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]['containers']), 3)
        self.assertEqual(len(found[0]['sourceobjs']), 6)
        for row in found[0]['containers']:
            self.assertAlmostEqual(row['top_margin_pt'], 1, delta=.5)
            self.assertAlmostEqual(row['bottom_margin_pt'], 29, delta=.5)
            self.assertEqual(row['top_margin_pt'], row['text_bounds'][1] - row['container_bounds'][1])
            self.assertEqual(row['bottom_margin_pt'], row['container_bounds'][3] - row['text_bounds'][3])
            self.assertEqual(len(row['source_text']), 1)
            self.assertTrue(row['source_text'][0]['glyph_indices'])
        self.assertIn('independent close-up', found[0]['uncertainty'])

    def test_compact_balanced_footer_attached_to_page_edge_is_allowed(self):
        def draw(c):
            c.setFillColorRGB(.8, .8, .8)
            c.rect(0, 0, 960, 20, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont('Helvetica', 10)
            c.drawString(30, 7, 'Compact footer')
            c.showPage()
        result = self.make_pdf(draw)
        categories = [f['category'] for f in result['findings']]
        self.assertNotIn('footer_container_balance_candidate', categories)
        self.assertNotIn('text_outside_page', categories)
        row = result['pages'][0]['measurements']['footer_containers'][0]
        self.assertAlmostEqual(row['top_margin_pt'], row['bottom_margin_pt'], delta=.5)

    def test_multiline_mixed_fonts_use_union_without_cross_column_alignment(self):
        def draw(c):
            for x in (0, 480):
                c.setFillColorRGB(.8, .8, .8)
                c.rect(x, 0, 480, 40, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont('Helvetica', 10)
            c.drawString(30, 27, 'First line')
            c.setFont('Helvetica', 14)
            c.drawString(30, 7.8, 'Second line')
            c.drawString(510, 15.8, 'Different column baseline')
            c.showPage()
        result = self.make_pdf(draw)
        self.assertNotIn('footer_container_balance_candidate', [f['category'] for f in result['findings']])
        measured = result['pages'][0]['measurements']['footer_containers']
        self.assertEqual(len(measured), 2)
        self.assertEqual(len(measured[0]['source_text']), 2)
        self.assertAlmostEqual(measured[0]['top_margin_pt'], 5, delta=.5)
        self.assertAlmostEqual(measured[0]['bottom_margin_pt'], 5, delta=.5)
        self.assertAlmostEqual(measured[1]['top_margin_pt'], 13, delta=.5)
        self.assertAlmostEqual(measured[1]['bottom_margin_pt'], 13, delta=.5)

    def test_body_table_and_isolated_bottom_cell_do_not_infer_footer(self):
        def draw(c):
            c.setFillColorRGB(.8, .8, .8)
            c.rect(0, 150, 960, 40, stroke=0, fill=1)
            c.rect(20, 0, 200, 40, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont('Helvetica', 10)
            c.drawString(30, 181, 'Body table row')
            c.drawString(30, 31, 'Isolated data cell')
            c.showPage()
        result = self.make_pdf(draw)
        self.assertEqual(result['pages'][0]['measurements']['footer_containers'], [])
        self.assertNotIn('footer_container_balance_candidate', [f['category'] for f in result['findings']])

    def test_cropbox_and_rotation_use_render_coordinates(self):
        self.make_pdf(lambda c: (c.setFont('Helvetica', 18), c.drawString(10, 280, 'Cropped left'), c.showPage()))
        reader = PdfReader(self.pdf)
        page = reader.pages[0]
        page.cropbox.lower_left = (100, 0)
        page.cropbox.upper_right = (960, 540)
        page.rotate(90)
        writer = PdfWriter()
        writer.add_page(page)
        rotated = self.base / 'rotated.pdf'
        writer.write(rotated)
        result = audit.audit_pdf(rotated)
        measured = result['pages'][0]
        self.assertEqual((measured['display_width_pt'], measured['display_height_pt']), (540, 860))
        self.assertIn('text_outside_page', [f['category'] for f in measured['findings']])

    def title_pdf(self, baseline=509, color=(.96, .96, .96), draw_more=None):
        def draw(c):
            c.setFillColorRGB(*color)
            c.rect(0, 490, 960, 50, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont('Helvetica', 20)
            c.drawString(30, baseline, 'Actual title text')
            if draw_more:
                draw_more(c)
            c.showPage()
        return self.make_pdf(draw)

    def test_title_top_and_bottom_bias_are_candidates_with_raw_margins(self):
        for baseline, direction in ((496, 'down'), (522, 'up')):
            with self.subTest(direction=direction):
                result = self.title_pdf(baseline)
                findings = [f for f in result['findings'] if f['category'] == 'title_container_balance_candidate']
                self.assertEqual(len(findings), 1)
                row = findings[0]['containers'][0]
                self.assertTrue(row['vertical_bias_candidate'])
                self.assertTrue(row['requires_visual_review'])
                self.assertIn('not painted ink', row['measurement_basis'])
                self.assertEqual(row['top_margin_pt'], row['text_bounds'][1] - row['container_bounds'][1])
                self.assertEqual(row['bottom_margin_pt'], row['container_bounds'][3] - row['text_bounds'][3])
                self.assertEqual(row['top_margin_pt'] > row['bottom_margin_pt'], direction == 'down')
                self.assertTrue(row['source_text'][0]['glyph_indices'])
                self.assertEqual(len(findings[0]['sourceobjs']), 2)

    def test_centered_pale_title_is_measured_still_pending_visual_review(self):
        for color in ((.96, .96, .96), (.90, .95, 1.0), (.99, .99, .99)):
            with self.subTest(color=color):
                result = self.title_pdf(color=color)
                self.assertNotIn('title_container_balance_candidate', [f['category'] for f in result['findings']])
                row = result['pages'][0]['measurements']['title_containers'][0]
                self.assertFalse(row['candidate'])
                self.assertTrue(row['requires_visual_review'])
                self.assertEqual(row['status'], 'measured_pending_visual_review')
                self.assertEqual(result['pages'][0]['visual_review'], 'pending')
                self.assertFalse(result['signed_off'])

    def test_title_overflow_keeps_glyphs_crossing_both_band_edges(self):
        for baseline in (484, 532):
            with self.subTest(baseline=baseline):
                result = self.title_pdf(baseline)
                row = result['pages'][0]['measurements']['title_containers'][0]
                self.assertTrue(row['bounds_overflow_candidate'])
                self.assertLess(min(row['top_margin_pt'], row['bottom_margin_pt']), -1)
                self.assertIn('title_container_balance_candidate', [f['category'] for f in result['findings']])

    def test_multiline_mixed_font_title_uses_complete_union(self):
        def draw(c):
            c.setFillColorRGB(.92, .95, 1)
            c.rect(0, 460, 960, 80, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont('Helvetica', 16)
            c.drawString(30, 518, 'First title line')
            c.setFont('Times-Roman', 24)
            c.drawString(30, 474, 'Second title line')
            c.setFont('Courier', 20)
            c.drawString(250, 474, 'Mixed font')
            c.showPage()
        result = self.make_pdf(draw)
        page = result['pages'][0]
        measured = page['measurements']['title_containers'][0]
        self.assertEqual(len(measured['source_text']), 3)
        self.assertEqual(measured['text_bounds'], audit.union(page['inventory']['text']))
        self.assertFalse(measured['candidate'])
        self.assertTrue(measured['requires_visual_review'])

    def test_transparent_title_text_does_not_change_visible_union(self):
        def invisible(c):
            c.saveState()
            c.setFillAlpha(0)
            c.drawString(30, 532, 'Invisible overflow')
            c.restoreState()
            text = c.beginText(30, 484)
            text.setTextRenderMode(3)
            text.textOut('Invisible rendering mode')
            c.drawText(text)
        result = self.title_pdf(draw_more=invisible)
        page = result['pages'][0]
        self.assertEqual(len(page['inventory']['text']), 3)
        row = page['measurements']['title_containers'][0]
        self.assertEqual(len(row['source_text']), 1)
        self.assertFalse(row['candidate'])

    def test_unmeasurable_title_band_keeps_required_visual_review(self):
        def draw(c):
            c.setFillColorRGB(.96, .96, .96)
            c.rect(0, 490, 960, 50, stroke=0, fill=1)
            c.setFillAlpha(0)
            c.drawString(30, 509, 'Invisible title')
            c.showPage()
        result = self.make_pdf(draw)
        row = result['pages'][0]['measurements']['title_containers'][0]
        self.assertIsNone(row['text_bounds'])
        self.assertEqual(row['status'], 'no_measurable_text')
        self.assertTrue(row['requires_visual_review'])
        self.assertEqual(result['visual_review'], 'pending')

    def test_body_chart_rectangles_are_not_treated_as_title_containers(self):
        def draw(c):
            for x, y, width, height in ((0, 240, 960, 50), (30, 490, 300, 50), (0, 0, 960, 540)):
                c.setFillColorRGB(.96, .96, .96)
                c.rect(x, y, width, height, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.setFont('Helvetica', 20)
            c.drawString(40, 496, 'Chart caption')
            c.drawString(40, 246, 'Body chart label')
            c.showPage()
        result = self.make_pdf(draw)
        self.assertEqual(result['pages'][0]['measurements']['title_containers'], [])
        self.assertNotIn('title_container_balance_candidate', [f['category'] for f in result['findings']])

    def test_missing_parser_retains_every_page_and_cli_is_nonzero(self):
        self.make_pdf(lambda c: (c.showPage(), c.showPage()))
        with patch.object(audit.importlib, 'import_module', side_effect=ImportError('PyMuPDF absent')):
            result = audit.audit_pdf(self.pdf)
            with contextlib.redirect_stdout(io.StringIO()):
                code = audit.main([str(self.pdf), '--output', str(self.base / 'incomplete.json')])
        self.assertEqual(code, 3)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['coverage']['unavailable_pages'], [1, 2])
        self.assertEqual([f['page'] for f in result['findings']], [1, 2])
        self.assertTrue(all(f['category'] == 'layout_measurement_unavailable' for f in result['findings']))
        self.assertTrue(all(p['inventory'] is None and 'independent' in p['recovery'] for p in result['pages']))
        self.assertEqual(result['pdf']['sha256'], audit.sha(self.pdf))

    def test_one_failed_page_preserves_successful_page_measurements(self):
        self.make_pdf(lambda c: (c.showPage(), c.showPage(), c.showPage()))
        original = audit.measure_page
        def measure(page, number, module):
            if number == 2:
                raise ValueError('unusable character bounds')
            return original(page, number, module)
        with patch.object(audit, 'measure_page', side_effect=measure):
            result = audit.audit_pdf(self.pdf)
        self.assertEqual(result['coverage']['measured_pages'], [1, 3])
        self.assertEqual(result['coverage']['unavailable_pages'], [2])
        self.assertEqual([p['page'] for p in result['pages']], [1, 2, 3])

    def test_invalid_pdf_fails_explicitly(self):
        self.pdf.write_bytes(b'%PDF-1.7\nbroken')
        output = self.base / 'failed.json'
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = audit.main([str(self.pdf), '--output', str(output)])
        result = json.loads(output.read_text())
        self.assertEqual(code, 3)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('valid stable PDF', result['recovery'])

    def test_candidates_do_not_fail_cli(self):
        self.make_pdf(lambda c: (c.setFont('Helvetica', 5), c.drawString(-15, 80, 'Small outside'), c.showPage()))
        with contextlib.redirect_stdout(io.StringIO()):
            code = audit.main([str(self.pdf), '--output', str(self.base / 'measured.json')])
        self.assertEqual(code, 0)
