"""Conservative component candidates; actual local/full-page review closes them."""
import math,re,statistics
from pptx.enum.dml import MSO_COLOR_TYPE,MSO_FILL_TYPE
from pptx.enum.text import PP_ALIGN

REASONS={'table_alignment_consistency_review','table_alignment_measurement_required',
         'chart_legend_clearance_review','chart_legend_geometry_required','chart_label_geometry_required',
         'interstitial_module_spacing_review','filled_text_color_review'}
REASONS.update({'floating_annotation_review','container_text_vertical_balance_review',
                'container_text_union_measurement_required','page_content_low_review','title_entry_position_review',
                'effective_content_entry_gap_review','text_container_excess_space_review','section_proximity_inversion_review'})

def numeric(text):
    return bool(re.fullmatch(r'[+−–-]?\d[\d,.]*(?:\s*(?:%|‰|mm|cm|m|s|ms|px|kWh|W|°))?',text.strip()))

def box(shape):return [shape.left/12700,shape.top/12700,(shape.left+shape.width)/12700,(shape.top+shape.height)/12700]
def finite_box(b):return isinstance(b,(list,tuple)) and len(b)==4 and all(type(x) in (int,float) and math.isfinite(x) for x in b) and b[2]>b[0] and b[3]>b[1]
def rgb(color):
    # Evidence must compare identically before and after JSON serialization.
    try:return list(color.rgb) if color.type==MSO_COLOR_TYPE.RGB else None
    except (ValueError,AttributeError):return None
def contrast(a,b):
    def lum(c):
        v=[x/255 for x in c];v=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in v]
        return sum(x*w for x,w in zip(v,(.2126,.7152,.0722)))
    x,y=sorted((lum(a),lum(b)));return (y+.05)/(x+.05)

