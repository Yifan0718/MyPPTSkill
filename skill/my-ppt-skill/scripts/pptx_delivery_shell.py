"""OPC-only delivery shell. Render externally; finalize before immutable audits.

The PNG argument must be the actual first-slide export of expected_sha256.
The final evidence gate independently compares it with its current render.
"""
import argparse
import hashlib
import json
import os
import posixpath
import tempfile
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET
from PIL import Image

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
THUMB_TYPE = 'http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail'
VIEW_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps'
THUMB = 'docProps/thumbnail.jpeg'
VIEW = 'ppt/viewProps.xml'

def sha(data):
    return hashlib.sha256(data).hexdigest().upper()

def unpack(data):
    with ZipFile(BytesIO(data)) as z:
        infos = z.infolist()
        parts = {i.filename: z.read(i) for i in infos}
        if len(parts) != len(infos):
            raise ValueError('Duplicate ZIP parts')
        return parts, infos, z.comment

def xml(root):
    return ET.tostring(root, encoding='UTF-8', xml_declaration=True)

def target_part(relname, target):
    base = '' if relname == '_rels/.rels' else posixpath.dirname(posixpath.dirname(relname))
    return posixpath.normpath(posixpath.join(base, unquote(target))).lstrip('/')

def thumbnail_bytes(png):
    with Image.open(BytesIO(png)) as source:
        if source.format != 'PNG':
            raise ValueError('First-slide export must be PNG')
        image = source.convert('RGB')
        image = image.resize((320, max(1, round(image.height * 320 / image.width))), Image.Resampling.LANCZOS)
        out = BytesIO()
        # Windows PowerPoint can reject a PNG package-thumbnail relationship
        # even when that PNG was exported by PowerPoint itself. Baseline JPEG
        # is verified by real background Open, while the source remains PNG.
        image.save(out, format='JPEG', quality=95, subsampling=0, optimize=False, progressive=False)
        return out.getvalue()

def fingerprint(parts, thumbnail_parts):
    """Content bytes plus semantic non-shell relationships, independent of diffs."""
    h = hashlib.sha256()
    excluded=set(thumbnail_parts)|{VIEW,'[Content_Types].xml'}
    for name in sorted(set(parts)-excluded):
        data=parts[name]
        if name.endswith('.rels'):
            relationships=[]
            for rel in ET.fromstring(data):
                if rel.get('Type')==THUMB_TYPE or (name=='ppt/_rels/presentation.xml.rels' and rel.get('Type')==VIEW_TYPE):
                    continue
                relationships.append(sorted(rel.attrib.items()))
            if not relationships: continue
            data=json.dumps(sorted(relationships),ensure_ascii=False).encode('utf8')
        h.update(name.encode('utf8') + b'\0' + hashlib.sha256(data).digest())
    return h.hexdigest().upper()

