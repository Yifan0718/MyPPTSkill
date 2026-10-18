"""Validate coverage disposition evidence before signoff (not proof of looking).
Usage: verify_coverage_review.py candidate.pptx coverage.json review.json render_dir report.json
Review schema is documented in references/layout-integrity.md.
"""
from pathlib import Path
import argparse, hashlib, json, math, sys
import statistics
from pptx import Presentation
from audit_layout_coverage import audit as rescan
from pptx.enum.dml import MSO_FILL_TYPE
from skill_state import check as check_skill_state
from connector_integrity import verify_connections
from render_evidence import validate_render_evidence,validate_manual_dispositions
from font_evidence import review_fonts
from interstitial_spacing import validate_interstitial_spacing
from measurement_fallback import eligible_code, validate_visual_fallback
from layout_visual_review import CODE as LAYOUT_VISUAL_CODE, validate_layout_visual_review
from pptx_delivery_shell import verify_shell

def verify_plot_table_pixels(finding, disposition, image_path, slide, scale):
    """Cross-check scanlines against the actual PNG, not supplied edge numbers."""
    from PIL import Image
    evidence=disposition.get('plot_table_edge_evidence',{})
    shapes={s.shape_id:s for s in slide.shapes}
    chart,table=[shapes[sid] for sid in finding['shape_ids']]
    with Image.open(image_path) as source:im=source.convert('RGB')
    # Slide width is stored by the caller; chart/table frame limits constrain rows.
    pp=evidence.get('pixels_per_pt')
    if type(pp) not in (int,float) or pp<=0:return 'Missing render pixel/point scale'
    expected=im.width/evidence.get('slide_width_pt',1)
    if abs(pp-expected)>1e-6:return 'Invalid edge measurement scale'
    edges=[]
    x0=max(0,math.floor((min(finding['plot_right_pt'],finding['table_right_pt'])-60*scale)*pp))
    x1=min(im.width,math.ceil((max((chart.left+chart.width)/12700,(table.left+table.width)/12700)+4*scale)*pp))
    for key,shape,expected_edge in [('chart_rows_px',chart,finding['plot_right_pt']),('table_rows_px',table,finding['table_right_pt'])]:
        rows=evidence.get(key,[])
        if len(rows)<3 or len(set(rows))!=len(rows):return 'At least three distinct scanlines per object are required'
        measured=[]
        for y in rows:
            if type(y) is not int or not max(0,shape.top/12700*pp)<=y<min(im.height,(shape.top+shape.height)/12700*pp):return 'Scanline is outside the actual object'
            # This path measures ordinary light-background charts/tables. Other
            # backgrounds remain unresolved instead of making up an edge.
            bg=im.getpixel((min(im.width-1,x1),y))
            points=[x for x in range(x0,x1) if max(abs(im.getpixel((x,y))[c]-bg[c]) for c in range(3))>20]
            if not points:return 'No measurable visible edge on this scanline'
            measured.append(max(points))
        if max(measured)-min(measured)>1:return 'Edge varies across scanlines; use stable actual boundaries'
        edge=statistics.median(measured)
        if abs(edge/pp-expected_edge)>6*scale:return 'Measured region is too far from the actual chart/table boundary'
        edges.append(edge)
    if abs(edges[0]-edges[1])>=max(2,.75*scale*pp):return 'Actual visible chart/table edges remain misaligned'
    return None

def white_container_visible_in_pixels(shape,image_path,slide_width_pt):
    """Prove an opaque white card against its actual surrounding page pixels.
    No author role/flag grants visibility. Uncertain contours remain pending.
    """
    if image_path is None or type(slide_width_pt) not in (int,float) or slide_width_pt<=0:return False
    try:
        from PIL import Image
        from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
        if shape.auto_shape_type not in (MSO_AUTO_SHAPE_TYPE.RECTANGLE,MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE) or abs(shape.rotation)>1e-6:return False
        fills=shape._element.xpath('./p:spPr/a:solidFill')
        if len(fills)!=1 or len(fills[0])!=1:return False
        color=fills[0][0]
        if color.tag.rsplit('}',1)[-1]!='srgbClr' or color.get('val','').upper()!='FFFFFF':return False
        if any(c.tag.rsplit('}',1)[-1]!='alpha' or int(c.get('val','0'))!=100000 for c in color):return False
        with Image.open(image_path) as opened:im=opened.convert('RGB')
        pp=im.width/slide_width_pt
        l,t,r,b=[v/12700*pp for v in (shape.left,shape.top,shape.left+shape.width,shape.top+shape.height)]
        if min(r-l,b-t)<12 or l<3 or t<3 or r+3>=im.width or b+3>=im.height:return False
        for side in ('left','right','top','bottom'):
            pairs=[]
            for fraction in (.25,.5,.75):
                x=int(l+(r-l)*fraction);y=int(t+(b-t)*fraction)
                if side=='left':inside,outside=(math.ceil(l)+2,y),(math.floor(l)-2,y)
                elif side=='right':inside,outside=(math.floor(r)-3,y),(math.ceil(r)+2,y)
                elif side=='top':inside,outside=(x,math.ceil(t)+2),(x,math.floor(t)-2)
                else:inside,outside=(x,math.floor(b)-3),(x,math.ceil(b)+2)
                a,c=im.getpixel(inside),im.getpixel(outside)
                pairs.append(max(abs(v-255) for v in a)<=5 and max(abs(a[k]-c[k]) for k in range(3))>=12)
            if not all(pairs):return False
        return True
    except (AttributeError,ValueError,TypeError,OSError,IndexError):return False