def scan(slide,n,render,scale=1):
    out=[]
    def add(reason,**kw):out.append({'reason':reason,**kw})
    records={r.get('audit_path'):r for r in render.get('text_records',[]) if r.get('slide')==n}
    def visit(shapes,parent='',owner=None):
        for s in shapes:
            path=(parent+'/group/' if parent else '')+str(s.shape_id);sid=owner or s.shape_id
            if hasattr(s,'shapes'):visit(s.shapes,path,sid)
            if s.has_table:
                rows=[];unknown=[]
                for ri,row in enumerate(s.table.rows,1):
                    cells=[]
                    for ci,cell in enumerate(row.cells,1):
                        if cell.is_spanned or not cell.text.strip():continue
                        cp=f'{path}/table/{ri}/{ci}';rec=records.get(cp,{})
                        aligns={p.alignment for p in cell.text_frame.paragraphs if p.text.strip()}
                        if None in aligns:
                            effective=rec.get('paragraph_alignment')
                            aligns.discard(None)
                            if effective in (1,2,3):aligns.add({1:PP_ALIGN.LEFT,2:PP_ALIGN.CENTER,3:PP_ALIGN.RIGHT}[effective])
                            else:unknown.append(cp)
                        cells.append({'audit_path':cp,'row':ri,'column':ci,'role':'number' if numeric(cell.text) else 'text',
                                      'alignment':sorted(int(a) for a in aligns),'vertical_anchor':str(cell.vertical_anchor),
                                      'margins_pt':[cell.margin_left/12700,cell.margin_right/12700,cell.margin_top/12700,cell.margin_bottom/12700]})
                    rows.append(cells)
                mismatches=[]
                # Compare equivalent roles within a row, and each body column.
                groups=[g for cells in rows for role in ('text','number') if len(g:=[c for c in cells if c['role']==role])>1]
                groups += [[c for row in rows[1:] for c in row if c['column']==ci] for ci in range(1,len(s.table.columns)+1)]
                for group in groups:
                    if len(group)>1 and (len({tuple(c['alignment']) for c in group})>1 or len({c['vertical_anchor'] for c in group})>1 or any(max(c['margins_pt'][k] for c in group)-min(c['margins_pt'][k] for c in group)>2*scale for k in range(4))):
                        mismatches.append(group)
                if mismatches:add('table_alignment_consistency_review',shape_ids=[sid],audit_path=path,cell_groups=mismatches)
                if unknown:add('table_alignment_measurement_required',shape_ids=[sid],audit_path=path,audit_paths=unknown)
            if s.has_chart:
                try:has_legend=s.chart.has_legend
                except (ValueError,AttributeError):has_legend=True
                try:
                    label_expected=any(plot.has_data_labels for plot in s.chart.plots)
                    expected_count=sum(len(series.points) for series in s.chart.series) if label_expected else 0
                except (ValueError,AttributeError,TypeError):label_expected=True;expected_count=None
                label_records=[x for x in render.get('chart_label_records',[]) if x.get('slide')==n and x.get('audit_path')==path]
                if label_expected and (not label_records or any(not finite_box(x.get('bounds_pt')) for x in label_records) or (expected_count is not None and len(label_records)!=expected_count)):
                    add('chart_label_geometry_required',shape_ids=[sid],audit_path=path,expected_count=expected_count,measured_count=len(label_records))
                if has_legend:
                    geom=next((x for x in render.get('chart_legend_records',[]) if x.get('slide')==n and x.get('audit_path')==path),None)
                    if not geom or not finite_box(geom.get('bounds_pt')):
                        add('chart_legend_geometry_required',shape_ids=[sid],audit_path=path)
                    else:
                        lb=geom['bounds_pt'];near=[]
                        for label in render.get('chart_label_records',[]):
                            if label.get('slide')!=n or label.get('audit_path')!=path:continue
                            b=label.get('bounds_pt')
                            if not finite_box(b):continue
                            dx=max(lb[0]-b[2],b[0]-lb[2],0);dy=max(lb[1]-b[3],b[1]-lb[3],0)
                            if math.hypot(dx,dy)<4*scale:near.append({'label':label,'distance_pt':math.hypot(dx,dy)})
                        if near:add('chart_legend_clearance_review',shape_ids=[sid],audit_path=path,legend=geom,near_labels=near,threshold_pt=4*scale)
            if s.has_text_frame and s.text.strip():
                try:bg=rgb(s.fill.fore_color) if s.fill.type==MSO_FILL_TYPE.SOLID else None
                except (AttributeError,ValueError):bg=None
                if bg:
                    runs=[r for p in s.text_frame.paragraphs for r in p.runs if r.text.strip()]
                    colors=[rgb(r.font.color) for r in runs];review=[]
                    for fg in colors:
                        if fg is None:review.append({'foreground':'inherited_or_theme','background':bg})
                        elif contrast(fg,bg)<4.5 or max(fg)-min(fg)>32:
                            review.append({'foreground':fg,'background':bg,'contrast':round(contrast(fg,bg),3),'colored_foreground':max(fg)-min(fg)>32})
                    if review:add('filled_text_color_review',shape_ids=[sid],audit_path=path,color_pairs=review)
    visit(slide.shapes)
    # Independent table -> unboxed explanation -> lower module candidates.
    shapes=list(slide.shapes)
    for table in [s for s in shapes if s.has_table]:
        tb=box(table)
        for mid in shapes:
            if not mid.has_text_frame or not mid.text.strip() or mid.shape_id==table.shape_id:continue
            rec=records.get(str(mid.shape_id),{})
            if all(type(rec.get(k)) in (int,float) and math.isfinite(rec[k]) for k in ('bound_left_pt','bound_top_pt','bound_width_pt','bound_height_pt')):
                mb=[rec['bound_left_pt'],rec['bound_top_pt'],rec['bound_left_pt']+rec['bound_width_pt'],rec['bound_top_pt']+rec['bound_height_pt']]
            else:mb=box(mid)
            overlap=min(tb[2],mb[2])-max(tb[0],mb[0])
            if overlap<.5*min(tb[2]-tb[0],mb[2]-mb[0]) or not 0<=mb[1]-tb[3]<=100*scale:continue
            after=[]
            for s in shapes:
                if s.shape_id in (table.shape_id,mid.shape_id) or s.name.startswith('page-number:'):continue
                b=box(s)
                if b[2]<=b[0] or b[3]<=b[1]:continue
                if 0<=b[1]-mb[3]<=100*scale and min(b[2],mb[2])-max(b[0],mb[0])>0:after.append((b[1],s))
            if not after:continue
            y=min(x[0] for x in after);lower=[s for yy,s in after if abs(yy-y)<2*scale]
            a,b=mb[1]-tb[3],y-mb[3]
            if min(a,b)<12*scale or abs(a-b)>max(3*scale,(a+b)/2*.2):
                add('interstitial_module_spacing_review',shape_ids=[table.shape_id,mid.shape_id]+[s.shape_id for s in lower],
                    gaps_pt=[a,b],text_bounds_pt=mb,minimum_pt=12*scale,balance_tolerance_pt=max(3*scale,(a+b)/2*.2))
    out.extend(scan_hierarchy(slide,n,render,scale))
    return out


