"""Evidence-bound visual resolution of explicitly unmeasurable relationships.

This validates provenance/completeness, not the truth of a human/agent observation.
Never call this as a generic exception handler or for a measured defect.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import math
import statistics
from PIL import Image, ImageChops


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def eligible_code(stage, error):
    """Classify only known measurement limitations; all other failures stay hard."""
    exact = {
        ('interstitial', 'After boundary must be a native opaque solid rectangle'): 'unsupported_adjacent_contour',
        ('plot_table', 'No measurable visible edge on this scanline'): 'unmeasurable_scanline',
        ('plot_table', 'Edge varies across scanlines; use stable actual boundaries'): 'unstable_scanline',
        ('region', 'Actual glyph bounds uncertain: perform local optical repair/reliable measurement and rescan; no role-based waiver'): 'uncertain_glyph_segmentation',
        ('center', 'Visible host contour or hosted text ink is unmeasurable'): 'uncertain_visible_center',
        ('chart_gap', 'Visible chart spacing boundaries are unmeasurable'): 'uncertain_chart_spacing',
    }
    if (stage, error) in exact:
        return exact[stage, error]
    if stage == 'interstitial' and isinstance(error, str):
        for prefix in ('Unverified object intersects the preceding row: ', 'Unlisted object intersects the local adjacency corridor: '):
            if error.startswith(prefix) and error[len(prefix):].isdigit():
                return 'unclassified_adjacent_object'
    return None


def _specific(value):
    return isinstance(value, str) and len(value.strip()) >= 20 and value.strip().lower() not in ('pass', 'verified', '通过')


def _time(value):
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('Visual fallback time needs a timezone')
    return t


def validate_visual_fallback(finding, disposition, stage, error, image_path,
                             slide, render, author_id):
    """Return (error, resolution). Successful resolution still needs all other gates.

    A separate reviewer must actually inspect both exact local pixels and the
    current full page. A reviewer JSON/file does not by itself prove this happened.
    """
    try:
        code = eligible_code(stage, error)
        if code is None:
            raise ValueError('This is not an eligible measurement uncertainty; repair it')
        if stage=='center' and (finding.get('reason')!='centered_text_visible_host_review' or finding.get('measurement_status')!='manual_review_required'):
            raise ValueError('A known center mismatch cannot enter visual fallback')
        if stage=='chart_gap' and (finding.get('reason')!='native_chart_spacing_unmeasurable' or finding.get('measurement_status')!='manual_review_required'):
            raise ValueError('A measured visible spacing defect cannot enter visual fallback')
        record = disposition.get('visual_fallback')
        if not isinstance(record, dict):
            raise ValueError('Measurement unresolved: supply local + full-page visual fallback evidence')
        if record.get('code') != code or record.get('original_error') != error:
            raise ValueError('Fallback must bind the exact original machine finding/error')
        sha = render['sha256']; image_sha = digest(image_path)
        if record.get('pptx_sha256') != sha or record.get('image_sha256') != image_sha:
            raise ValueError('Fallback input/image is stale')
        if image_sha != render['raster_hashes'][str(finding['slide'])]:
            raise ValueError('Fallback is not the current renderer image')
        # Bind the whole visible page inventory, not an author-selected subset.
        actual_ids = {s.shape_id for s in slide.shapes}
        object_ids = record.get('page_object_ids')
        if not isinstance(object_ids, list) or any(type(i) is not int for i in object_ids) or len(set(object_ids)) != len(object_ids) or set(object_ids) != actual_ids:
            raise ValueError('Fallback must inventory every native page object')
        targets = set(finding.get('shape_ids', []))
        if stage == 'interstitial':
            contract = disposition.get('spacing_contract', {})
            targets.update(contract.get('before_shape_ids', []))
            targets.update([contract.get('middle_shape_id'), contract.get('after_shape_id')])
            if code == 'unclassified_adjacent_object':
                targets.add(int(error.rsplit(': ', 1)[1]))
        if not targets or not targets <= actual_ids:
            raise ValueError('Fallback lacks actual relationship targets')
        if not _specific(record.get('measurement_limitation')) or not _specific(record.get('local_observation')) or not _specific(record.get('global_observation')):
            raise ValueError('Fallback needs specific measurement, local and global observations')
        if record.get('local_result') != 'pass' or record.get('global_result') != 'pass' or record.get('unresolved') != []:
            raise ValueError('Visual uncertainty or an actual defect remains unresolved')
        if record.get('returned_to_full_page') is not True or record.get('normal_size_viewed') is not True:
            raise ValueError('Fallback needs normal-size full-page return after local inspection')
        observations = record.get('target_observations')
        if not isinstance(observations, dict) or set(observations) != set(map(str, targets)) or not all(_specific(v) for v in observations.values()):
            raise ValueError('Every relationship/obstruction target needs a specific visual observation')
        detail = record.get('detail', {})
        box = detail.get('crop_box_px')
        if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
            raise ValueError('Fallback needs an integer local crop box')
        with Image.open(image_path) as original, Image.open(detail['path']) as crop:
            page = original.convert('RGB'); local = crop.convert('RGB')
            if not (0 <= box[0] < box[2] <= page.width and 0 <= box[1] < box[3] <= page.height) or box == [0, 0, page.width, page.height]:
                raise ValueError('Fallback local crop cannot be empty, outside, or the full page')
            if detail.get('sha256') != digest(detail['path']) or local.size != (box[2]-box[0], box[3]-box[1]) or ImageChops.difference(local, page.crop(box)).getbbox():
                raise ValueError('Fallback detail is not exact current page pixels')
            prs = slide.part.package.presentation_part.presentation
            sx, sy = page.width/(prs.slide_width/12700), page.height/(prs.slide_height/12700)
            members = [s for s in slide.shapes if s.shape_id in targets]
            # Unknown/rotated geometry cannot be silently approximated here.
            if any(abs(s.rotation) > 1e-6 for s in members):
                raise ValueError('Rotated fallback targets need a verified contour before using this path')
            bounds = [min(s.left for s in members)/12700*sx, min(s.top for s in members)/12700*sy,
                      max(s.left+s.width for s in members)/12700*sx, max(s.top+s.height for s in members)/12700*sy]
            # Include surrounding context, not only isolated glyphs or one chosen gap.
            context = [max(0, math.floor(bounds[0])-2), max(0, math.floor(bounds[1])-2),
                       min(page.width, math.ceil(bounds[2])+2), min(page.height, math.ceil(bounds[3])+2)]
            if stage in ('center','chart_gap'):
                context=finding.get('crop_box_px')
                if not isinstance(context,list) or len(context)!=4 or any(type(v) is not int for v in context):
                    raise ValueError('Missing independently scanned visual inspection region')
            if not (box[0] <= context[0] and box[1] <= context[1] and box[2] >= context[2] and box[3] >= context[3]):
                raise ValueError('Local fallback crop omits relationship members or boundary context')
            if not any(lo != hi for lo, hi in local.getextrema()):
                raise ValueError('Unrelated blank pixels cannot resolve a relationship')
            measured = record.get('visible_measurements', {})
            if not isinstance(measured, dict):
                raise ValueError('Missing local visible measurements')
            def finite_values(values, count):
                return isinstance(values, list) and len(values) == count and all(type(v) in (int, float) and math.isfinite(v) for v in values)
            shapes = {s.shape_id:s for s in slide.shapes}
            scale = prs.slide_height/12700/540
            if stage=='chart_gap':
                edges=measured.get('vertical_edges_px')
                if not finite_values(edges,4):raise ValueError('Measure actual chart-bottom, caption-top/bottom and following-container top')
                known=finding.get('visible_edges_px',[None]*4)
                for i in finding.get('known_edge_indices',[]):
                    if type(i) is not int or not 0<=i<4 or known[i] is None or edges[i]!=known[i]:
                        raise ValueError('Known visible gap edges cannot be replaced by author measurements')
                if len(finding['shape_ids'])!=3:raise ValueError('Visible chart spacing requires the complete three-object relationship')
                chart,caption,after=[shapes[i] for i in finding['shape_ids']]
                a,b,c,d=edges
                if not (chart.top/12700*sy<=a<=(chart.top+chart.height)/12700*sy and
                        caption.top/12700*sy-1<=b<c<=(caption.top+caption.height)/12700*sy+1 and
                        after.top/12700*sy<=d<=(after.top+after.height)/12700*sy):
                    raise ValueError('Claimed gap edges lie outside the independently identified objects')
                above,below=(b-a)/sy,(d-c)/sy
                minimum=finding.get('minimum_gap_pt',12*scale)
                if type(minimum) not in (int,float) or not math.isfinite(minimum) or minimum<12*scale:
                    raise ValueError('Invalid or weakened visible gap minimum')
                if min(above,below)<minimum or abs(above-below)>max(3*scale,.2*(above+below)/2):
                    raise ValueError('Actual visible spacing is insufficient/unbalanced; repair it')
            elif stage=='center':
                if measured.get('reference')!='visible_hole':raise ValueError('Measure the actual visible hole, not Chart frame or PlotArea')
                boxes=[]
                for name in ('host_bbox_px','hole_bbox_px','text_group_bbox_px'):
                    bb=measured.get(name)
                    if not finite_values(bb,4) or not (0<=bb[0]<bb[2]<=page.width and 0<=bb[1]<bb[3]<=page.height):
                        raise ValueError('Missing actual center contour/text ink measurements')
                    if name in finding.get('measurement_known_fields',[]) and finding.get(name) is not None and bb!=finding[name]:
                        raise ValueError('Known center geometry cannot be replaced by author measurements')
                    if bb[0]<box[0] or bb[1]<box[1] or bb[2]>box[2] or bb[3]>box[3]:
                        raise ValueError('Center measurements extend outside the actual detail context')
                    boxes.append(bb)
                host,hole,ink=boxes
                if not (host[0]<=hole[0]<=ink[0] and host[1]<=hole[1]<=ink[1] and ink[2]<=hole[2]<=host[2] and ink[3]<=hole[3]<=host[3]):
                    raise ValueError('Text ink is not contained by the actual visible hole/host')
                tol=max(2,.75*scale*sx)
                if max(abs((hole[0]+hole[2]-ink[0]-ink[2])/2),abs((hole[1]+hole[3]-ink[1]-ink[3])/2))>=tol:
                    raise ValueError('Visual center measurements confirm a mismatch; repair it')
            elif stage == 'interstitial':
                from interstitial_spacing import _opaque_rectangle, _full_slide_background_ids
                edges = measured.get('vertical_edges_px')
                if not finite_values(edges, 4):
                    raise ValueError('Measure before-bottom, middle-top/bottom, after-top in current pixels')
                a, b, c, d = edges
                middle = shapes[contract['middle_shape_id']]
                after = shapes[contract['after_shape_id']]
                before = [shapes[i] for i in contract['before_shape_ids']]
                records=[r for r in render.get('text_records',[]) if r.get('slide')==finding['slide'] and r.get('shape_id')==middle.shape_id and r.get('kind')=='text']
                if len(records)!=1:
                    raise ValueError('Fallback cannot replace missing current middle glyph geometry')
                mr=records[0]
                if not finite_values([mr.get(k) for k in ('bound_top_pt','bound_height_pt')],2) or mr['bound_height_pt']<=0:
                    raise ValueError('Fallback cannot replace invalid middle glyph geometry')
                expected_b=mr['bound_top_pt']*sy; expected_c=(mr['bound_top_pt']+mr['bound_height_pt'])*sy
                if abs(b-expected_b)>1 or abs(c-expected_c)>1:
                    raise ValueError('Known middle glyph edges cannot be replaced by author measurements')
                backgrounds=_full_slide_background_ids(slide)
                known={}
                for sid,s in shapes.items():
                    if sid in backgrounds or sid==middle.shape_id:continue
                    if min(s.left+s.width,middle.left+middle.width)<=max(s.left,middle.left):continue
                    if _opaque_rectangle(s):
                        known[sid]=[s.left/12700,s.top/12700,(s.left+s.width)/12700,(s.top+s.height)/12700]
                    elif s.has_text_frame and s.text.strip() and abs(s.rotation)<1e-6:
                        rr=[r for r in render.get('text_records',[]) if r.get('slide')==finding['slide'] and r.get('shape_id')==sid and r.get('kind')=='text']
                        if len(rr)==1:
                            vv=[rr[0].get(k) for k in ('bound_left_pt','bound_top_pt','bound_width_pt','bound_height_pt')]
                            if finite_values(vv,4) and min(vv[2:])>0:known[sid]=[vv[0],vv[1],vv[0]+vv[2],vv[1]+vv[3]]
                previous={sid:box for sid,box in known.items() if box[3]<=mr['bound_top_pt']}
                if previous:
                    nearest=max(bb[3] for bb in previous.values())
                    for sid,bb in previous.items():
                        if abs(bb[3]-nearest)>.25*scale or sid in contract['before_shape_ids']:continue
                        contained=any(s.left/12700<=bb[0] and s.top/12700<=bb[1] and (s.left+s.width)/12700>=bb[2] and (s.top+s.height)/12700>=bb[3] for s in before)
                        if not contained:raise ValueError('Fallback omits a known nearer preceding object')
                known_bottoms=[known[s.shape_id][3]*sy for s in before if s.shape_id in known]
                if known_bottoms and mr['bound_top_pt']-max(known_bottoms)/sy < 12*scale:
                    raise ValueError('Known preceding gap is below the minimum; visual fallback cannot change it')
                if known_bottoms and (a<max(known_bottoms)-1 or (len(known_bottoms)==len(before) and abs(a-max(known_bottoms))>1)):
                    raise ValueError('Known preceding boundaries cannot be replaced by author measurements')
                if _opaque_rectangle(after) and abs(d-after.top/12700*sy)>1:
                    raise ValueError('Known following boundary cannot be replaced by author measurements')
                if not (min(s.top for s in before)/12700*sy <= a <= max(s.top+s.height for s in before)/12700*sy and
                        middle.top/12700*sy <= b < c <= (middle.top+middle.height)/12700*sy and
                        after.top/12700*sy <= d <= (after.top+after.height)/12700*sy):
                    raise ValueError('Claimed visible edges lie outside actual relationship members')
                above, below = (b-a)/sy, (d-c)/sy
                if min(above, below) < 12*scale or abs(above-below) > max(3*scale, .2*(above+below)/2):
                    raise ValueError('Visual measurements reveal insufficient/unbalanced gaps; repair them')
            elif stage in ('plot_table', 'region'):
                anchors = measured.get('anchors_px')
                if not isinstance(anchors, dict) or set(anchors) != set(map(str, targets)) or not finite_values(list(anchors.values()),len(targets)):
                    raise ValueError('Measure the common visible anchor for every related object')
                required_anchor = 'right' if stage == 'plot_table' else disposition.get('relation_contract',{}).get('common_visual_anchor')
                if required_anchor not in ('left','center','right') or measured.get('anchor') != required_anchor:
                    raise ValueError('Visual fallback cannot change the intended alignment criterion')
                for sid, x in anchors.items():
                    s=shapes[int(sid)]
                    if not s.left/12700*sx <= x <= (s.left+s.width)/12700*sx:
                        raise ValueError('Claimed visible anchor is outside its actual object')
                if stage == 'plot_table':
                    proof=disposition.get('plot_table_edge_evidence',{})
                    if proof.get('slide_width_pt')!=prs.slide_width/12700 or type(proof.get('pixels_per_pt')) not in (int,float) or abs(proof['pixels_per_pt']-sx)>1e-6:
                        raise ValueError('Fallback cannot replace invalid scanline coordinates/scale')
                    chart,table=[shapes[sid] for sid in finding['shape_ids']]
                    x0=max(0,math.floor((min(finding['plot_right_pt'],finding['table_right_pt'])-60*scale)*sx))
                    x1=min(page.width,math.ceil((max((chart.left+chart.width)/12700,(table.left+table.width)/12700)+4*scale)*sx))
                    for name,s,expected in [('chart_rows_px',chart,finding['plot_right_pt']),('table_rows_px',table,finding['table_right_pt'])]:
                        rows=proof.get(name,[])
                        if not isinstance(rows,list) or len(rows)<3 or any(type(y) is not int for y in rows) or len(set(rows))!=len(rows):
                            raise ValueError('Fallback cannot replace missing/invalid scanlines')
                        if any(not max(0,s.top/12700*sy)<=y<min(page.height,(s.top+s.height)/12700*sy) for y in rows):
                            raise ValueError('Fallback scanline is outside its actual object')
                        values=[]
                        for y in rows:
                            bg=page.getpixel((min(page.width-1,x1),y))
                            points=[x for x in range(x0,x1) if max(abs(page.getpixel((x,y))[c]-bg[c]) for c in range(3))>20]
                            if points:values.append(max(points))
                        if len(values)==len(rows) and max(values)-min(values)<=1:
                            known=statistics.median(values)
                            if abs(known/sx-expected)>6*scale:
                                raise ValueError('Known scanline boundary is inconsistent with its actual object')
                            if abs(anchors[str(s.shape_id)]-known)>1:
                                raise ValueError('Known stable scanline edge cannot be replaced by author measurements')
                threshold=max(2,.75*scale*sx)
                if max(anchors.values())-min(anchors.values()) >= threshold:
                    raise ValueError('Visual measurements confirm misalignment; repair it')
        # Recorded independent review binds exact pixels and exact original error.
        ref = record.get('independent_review', {})
        path = Path(ref.get('path', ''))
        if not path.is_file() or ref.get('sha256') != digest(path):
            raise ValueError('Missing/stale independent visual review record')
        import json
        independent = json.loads(path.read_text(encoding='utf-8-sig'))
        reviewer = independent.get('reviewer_id')
        if not isinstance(author_id, str) or not author_id.strip() or not isinstance(reviewer, str) or not reviewer.strip() or reviewer == author_id:
            raise ValueError('Fallback requires a different actual visual reviewer, not author self-exemption')
        expected = {'finding_id': finding['id'], 'slide': finding['slide'], 'code': code,
                    'original_error': error, 'pptx_sha256': sha, 'image_sha256': image_sha,
                    'detail_sha256': detail['sha256'], 'decision': 'visually_resolved',
                    'unresolved': [], 'local_viewed': True, 'full_page_viewed': True,
                    'visible_measurements': measured}
        if any(independent.get(k) != v for k, v in expected.items()):
            raise ValueError('Independent reviewer did not close this exact local/full-page finding')
        for field in ('local_observation', 'global_observation', 'review_source'):
            if not _specific(independent.get(field)):
                raise ValueError('Independent review needs specific observations and actual review provenance')
        if not _time(render['render_finished_utc']) <= _time(independent['reviewed_at']) <= _time(record['reviewed_at']):
            raise ValueError('Visual fallback review must follow rendering and independent inspection')
        return None, {'finding_id': finding['id'], 'code': code, 'original_error': error,
                      'resolution': 'visually_resolved_pending_signoff', 'reviewer_id': reviewer,
                      'independent_review_sha256': ref['sha256'], 'image_sha256': image_sha,
                      'detail_sha256': detail['sha256']}
    except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
        return str(exc), None