def validate_region_contract(finding, disposition, slide, scale, image_path=None, slide_width_pt=None):
    """Validate a relationship, never a waiver of the relationship's geometry."""
    contract=disposition.get('relation_contract',{})
    ids=finding['shape_ids']
    if set(contract.get('shape_ids',[]))!=set(ids):return 'Relation contract must cover exactly the flagged objects'
    shapes={s.shape_id:s for s in slide.shapes}
    if any(sid not in shapes for sid in ids):return 'Unknown relation member'
    bounds=[[s.left/12700,s.top/12700,s.width/12700,s.height/12700] for s in (shapes[sid] for sid in ids)]
    kind=contract.get('kind');anchors=finding.get('native_anchors',[])
    if kind in ('different_alignment_roles','common_visual_anchor'):
        if kind=='different_alignment_roles' and (len(set(anchors))<2 or any(a not in ('left','center','right') for a in anchors)):return 'Native paragraph alignment does not support these different roles; use common_visual_anchor for same-mode optical compensation'
        anchor=contract.get('common_visual_anchor')
        if anchor not in ('left','center','right'):return 'Different paragraph modes do not exempt a stack: declare and verify a common actual visual anchor'
        boxes=finding.get('ink_bounds_px');threshold=finding.get('threshold_px')
        if not boxes or len(boxes)!=len(ids) or not threshold:return 'Actual glyph bounds uncertain: perform local optical repair/reliable measurement and rescan; no role-based waiver'
        positions=[{'left':b[0],'center':(b[0]+b[2])/2,'right':b[2]}[anchor] for b in boxes]
        if max(positions)-min(positions)>=threshold:return 'Title/value/explanation have no shared visible anchor; repair the whole stack and rerender'
    elif kind=='spanning_region':
        if not any(a[2]>=1.5*b[2] and a[0]<=b[0]+.5 and a[0]+a[2]>=b[0]+b[2]-.5 for i,a in enumerate(bounds) for j,b in enumerate(bounds) if i!=j):
            return 'No actual spanning geometry; cannot rename an ordinary stack as a summary'
    elif kind=='hierarchy_indent':
        levels=contract.get('levels',{});indent=contract.get('indent_pt')
        if anchors and any(a!='left' for a in anchors):return 'Hierarchy indentation requires left-aligned members'
        if type(indent) not in (int,float) or not math.isfinite(indent) or not 6*scale<=indent<=48*scale:return 'Invalid hierarchy step'
        if set(levels)!=set(map(str,ids)) or any(type(v) is not int or not 0<=v<=5 for v in levels.values()) or len(set(levels.values()))<2:return 'Each member needs an explicit valid hierarchy level'
        bases=[box[0]-levels[str(sid)]*indent for sid,box in zip(ids,bounds)]
        if max(bases)-min(bases)>1.5*scale:return 'Actual indentation does not match the claimed hierarchy'
    elif kind=='separate_visible_containers':
        mapping=contract.get('containers',{})
        if set(mapping)!=set(map(str,ids)) or len(set(mapping.values()))<2:return 'Distinct actual containers are required'
        container_bounds={}
        for sid,box in zip(ids,bounds):
            c=shapes.get(mapping[str(sid)])
            if c is None:return 'Missing actual container'
            visible=False
            try:visible=c.fill.type==MSO_FILL_TYPE.SOLID and str(c.fill.fore_color.rgb) not in ('FFFFFF','None')
            except (AttributeError,ValueError,TypeError):pass
            try:visible=visible or c.line.fill.type==MSO_FILL_TYPE.SOLID
            except (AttributeError,ValueError,TypeError):pass
            if not visible:
                visible=white_container_visible_in_pixels(c,image_path,slide_width_pt)
            # Transparency is equally relevant to external and self containers.
            paints=c._element.xpath('./p:spPr/a:solidFill | ./p:spPr/a:ln/a:solidFill')
            if paints and all(any(int(a.get('val','0'))<50000 for a in paint.xpath('.//a:alpha')) for paint in paints):
                visible=False
            cb=[c.left/12700,c.top/12700,c.width/12700,c.height/12700]
            if not visible or cb[0]>box[0]+.5 or cb[1]>box[1]+.5 or cb[0]+cb[2]<box[0]+box[2]-.5 or cb[1]+cb[3]<box[1]+box[3]-.5:return 'Container must be visible and really contain the member'
            if c.shape_id==sid:
                solid=c._element.xpath('./p:spPr/a:solidFill')
                if not solid or not c.has_text_frame or any(int(a.get('val','0'))<50000 for a in c._element.xpath('./p:spPr/a:solidFill//a:alpha')):
                    return 'Self-container must be a real opaque filled text component, not an invisible frame'
            container_bounds[c.shape_id]=cb
        cb=list(container_bounds.values())
        for i,a in enumerate(cb):
            for b in cb[i+1:]:
                if min(a[0]+a[2],b[0]+b[2])-max(a[0],b[0])>.5*scale and min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1])>.5*scale:
                    return 'Claimed independent containers overlap; this does not establish separate modules'
    else:return 'Unsupported relationship: repair the page or provide a verifiable structural contract'
    if not contract.get('visible_relation_explanation'):return 'Explain the actual visible relationship, not merely its type'
    return None

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest().upper()