def scan_hierarchy(slide,n,render,scale=1):
    """Locate hierarchy candidates; role/necessity and optical weight need visual review."""
    out=[];prs=slide.part.package.presentation_part.presentation
    width,height=prs.slide_width/12700,prs.slide_height/12700
    shapes=list(slide.shapes)
    records={r.get('audit_path'):r for r in render.get('text_records',[]) if r.get('slide')==n and isinstance(r,dict)}
    texts=[]
    for s in shapes:
        if not s.has_text_frame or not s.text.strip():continue
        if re.fullmatch(r'[1-9]\d*/[1-9]\d*',s.text.strip()):continue
        r=records.get(str(s.shape_id),{})
        keys=('bound_left_pt','bound_top_pt','bound_width_pt','bound_height_pt')
        measured=all(type(r.get(k)) in (int,float) and math.isfinite(r[k]) for k in keys) and r.get('bound_width_pt',0)>0 and r.get('bound_height_pt',0)>0
        b=[r['bound_left_pt'],r['bound_top_pt'],r['bound_left_pt']+r['bound_width_pt'],r['bound_top_pt']+r['bound_height_pt']] if measured else box(s)
        sizes=r.get('run_font_sizes_pt') or [r.get('font_pt')]
        sizes=[v for v in sizes if type(v) in (int,float) and math.isfinite(v) and v>0]
        if not sizes:sizes=[run.font.size.pt for p in s.text_frame.paragraphs for run in p.runs if run.text.strip() and run.font.size]
        texts.append({'shape_id':s.shape_id,'audit_path':str(s.shape_id),'text':s.text,'bounds_pt':b,'font_pt':max(sizes) if sizes else None,'measured':measured})
    # Semantic candidates inferred from aligned title/body/title sequences.
    # These are review requests: mixed roles and paragraph-internal structures
    # still need actual local/full-page inspection.
    out.extend(scan_section_proximity(texts,scale))
    hosts=[]
    for s in shapes:
        if s.has_text_frame and s.text.strip():continue
        try:
            visible=s.fill.type==MSO_FILL_TYPE.SOLID and not any(e.get('val')=='0' for e in s._element.xpath('./p:spPr/a:solidFill/*/a:alpha'))
        except (AttributeError,ValueError):visible=False
        b=box(s)
        if visible and finite_box(b) and b[2]-b[0]>=24*scale and b[3]-b[1]>=20*scale and (b[2]-b[0])*(b[3]-b[1])<.75*width*height:
            hosts.append((s,b))
    def inside(a,b):return a[0]>=b[0]-.5*scale and a[1]>=b[1]-.5*scale and a[2]<=b[2]+.5*scale and a[3]<=b[3]+.5*scale
    host_order={s.shape_id:i for i,(s,_) in enumerate(hosts)}
    def more_specific(other,ob,host,hb):
        oa=(ob[2]-ob[0])*(ob[3]-ob[1]);ha=(hb[2]-hb[0])*(hb[3]-hb[1])
        return oa<ha-1e-6 or (abs(oa-ha)<=1e-6 and host_order[other.shape_id]>host_order[host.shape_id])
    for host,hb in hosts:
        members=[t for t in texts if inside(t['bounds_pt'],hb)]
        # Review the smallest real host; enclosing panels remain covered by normal layout review.
        members=[t for t in members if not any(other.shape_id!=host.shape_id and inside(ob,hb) and inside(t['bounds_pt'],ob) and more_specific(other,ob,host,hb) for other,ob in hosts)]
        if not members:continue
        ids=[host.shape_id]+[t['shape_id'] for t in members]
        graphics=[s for s in shapes if s.shape_id!=host.shape_id and not (s.has_text_frame and s.text.strip()) and inside(box(s),hb) and not (s.shape_id in host_order and not more_specific(s,box(s),host,hb))]
        if graphics:
            out.append({'reason':'container_text_union_measurement_required','shape_ids':ids+[s.shape_id for s in graphics],
                        'host_bounds_pt':hb,'measurement_limitation':'Mixed text/graphics require their complete visual group; do not center only the text subset'});continue
        if any(not t['measured'] for t in members):
            out.append({'reason':'container_text_union_measurement_required','shape_ids':ids,'host_bounds_pt':hb,'audit_paths':[t['audit_path'] for t in members]});continue
        union=[min(t['bounds_pt'][0] for t in members),min(t['bounds_pt'][1] for t in members),max(t['bounds_pt'][2] for t in members),max(t['bounds_pt'][3] for t in members)]
        above,below=union[1]-hb[1],hb[3]-union[3];tol=max(3*scale,.2*max(0,(above+below)/2))
        # A centered text group can still sit in an unnecessarily tall empty card.
        if min(above,below)>32*scale and (union[3]-union[1])/(hb[3]-hb[1])<.72:
            out.append({'reason':'text_container_excess_space_review','shape_ids':ids,'host_bounds_pt':hb,
                        'text_union_bounds_pt':union,'top_gap_pt':above,'bottom_gap_pt':below,
                        'text_height_fraction':(union[3]-union[1])/(hb[3]-hb[1]),
                        'required':'Check effective information density independently of centering. Resize the real container or reorganize useful content; color area is not evidence of density.'})
        if abs(above-below)>tol:
            out.append({'reason':'container_text_vertical_balance_review','shape_ids':ids,'host_bounds_pt':hb,'text_union_bounds_pt':union,
                        'top_gap_pt':above,'bottom_gap_pt':below,'center_offset_pt':(above-below)/2,'tolerance_pt':tol,'measurement_basis':'rendered_text_bounds; confirm actual ink locally and at full page'})
    headings=[t for t in texts if t['font_pt'] is not None and t['font_pt']>=22*scale and not numeric(t['text'])]
    if not headings:return out
    heading=max(headings,key=lambda t:(t['font_pt'],-t['bounds_pt'][1]));cutoff=min(18*scale,.6*heading['font_pt'])
    if heading['bounds_pt'][1]>=.2*height:
        out.append({'reason':'title_entry_position_review','shape_ids':[heading['shape_id']],
                    'title_bounds_pt':heading['bounds_pt'],'page_height_pt':height,
                    'title_top_ratio':heading['bounds_pt'][1]/height,
                    'measurement_basis':'rendered_text_bounds' if heading['measured'] else 'native_frame_requires_visual_measurement',
                    'required':'Inspect actual title ink, top whitespace, whole composition and redundant title layers; cover status is not an exemption. The 20% threshold requests visual review, not a mandatory move.'})
    small=[]
    for t in texts:
        if t['shape_id']==heading['shape_id'] or t['font_pt'] is None or t['font_pt']>cutoff:continue
        containing=[b for _,b in hosts if inside(t['bounds_pt'],b)]
        metric_companion=any(numeric(v['text']) and v['font_pt'] is not None and v['font_pt']>=max(28*scale,t['font_pt']*1.6) and any(inside(v['bounds_pt'],b) for b in containing) for v in texts)
        if containing and not metric_companion:continue
        b=t['bounds_pt'];position='above_title' if b[3]<=heading['bounds_pt'][1]+2*scale else 'page_bottom' if b[1]>=.82*height else 'detached_text'
        small.append({**t,'position_hint':position})
    if small:out.append({'reason':'floating_annotation_review','shape_ids':[t['shape_id'] for t in small],
                         'title_shape_id':heading['shape_id'],'candidates':small,'required':'Inspect every detached small text, retain meaningful labels/symbols, promote key information or consolidate necessary annotations at page bottom'})
    # Use measured text, not its enclosing blank background, as a content start.
    # Photos/charts/groups/freeforms keep their actual bounds as candidates; their
    # internal whitespace requires visual inspection, never automatic cropping.
    effective=[t for t in texts if t['shape_id']!=heading['shape_id'] and finite_box(t['bounds_pt'])
               and t['bounds_pt'][1]>=heading['bounds_pt'][3]-2*scale]
    picture_like=[]
    for s in shapes:
        b=box(s)
        if s.shape_type in (6,13,19) or s.has_chart or s.has_table:
            if finite_box(b) and b[1]>=heading['bounds_pt'][3]-2*scale:
                picture_like.append({'shape_id':s.shape_id,'bounds_pt':b,'measured':False,'kind':'graphic_requires_internal_review'})
    effective+=picture_like
    if effective:
        first=min(effective,key=lambda t:t['bounds_pt'][1]);gap=first['bounds_pt'][1]-heading['bounds_pt'][3]
        if gap>36*scale:
            containing=[(s,b) for s,b in hosts if inside(first['bounds_pt'],b)]
            out.append({'reason':'effective_content_entry_gap_review','shape_ids':[heading['shape_id'],first['shape_id']],
                        'title_bottom_pt':heading['bounds_pt'][3],'effective_content_top_pt':first['bounds_pt'][1],
                        'gap_pt':gap,'review_trigger_pt':36*scale,
                        'containing_backgrounds':[{'shape_id':s.shape_id,'top_pt':b[1],
                            'outside_gap_pt':b[1]-heading['bounds_pt'][3],'inside_gap_pt':first['bounds_pt'][1]-b[1]} for s,b in containing],
                        'measurement_basis':'rendered_text_bounds' if heading['measured'] and first.get('measured') else 'partial_geometry_requires_local_and_full_page_review',
                        'required':'Review the combined outer and inner gap, effective graphics, and page density. Preserve content and test a tighter layout when empty or bottom-heavy.'})
    occupied=[];actual_text_bounds={t['shape_id']:t['bounds_pt'] for t in texts}
    for s in shapes:
        b=actual_text_bounds.get(s.shape_id,box(s))
        if s.shape_id==heading['shape_id'] or not finite_box(b):continue
        if s.has_text_frame and re.fullmatch(r'[1-9]\d*/[1-9]\d*',s.text.strip()):continue
        if (b[2]-b[0])*(b[3]-b[1])>.75*width*height:continue
        if b[1]>=heading['bounds_pt'][3]+3*scale and b[3]<=.94*height:occupied.append((s,b))
    if occupied:
        top=min(b[1] for _,b in occupied);bottom=max(b[3] for _,b in occupied)
        upper=top-heading['bounds_pt'][3];lower=max(0,.94*height-bottom)
        if (top+bottom)/2>.55*height and upper>max(24*scale,lower*1.4+3*scale):
            out.append({'reason':'page_content_low_review','shape_ids':[s.shape_id for s,_ in occupied],
                        'title_shape_id':heading['shape_id'],'body_top_pt':top,'body_bottom_pt':bottom,'upper_gap_pt':upper,'lower_gap_pt':lower,
                        'required':'Review whole-page optical weight and information density; compact the title zone and reposition meaningful content'})
    return out


