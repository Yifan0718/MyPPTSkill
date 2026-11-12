"""Validate Beamer evidence links; actual visual judgement remains with reviewers."""
from pathlib import Path
import argparse
import json
import math
from PIL import Image, ImageChops
import skill_state
from build_beamer import digest as sha, inspect_pdf

CHECKS = ('content_reading', 'layout', 'local_detail', 'full_page_return',
          'cross_page', 'palette', 'floating_notes', 'container_balance',
          'density_and_balance', 'typography_consistency', 'effective_content_spacing',
          'content_sufficiency', 'regional_balance', 'grouping_and_spacing')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def observation(value):
    return isinstance(value, str) and len(value.strip()) >= 8 and value.strip().lower() not in ('verified', 'no issues', 'all passed')


def identity(value):
    return value.strip().casefold() if isinstance(value, str) else ''


def identified_containers(audit_page):
    """All identified bands need coverage, including balanced measurements."""
    measurements = audit_page.get('measurements')
    if measurements is None:
        return {}
    if not isinstance(measurements, dict):
        raise ValueError('Layout measurements must be an object or unavailable')
    result = {}
    for kind in ('footer', 'title'):
        rows = measurements.get(kind + '_containers', [])
        if not isinstance(rows, list):
            raise ValueError('Layout container measurements must be an array')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('Malformed layout container')
            identifier, box = row.get('container_id'), row.get('container_bounds')
            if not isinstance(identifier, str) or not identifier.strip() or identifier in result:
                raise ValueError('Layout container ID missing or duplicate')
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                    or box[0] >= box[2] or box[1] >= box[3]):
                raise ValueError('Invalid layout container bounds')
            result[identifier] = row
    return result


def container_pixel_bounds(box, pdf_page, render, dpi=None):
    """Map displayed PDF bounds to current pixels, including rounded edges."""
    width, height = pdf_page['display_width_pt'], pdf_page['display_height_pt']
    if dpi is not None:
        if type(dpi) not in (int, float) or not math.isfinite(dpi) or dpi <= 0:
            raise ValueError('Invalid build DPI for container coverage')
        sx = sy = dpi / 72
        if abs(width * sx - render['width_px']) > 2 or abs(height * sy - render['height_px']) > 2:
            raise ValueError('Build DPI and render dimensions disagree')
    else:
        # Older fixtures/reports lack DPI; actual PDF display dimensions and
        # the hash-checked PNG still determine their pixel coordinate mapping.
        sx, sy = render['width_px'] / width, render['height_px'] / height
    target = [max(0, math.floor(box[0] * sx)), max(0, math.floor(box[1] * sy)),
              min(render['width_px'], math.ceil(box[2] * sx)),
              min(render['height_px'], math.ceil(box[3] * sy))]
    if target[0] >= target[2] or target[1] >= target[3]:
        raise ValueError('Container has no visible area in the current render')
    return target


def pixel_region_covered(target, boxes):
    """Exact union coverage permits tiled local views of page-spanning hosts."""
    left,top,right,bottom=target
    xs=sorted({left,right}|{max(left,min(right,x)) for box in boxes for x in (box[0],box[2])})
    for a,b in zip(xs,xs[1:]):
        if a==b:continue
        edge=top
        for start,end in sorted((max(top,box[1]),min(bottom,box[3])) for box in boxes if box[0]<=a and box[2]>=b):
            if start>edge:break
            edge=max(edge,end)
        if edge<bottom:return False
    return True