def verified_optical_anchor(finding, disposition):
    contract=disposition.get('alignment_contract',{})
    anchor=contract.get('anchor');ids=contract.get('shape_ids',[])
    if anchor not in ('left','center','right') or set(ids)!=set(finding.get('shape_ids',[])) or len(ids)!=len(set(ids)):return False
    boxes=finding.get('ink_bounds_px');threshold=finding.get('threshold_px')
    if not boxes or len(boxes)!=len(ids) or not threshold:return False
    values=[{'left':b[0],'center':(b[0]+b[2])/2,'right':b[2]}[anchor] for b in boxes]
    return max(values)-min(values)<threshold

def validate_center_alignment_review(finding,disposition,image_path):
    """A reliable visible-center mismatch cannot be signed away with a role."""
    if finding.get('measurement_status')=='measured_misalignment':
        return 'Visible hosted text is misaligned; reposition the complete group and rerender'
    if finding.get('measurement_status') not in ('measured_aligned','manual_review_required'):
        return 'Unknown center measurement state'
    c=disposition.get('center_alignment_contract',{})
    if c.get('chart_audit_path')!=finding.get('chart_audit_path') or c.get('reference')!='visible_host_or_hole':
        return 'Center review must bind the actual visible host/hole, not a frame or PlotArea'
    ids=c.get('text_audit_paths')
    if not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)!=set(finding.get('text_audit_paths',[])):
        return 'Center review must include the complete hosted text group'
    for key in ('center_observation','internal_group_observation'):
        if not isinstance(c.get(key),str) or len(c[key].strip())<20:
            return 'Center review needs specific center and internal group observations'
    try:
        from PIL import Image,ImageChops
        detail=disposition.get('detail_evidence',{});box=detail.get('crop_box_px');expected=finding.get('crop_box_px')
        if not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box):return 'Center review needs its actual local crop coordinates'
        if not isinstance(expected,list) or len(expected)!=4:return 'Center finding lacks a verifiable local inspection region'
        with Image.open(image_path) as opened,Image.open(detail['path']) as local:
            im=opened.convert('RGB');crop=local.convert('RGB')
            if not 0<=box[0]<box[2]<=im.width or not 0<=box[1]<box[3]<=im.height or box==[0,0,im.width,im.height]:return 'Center local review cannot be an empty/unrelated/full-page substitute'
            if box[0]>expected[0] or box[1]>expected[1] or box[2]<expected[2] or box[3]<expected[3]:return 'Center crop omits visible host or text group context'
            actual=im.crop(box)
            if crop.size!=actual.size or ImageChops.difference(crop,actual).getbbox():return 'Center crop is not current rendered pixels'
    except (KeyError,ValueError,TypeError,OSError) as exc:return 'Invalid center crop evidence: '+str(exc)
    if finding['measurement_status']=='manual_review_required':
        return 'Visible host contour or hosted text ink is unmeasurable'
    delta=finding.get('delta_px');tolerance=finding.get('tolerance_px')
    if not isinstance(delta,list) or len(delta)!=2 or type(tolerance) not in (int,float) or tolerance<=0:return 'Missing reliable center measurement'
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>=tolerance for v in delta):
        return 'Visible hosted text is misaligned; reposition the complete group and rerender'
    return None

