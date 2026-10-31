"""Create a two-page real-render probe: normal footer note and invalid 8pt footer."""
from pathlib import Path
import argparse
from pptx import Presentation
from pptx.util import Pt

def main():
 ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);a=ap.parse_args()
 if a.output.exists():raise ValueError('Choose a fresh output PPTX')
 p=Presentation();p.slide_width=Pt(960);p.slide_height=Pt(540)
 for n in (1,2):
  sl=p.slides.add_slide(p.slide_layouts[6])
  for name,x,y,w,h,value,size in [('title:probe',48,40,850,48,'页底注释规则验证',32),('body:probe',48,170,820,80,'正文与普通注释采用一致的正常字号。',20),('footnote:necessary' if n==1 else 'chart-note:dense:footer',48,470 if n==1 else 488,780,36 if n==1 else 26,'样本口径：100条测试记录。',20 if n==1 else 8),('page-number:probe',872,494,40,20,f'{n}/2',10)]:
   s=sl.shapes.add_textbox(Pt(x),Pt(y),Pt(w),Pt(h));s.name=name;s.text=value
   s.text_frame.margin_left=s.text_frame.margin_right=s.text_frame.margin_top=s.text_frame.margin_bottom=0
   for pa in s.text_frame.paragraphs:
    for r in pa.runs:r.font.name='Microsoft YaHei';r.font.size=Pt(size)
 a.output.parent.mkdir(parents=True,exist_ok=True);p.save(a.output)
if __name__=='__main__':main()