def verify(build_path, review_path, _live_inputs=True, _baseline=False):
    issues, files = [], {}

    def need(ok, message):
        if not ok:
            issues.append(message)
        return bool(ok)

    def linked(record, label):
        if not isinstance(record, dict):
            need(False, label + ': missing file evidence')
            return None
        path, expected = record.get('path'), record.get('sha256')
        if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
            need(False, label + ': missing absolute file path')
            return None
        if not isinstance(expected, str) or sha(path).lower() != expected.lower():
            need(False, label + ': stale hash')
            return None
        files[str(Path(path).resolve())] = expected.lower()
        return Path(path)

    def linked_json(record, label):
        path = linked(record, label)
        if path is None:
            return None, {}
        value = load(path)
        if not isinstance(value, dict):
            need(False, label + ': JSON must be an object')
            return path, {}
        return path, value

    def closeup(record, render, label):
        path = linked(record, label)
        if path is None or not isinstance(render, dict):
            return
        need(record.get('render_sha256') == render.get('sha256'), label + ': parent render differs')
        box = record.get('crop_box')
        if not isinstance(box, list) or len(box) != 4 or any(type(value) is not int for value in box):
            need(False, label + ': require integer pixel crop_box')
            return
        parent = linked(render, label + ' parent')
        if parent is None:
            return
        with Image.open(parent) as whole, Image.open(path) as crop:
            left, top, right, bottom = box
            if not need(0 <= left < right <= whole.width and 0 <= top < bottom <= whole.height,
                        label + ': crop outside current image'):
                return
            if not need([left, top, right, bottom] != [0, 0, whole.width, whole.height],
                        label + ': whole-page image cannot substitute for a local view; crop the relevant objects and keep the full-page review separately'):
                return
            actual, supplied = whole.convert('RGBA').crop(tuple(box)), crop.convert('RGBA')
            same = actual.size == supplied.size and all(channel.getbbox() is None for channel in ImageChops.difference(actual, supplied).split())
            need(same, label + ': crop pixels differ from current render')

    def build_assets(b, label):
        need(b.get('schema') == 'beamer-build/v1' and b.get('status') == 'pending_visual_review'
             and type(b.get('exit_code')) is int and b.get('exit_code') == 0
             and b.get('signed_off') is False and b.get('visual_review') == 'pending',
             label + ': require a completed build/render report pending visual review')
        pdf = linked({'path': b.get('pdf_path'), 'sha256': b.get('pdf_sha256')}, label + ' PDF')
        count = 0
        pages = []
        if pdf:
            pages, _ = inspect_pdf(pdf, 16 / 9, 0.01)
            count = len(pages)
        need(type(b.get('physical_page_count')) is int and count > 0 and b.get('physical_page_count') == count,
             label + ': physical PDF page count differs')
        _, audit = linked_json(b.get('layout_audit'), label + ' layout audit')
        need(audit.get('schema') == 'beamer-layout-audit/v1' and audit.get('status') in ('complete','incomplete')
             and audit.get('signed_off') is False and audit.get('visual_review') == 'pending', label + ': layout audit missing or invalid')
        need(audit.get('pdf', {}).get('sha256') == b.get('pdf_sha256')
             and audit.get('physical_page_count') == count, label + ': layout audit targets another PDF')
        expected_pages = list(range(1, count + 1))
        coverage = audit.get('coverage', {})
        need(coverage.get('expected_pages') == expected_pages, label + ': audit coverage differs')
        audit_pages = audit.get('pages', [])
        need(isinstance(audit_pages, list) and len(audit_pages) == count
             and {p.get('page') for p in audit_pages if isinstance(p, dict)} == set(expected_pages), label + ': audit page inventory incomplete')
        audit_findings = audit.get('findings', [])
        need(isinstance(audit_findings, list) and all(f in b.get('findings', []) for f in audit_findings), label + ': build dropped layout findings')
        # A missing measurement must reach independent visual closure through
        # a concrete finding, rather than disappearing into an empty inventory.
        measured, unavailable = coverage.get('measured_pages'), coverage.get('unavailable_pages')
        valid_partition = all(isinstance(values, list) and all(type(n) is int for n in values)
                              and len(values) == len(set(values)) for values in (measured, unavailable))
        valid_partition = valid_partition and not set(measured).intersection(unavailable) and set(measured + unavailable) == set(expected_pages)
        need(valid_partition, label + ': audit measured/unavailable page coverage is inconsistent')
        if valid_partition and isinstance(audit_pages, list):
            need(audit.get('status') == ('incomplete' if unavailable else 'complete'), label + ': audit status disagrees with unavailable pages')
            for row in audit_pages:
                number = row.get('page')
                row_findings = row.get('findings')
                valid_findings = isinstance(row_findings, list) and all(isinstance(f, dict) and f.get('page') == number for f in row_findings)
                need(valid_findings, label + ': malformed per-page findings')
                if valid_findings:
                    need(all(f in audit_findings for f in row_findings), label + ': global audit dropped a per-page finding')
                if number in measured:
                    need(row.get('status') == 'complete' and isinstance(row.get('inventory'), dict)
                         and isinstance(row.get('measurements'), dict), label + ': measured page lacks complete object measurements')
                elif number in unavailable:
                    need(row.get('status') == 'incomplete', label + ': unavailable page has inconsistent status')
                    need(valid_findings and any(f.get('category') == 'layout_measurement_unavailable' for f in row_findings),
                         label + ': unavailable page needs a measurement finding and independent local/full-page review')
        rows = b.get('renders')
        if not need(isinstance(rows, list), label + ': renders must be an array'):
            rows = []
        renders = {}
        for item in rows:
            if not isinstance(item, dict):
                need(False, label + ': malformed render')
                continue
            number = item.get('page')
            if not need(type(number) is int and 1 <= number <= count and number not in renders,
                        label + ': duplicate/invalid render page'):
                continue
            renders[number] = item
            path = linked(item, label + ' page render')
            need(item.get('pdf_sha256') == b.get('pdf_sha256'), label + ': render targets another PDF')
            if path:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    image.load()
                    need(type(item.get('width_px')) is int and type(item.get('height_px')) is int
                         and image.size == (item.get('width_px'), item.get('height_px')),
                         label + ': render dimensions differ')
        need(set(renders) == set(range(1, count + 1)), label + ': render coverage missing or extra pages')
        return count, renders, audit, {page['page']: page for page in pages}

    def page_observations(page, render, number):
        checks = page.get('visual_checks')
        for name in CHECKS:
            need(isinstance(checks, dict) and observation(checks.get(name)), f'Page {number}: describe {name}')
        need(observation(page.get('optical_and_connectors')), f'Page {number}: inspect glyph edges, figures and connections')
        crops = page.get('closeups')
        if need(isinstance(crops, list), f'Page {number}: closeups must be an array'):
            for crop in crops:
                closeup(crop, render, f'Page {number} close-up')
                need(isinstance(crop, dict) and observation(crop.get('observation')), 'Describe actual close-up observation')

    def container_observations(page, render, number, audit_page, pdf_page, dpi):
        expected = identified_containers(audit_page)
        rows = page.get('container_checks', [])
        if not need(isinstance(rows, list), f'Page {number}: container_checks must be an array'):
            return
        seen = set()
        for row in rows:
            if not need(isinstance(row, dict), f'Page {number}: malformed container check'):
                continue
            identifier = row.get('container_id')
            if not need(isinstance(identifier, str) and identifier in expected and identifier not in seen,
                        f'Page {number}: duplicate or extra container check'):
                continue
            seen.add(identifier)
            label = f'Page {number} container {identifier}'
            need(observation(row.get('observation')), label + ': describe actual segment balance and visible glyphs')
            need(row.get('status', 'reviewed') == 'reviewed', label + ': container remains pending')
            need(row.get('full_page_return') is True, label + ': return to the full page after local inspection')
            local = row.get('local_view')
            closeup(local, render, label + ' local view')
            crop = local.get('crop_box') if isinstance(local, dict) else None
            if isinstance(crop, list) and len(crop) == 4 and all(type(v) is int for v in crop):
                target = container_pixel_bounds(expected[identifier]['container_bounds'], pdf_page, render, dpi)
                need(crop[0] <= target[0] and crop[1] <= target[1] and crop[2] >= target[2] and crop[3] >= target[3],
                     label + ': local crop does not cover the complete target container')
        need(seen == set(expected), f'Page {number}: container check coverage incomplete; inspect every identified footer/title segment')

    try:
        before = sha(build_path), sha(review_path)
        files[str(Path(build_path).resolve())], files[str(Path(review_path).resolve())] = before
        b, r = load(build_path), load(review_path)
        if not isinstance(b, dict) or not isinstance(r, dict):
            raise ValueError('Build/review must be JSON objects')
        need(r.get('schema') == 'beamer-review/v1', 'Require beamer-review/v1')
        need(r.get('status', 'reviewed') == 'reviewed', 'Review remains unreviewed')
        need(r.get('build_report_sha256') == before[0], 'Review targets another build report')
        need(observation(r.get('audience')), 'Describe audience and first-reading context')
        need(bool(identity(r.get('reviewer'))), 'Missing actual reviewer')
        need(r.get('unresolved') == [], 'Unresolved findings remain')
        lock_path, lock = linked_json(r.get('skill_lock'), 'Skill rule lock')
        rule_root = Path(__file__).resolve().parent.parent
        need(Path(lock.get('root', '')).resolve() == rule_root, 'Skill lock targets another installation')
        if lock_path: need(skill_state.check(lock_path, rule_root)['status'] == 'unchanged', 'Skill rules changed; refreeze and review against current rules')
        count, renders, audit, pdf_pages = build_assets(b, 'Current build')
        audit_pages = {page['page']: page for page in audit.get('pages', []) if isinstance(page, dict)}
        snapshots = [b.get(name) for name in ('input_hashes_before', 'input_hashes_after')]
        for name, values in zip(('input_hashes_before', 'input_hashes_after'), snapshots):
            need(isinstance(values, dict) and bool(values), 'Missing ' + name)
        need(snapshots[0] == snapshots[1], 'Build input changed between snapshots')
        tracked = {}
        for name in ('input_hashes_before', 'input_hashes_after', 'dependency_hashes'):
            values = b.get(name)
            if need(isinstance(values, dict), name + ' must be an object'):
                for path, value in values.items():
                    need(isinstance(path, str) and Path(path).is_absolute() and isinstance(value, str)
                         and len(value) == 64 and all(c in '0123456789abcdef' for c in value.lower()),
                         'Malformed input hash record')
                    if path in tracked:
                        need(tracked[path] == value, 'Build input changed between snapshots: ' + path)
                    tracked[path] = value
        need(isinstance(b.get('source_path'), str) and b.get('source_path') in tracked,
             'Main source is missing from input hashes')
        if _live_inputs:
            for path, value in tracked.items():
                linked({'path': path, 'sha256': value}, 'Current input dependency')
        scope = r.get('scope', 'full')
        need(scope in ('full', 'amendment'), 'Unknown review scope')
        baseline = {}
        if scope == 'amendment':
            if _baseline:
                raise ValueError('Amendment requires a full baseline, not another amendment')
            base = r.get('baseline')
            if not isinstance(base, dict):
                base = {}
            signoff_path, signoff = linked_json(base.get('signoff'), 'Baseline signoff')
            old_review_path, old = linked_json(base.get('review'), 'Baseline review')
            old_build_path, old_build = linked_json(base.get('build'), 'Baseline build')
            need(observation(r.get('user_reported_issue')), 'Amendment requires actual user issue reference and description')
            need(signoff.get('status') == 'signed_off' and signoff.get('scope') == 'full'
                 and signoff.get('unresolved') == [] and bool(identity(signoff.get('reviewer')))
                 and observation(signoff.get('reference')), 'Baseline must have actual full signoff and its review reference')
            if signoff_path and old_review_path and old_build_path:
                need(signoff.get('review_sha256') == sha(old_review_path)
                     and signoff.get('build_report_sha256') == sha(old_build_path)
                     and signoff.get('pdf_sha256') == old_build.get('pdf_sha256'), 'Baseline signoff links differ')
                need(old.get('scope', 'full') == 'full', 'Baseline must have full review scope')
                old_count, old_renders, _, _ = build_assets(old_build, 'Baseline build')
                need(old_count == count, 'Changed page count requires full review')
                prior = verify(old_build_path, old_review_path, _live_inputs=False, _baseline=True)
                need(not prior['issues'], 'Baseline evidence is invalid: ' + '; '.join(prior['issues']))
                for page in old.get('pages', []) if isinstance(old.get('pages'), list) else []:
                    if isinstance(page, dict) and type(page.get('page')) is int:
                        number = page['page']
                        baseline[number] = (page, old_renders.get(number, {}))
        rows = r.get('pages')
        if not need(isinstance(rows, list), 'Review pages must be an array'):
            rows = []
        seen = set()
        for page in rows:
            if not isinstance(page, dict):
                need(False, 'Malformed page review')
                continue
            number = page.get('page')
            if not need(type(number) is int and 1 <= number <= count and number not in seen,
                        'Duplicate/invalid reviewed page'):
                continue
            seen.add(number)
            render = renders.get(number, {})
            need(bool(render) and page.get('render_sha256') == render.get('sha256'), 'Page review targets another render')
            inherited = page.get('status') == 'inherited'
            if inherited:
                old_page, old_render = baseline.get(number, ({}, {}))
                need(scope == 'amendment' and old_page.get('status') == 'reviewed'
                     and old_page.get('render_sha256') == page.get('render_sha256')
                     and old_render.get('sha256') == render.get('sha256'),
                     'Inherited page requires identical reviewed baseline image')
                page = old_page
            else:
                need(page.get('status') == 'reviewed', 'Page not actually reviewed')
            page_observations(page, render, number)
            # Historical signed-off baselines and unchanged inherited pages
            # retain their original evidence contract. New/full review pages
            # must cover every currently identified band, even without issues.
            if (not _baseline and not inherited) or (_baseline and 'container_checks' in page):
                container_observations(page, render, number, audit_pages.get(number, {}),
                                       pdf_pages.get(number, {}), b.get('dpi'))
        need(seen == set(range(1, count + 1)), 'Every physical page needs current or valid inherited review')
        groups = {}
        for group in ('warnings', 'findings'):
            original = b.get(group, [])
            groups[group] = original if isinstance(original, list) else []
            need(isinstance(original, list) and all(isinstance(item, dict) for item in groups[group]),
                 group + ' must be an array of diagnostic objects')
        diagnostics = r.get('diagnostics', [])
        if not need(isinstance(diagnostics, list), 'diagnostics must be an array'):
            diagnostics = []
        covered = set()
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict):
                need(False, 'Malformed diagnostic review')
                continue
            group, index = diagnostic.get('group'), diagnostic.get('index')
            if not need(isinstance(group, str) and group in groups and type(index) is int
                        and 0 <= index < len(groups[group]) and (group, index) not in covered,
                        'Invalid/duplicate diagnostic reference'):
                continue
            covered.add((group, index))
            need(observation(diagnostic.get('observation')), 'Diagnostic needs a concrete review observation')
            need(diagnostic.get('status') in ('visually_checked', 'independently_resolved'), 'Diagnostic is unresolved')
            if group == 'findings' or diagnostic.get('status') == 'independently_resolved':
                need(diagnostic.get('status') == 'independently_resolved', 'Rule findings require independent local and full-page resolution')
                need(bool(identity(r.get('author'))), 'Independent closure requires the actual author identity')
                _, independent = linked_json(diagnostic.get('independent_review'), 'Independent review record')
                need(independent.get('schema') == 'beamer-independent-review/v1', 'Independent record schema differs')
                reviewer = identity(independent.get('reviewer'))
                need(bool(reviewer) and reviewer not in {identity(r.get('reviewer')), identity(r.get('author'))},
                     'Independent reviewer must differ from author and primary reviewer')
                need(independent.get('build_report_sha256') == before[0]
                     and independent.get('pdf_sha256') == b.get('pdf_sha256')
                     and independent.get('diagnostic') == {'group': group, 'index': index}, 'Independent candidate/diagnostic links differ')
                need(independent.get('decision') == 'visually_resolved' and independent.get('unresolved') == []
                     and independent.get('local_viewed') is True and independent.get('full_page_viewed') is True,
                     'Independent review must record completed local and full-page viewing')
                for name in ('reference', 'local_observation', 'full_page_observation'):
                    need(observation(independent.get(name)), 'Independent review needs concrete ' + name)
                number = independent.get('page')
                valid_page = type(number) is int and number in renders
                need(valid_page, 'Independent review page missing')
                original = groups[group][index]
                original_page = original.get('page') if isinstance(original, dict) else None
                if original_page is not None:
                    need(number == original_page, 'Independent review targets another finding page')
                if valid_page:
                    need(independent.get('render_sha256') == renders[number].get('sha256'), 'Independent whole-page hash differs')
                    if original.get('category') in ('body_vertical_balance_candidate','body_container_content_review'):
                        try:
                            bounds = original.get('bounds')
                            if not isinstance(bounds,list) or len(bounds)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds):
                                raise ValueError('Require four finite PDF bounds')
                            target = container_pixel_bounds(bounds, pdf_pages[number], renders[number], b.get('dpi'))
                            locals_ = independent.get('closeups') if 'closeups' in independent else [independent.get('closeup')]
                            if not isinstance(locals_,list) or not locals_:
                                raise ValueError('Provide one or more current local views')
                            boxes=[]
                            for index_,local in enumerate(locals_):
                                closeup(local,renders[number],f'Independent current close-up {index_+1}')
                                crop=local.get('crop_box',[]) if isinstance(local,dict) else []
                                if isinstance(crop,list) and len(crop)==4 and all(type(v) is int for v in crop):
                                    boxes.append(crop)
                            need(bool(boxes) and pixel_region_covered(target,boxes),
                                 'Body balance local views must jointly include the complete upper/body/lower comparison region')
                        except (KeyError, TypeError, ValueError, IndexError, OverflowError) as error:
                            need(False, 'Body balance context unavailable: ' + str(error))
                    else:
                        closeup(independent.get('closeup'),renders[number],'Independent current close-up')
        expected = {(group, index) for group, values in groups.items() for index in range(len(values))}
        need(covered == expected, 'Diagnostic coverage is incomplete')
        exceptions = r.get('font_exceptions')
        if not need(isinstance(exceptions, list), 'font_exceptions must be an array, empty if unused'):
            exceptions = []
        ids = set()
        for exception in exceptions:
            if not isinstance(exception, dict):
                need(False, 'Malformed font exception')
                continue
            identifier = exception.get('id')
            if not need(isinstance(identifier, str) and bool(identifier.strip()) and identifier not in ids,
                        'Font exception ID missing/duplicate'):
                continue
            ids.add(identifier)
            number = exception.get('page')
            valid_page = type(number) is int and number in renders
            need(valid_page and observation(exception.get('component')), 'Font exception target missing')
            for name in ('ten_equivalent_render_problem', 'ten_equivalent_target', 'ten_equivalent_method',
                         'measurement_uncertainty', 'necessity', 'layout_and_split_attempts', 'final_visual_observation'):
                need(observation(exception.get(name)), 'Font exception evidence missing: ' + name)
            _, ten_build = linked_json(exception.get('ten_equivalent_build'), 'Ten-equivalent build')
            _, ten_renders, _, _ = build_assets(ten_build, 'Ten-equivalent build')
            ten_before, ten_after = ten_build.get('input_hashes_before'), ten_build.get('input_hashes_after')
            need(isinstance(ten_before, dict) and bool(ten_before) and ten_before == ten_after,
                 'Ten-equivalent build input snapshots differ or are missing')
            ten_pdf_record = exception.get('ten_equivalent_pdf')
            ten_pdf = linked(ten_pdf_record, 'Ten-equivalent PDF')
            need(ten_pdf is not None and isinstance(ten_pdf_record, dict)
                 and ten_pdf_record.get('sha256') == ten_build.get('pdf_sha256'),
                 'Ten-equivalent PDF differs from its build')
            ten_number = exception.get('ten_equivalent_page', number)
            valid_ten = type(ten_number) is int and ten_number in ten_renders
            need(valid_ten, 'Ten-equivalent target page missing')
            source_record = exception.get('ten_equivalent_source')
            linked(source_record, 'Ten-equivalent source snapshot')
            if isinstance(source_record, dict):
                original_path = source_record.get('original_path')
                hashes = ten_build.get('input_hashes_before', {})
                need(isinstance(original_path, str) and isinstance(hashes, dict)
                     and hashes.get(original_path) == source_record.get('sha256'),
                     'Ten-equivalent source snapshot differs from recorded input')
                need(observation(source_record.get('location')), 'Identify target source location and component')
            if valid_ten:
                closeup(exception.get('ten_equivalent_closeup'), ten_renders[ten_number], 'Ten-equivalent close-up')
            if valid_page:
                closeup(exception.get('final_closeup'), renders[number], 'Final font close-up')
        for path, expected in files.items():
            need(Path(path).is_file() and sha(path).lower() == expected, 'Evidence changed during verification: ' + path)
        if lock_path:
            need(skill_state.check(lock_path, rule_root)['status'] == 'unchanged',
                 'Skill rules changed during verification; preserve this run and recheck against a stable current rule lock')
    except Exception as error:
        issues.append(type(error).__name__ + ': ' + str(error))
    return {'schema': 'beamer-review-check/v1',
            'status': 'failed' if issues else 'evidence_complete_pending_visual_signoff',
            'issues': issues, 'signed_off': False,
            'next_step': 'Resolve defects or complete independent visual evidence, then recheck.' if issues
            else 'Actual reviewer completes signoff for this unchanged candidate; this checker validates links and pixels, not visual quality or reviewer identity.'}