def validate_gap_audit(pptx,review,render,render_dir):
    """Recompute raw gap reports; close only bound, measured visual disputes."""
    from audit_layout_gaps import audit as audit_gaps
    from visible_chart_spacing import measure_relation,discover_relations
    from PIL import Image,ImageChops
    issues=[];resolved=[];bound_files=[]
    def require(ok,message):
        if not ok:raise ValueError(message)
    def load_bound(item,path_key,hash_key):
        path=Path(item.get(path_key,''));require(path.is_file(),'Missing gap evidence file: '+path_key)
        value=digest(path);require(item.get(hash_key)==value,'Stale gap evidence: '+path_key);bound_files.append((path,value))
        return json.loads(path.read_text(encoding='utf-8-sig'))
    try:
        evidence=review.get('gap_audit');require(isinstance(evidence,dict),'Final review needs gap_audit bound to the original layout and raw gap report')
        spec=load_bound(evidence,'layout_path','layout_sha256');raw=load_bound(evidence,'report_path','report_sha256')
        fresh=audit_gaps(pptx,spec)
        require(raw==fresh,'Raw gap report differs from current independent audit; do not delete or rewrite its issues')
        require(raw.get('full_deck') is True,'Gap evidence must cover the full candidate')
        # Discover from native objects even when the author's frame-based plan
        # passes or omits/splits the chart/caption relationship entirely.
        derived=discover_relations(pptx,render,render_dir)
        def native_ids(row):return tuple(tuple(b.get('shape_ids',[])) for b in row.get('blocks',[]))
        expected_rows={(r['slide'],r['name']):dict(r) for r in derived}
        require(len(expected_rows)==len(derived),'Duplicate independent chart-spacing relationship')
        wanted={key:[] for key in expected_rows}
        for key,row in expected_rows.items():
            matching=[r for r in raw['comparisons'] if r['slide']==row['slide'] and r['axis']=='vertical' and native_ids(r)==native_ids(row)]
            if matching:row['minimum_gap_pt']=max([row['minimum_gap_pt']]+[r['minimum_gap_pt'] for r in matching])
        layout_reviews=evidence.get('layout_reviews',[])
        require(isinstance(layout_reviews,list),'layout_reviews must be an array')
        layout_index={r.get('finding_id'):r for r in layout_reviews}
        require(len(layout_index)==len(layout_reviews),'Duplicate original gap issue reviews')
        used_layout=set();prs=Presentation(pptx)
        for issue_number,issue in enumerate(raw['issues'],1):
            require(issue.get('reason') in ('gap_below_minimum_or_overlap','peer_gap_imbalance','unverified_multi_shape_block'),'Input/coverage gap audit error cannot be replaced by a visual layout result')
            raw_rows=[r for r in raw['comparisons'] if r['slide']==issue['slide'] and r['name']==issue['name']]
            require(len(raw_rows)==1,'Raw gap issue does not identify one complete comparison')
            finding_id=f'gap-raw:{issue_number}'
            if finding_id in layout_index:
                item=layout_index[finding_id];finding={'id':finding_id,'slide':issue['slide'],'reason':'original_gap_layout_rule',
                                                      'original_issue':issue,'original_comparison':raw_rows[0]}
                errors=[json.dumps(issue,ensure_ascii=False,sort_keys=True)]
                error,resolution=validate_layout_visual_review(finding,item,render_dir/f"slide-{issue['slide']:02}.png",prs.slides[issue['slide']-1],render,review.get('author_id'),errors)
                require(error is None,error);resolved.append(resolution);used_layout.add(finding_id)
                continue
            matching=[key for key,row in expected_rows.items() if row['slide']==issue['slide'] and native_ids(row)==native_ids(raw_rows[0])]
            require(len(matching)==1,'Raw gap defect has no independently discovered complete chart/caption relationship; repair or provide another verified adapter')
            wanted[matching[0]].append(issue)
        require(set(layout_index)==used_layout,'Unused or invented original gap layout review')
        done=evidence.get('visible_reviews',[]);require(isinstance(done,list),'visible_reviews must be an array')
        keys=[(r.get('slide'),r.get('comparison_name')) for r in done]
        require(len(keys)==len(set(keys)) and set(keys)==set(wanted),'Every independently discovered chart-spacing group needs a pixel/visual review, even if frame gaps passed; no missing or unused exemptions')
        prs=Presentation(pptx)
        for item in done:
            n,name=item['slide'],item['comparison_name']
            measured=measure_relation(pptx,render,render_dir,n,expected_rows[n,name])
            recorded=load_bound(item,'measurement_path','measurement_sha256')
            require(recorded==measured,'Visible gap measurement must equal the current independent pixel calculation')
            state=measured.get('measurement_status')
            if item.get('visual_fallback',{}).get('code')==LAYOUT_VISUAL_CODE:
                require(state in ('measured_valid_pending_visual_review','manual_review_required','measured_defect'),'Invalid/missing native gap evidence cannot be replaced by visual acceptance')
                finding={**measured,'id':f'gap-p{n}-{name}','reason':'native_chart_spacing_rule_result','original_raw_issues':wanted[n,name]}
                errors=[json.dumps({'measurement_status':state,'visible_gaps_pt':measured.get('visible_gaps_pt'),
                                    'minimum_gap_pt':expected_rows[n,name].get('minimum_gap_pt'),'defects':measured.get('defects'),
                                    'measurement_limitation':measured.get('measurement_limitation')},ensure_ascii=False,sort_keys=True)]
                error,resolution=validate_layout_visual_review(finding,item,render_dir/f'slide-{n:02}.png',prs.slides[n-1],render,review.get('author_id'),errors)
                require(error is None,error)
                resolved.append({'slide':n,'comparison_name':name,'raw_issues':wanted[n,name],
                                 'measurement_sha256':item['measurement_sha256'],**resolution})
                continue
            require(state in ('measured_valid_pending_visual_review','manual_review_required'),'Actual visible gap defect or invalid native relationship must be repaired')
            require(item.get('decision')=='verified_in_context' and item.get('returned_to_full_page') is True,'Visible gap relationship is still pending actual local/full-page inspection')
            require(isinstance(item.get('observation'),str) and len(item['observation'].strip())>=20,'Visible gap resolution needs a specific observation')
            image=render_dir/f'slide-{n:02}.png';detail=item.get('detail_evidence',{});crop=Path(detail.get('path',''))
            require(crop.is_file() and detail.get('sha256')==digest(crop),'Missing/stale local gap evidence')
            bound_files.append((crop,digest(crop)))
            require(item.get('image_sha256')==digest(image)==measured['image_sha256']==detail.get('source_image_sha256'),'Visible gap evidence is not bound to the current page')
            box=detail.get('crop_box_px');expected=measured.get('crop_box_px')
            require(isinstance(box,list) and len(box)==4 and all(type(v) is int for v in box),'Invalid local gap crop coordinates')
            require(isinstance(expected,list) and len(expected)==4,'Unresolved gap context location')
            with Image.open(image) as source,Image.open(crop) as local:
                source=source.convert('RGB');local=local.convert('RGB')
                require(0<=box[0]<box[2]<=source.width and 0<=box[1]<box[3]<=source.height,'Gap crop outside current page')
                require(box!=[0,0,source.width,source.height],'A full page does not replace local gap inspection')
                require(box[0]<=expected[0] and box[1]<=expected[1] and box[2]>=expected[2] and box[3]>=expected[3],'Local gap crop omits the complete three-object relationship')
                actual=source.crop(box);require(local.size==actual.size and ImageChops.difference(local,actual).getbbox() is None,'Gap crop is not exact current rendered pixels')
            if state=='manual_review_required':
                finding={**measured,'id':f'gap-p{n}-{name}','reason':'native_chart_spacing_unmeasurable'}
                error,resolution=validate_visual_fallback(finding,item,'chart_gap','Visible chart spacing boundaries are unmeasurable',image,prs.slides[n-1],render,review.get('author_id'))
                require(error is None,error)
            else:
                require('visual_fallback' not in item,'Reliable pixel measurement does not need an author-declared fallback')
                resolution={'resolution':'pixel_geometry_verified_pending_signoff'}
            resolved.append({'slide':n,'comparison_name':name,'raw_issues':wanted[n,name],
                             'visible_gaps_pt':measured.get('visible_gaps_pt'),'measurement_sha256':item['measurement_sha256'],
                             'image_sha256':item['image_sha256'],**resolution})
        for path,original_hash in bound_files:require(digest(path)==original_hash,'Gap evidence changed during validation')
    except (ValueError,TypeError,KeyError,AttributeError,OSError) as exc:
        issues.append({'reason':'Gap audit unresolved: '+str(exc)})
    return issues,resolved

