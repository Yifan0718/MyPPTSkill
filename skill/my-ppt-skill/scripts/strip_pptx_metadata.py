"""Clear generator identity only; preserve other properties; set grounded author.
Run before final rendering/signoff. No --author means no asserted author.
"""
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
import argparse, hashlib, tempfile, os, sys
from lxml import etree as ET
from pptx_delivery_shell import transform as transform_delivery_shell
DC='http://purl.org/dc/elements/1.1/'
GEN_KEYS={'generator','generatedby','generated_by','creationtool','creation_tool','creatortool','creator_tool','producer'}
def transform(data,author=None):
    with ZipFile(BytesIO(data)) as z:
        infos=z.infolist();parts={i.filename:z.read(i.filename) for i in infos};comment=z.comment
    if len(infos)!=len(parts):raise ValueError('Duplicate ZIP parts')
    changed=[]
    for name in ('docProps/app.xml','docProps/custom.xml','docProps/core.xml'):
        if name not in parts:continue
        root=ET.fromstring(parts[name]);dirty=False
        for el in list(root):
            local=el.tag.rsplit('}',1)[-1]
            is_generator=(name=='docProps/app.xml' and local in ('Application','AppVersion')) or (name=='docProps/custom.xml' and el.get('name','').lower().replace(' ','') in GEN_KEYS)
            if is_generator or (name=='docProps/core.xml' and el.tag=='{'+DC+'}creator'):
                root.remove(el);dirty=True
        if name=='docProps/core.xml' and author:
            el=ET.SubElement(root,'{'+DC+'}creator');el.text=author;dirty=True
        if dirty:parts[name]=ET.tostring(root,encoding='utf-8',xml_declaration=True);changed.append(name)
    if author and 'docProps/core.xml' not in parts:raise ValueError('Core properties missing; set author through authoring library before cleanup')
    out=BytesIO()
    with ZipFile(out,'w') as z:
        z.comment=comment
        for info in infos:z.writestr(info,parts[info.filename])
    cleaned,shell=transform_delivery_shell(out.getvalue())
    return cleaned,sorted(set(changed+shell['changed_parts']))

def findings(data,author=None):
    out=[];actual=[]
    with ZipFile(BytesIO(data)) as z:
        for name in ('docProps/app.xml','docProps/custom.xml','docProps/core.xml'):
            if name not in z.namelist():continue
            for el in ET.fromstring(z.read(name)):
                local=el.tag.rsplit('}',1)[-1]
                if name=='docProps/app.xml' and local in ('Application','AppVersion') and (el.text or '').strip():out.append(name+':'+local)
                if name=='docProps/custom.xml' and el.get('name','').lower().replace(' ','') in GEN_KEYS:out.append(name+':'+el.get('name',''))
                if el.tag=='{'+DC+'}creator' and (el.text or '').strip():actual.append(el.text)
    if actual!=([author] if author else []):out.append('author differs from supplied attribution')
    return out

def strip_metadata(path,author=None):
    path=Path(path);original=path.read_bytes();before=hashlib.sha256(original).digest();data,changed=transform(original,author)
    if findings(data,author):raise RuntimeError('Generator/author validation failed')
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode='wb',prefix=path.name+'.metadata-',suffix='.tmp',dir=path.parent,delete=False) as stream:
            tmp=Path(stream.name);stream.write(data);stream.flush();os.fsync(stream.fileno())
        if hashlib.sha256(path.read_bytes()).digest()!=before:
            raise RuntimeError('PPTX changed during metadata cleanup; external edit preserved. Retry from a stable candidate.')
        os.replace(tmp,path)
    finally:
        if tmp is not None:tmp.unlink(missing_ok=True)
    return changed

def main():
    ap=argparse.ArgumentParser();ap.add_argument('pptx',type=Path);ap.add_argument('--author',help='Author explicitly supplied or grounded in an actual author credit');ap.add_argument('--check',action='store_true');a=ap.parse_args()
    try:
        if a.check:
            found=findings(a.pptx.read_bytes(),a.author);print('\n'.join(found) if found else 'PASS: generator cleared; author attribution matches');return 1 if found else 0
        print('Updated property parts:',len(strip_metadata(a.pptx,a.author)));return 0
    except Exception as exc:
        print('ERR Metadata cleanup/check failed: '+str(exc),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
