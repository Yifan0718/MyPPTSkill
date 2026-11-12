"""Measure actual PDF objects; candidates always require rendered visual review.

PyMuPDF is optional for measurement, never installed here. Missing/failed
measurement has explicit per-page coverage and recovery. CLI exit 0 means
measurement completed, 3 means incomplete/error; neither means visual sign-off.
"""
from pathlib import Path
import argparse
import hashlib
import importlib
import json
import math

from report_io import emit_report


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bounds(values):
    result = [float(v) for v in values]
    if len(result) != 4 or not all(math.isfinite(v) for v in result):
        raise ValueError('Invalid PDF object bounds')
    return [round(v, 4) for v in result]


def union(objects):
    boxes = [obj['bounds'] for obj in objects]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None


def candidate(number, category, objects, message, uncertainty, box=None):
    return {'category': category, 'page': number, 'status': 'pending_visual_review',
            'bounds': box if box is not None else union(objects),
            'sourceobjs': [obj['id'] for obj in objects], 'message': message,
            'uncertainty': uncertainty, 'coordinate_system': 'display_cropbox_top_left_pdf_pt'}


def unavailable(number, error):
    finding = candidate(number, 'layout_measurement_unavailable', [],
                        'PDF object measurement unavailable: ' + str(error),
                        'Object coverage is unknown; inspect this entire rendered page and relevant close-ups independently.')
    return {'page': number, 'status': 'incomplete', 'visual_review': 'pending',
            'inventory': None, 'measurements': None, 'findings': [finding],
            'recovery': 'Use an existing Python runtime with PyMuPDF and retry, or retain this finding and complete independent local plus full-page visual review.'}


def footer_balance(number, width, height, texts, paths):
    """Inspect thin bottom background strips, without assigning author roles.

    Each container uses the union of its non-space glyph boxes, including mixed
    sizes and multiple lines. This never compares baselines between columns.
    """
    scale = height / 540
    strips = []
    for item in paths:
        left, top, right, bottom = item['bounds']
        fill = item['fill']
        if (item['has_rectangle'] and item['item_count'] == 1 and fill is not None
                and not all(channel >= .98 for channel in fill)
                and item['fill_opacity'] != 0
                and top >= height * .88 and abs(bottom - height) <= max(.5, height * .005)
                and height * .012 <= bottom - top <= height * .1
                and right - left >= width * .18):
            strips.append(item)
    # Require a broad bottom band, possibly split into independently colored
    # panels; an isolated data cell is insufficient evidence for a footer role.
    intervals = sorted((max(0, p['bounds'][0]), min(width, p['bounds'][2])) for p in strips)
    covered, edge = 0, 0
    for left, right in intervals:
        covered += max(0, right - max(edge, left))
        edge = max(edge, right)
    if covered < width * .65:
        return [], []
    measurements, affected = [], []
    for strip in strips:
        left, top, right, bottom = strip['bounds']
        glyphs, members = [], []
        for text in texts:
            indices = []
            for index, (char, box) in enumerate(zip(text['text'], text['glyph_bounds'])):
                if (char.strip() and box[0] >= left - .5 and box[2] <= right + .5
                        and box[1] >= top - .5 and box[3] <= bottom + .5):
                    glyphs.append({'bounds': box})
                    indices.append(index)
            if indices:
                members.append({'id': text['id'], 'glyph_indices': indices})
        text_box = union(glyphs)
        if text_box is None:
            continue
        above, below = text_box[1] - top, bottom - text_box[3]
        difference = abs(above - below)
        biased = (difference > max(3 * scale, .28 * (bottom - top))
                  and max(above, below) > 3 * max(min(above, below), scale))
        measurement = {'container_id': strip['id'], 'container_bounds': strip['bounds'],
                       'text_bounds': text_box, 'source_text': members,
                       'top_margin_pt': above, 'bottom_margin_pt': below,
                       'margin_difference_pt': difference,
                       'margin_difference_normalized_540': difference / scale,
                       'candidate': biased}
        measurements.append(measurement)
        if biased:
            affected.append(measurement)
    if not affected:
        return measurements, []
    ids = {row['container_id'] for row in affected}
    ids.update(member['id'] for row in affected for member in row['source_text'])
    objects = [item for item in paths + texts if item['id'] in ids]
    finding = candidate(number, 'footer_container_balance_candidate', objects,
                        'Text within a broad filled bottom strip has strongly unequal top and bottom margins.',
                        'Bottom-strip and footer roles are provisional. Glyph boxes approximate metrics, not complete ink; clipping, optical balance and intentional multiline layout require independent close-up and full-page review. Page-edge attachment itself is allowed.')
    finding['containers'] = affected
    return measurements, [finding]