def check_visual_passes(review, render_dir, sha, count, findings=None, coverage_pages=None):
    issues=[]
    passes=review.get('visual_passes',[])
    modes=[p.get('mode') for p in passes]
    if sorted(m for m in modes if isinstance(m,str))!=['content','layout'] or len(passes)!=2:
        return [{'reason':'Two distinct final visual passes are required: content and layout'}]
    for p in passes:
        if p.get('sha256')!=sha:issues.append({'reason':'Visual pass uses a stale PPTX hash'})
        pages=p.get('pages',[]);numbers=[r.get('slide') for r in pages]
        if any(type(n) is not int for n in numbers) or sorted(numbers)!=list(range(1,count+1)):
            issues.append({'reason':'Visual pass must cover every slide exactly once','mode':p['mode']});continue
        required=('readability','chart_semantics','language','quantity_unit_pairing') if p['mode']=='content' else (
            'row_alignment','column_alignment','whitespace','containment_and_connectors','page_number','rules_crosscheck','optical_edges')
        for row in pages:
            image=render_dir/f"slide-{row['slide']:02}.png"
            if not image.is_file() or row.get('image_sha256')!=digest(image):
                issues.append({'slide':row['slide'],'reason':'Visual pass image missing or stale'})
            if row.get('result')!='pass' or row.get('normal_size_viewed') is not True:
                issues.append({'slide':row['slide'],'reason':'Final visual pass not complete'})
            checks=row.get('checks',{})
            if p['mode']=='layout':
                expected_ids={f['id'] for f in (findings or []) if f['slide']==row['slide']}
                checked_ids=row.get('rule_findings_reviewed')
                if not isinstance(checked_ids,list) or len(checked_ids)!=len(set(checked_ids)) or set(checked_ids)!=expected_ids:
                    issues.append({'slide':row['slide'],'reason':'Visual-rule crosscheck omits or invents page findings'})
                targets={o['shape_id'] for page in (coverage_pages or []) if page['slide']==row['slide'] for o in page.get('optical_review_targets',[])}
                optical=row.get('optical_targets_reviewed')
                if not isinstance(optical,list) or len(optical)!=len(set(optical)) or set(optical)!=targets:
                    issues.append({'slide':row['slide'],'reason':'Optical review must cover every object, including excluded roles and internal visuals'})
            for key in required:
                value=checks.get(key)
                if not isinstance(value,str) or not value.strip() or value.strip().lower() in ('pass','passed','ok','n/a','通过','无','不适用'):
                    issues.append({'slide':row['slide'],'reason':'Missing specific visual observation','check':key,'mode':p['mode']})
    return issues

