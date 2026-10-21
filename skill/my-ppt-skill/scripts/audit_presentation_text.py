"""Extract all slide/chart/notes/master text for a separate semantic review.
Return 2 for suspect wording, 3 for extraction errors, 0 for no regex candidates.
No regex candidates is NOT a language signoff.
"""
from pathlib import Path
from zipfile import ZipFile
import argparse, hashlib, json, re
from lxml import etree

PATTERNS = [r'仅供参考|不代表|不能据此|不做排名|不提供无来源',
            r'仍(?:然)?(?:需|要|依赖)', r'只是(?:起点|开始)',
            r'本(?:页|报告|演示).{0,20}(?:仅|不做|用于说明|采用|避免)',
            r'发布记录.{0,20}披露.{0,20}估计', r'已渲染验收|全部图表可编辑|来源已放入备注']

def audit(path):
    data=path.read_bytes();digest=hashlib.sha256(data).hexdigest().upper()
    parts=[];findings=[]
    with ZipFile(path) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise ValueError('Duplicate ZIP entries')
        for name in sorted(z.namelist()):
            if not re.match(r'ppt/(slides|notesSlides|slideMasters|slideLayouts|notesMasters|charts)/[^/]+\.xml$',name):continue
            root=etree.fromstring(z.read(name))
            paragraphs=[''.join(p.itertext()).strip() for p in root.xpath('//*[local-name()="p"]')]
            # DrawingML runs are joined without formatting-run separators. Chart
            # cached strings sit outside paragraphs and are reviewed separately.
            paragraphs=[''.join(p.xpath('.//*[local-name()="t"]/text()')).strip() for p in root.xpath('//*[local-name()="p"]')]
            if '/charts/' in name:
                paragraphs+=root.xpath('//*[local-name()="strCache"]//*[local-name()="v"]/text()')
            texts=[t for t in paragraphs if t]
            parts.append({'part':name,'paragraphs':texts})
            for index,t in enumerate(texts):
                hits=[pattern for pattern in PATTERNS if re.search(pattern,t)]
                if hits:findings.append({'id':f'language-{len(findings)+1}','part':name,'paragraph':index,'text':t,'patterns':hits})
    if not any(p['part'].startswith('ppt/slides/') for p in parts):raise ValueError('No slides extracted')
    if hashlib.sha256(path.read_bytes()).hexdigest().upper()!=digest:raise ValueError('Input changed during extraction')
    return {'sha256':digest,'status':'language_review_required','regex_candidates':findings,'parts':parts,
            'required_review':'Read ALL extracted paragraphs in context; regex misses semantic variants and cannot authorize publication.'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('pptx',type=Path);ap.add_argument('report',type=Path);a=ap.parse_args()
    try:result=audit(a.pptx);code=2 if result['regex_candidates'] else 0
    except Exception as exc:result={'status':'failed','error':str(exc)};code=3
    from report_io import emit_report
    report_error=emit_report(a.report,result,inputs=(a.pptx,),frozen_dirs=())
    if report_error:return report_error
    print(result['status']);return code

if __name__=='__main__':raise SystemExit(main())