def title_balance(number, width, height, texts, paths):
    """Measure broad pale top bands; roles and optical ink remain unproved."""
    scale = height / 540
    measurements, affected = [], []
    for strip in paths:
        left, top, right, bottom = strip['bounds']
        fill = strip['fill']
        if not (strip['has_rectangle'] and strip['item_count'] == 1 and fill is not None
                and all(channel >= .7 for channel in fill)
                and not all(channel >= .995 for channel in fill)
                and strip['fill_opacity'] != 0
                and -.5 <= top <= height * .02
                and height * .025 <= bottom - top <= height * .16
                and right - left >= width * .8
                and left <= width * .1 and right >= width * .9):
            continue
        glyphs, members = [], []
        for text in texts:
            indices = []
            for index, (char, box) in enumerate(zip(text['text'], text['glyph_bounds'])):
                # Keep complete intersecting glyph boxes, including the part
                # outside the band. Containment-only selection hides overflow.
                if (char.strip() and box[2] > left and box[0] < right
                        and box[3] > top and box[1] < bottom):
                    glyphs.append({'bounds': box})
                    indices.append(index)
            if indices:
                members.append({'id': text['id'], 'glyph_indices': indices})
        text_box = union(glyphs)
        measurement = {'container_id': strip['id'], 'container_bounds': strip['bounds'],
                       'text_bounds': text_box, 'source_text': members,
                       'requires_visual_review': True,
                       'measurement_basis': 'Union of intersecting non-space visible glyph font-metric boxes; these are not painted ink. Title role, clipping and optical balance need independent close-up and full-page visual review.',
                       'candidate': False}
        if text_box is None:
            measurement['status'] = 'no_measurable_text'
            measurements.append(measurement)
            continue
        above, below = text_box[1] - top, bottom - text_box[3]
        difference = abs(above - below)
        biased = (difference > max(3 * scale, .12 * (bottom - top))
                  and max(above, below) > 1.8 * max(min(above, below), scale))
        overflow = min(above, below, text_box[0] - left, right - text_box[2]) < -max(.5, scale)
        measurement.update(status='measured_pending_visual_review',
                           top_margin_pt=above, bottom_margin_pt=below,
                           margin_difference_pt=difference,
                           margin_difference_normalized_540=difference / scale,
                           vertical_bias_candidate=biased, bounds_overflow_candidate=overflow,
                           candidate=biased or overflow)
        measurements.append(measurement)
        if measurement['candidate']:
            affected.append(measurement)
    if not affected:
        return measurements, []
    ids = {row['container_id'] for row in affected}
    ids.update(member['id'] for row in affected for member in row['source_text'])
    objects = [item for item in paths + texts if item['id'] in ids]
    finding = candidate(number, 'title_container_balance_candidate', objects,
                        'Visible text associated with a broad pale top band has unequal vertical margins or extends outside its container.',
                        'The band is a provisional title-container candidate. Font-metric boxes are not painted ink, and apparent balance does not establish visual correctness. Inspect independent local and full-page evidence, including mixed fonts and multiline text.')
    finding.update(containers=affected, requires_visual_review=True)
    return measurements, [finding]