def scan_section_proximity(texts,scale=1):
    out=[]
    valid=[t for t in texts if finite_box(t.get('bounds_pt')) and type(t.get('font_pt')) in (int,float)]
    def aligned(a,b):
        aa,bb=a['bounds_pt'],b['bounds_pt']
        return abs(aa[0]-bb[0])<=6*scale and min(aa[2],bb[2])-max(aa[0],bb[0])>=.6*min(aa[2]-aa[0],bb[2]-bb[0])
    for title in valid:
        if title['font_pt']<22*scale or numeric(title.get('text','')):continue
        later=sorted([t for t in valid if t is not title and aligned(title,t) and t['bounds_pt'][1]>=title['bounds_pt'][3]-1*scale],key=lambda t:t['bounds_pt'][1])
        if len(later)<2:continue
        body,nxt=later[:2]
        if body['font_pt']>title['font_pt']-2*scale or abs(nxt['font_pt']-title['font_pt'])>1*scale:continue
        inner=body['bounds_pt'][1]-title['bounds_pt'][3];outer=nxt['bounds_pt'][1]-body['bounds_pt'][3]
        if max(inner,outer)>90*scale:continue
        if outer<inner+6*scale:
            out.append({'reason':'section_proximity_inversion_review','shape_ids':[title['shape_id'],body['shape_id'],nxt['shape_id']],
                        'within_section_gap_pt':inner,'between_sections_gap_pt':outer,'desired_hierarchy_difference_pt':6*scale,
                        'bounds_pt':[title['bounds_pt'],body['bounds_pt'],nxt['bounds_pt']],
                        'measurement_basis':'rendered_text_bounds' if all(t.get('measured') for t in (title,body,nxt)) else 'partial_geometry_requires_visual_review',
                        'required':'Check which title the body belongs to. Within-section proximity must read tighter than the separation to the next peer section; inspect actual ink and full-page grouping.'})
    return out