def transform(data, first_slide=None):
    parts, infos, comment = unpack(data)
    before = dict(parts)
    old = {n for n in parts if n.startswith('docProps/thumbnail.')}
    reused = set()
    for name in list(parts):
        if not name.endswith('.rels'):
            continue
        root = ET.fromstring(parts[name]); dirty = False
        for rel in list(root):
            target = target_part(name, rel.get('Target', ''))
            if rel.get('Type') == THUMB_TYPE:
                if rel.get('TargetMode') != 'External' and target.rsplit('.',1)[-1].lower() in ('png','jpeg','jpg','gif','bmp','emf','wmf','tif','tiff'):
                    old.add(target)
                root.remove(rel); dirty = True
            elif rel.get('TargetMode') != 'External':
                reused.add(target)
        if dirty:
            parts[name] = xml(root)
    removed = old - reused
    for name in removed:
        parts.pop(name, None)
    thumb=THUMB
    if first_slide is not None and thumb in reused:
        index=1
        while f'docProps/thumbnail.{index}.jpeg' in parts:
            index+=1
        thumb=f'docProps/thumbnail.{index}.jpeg'
    view = ET.fromstring(parts[VIEW]) if VIEW in parts else ET.Element('{'+P+'}viewPr', nsmap={'p': P})
    view.set('lastView', 'sldView')
    normal = view.find('{'+P+'}normalViewPr')
    if normal is None:
        normal = ET.Element('{'+P+'}normalViewPr'); view.insert(0, normal)
    for key, value in {'preferSingleView':'0','vertBarState':'restored','horzBarState':'restored'}.items():
        normal.set(key, value)
    for index, (name, size) in enumerate((('restoredLeft','18000'),('restoredTop','90000'))):
        child = normal.find('{'+P+'}'+name)
        if child is None:
            child = ET.Element('{'+P+'}'+name); normal.insert(index, child)
        child.set('sz', size)
    slide_view=view.find('{'+P+'}slideViewPr')
    if slide_view is None:
        slide_view=ET.Element('{'+P+'}slideViewPr'); view.insert(list(view).index(normal)+1,slide_view)
    common=slide_view.find('{'+P+'}cSldViewPr')
    if common is None:
        common=ET.Element('{'+P+'}cSldViewPr'); slide_view.insert(0,common)
    camera=common.find('{'+P+'}cViewPr')
    if camera is None:
        camera=ET.Element('{'+P+'}cViewPr'); common.insert(0,camera)
    camera.set('varScale','1')
    # PowerPoint stores nonzero origins even when fitted. Preserve existing
    # zoom/pan state; varScale is the actual fit-to-window switch.
    scale=camera.find('{'+P+'}scale')
    if scale is None:
        scale=ET.Element('{'+P+'}scale'); camera.insert(0,scale)
    for axis in ('sx','sy'):
        if scale.find('{'+A+'}'+axis) is None:
            ET.SubElement(scale,'{'+A+'}'+axis,n='1',d='1')
    if camera.find('{'+P+'}origin') is None:
        ET.SubElement(camera,'{'+P+'}origin',x='0',y='0')
    parts[VIEW] = xml(view)
    relname = 'ppt/_rels/presentation.xml.rels'
    rels = ET.fromstring(parts[relname]) if relname in parts else ET.Element('{'+R+'}Relationships', nsmap={None:R})
    for rel in list(rels):
        if rel.get('Type') == VIEW_TYPE:
            rels.remove(rel)
    def add_rel(root, kind, target):
        used = {r.get('Id') for r in root}; index = 1
        while 'rId'+str(index) in used:
            index += 1
        ET.SubElement(root, '{'+R+'}Relationship', Id='rId'+str(index), Type=kind, Target=target)
    add_rel(rels, VIEW_TYPE, 'viewProps.xml')
    parts[relname] = xml(rels)
    types = ET.fromstring(parts['[Content_Types].xml'])
    for entry in list(types):
        if entry.get('PartName','').lstrip('/') in removed | {VIEW}:
            types.remove(entry)
        elif entry.tag=='{'+CT+'}Default':
            extension=entry.get('Extension','').lower()
            if any(n.rsplit('.',1)[-1].lower()==extension for n in removed) and not any(n.rsplit('.',1)[-1].lower()==extension for n in parts):
                types.remove(entry)
    ET.SubElement(types, '{'+CT+'}Override', PartName='/'+VIEW, ContentType='application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml')
    if first_slide is not None:
        parts[thumb] = thumbnail_bytes(first_slide)
        root = ET.fromstring(parts['_rels/.rels']) if '_rels/.rels' in parts else ET.Element('{'+R+'}Relationships', nsmap={None:R})
        add_rel(root, THUMB_TYPE, thumb)
        parts['_rels/.rels'] = xml(root)
        ET.SubElement(types, '{'+CT+'}Override', PartName='/'+thumb, ContentType='image/jpeg')
    parts['[Content_Types].xml'] = xml(types)
    changed = sorted(n for n in set(before)|set(parts) if before.get(n) != parts.get(n))
    thumbnail_parts=removed|({thumb} if first_slide is not None else set())
    content_before = fingerprint(before, thumbnail_parts)
    content_after = fingerprint(parts, thumbnail_parts)
    if content_before != content_after:
        raise ValueError('Body/content relationship fingerprint changed')
    # Enforce the whitelist independently from the produced change list.
    allowed = removed | {VIEW, thumb, '[Content_Types].xml', relname}
    allowed |= {n for n in before if n.endswith('.rels') and THUMB_TYPE.encode() in before[n]}
    if first_slide is not None:
        allowed.add('_rels/.rels')
    if set(changed) - allowed:
        raise ValueError('Unexpected content mutation')
    out = BytesIO()
    with ZipFile(out, 'w') as z:
        z.comment = comment
        existing = set()
        for info in infos:
            if info.filename in parts:
                z.writestr(info, parts[info.filename]); existing.add(info.filename)
        for name in sorted(set(parts)-existing):
            z.writestr(name, parts[name], compress_type=ZIP_DEFLATED)
    return out.getvalue(), {'changed_parts':changed, 'thumbnail_part':thumb if first_slide is not None else None,'content_fingerprint_before':content_before,
                             'content_fingerprint_after':content_after,
                             'preserved_parts_sha256':{n:sha(before[n]) for n in sorted(set(before)-set(changed))}}