def body_vertical_balance(number, width, height, texts, images, paths, titles, footers):
    """Screen both directions between detected bands; optical balance stays visual.

    Page-wide background rectangles cannot supply body content. Image viewports
    and outlined plots remain provisional: their white padding needs inspection.
    Covers and themes without a detected title band retain manual review.
    """
    if not titles:
        return {'status': 'visual_review_required', 'reason': 'No reliable title-band boundary'}, []
    top = max(row['container_bounds'][3] for row in titles)
    bottom = min((row['container_bounds'][1] for row in footers), default=height * .94)
    scale = height / 540
    if bottom <= top:
        return {'status': 'visual_review_required', 'reason': 'Body interval unavailable'}, []
    members = []
    for obj in texts + images + paths:
        left, y0, right, y1 = obj['bounds']
        if y0 < top - .5 or y1 > bottom + .5 or right <= 0 or left >= width:
            continue
        if obj['kind'] == 'path':
            fill_visible = obj.get('fill') is not None and obj.get('fill_opacity') != 0
            stroke_visible = obj.get('stroke') is not None and obj.get('stroke_opacity') != 0
            if not (fill_visible or stroke_visible):
                continue
            if obj.get('has_rectangle') and right-left >= width*.85 and y1-y0 >= (bottom-top)*.75:
                continue
        members.append(obj)
    box = union(members)
    if box is None:
        return {'status': 'visual_review_required', 'reason': 'Body objects unavailable'}, []
    upper, lower = max(0, box[1]-top), max(0, bottom-box[3])
    difference = abs(upper-lower)
    suspect = difference/scale > 60 and max(upper,lower) > 2*max(min(upper,lower),8*scale)
    measure = {'status': 'measured_pending_visual_review', 'body_interval_pt': [top,bottom],
               'content_bounds_pt': box, 'upper_gap_pt': upper, 'lower_gap_pt': lower,
               'gap_difference_normalized_540': difference/scale,
               'direction': 'top_heavy' if lower > upper else 'bottom_heavy' if upper > lower else 'balanced',
               'candidate': suspect, 'sourceobjs': [obj['id'] for obj in members],
               'basis': 'Object-envelope screening. Compare actual ink, inner gaps and semantic groups on local and full-page renders; no automatic layout approval.'}
    if not suspect:
        return measure, []
    finding = candidate(number, 'body_vertical_balance_candidate', members,
                        'Body envelope leaves strongly unequal space above and below ('+measure['direction']+').',
                        'Detected bands, image padding, math metrics and meaningful whitespace need independent local plus full-page review. Keep content and tight title association; do not enforce mechanical centering.',
                        [0,top,width,bottom])
    finding['vertical_balance'] = measure
    return measure, [finding]


def body_container_content(number, width, height, texts, images, paths, titles, footers):
    """Keep painted containers, then inspect the content their envelopes hide."""
    top=max((row['container_bounds'][3] for row in titles),default=0)
    bottom=min((row['container_bounds'][1] for row in footers),default=height)
    scale=height/540;measurements=[];findings=[]
    for host in paths:
        h=host['bounds']
        if not (host.get('has_rectangle') and host.get('item_count')==1 and
                host.get('fill') is not None and host.get('fill_opacity')!=0 and
                h[1]>=top-.5 and h[3]<=bottom+.5 and
                (h[2]-h[0])*(h[3]-h[1])>=width*height*.08):continue
        children=[]
        for obj in texts+images+paths:
            b=obj['bounds']
            if obj['id']==host['id'] or b==h or not (h[0]<=b[0] and h[1]<=b[1] and h[2]>=b[2] and h[3]>=b[3]):continue
            if obj['kind']=='path' and not ((obj.get('fill') is not None and obj.get('fill_opacity')!=0) or
                                          (obj.get('stroke') is not None and obj.get('stroke_opacity')!=0)):continue
            children.append(obj)
        box=union(children)
        if box is None:continue
        upper,lower=max(0,box[1]-h[1]),max(0,h[3]-box[3])
        graphics=[obj for obj in children if obj['kind']!='text']
        suspect=abs(upper-lower)/scale>60 and max(upper,lower)>2*max(min(upper,lower),8*scale)
        sparse_text=not graphics and (box[3]-box[1])<(h[3]-h[1])*.35 and (upper+lower)/scale>120
        measurement={'container_id':host['id'],'container_bounds_pt':h,'content_bounds_pt':box,
                     'upper_gap_pt':upper,'lower_gap_pt':lower,'candidate':suspect or sparse_text,
                     'vertical_bias_candidate':suspect,'sparse_text_candidate':sparse_text,
                     'graphic_object_ids':[obj['id'] for obj in graphics],
                     'sourceobjs':[obj['id'] for obj in children],'status':'measured_pending_visual_review'}
        measurements.append(measurement)
        if suspect or sparse_text or graphics:
            finding=candidate(number,'body_container_content_review',[host]+children,
                'Inspect the actual content and empty regions inside this painted body container.',
                'A container envelope cannot prove internal balance or content sufficiency. Preserve visible graphics and inspect their actual ink, labels, local space and full-page composition.',h)
            finding['container_balance']=measurement;findings.append(finding)
    return measurements,findings


