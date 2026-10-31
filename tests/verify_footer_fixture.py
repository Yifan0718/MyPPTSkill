"""Check the actual PowerPoint audit from generate_footer_fixture.py."""
import argparse,json
from pathlib import Path
def main():
 ap=argparse.ArgumentParser();ap.add_argument('audit',type=Path);a=ap.parse_args();r=json.loads(a.audit.read_text('utf-8-sig'))
 assert r['slide_count']==2
 assert not any(x['slide']==1 for x in r['issues']),'Normal-size footer has a preflight issue'
 assert not any(x['reason']=='non_page_number_footer_forbidden' for x in r['issues']),'Obsolete blanket footer ban is active'
 assert any(x['slide']==1 and x['reason']=='footer_annotation_requires_normal_font_purpose_and_page_number_clearance' for x in r['manual_review'])
 assert any(x['slide']==2 and x['reason']=='run_font_too_small' and x['actual']==8 and x['minimum']==12 for x in r['issues'])
 print('PASS: normal-size footer remains visually reviewed; ordinary 8pt footer is rejected.')
if __name__=='__main__':main()
