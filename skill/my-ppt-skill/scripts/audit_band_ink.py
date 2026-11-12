"""Optional pixel diagnosis of PDF title/footer bands; never visual sign-off.

Read a current build report and its hashed layout/PDF/renders. Output a new JSON
beside the evidence, never over an input or inside its frozen render directory.
Exit 0 means diagnosis recorded (including manual-review cases); input/output
errors return 3 with recovery. This helper is not a build or delivery gate.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import sys

from report_io import emit_report


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def linked(record, label):
    if not isinstance(record, dict):
        raise ValueError(label + ': missing evidence link')
    path = Path(record.get('path', ''))
    if not path.is_absolute() or not path.is_file() or sha(path) != record.get('sha256'):
        raise ValueError(label + ': missing file or stale hash')
    return path


def indexed(rows, count, label):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(label + ': expected page array')
    numbers = [row.get('page') for row in rows]
    if any(type(number) is not int for number in numbers) or sorted(numbers) != list(range(1, count + 1)):
        raise ValueError(label + ': missing, duplicate or extra pages')
    return {row['page']: row for row in rows}


def valid_box(box):
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in box)
            or box[2] <= box[0] or box[3] <= box[1]):
        raise ValueError('Invalid container bounds')
    return list(box)


def overlaps(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) + .1 and min(a[3], b[3]) > max(a[1], b[1]) + .1


def band_containers(measurements, inventory, width, height):
    """Include unlettered geometric bands omitted by text-dependent audits."""
    result = [(kind, row) for kind in ('footer', 'title')
              for row in measurements.get(kind + '_containers', [])]
    known = {row['container_id'] for _, row in result}
    footer, title = [], []
    for path in inventory.get('paths', []):
        fill = path.get('fill')
        if not path.get('has_rectangle') or path.get('item_count') != 1 or fill is None:
            continue
        left, top, right, bottom = valid_box(path['bounds'])
        if (top >= height * .88 and abs(bottom - height) <= max(.5, height * .005)
                and height * .012 <= bottom - top <= height * .1 and right - left >= width * .18):
            footer.append(path)
        if (all(c >= .7 for c in fill) and not all(c >= .995 for c in fill)
                and -.5 <= top <= height * .02 and height * .025 <= bottom - top <= height * .16
                and right - left >= width * .8 and left <= width * .1 and right >= width * .9):
            title.append(path)
    intervals = sorted((max(0, p['bounds'][0]), min(width, p['bounds'][2])) for p in footer)
    covered, edge = 0, 0
    for left, right in intervals:
        covered += max(0, right - max(left, edge))
        edge = max(edge, right)
    for kind, candidates in (('footer', footer if covered >= width * .65 else []), ('title', title)):
        for path in candidates:
            if path['id'] not in known:
                result.append((kind, {'container_id': path['id'], 'container_bounds': path['bounds']}))
                known.add(path['id'])
    return result


def measure_band(image, container, path, inventory, dpi, kind):
    box = valid_box(container['container_bounds'])
    if path.get('bounds') != box:
        raise ValueError('Container bounds differ from the linked PDF drawing')
    scale = dpi / 72
    row = {'kind': kind, 'container_id': path['id'], 'pdf_bounds': box,
           'mapped_bounds_px': [value * scale for value in box],
           'requires_visual_review': True, 'candidate': None,
           'confidence': 'requires_manual_review', 'reasons': [],
           'band_bounds_px': None, 'foreground_bounds_px': None,
           'top_margin_px': None, 'bottom_margin_px': None,
           'margin_difference_px': None,
           'measurement_basis': 'Thresholded visible pixels in an identified solid-color band; foreground can include non-text marks. Bounds use exclusive right/bottom pixels. Inspect actual local and full-page images even when margins appear balanced.'}

    def manual(reason):
        row['reasons'].append(reason)
        return row

    if image.info.get('diagnostic_transparency'):
        return manual('transparent_png_requires_compositing_review')
    fill = path.get('fill')
    if (not isinstance(fill, (list, tuple)) or len(fill) not in (1, 3)
            or any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in fill)):
        return manual('unsupported_or_unknown_fill_color')
    opacity = path.get('fill_opacity')
    if not isinstance(opacity, (int, float)) or not math.isfinite(opacity) or opacity < .98:
        return manual('translucent_or_unknown_background_alpha')
    if not path.get('has_rectangle') or path.get('item_count') != 1:
        return manual('non_rectangular_or_complex_background')
    for text in inventory.get('text', []):
        alpha = text.get('opacity')
        if (text.get('bounds') and overlaps(box, text['bounds']) and text.get('paint_type') != 3
                and alpha != 0 and (not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha < .9)):
            return manual('low_or_unknown_text_alpha')
    rgb = tuple(round(value * 255) for value in (fill * 3 if len(fill) == 1 else fill))
    white_distance = max(255 - value for value in rgb)
    row['expected_fill_rgb'] = list(rgb)
    if white_distance < 4:
        return manual('background_indistinguishable_from_white_canvas')
    tolerance = max(1, min(10, white_distance / 3))
    foreground_tolerance = max(12, tolerance * 2)
    row['thresholds'] = {'background_rgb_distance': tolerance,
                         'foreground_rgb_distance': foreground_tolerance,
                         'minimum_background_fraction_per_row': .6}
    # A full-page underlying fill is harmless. Other intersecting artwork may
    # be mistaken for characters and must go back to visual inspection.
    for item in inventory.get('images', []) + inventory.get('paths', []):
        if item.get('id') == path['id']:
            continue
        other = item.get('bounds')
        if other and overlaps(box, other):
            enclosing = other[0] <= box[0] + .1 and other[1] <= box[1] + .1 and other[2] >= box[2] - .1 and other[3] >= box[3] - .1
            if item.get('kind') == 'image' or not enclosing:
                return manual('overlapping_graphics_or_complex_background')
    # Exclude vertical seams from sampling, but map y using DPI, never the
    # rounded PNG height. Poppler may append a white partial-page pixel row.
    left = max(0, math.ceil(box[0] * scale) + 1)
    right = min(image.width, math.floor(box[2] * scale) - 1)
    top = max(0, math.floor(box[1] * scale) - 2)
    bottom = min(image.height, math.ceil(box[3] * scale) + 2)
    if right <= left or bottom <= top:
        return manual('band_too_small_or_outside_render')
    pixels = image.load()
    background_rows, fractions = [], []
    for y in range(top, bottom):
        count = sum(max(abs(pixels[x, y][channel] - rgb[channel]) for channel in range(3)) <= tolerance
                    for x in range(left, right))
        fraction = count / (right - left)
        fractions.append([y, round(fraction, 4)])
        if fraction >= .6:
            background_rows.append(y)
    row['background_row_fractions'] = fractions
    if not background_rows:
        return manual('known_fill_not_found_in_render')
    if background_rows != list(range(background_rows[0], background_rows[-1] + 1)):
        return manual('noncontiguous_band_rows_or_complex_foreground')
    y0, y1 = background_rows[0], background_rows[-1] + 1
    if (abs(y0 - box[1] * scale) > 2 or abs(y1 - box[3] * scale) > 2 or y1 - y0 < 2):
        return manual('pixel_band_extent_disagrees_with_pdf_bounds')
    row['band_bounds_px'] = [left, y0, right, y1]
    row['excluded_non_band_rows_px'] = [y for y in range(top, bottom) if y not in background_rows]
    foreground = []
    for y in range(y0, y1):
        for x in range(left, right):
            if max(abs(pixels[x, y][channel] - rgb[channel]) for channel in range(3)) > foreground_tolerance:
                foreground.append((x, y))
    row['foreground_pixel_count'] = len(foreground)
    if not foreground:
        return manual('no_visible_foreground_glyphs_found')
    if len(foreground) / ((right - left) * (y1 - y0)) > .35:
        return manual('dense_or_nonuniform_foreground_requires_visual_disambiguation')
    xs, ys = zip(*foreground)
    row['antialiased_extent_bounds_px'] = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
    # Half of the observed maximum contrast estimates the solid glyph body;
    # retain low-contrast antialias tails separately instead of silently
    # interpreting one faint edge pixel as the optical extent.
    peak_contrast = max(max(abs(pixels[x, y][channel] - rgb[channel]) for channel in range(3))
                        for x, y in foreground)
    core_threshold = max(foreground_tolerance, peak_contrast * .5)
    core = [(x, y) for x, y in foreground
            if max(abs(pixels[x, y][channel] - rgb[channel]) for channel in range(3)) >= core_threshold]
    row['thresholds'].update(observed_peak_contrast=peak_contrast, foreground_core_rgb_distance=core_threshold)
    if peak_contrast < 32 or not core:
        return manual('low_contrast_foreground_requires_visual_review')
    xs, ys = zip(*core)
    ink = [min(xs), min(ys), max(xs) + 1, max(ys) + 1]
    above, below = ink[1] - y0, y1 - ink[3]
    difference = abs(above - below)
    row.update(foreground_bounds_px=ink, top_margin_px=above, bottom_margin_px=below,
               margin_difference_px=difference,
               candidate=difference >= 3 and max(above, below) > 1.8 * max(min(above, below), 1),
               confidence='measurable_solid_band',
               limitation='Reported margins use the half-peak-contrast foreground core. Low-contrast antialias extent is retained separately. These pixels do not prove glyph semantics or optical correctness.')
    raw = row['antialiased_extent_bounds_px']
    raw_top, raw_bottom = raw[1] - y0, y1 - raw[3]
    raw_candidate = abs(raw_top - raw_bottom) >= 3 and max(raw_top, raw_bottom) > 1.8 * max(min(raw_top, raw_bottom), 1)
    row['antialias_margins_px'] = {'top': raw_top, 'bottom': raw_bottom, 'candidate': raw_candidate}
    if raw_candidate != row['candidate']:
        row['confidence'] = 'requires_manual_review'
        row['reasons'].append('balance_candidate_changes_with_antialias_threshold')
    return row


def diagnose(build_path):
    # Import inside the CLI failure boundary so a missing optional image
    # runtime still produces a retained diagnostic and a recovery route.
    from PIL import Image

    build_path = Path(build_path).resolve()
    build_hash = sha(build_path)
    build = load(build_path)
    if build.get('schema') != 'beamer-build/v1':
        raise ValueError('Require a Beamer build report')
    count, dpi = build.get('physical_page_count'), build.get('dpi')
    if type(count) is not int or count <= 0 or not isinstance(dpi, (int, float)) or not math.isfinite(dpi) or dpi <= 0:
        raise ValueError('Invalid physical page count or render DPI')
    pdf = linked({'path': build.get('pdf_path'), 'sha256': build.get('pdf_sha256')}, 'PDF')
    layout_path = linked(build.get('layout_audit'), 'Layout audit')
    layout = load(layout_path)
    if (layout.get('schema') != 'beamer-layout-audit/v1'
            or layout.get('physical_page_count') != count
            or layout.get('pdf') != {'path': str(pdf), 'sha256': build['pdf_sha256']}):
        raise ValueError('Layout audit targets a different PDF or page set')
    pages = indexed(build.get('pages'), count, 'PDF pages')
    renders = indexed(build.get('renders'), count, 'Renders')
    measured = indexed(layout.get('pages'), count, 'Layout pages')
    report = {'schema': 'beamer-band-ink/v1', 'status': 'completed_pending_visual_review',
              'visual_review': 'pending', 'signed_off': False, 'requires_visual_review': True,
              'build_report': {'path': str(build_path), 'sha256': build_hash},
              'layout_audit': build['layout_audit'],
              'pdf': {'path': str(pdf), 'sha256': build['pdf_sha256']},
              'dpi': dpi, 'physical_page_count': count, 'pages': [], 'findings': []}
    for number in range(1, count + 1):
        render, page = renders[number], measured[number]
        png = linked(render, 'Page ' + str(number) + ' render')
        if render.get('pdf_sha256') != build['pdf_sha256']:
            raise ValueError('Render targets a different PDF')
        with Image.open(png) as opened:
            opened.load()
            image = opened.convert('RGB')
            image.info['diagnostic_transparency'] = ('A' in opened.getbands() and opened.getchannel('A').getextrema()[0] < 255) or 'transparency' in opened.info
        if image.size != (render.get('width_px'), render.get('height_px')):
            raise ValueError('Render dimensions differ from its report')
        if any(abs(actual - pages[number][key] * dpi / 72) > 2
               for actual, key in zip(image.size, ('display_width_pt', 'display_height_pt'))):
            raise ValueError('Render dimensions disagree with PDF page and DPI')
        result = {'page': number, 'render': render, 'requires_visual_review': True, 'containers': []}
        inventory, measurements = page.get('inventory'), page.get('measurements')
        if not isinstance(inventory, dict) or not isinstance(measurements, dict):
            result.update(status='requires_manual_review', reason='layout_measurement_unavailable')
        else:
            drawings = {item['id']: item for item in inventory.get('paths', [])}
            for kind, container in band_containers(measurements, inventory, pages[number]['display_width_pt'], pages[number]['display_height_pt']):
                path = drawings.get(container.get('container_id'))
                if path is None:
                    raise ValueError('Band container has no corresponding PDF drawing')
                item = measure_band(image, container, path, inventory, dpi, kind)
                result['containers'].append(item)
                if item['candidate']:
                    report['findings'].append({'page': number, 'category': kind + '_ink_balance_candidate',
                                               'container_id': item['container_id'], 'requires_visual_review': True,
                                               'foreground_bounds_px': item['foreground_bounds_px'],
                                               'top_margin_px': item['top_margin_px'], 'bottom_margin_px': item['bottom_margin_px']})
            result['status'] = 'measured_pending_visual_review' if result['containers'] else 'no_identified_bands_requires_visual_review'
        report['pages'].append(result)
        if sha(png) != render['sha256']:
            raise ValueError('Render changed during diagnosis')
    if sha(build_path) != build_hash or sha(layout_path) != build['layout_audit']['sha256'] or sha(pdf) != build['pdf_sha256']:
        raise ValueError('Input evidence changed during diagnosis')
    return report


class Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({'schema': 'beamer-band-ink/v1', 'status': 'failed',
                          'signed_off': False, 'requires_visual_review': True,
                          'stage': 'arguments', 'error': message,
                          'recovery': 'Run audit_band_ink.py --help, supply a build report and --output with an independent new JSON path, then rerun.'}), file=sys.stderr)
        raise SystemExit(3)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('build_report', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        print(json.dumps({'status': 'failed', 'error': 'Output already exists; retained unchanged.',
                          'recovery': 'Choose an independent new JSON output path.'}), file=sys.stderr)
        return 3
    try:
        report = diagnose(args.build_report)
        code = 0
    except Exception as error:
        recovery = ('Use an existing Python runtime containing Pillow and rerun to a new JSON, or retain this failure report and complete independent real local plus full-page visual review. No dependency is installed automatically.'
                    if isinstance(error, ImportError) else
                    'Restore matching current build/layout/PDF/PNG evidence and rerun to a new JSON. Inspect local and full-page images for unavailable or ambiguous pixel measurements.')
        report = {'schema': 'beamer-band-ink/v1', 'status': 'failed', 'signed_off': False,
                  'requires_visual_review': True, 'error': type(error).__name__ + ': ' + str(error),
                  'recovery': recovery}
        code = 3
    frozen = []
    try:
        build = load(args.build_report)
        renders = build.get('renders', []) if isinstance(build, dict) else []
        if isinstance(renders, list):
            frozen = sorted({str(Path(row['path']).parent) for row in renders
                             if isinstance(row, dict) and isinstance(row.get('path'), str)
                             and row['path'] and Path(row['path']).is_absolute()
                             and Path(row['path']).is_file()})
    except (OSError, ValueError, KeyError, TypeError):
        pass
    code = emit_report(args.output, report, inputs=[args.build_report], frozen_dirs=frozen) or code
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