def measure_page(page, number, module, small_text_pt=12):
    width, height = float(page.rect.width), float(page.rect.height)
    if not all(math.isfinite(x) and x > 0 for x in (width, height)):
        raise ValueError('Invalid display dimensions')
    rotation = page.rotation_matrix

    def display_box(box):
        return bounds(module.Rect(box) * rotation)

    texts, images, paths = [], [], []
    # Unlike page.get_text(), the trace retains text drawn beyond page edges.
    for index, span in enumerate(page.get_texttrace()):
        glyphs = span.get('chars', ())
        size = float(span['size'])
        if not math.isfinite(size) or size < 0:
            raise ValueError('Invalid extracted font size')
        text = ''.join(chr(char[0]) if 0 <= char[0] <= 0x10ffff else '\ufffd' for char in glyphs)
        texts.append({'id': f'p{number}:text:{index}', 'kind': 'text',
                      'bounds': display_box(span['bbox']), 'text': text,
                      'font': span.get('font'), 'effective_size_pt': size,
                      'normalized_size_540': size / height * 540,
                      'glyph_count': len(glyphs), 'paint_type': span.get('type'),
                      'opacity': span.get('opacity'), 'sequence': span.get('seqno'),
                      'glyph_bounds': [display_box(char[3]) for char in glyphs]})
    for index, item in enumerate(page.get_image_info()):
        images.append({'id': f'p{number}:image:{index}', 'kind': 'image',
                       'bounds': display_box(item['bbox']),
                       'pixel_width': item.get('width'), 'pixel_height': item.get('height')})
    for index, item in enumerate(page.get_drawings()):
        paths.append({'id': f'p{number}:path:{index}', 'kind': 'path',
                      'bounds': display_box(item['rect']), 'paint_type': item.get('type'),
                      'fill': item.get('fill'), 'stroke': item.get('color'),
                      'fill_opacity': item.get('fill_opacity'), 'stroke_opacity': item.get('stroke_opacity'),
                      'item_count': len(item.get('items', [])),
                      'has_rectangle': any(part[0] == 're' for part in item.get('items', []))})
    visible_text = [x for x in texts if x['text'].strip() and x['paint_type'] != 3 and x['opacity'] != 0]
    footer_measurements, findings = footer_balance(number, width, height, visible_text, paths)
    title_measurements, title_findings = title_balance(number, width, height, visible_text, paths)
    findings.extend(title_findings)
    vertical_measurement, vertical_findings = body_vertical_balance(
        number, width, height, visible_text, images, paths, title_measurements, footer_measurements)
    findings.extend(vertical_findings)
    body_containers,container_findings=body_container_content(
        number,width,height,visible_text,images,paths,title_measurements,footer_measurements)
    findings.extend(container_findings)
    outside = [x for x in visible_text if x['bounds'][0] < -0.5 or x['bounds'][1] < -0.5
               or x['bounds'][2] > width + 0.5 or x['bounds'][3] > height + 0.5]
    if outside:
        findings.append(candidate(number, 'text_outside_page', outside,
                                  'Extracted text bounds extend beyond the displayed page.',
                                  'Trace bounds approximate glyph metrics; clipping, masks and actual painted edges need rendered verification.'))
    small = [x for x in visible_text if x['normalized_size_540'] < small_text_pt]
    if small:
        findings.append(candidate(number, 'small_text_candidate', small,
                                  f'Effective font size normalized to a 540 pt page height is below {small_text_pt:g} pt.',
                                  'Semantic roles are unproved; math subscripts, footers and complex figure labels require local and full-page reading. This is not an automatic failure or a font-role assignment.'))
    intervals = sorted((max(0, x['bounds'][1]), min(height, x['bounds'][3])) for x in visible_text
                       if x['bounds'][3] > 0 and x['bounds'][1] < height and x['bounds'][2] > 0 and x['bounds'][0] < width)
    merged = []
    for top, bottom in intervals:
        if merged and top <= merged[-1][1]:
            merged[-1][1] = max(bottom, merged[-1][1])
        else:
            merged.append([top, bottom])
    gaps = [[merged[i][1], merged[i + 1][0]] for i in range(len(merged) - 1)]
    largest_gap = max(gaps, key=lambda gap: gap[1] - gap[0]) if gaps else None
    if not texts and not images and not paths:
        findings.append(candidate(number, 'empty_page_candidate', [],
                                  'No text, image or drawing objects were extracted.',
                                  'Annotations and unsupported content may still paint; inspect the actual full page.', [0, 0, width, height]))
    if merged and merged[0][0] / height > 0.35:
        findings.append(candidate(number, 'distant_text_entry_candidate', visible_text,
                                  'The first extracted visible text begins below 35% of page height.',
                                  'No title or first-figure role is inferred; image-led pages may be intentional.'))
    placeholders = [x for x in paths if x['has_rectangle'] and x['fill'] is None
                    and (x['bounds'][2] - x['bounds'][0]) * (x['bounds'][3] - x['bounds'][1]) > width * height * 0.08]
    complex_paths = paths if len(paths) > 12 else []
    vector_only = paths if paths and not visible_text and not images else []
    if images or placeholders or complex_paths or vector_only:
        selected = images + (complex_paths or vector_only or placeholders)
        findings.append(candidate(number, 'graphic_content_review', selected,
                                  'Inspect image contents, complex vector regions and large outline rectangles for real content, labels and possible placeholders.',
                                  'Image viewports and path envelopes do not measure painted ink or content sufficiency; rectangles can be legitimate frames and figures need visual inspection.'))
    return {'page': number, 'status': 'complete', 'visual_review': 'pending',
            'display_width_pt': width, 'display_height_pt': height,
            'inventory': {'text': texts, 'images': images, 'paths': paths},
            'measurements': {'visible_text_span_count': len(visible_text),
                             'footer_containers': footer_measurements,
                             'title_containers': title_measurements,
                             'body_vertical_balance': vertical_measurement,
                             'body_content_containers': body_containers,
                             'first_visible_text_top_ratio': merged[0][0] / height if merged else None,
                             'largest_internal_text_gap_bounds': [0, largest_gap[0], width, largest_gap[1]] if largest_gap else None,
                             'largest_internal_text_gap_ratio': (largest_gap[1] - largest_gap[0]) / height if largest_gap else None,
                             'scope': 'Text intervals only; images and path envelopes are not density evidence. Title roles, meaningful whitespace and content sufficiency require visual review.'},
            'findings': findings}