def template(build_path):
    b = load(build_path)
    if not isinstance(b, dict) or b.get('schema') != 'beamer-build/v1' or b.get('status') != 'pending_visual_review':
        raise ValueError('Require a completed beamer-build/v1 report')
    count, renders = b.get('physical_page_count'), b.get('renders')
    if type(count) is not int or count <= 0 or not isinstance(renders, list):
        raise ValueError('Build report lacks physical page coverage')
    if any(not isinstance(row, dict) or type(row.get('page')) is not int for row in renders):
        raise ValueError('Malformed render page')
    ordered = {row['page']: row for row in renders}
    if len(ordered) != len(renders) or set(ordered) != set(range(1, count + 1)):
        raise ValueError('Build report lacks physical page coverage')
    link = b.get('layout_audit')
    if not isinstance(link, dict) or not isinstance(link.get('path'), str) or sha(link['path']) != link.get('sha256'):
        raise ValueError('Template requires the current hash-linked layout audit')
    audit = load(link['path'])
    rows = audit.get('pages', [])
    if (audit.get('schema') != 'beamer-layout-audit/v1' or audit.get('pdf', {}).get('sha256') != b.get('pdf_sha256')
            or not isinstance(rows, list) or len(rows) != count
            or any(not isinstance(row, dict) or type(row.get('page')) is not int for row in rows)
            or {row['page'] for row in rows} != set(range(1, count + 1))):
        raise ValueError('Template layout audit PDF or physical page coverage differs')
    containers = {row['page']: identified_containers(row) for row in rows}
    diagnostics = []
    for group in ('warnings', 'findings'):
        values = b.get(group, [])
        if not isinstance(values, list):
            raise ValueError(group + ' must be an array')
        for index, _ in enumerate(values):
            row = {'group': group, 'index': index, 'status': 'pending', 'observation': ''}
            if group == 'findings':
                row['independent_review'] = {'path': '', 'sha256': ''}
            diagnostics.append(row)
    return {'schema': 'beamer-review/v1', 'build_report_sha256': sha(build_path), 'scope': 'full',
            'status': 'unreviewed', 'reviewer': '', 'author': '', 'audience': '',
            'skill_lock': {'path': '', 'sha256': ''},
            'unresolved': ['pending_visual_review'],
            'pages': [{'page': number, 'render_sha256': ordered[number].get('sha256'), 'status': 'unreviewed',
                       'visual_checks': {name: '' for name in CHECKS}, 'optical_and_connectors': '', 'closeups': [],
                       'container_checks': [{'container_id': identifier, 'status': 'pending', 'observation': '',
                                             'container_bounds_pdf_pt': row['container_bounds'],
                                             'local_view': {'path': '', 'sha256': '', 'render_sha256': ordered[number].get('sha256'), 'crop_box': []},
                                             'full_page_return': False,
                                             'instruction': 'Inspect this segment locally and on the full page. Save a current pixel-identical crop covering its entire PDF container; one whole-band crop may serve multiple segments. Describe this segment specifically, fill the evidence link/crop_box, then mark status reviewed and full_page_return true.'}
                                            for identifier, row in containers[number].items()]}
                      for number in range(1, count + 1)],
            'diagnostics': diagnostics, 'font_exceptions': []}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({'status': 'failed', 'reason': message,
                          'recovery': 'Use build_report review output, or --template BUILD_REPORT REVIEW_OUTPUT.'}))
        raise SystemExit(2)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--template', nargs=2, type=Path, metavar=('BUILD_REPORT', 'REVIEW_OUTPUT'))
    parser.add_argument('paths', nargs='*', type=Path, metavar='PATH')
    args = parser.parse_args(argv)
    if args.template and args.paths:
        parser.error('--template cannot be combined with positional arguments')
    if not args.template and len(args.paths) != 3:
        parser.error('Provide build_report, review, and output')
    try:
        if args.template:
            build_path, output = args.template
            inputs = [build_path]
        else:
            build_path, review_path, output = args.paths
            inputs = [build_path, review_path]
        if output.resolve() in [path.resolve() for path in inputs]:
            raise ValueError('Output must not overwrite evidence')
        if output.exists():
            raise ValueError('Choose a fresh output path; existing files are preserved')
        result = template(build_path) if args.template else verify(build_path, review_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('x', encoding='utf8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'status': result['status'], 'issues': len(result.get('issues', [])), 'report': str(output)}))
        return 1 if result.get('issues') else 0
    except Exception as error:
        print(json.dumps({'status': 'failed', 'reason': str(error),
                          'recovery': 'Check evidence files and choose a fresh writable output path.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