def verify(pptx, coverage_path, review, render_dir):
    lock=review.get('skill_lock',{})
    lock_path=Path(lock.get('path',''))
    if not lock_path.is_file() or lock.get('sha256')!=digest(lock_path):raise ValueError('Final review needs the exact frozen Skill lock file/hash')
    state=check_skill_state(lock_path)
    if state['changed_files']:raise ValueError('Skill changed after the run was frozen; pause, create a new revision and repeat applicable checks: '+', '.join(state['changed_files']))
    coverage=json.loads(coverage_path.read_text(encoding='utf-8-sig'))
    sha=digest(pptx);issues=[];visual_resolutions=[];layout_review_candidates=[]
    # Recompute rather than trusting an Agent-edited list with removed findings.
    render=json.loads((render_dir/'audit.json').read_text(encoding='utf-8-sig'))
    validate_render_evidence(pptx,render,render_dir,review=review,resolutions=visual_resolutions)
    if coverage!=rescan(pptx,render):raise ValueError('Coverage differs from current independent scan; findings may not be removed or rewritten')
    prs=Presentation(pptx);scale=prs.slide_height/12700/540
    if coverage.get('sha256')!=sha or review.get('sha256')!=sha:raise ValueError('PPTX hash mismatch')
    if review.get('coverage_sha256')!=digest(coverage_path):raise ValueError('Review does not bind this exact coverage report')
    if coverage.get('status') not in ('review_required','coverage_pass_pending_visual_review'):raise ValueError('Invalid coverage status')
    for page in coverage['pages']:
        image=render_dir/f"slide-{page['slide']:02}.png"
        if not image.is_file() or page.get('raster_sha256')!=digest(image):raise ValueError('Review image differs from the image measured by coverage')
    items=review.get('items',[]);ids=[x.get('finding_id') for x in items]
    wanted={x['id'] for x in coverage['findings']}
    if len(ids)!=len(set(ids)) or set(ids)!=wanted:raise ValueError('Missing, duplicate, or extra finding dispositions')
    index={x['finding_id']:x for x in items}
    for f in coverage['findings']:
        r=index[f['id']];reason=f['reason'];image=render_dir/f"slide-{f['slide']:02}.png"
        def fail(msg):issues.append({'id':f['id'],'reason':msg})
        layout_failures=[]
        def layout_fail(msg):layout_failures.append(msg)
        generic_visual=r.get('visual_fallback',{}).get('code')==LAYOUT_VISUAL_CODE
        fallback_used=False
        def resolve_measurement(stage,error):
            nonlocal fallback_used
            if generic_visual:return error
            if eligible_code(stage,error) is None or 'visual_fallback' not in r:return error
            fallback_used=True
            unresolved,resolution=validate_visual_fallback(f,r,stage,error,image,prs.slides[f['slide']-1],render,review.get('author_id'))
            if resolution:visual_resolutions.append(resolution)
            return unresolved
        if r.get('decision')!='verified_in_context':fail('No waiver/skip/automatic-pass decisions allowed')
        if r.get('no_visible_collision_or_alignment_defect') is False:fail('Disposition reports an actual visible layout defect; continue repair')
        if not image.is_file() or r.get('image_sha256')!=digest(image):fail('Missing or mismatched actual page image')
        for field in ('criterion','observation','object_relation'):
            if not isinstance(r.get(field),str) or not r[field].strip():fail('Missing specific '+field)
        values=r.get('measurements',{})
        if not isinstance(values,dict) or not values:fail('No measurement evidence')
        # No smaller top_delta may override a failing center criterion.
        if reason=='rendered_row_text_misaligned':
            if r.get('object_relation')!='data-positioned labels':
                layout_fail('Actual row-center mismatch must be repaired and rescanned; top alignment cannot waive it')
        if reason=='rendered_column_text_anchor_mismatch':
            # A whole stack may use a common center/right anchor, but its ACTUAL
            # values must satisfy the same tolerance for every member.
            anchor=r.get('alignment_contract',{}).get('anchor')
            field={'center':'center_delta_pt','right':'right_delta_pt'}.get(anchor)
            contract_ids=r.get('alignment_contract',{}).get('shape_ids',[])
            verified_alternative=(field is not None and set(contract_ids)==set(f['shape_ids'])
                                  and f.get(field,float('inf'))<=2*scale)
            if not verified_alternative and not verified_optical_anchor(f,r) and r.get('object_relation')!='data-positioned labels':
                layout_fail('Whole stack has no verified common anchor; repair and rescan')
        if reason=='rendered_ink_column_misaligned':
            anchor=r.get('alignment_contract',{}).get('anchor')
            field={'center':'center_delta_px','right':'right_delta_px'}.get(anchor)
            ids=r.get('alignment_contract',{}).get('shape_ids',[])
            verified=(field is not None and set(ids)==set(f['shape_ids']) and f[field]<f['threshold_px'])
            if not verified and r.get('object_relation')!='data-positioned labels':
                layout_fail('Visible glyph edges disagree despite coordinates; optical repair and rescan required')
        if reason=='rendered_ink_row_misaligned' and r.get('object_relation')!='data-positioned labels':
            layout_fail('Visible glyph centers disagree; coordinate tolerance cannot waive optical misalignment')
        if reason=='chart_sidebar_vertical_balance':
            actual=f.get('plot_center_delta_pt')
            plot_aligned=type(actual) in (int,float) and math.isfinite(actual) and abs(actual)<=6*scale
            if not plot_aligned and r.get('object_relation')!='data-positioned labels':
                layout_fail('Layout anchor/balance mismatch must be repaired and rescanned; role descriptions cannot waive it')
        if reason=='chart_table_visible_edge_requires_review':
            if f['delta_pt']>2*scale:
                proof=r.get('plot_table_edge_evidence',{})
                if proof.get('slide_width_pt')!=prs.slide_width/12700:
                    layout_fail('Stacked chart/table edge mismatch requires actual-pixel scanline evidence or repair')
                else:
                    error=verify_plot_table_pixels(f,r,image,prs.slides[f['slide']-1],scale)
                    if error:
                        error=resolve_measurement('plot_table',error)
                        if error:layout_fail(error)
        if r.get('object_relation')=='data-positioned labels':
            trace=r.get('data_mapping',{})
            path=Path(trace.get('path',''))
            if not path.is_file() or trace.get('sha256')!=digest(path) or not trace.get('formula') or not trace.get('object_ids'):
                fail('Data-position exception needs source mapping file/hash/formula/object IDs; a role name is insufficient')
            expected_ids=set(f.get('shape_ids',[]))
            if expected_ids and not expected_ids.issubset(set(trace.get('object_ids',[]))):
                fail('Data mapping does not cover the flagged objects')
        if reason=='axis_stack_spanning_region_review':
            relation=r.get('axis_region_contract',{})
            if relation.get('kind')!='linear_axis_and_spanning_text' or relation.get('spanning_text_id')!=f['spanning_text_id']:
                layout_fail('Actual axis/full-width relationship must be explicitly reviewed')
            for key in ('axis_tick_ids','matched_grid_ids'):
                values=relation.get(key,[])
                if not isinstance(values,list) or len(values)!=len(set(values)) or set(values)!=set(f[key]):
                    layout_fail('Axis-region contract must include every actual tick and matched grid line')
        if reason=='text_region_relation_requires_review':
            error=validate_region_contract(f,r,prs.slides[f['slide']-1],scale,image,prs.slide_width/12700)
            if error:
                error=resolve_measurement('region',error)
                if error:layout_fail(error)
        if reason in ('centered_text_visible_host_misaligned','centered_text_visible_host_review'):
            error=validate_center_alignment_review(f,r,image)
            if error:
                error=resolve_measurement('center',error)
                if error:layout_fail(error)
        if not generic_visual and (reason in ('rendered_text_rectangles_overlap','connector_crosses_or_touches_text',
                      'nonstraight_connector_path_requires_review','connector_geometry_unavailable',
                      'multiline_or_mixed_font_row_alignment_requires_review','glyph_ink_alignment_requires_review',
                      'mixed_typography_optical_review','text_region_relation_requires_review',
                      'cross_page_title_ink_requires_review','cross_page_title_ink_misaligned',
                      'chart_table_visible_edge_requires_review','axis_stack_spanning_region_review',
                      'centered_text_visible_host_misaligned','centered_text_visible_host_review') or (reason=='rendered_column_text_anchor_mismatch' and verified_optical_anchor(f,r)) or (reason=='chart_sidebar_vertical_balance' and plot_aligned) or (reason=='header_body_boundary_review' and r.get('spacing_contract'))):
            if r.get('object_relation')=='data-positioned labels':
                fail('Data position cannot waive a collision, unreadable text, or an unmeasured alignment')
            detail=r.get('detail_evidence',{});path=Path(detail.get('path',''))
            if not path.is_file() or detail.get('sha256')!=digest(path) or detail.get('source_image_sha256')!=r.get('image_sha256'):
                fail('This geometry candidate requires current local render evidence and return-to-full-page review')
            if r.get('returned_to_full_page') is not True:fail('Local detail was not rechecked at full-page scale')
            if r.get('no_visible_collision_or_alignment_defect') is not True:
                fail('Visible collision or alignment uncertainty remains unresolved')
        if reason=='header_body_boundary_review':
            # A real standalone cover has no chart/conclusion pair. It still
            # requires quantified whole-page composition evidence, not a waiver.
            if f['slide']==1 and r.get('object_relation')=='standalone cover composition':
                if not all(k in values for k in ('left_content_bounds_pt','right_content_bounds_pt','title_to_content_gap_pt','content_to_bottom_gap_pt')):
                    layout_fail('Cover requires both content bounds and title/bottom spacing evidence')
            elif all(isinstance(values.get(k),(int,float)) and math.isfinite(values[k]) and values[k]>=0 for k in ('above_visual_gap_pt','below_visual_gap_pt')):
                a,b=values['above_visual_gap_pt'],values['below_visual_gap_pt']
                if abs(a-b)>max(3*scale,(a+b)/2*.2):
                    error=validate_interstitial_spacing(f,r,prs.slides[f['slide']-1],render,scale)
                    if error:
                        error=resolve_measurement('interstitial',error)
                        if error:layout_fail('Unbalanced or unverified whitespace: '+error)
            else:
                layout_fail('Missing measured above_visual_gap_pt or below_visual_gap_pt')
        if layout_failures or generic_visual:
            original_errors=layout_failures or ['Original layout finding requires visual reconciliation: '+reason]
            layout_review_candidates.append({'finding_id':f['id'],'original_finding':f,'rule_failures':original_errors})
        if generic_visual:
            fallback_used=True
            error,resolution=validate_layout_visual_review(f,r,image,prs.slides[f['slide']-1],render,review.get('author_id'),original_errors)
            if resolution:visual_resolutions.append(resolution)
            if error:
                for msg in original_errors:fail(msg)
                fail(error)
        else:
            for msg in layout_failures:fail(msg)
        if 'visual_fallback' in r and not fallback_used:
            fail('Unused/ineligible visual fallback: no author-declared exemption is accepted')
    issues.extend(verify_connections(prs,review,render_dir,render=render,resolutions=visual_resolutions))
    gap_issues,gap_resolutions=validate_gap_audit(pptx,review,render,render_dir)
    issues.extend(gap_issues)
    issues.extend(validate_manual_dispositions(render,review,render_dir))
    issues.extend(review_fonts(pptx,render,review))
    issues.extend(check_visual_passes(review,render_dir,sha,coverage['slide_count'],coverage['findings'],coverage['pages']))
    # Delivery shell is a final hard gate, outside all layout/visual waivers.
    shell_errors=verify_shell(pptx,render_dir/'slide-01.png')
    if shell_errors:
        quote=lambda value: "'"+str(value).replace("'","''")+"'"
        # Preparation must reproduce the renderer's export resolution exactly;
        # changing it can change antialiasing after thumbnail downsampling.
        from PIL import Image
        try:
            with Image.open(render_dir/'slide-01.png') as first_image:
                width_argument=' -Width '+str(first_image.width)
        except (OSError,ValueError):
            width_argument=''
        recovery=("Finish strip_pptx_metadata.py first, then run PowerShell: & "
                  +quote(Path(__file__).with_name('prepare_pptx_delivery.ps1'))
                  +' -InputPptx '+quote(Path(pptx).resolve())
                  +' -OutputDir '+quote(render_dir.parent/'shell-prep')
                  +' -PythonExe '+quote(sys.executable)
                  +width_argument
                  +'\nThen rerun the read-only full render and rebuild current audit/review evidence. '
                   'Do not strip metadata after preparation; that intentionally removes the prepared thumbnail.')
        issues.extend({'reason':error,'stage':'delivery_shell','recovery':recovery} for error in shell_errors)
    if digest(pptx)!=sha:issues.append({'reason':'PPTX changed during evidence validation'})
    if check_skill_state(lock_path)['changed_files']:issues.append({'reason':'Skill changed during evidence validation'})
    result={'sha256':sha,'status':'failed' if issues else 'evidence_complete_pending_visual_signoff','issues':issues}
    if visual_resolutions:result['visual_resolutions']=visual_resolutions
    if layout_review_candidates:result['layout_review_candidates']=layout_review_candidates
    if gap_resolutions:result['visible_gap_resolutions']=gap_resolutions
    return result

def main():
    ap=argparse.ArgumentParser()
    for n in ('pptx','coverage','review','render_dir','report'):ap.add_argument(n,type=Path)
    a=ap.parse_args()
    try:r=verify(a.pptx,a.coverage,json.loads(a.review.read_text(encoding='utf-8-sig')),a.render_dir)
    except Exception as exc:r={'status':'failed','issues':[{'reason':str(exc)}]}
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
    print(r['status']);return 2 if r['issues'] else 0

if __name__=='__main__':raise SystemExit(main())