def audit_pdf(path):
    # Independent structural parsing distinguishes invalid PDF from unavailable
    # optional layout extraction. This is also used when the CLI runs alone.
    from build_beamer import inspect_pdf
    path = Path(path).resolve()
    geometry, _ = inspect_pdf(path, 16 / 9, 0.01)
    pdf_hash = sha(path)
    count = len(geometry)
    report = {'schema': 'beamer-layout-audit/v1', 'status': 'complete',
              'pdf': {'path': str(path), 'sha256': pdf_hash},
              'physical_page_count': count, 'visual_review': 'pending', 'signed_off': False,
              'coordinate_system': 'display_cropbox_top_left_pdf_pt',
              'policy': {'reference_height_pt': 540, 'small_text_candidate_below_pt': 12,
                         'bounds_are_ink': False, 'semantic_roles_inferred': False},
              'pages': [], 'findings': [],
              'limitations': 'Object traces are candidates, not complete ink geometry. Clipping, transparency, occlusion, annotations, outlined text and image contents require actual visual review of every physical page.'}
    try:
        module = importlib.import_module('pymupdf')
        report['parser'] = {'name': 'PyMuPDF', 'version': str(module.VersionBind)}
        with module.open(path) as document:
            if len(document) != count:
                raise ValueError('Layout parser page count differs from structural PDF parser')
            for number in range(1, count + 1):
                try:
                    row = measure_page(document[number - 1], number, module)
                except Exception as error:
                    row = unavailable(number, type(error).__name__ + ': ' + str(error))
                report['pages'].append(row)
    except Exception as error:
        report['parser_error'] = type(error).__name__ + ': ' + str(error)
        report['pages'] = [unavailable(number, report['parser_error']) for number in range(1, count + 1)]
    if sha(path) != pdf_hash:
        raise ValueError('PDF changed during layout audit; freeze and rebuild current evidence')
    measured = [row['page'] for row in report['pages'] if row['status'] == 'complete']
    report['coverage'] = {'expected_pages': list(range(1, count + 1)), 'measured_pages': measured,
                          'unavailable_pages': [row['page'] for row in report['pages'] if row['status'] != 'complete']}
    report['findings'] = [finding for row in report['pages'] for finding in row['findings']]
    if len(measured) != count:
        report['status'] = 'incomplete'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit_pdf(args.pdf)
        code = 0 if report['status'] == 'complete' else 3
    except Exception as error:
        code = 3
        report = {'schema': 'beamer-layout-audit/v1', 'status': 'failed',
                  'visual_review': 'pending', 'signed_off': False,
                  'error': type(error).__name__ + ': ' + str(error),
                  'recovery': 'Restore a valid stable PDF and rerun; invalid PDF evidence requires a fresh build.'}
    write_code = emit_report(args.output, report, inputs=[args.pdf])
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return write_code or code


if __name__ == '__main__':
    raise SystemExit(main())