def atomic_replace(path, data, expected):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=path.name+'.shell-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if sha(path.read_bytes()) != expected.upper():
            raise ValueError('PPTX source hash changed before commit')
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def clean_intermediate(pptx_path):
    path = Path(pptx_path); data = path.read_bytes()
    result, proof = transform(data)
    atomic_replace(path,result,sha(data))
    return proof

def finalize(pptx_path, expected_sha256, first_slide_png, proof_path):
    path = Path(pptx_path); data = path.read_bytes()
    if sha(data) != expected_sha256.upper():
        raise ValueError('PPTX source hash does not match actual render source')
    png = Path(first_slide_png).read_bytes()
    result, proof = transform(data,png)
    errors = verify_shell(result,png)
    if errors:
        raise ValueError('Prepared delivery shell failed validation: '+'; '.join(errors))
    proof.update({'before_sha256':sha(data),'after_sha256':sha(result),
                  'first_slide_path':str(Path(first_slide_png).resolve()),'first_slide_sha256':sha(png),
                  'thumbnail_sha256':sha(thumbnail_bytes(png)), 'operation':'delivery_shell_only'})
    proof_file = Path(proof_path)
    if proof_file.resolve() in (path.resolve(), Path(first_slide_png).resolve()):
        raise ValueError('Proof path must be distinct from input files')
    proof_file.parent.mkdir(parents=True, exist_ok=True)
    if proof_file.exists() and not proof_file.is_file():
        raise ValueError('Proof destination is not a regular file')
    fd,temp=tempfile.mkstemp(prefix=proof_file.name+'.',suffix='.tmp',dir=proof_file.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as stream:
            stream.write(json.dumps(proof,ensure_ascii=False,indent=2)); stream.flush(); os.fsync(stream.fileno())
        atomic_replace(path,result,expected_sha256)
        try:
            os.replace(temp,proof_file)
        except Exception as commit_error:
            # Two paths cannot be committed atomically. Restore only our own
            # committed bytes; never overwrite a concurrent user's change.
            try:
                atomic_replace(path, data, sha(result))
            except Exception as rollback_error:
                raise RuntimeError(
                    'Proof commit failed; PPTX rollback refused or failed. '
                    'No concurrent change was intentionally overwritten; inspect the current PPTX '
                    'and rerun preparation with a fresh render/hash. '
                    f'Proof error: {commit_error}; rollback error: {rollback_error}'
                ) from commit_error
            raise RuntimeError('Proof commit failed; original PPTX restored. '
                               'Fix the proof destination and rerun preparation: '+str(commit_error)) from commit_error
    finally:
        if os.path.exists(temp): os.unlink(temp)
    return proof

def verify_shell(pptx_path, first_slide_png):
    """Check files or in-memory bytes; only final gate supplies current render."""
    errors = []
    try:
        parts, _, _ = unpack(pptx_path if isinstance(pptx_path,bytes) else Path(pptx_path).read_bytes())
        matches = []; reused = set()
        for name, data in parts.items():
            if name.endswith('.rels'):
                for rel in ET.fromstring(data):
                    if rel.get('Type') == THUMB_TYPE: matches.append((name,rel))
                    elif rel.get('TargetMode')!='External': reused.add(target_part(name,rel.get('Target','')))
        thumb=target_part('_rels/.rels',matches[0][1].get('Target','')) if len(matches)==1 else THUMB
        if any(n.startswith('docProps/thumbnail.') and n!=thumb and n not in reused for n in parts):
            errors.append('Delivery shell contains stale thumbnail parts')
        if len(matches)!=1 or matches[0][0]!='_rels/.rels' or not thumb.startswith('docProps/thumbnail.') or not thumb.endswith('.jpeg') or thumb in reused or matches[0][1].get('TargetMode')=='External':
            errors.append('Delivery thumbnail relationship must uniquely target canonical thumbnail')
        expected = thumbnail_bytes(first_slide_png if isinstance(first_slide_png,bytes) else Path(first_slide_png).read_bytes())
        with Image.open(BytesIO(parts[thumb])) as actual, Image.open(BytesIO(expected)) as target:
            if actual.format!='JPEG' or actual.mode!='RGB' or actual.size!=target.size or actual.tobytes()!=target.tobytes():
                errors.append('Delivery thumbnail differs from actual current first-slide render')
        view = ET.fromstring(parts[VIEW]); normal = view.find('{'+P+'}normalViewPr')
        camera=view.find('{'+P+'}slideViewPr/{'+P+'}cSldViewPr/{'+P+'}cViewPr')
        if camera is None or camera.get('varScale')!='1':
            errors.append('Delivery slide view must fit the current window (varScale=1)')
        if view.get('lastView')!='sldView' or normal is None:
            errors.append('Delivery normal view is missing or incorrect')
        else:
            for key,val in {'preferSingleView':'0','vertBarState':'restored','horzBarState':'restored'}.items():
                if normal.get(key)!=val: errors.append('Delivery normal view incorrect: '+key)
            for name,size in (('restoredLeft','18000'),('restoredTop','90000')):
                child=normal.find('{'+P+'}'+name)
                if child is None or child.get('sz')!=size: errors.append('Delivery pane size incorrect: '+name)
        rels = ET.fromstring(parts['ppt/_rels/presentation.xml.rels'])
        views = [r for r in rels if r.get('Type')==VIEW_TYPE]
        if len(views)!=1 or target_part('ppt/_rels/presentation.xml.rels',views[0].get('Target',''))!=VIEW or views[0].get('TargetMode')=='External':
            errors.append('Delivery view relationship missing or incorrect')
        types = ET.fromstring(parts['[Content_Types].xml'])
        for name,kind in ((thumb,'image/jpeg'),(VIEW,'application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml')):
            entries=[e for e in types if e.get('PartName')=='/'+name]
            if len(entries)!=1 or entries[0].get('ContentType')!=kind: errors.append('Delivery content type incorrect: '+name)
    except (OSError,KeyError,ValueError,ET.XMLSyntaxError) as exc:
        errors.append('Delivery shell invalid: '+str(exc))
    return errors

def main():
    parser=argparse.ArgumentParser(); commands=parser.add_subparsers(dest='command',required=True)
    final=commands.add_parser('finalize')
    for option in ('pptx','expected-sha256','first-slide','proof'): final.add_argument('--'+option,required=True)
    clean=commands.add_parser('clean'); clean.add_argument('--pptx',required=True)
    check=commands.add_parser('verify'); check.add_argument('--pptx',required=True); check.add_argument('--first-slide',required=True)
    args=parser.parse_args()
    if args.command=='finalize':
        result=finalize(args.pptx,args.expected_sha256,args.first_slide,args.proof)
        print(json.dumps({'status':'prepared_pending_final_render','after_sha256':result['after_sha256'],'proof':str(Path(args.proof).resolve())}))
    elif args.command=='clean':
        result=clean_intermediate(args.pptx)
        print(json.dumps({'status':'intermediate_shell_cleaned','changed_parts':result['changed_parts']}))
    else:
        errors=verify_shell(args.pptx,args.first_slide); print(json.dumps(errors)); return 2 if errors else 0
    return 0

if __name__=='__main__': raise SystemExit(main())
