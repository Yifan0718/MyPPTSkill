"""Synthetic wording/extraction cases; semantic review determines subject relevance."""
import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from lxml import etree
from pptx import Presentation
from pptx.util import Pt
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
import audit_presentation_text as language

class ProductionInstructionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.p=Presentation();self.s=self.p.slides.add_slide(self.p.slide_layouts[6]);self.path=self.root/'case.pptx'
 def text(self,value):
  s=self.s.shapes.add_textbox(Pt(40),Pt(40),Pt(600),Pt(100));s.text=value;return s
 def audit(self):self.p.save(self.path);return language.audit(self.path)
 def test_explicit_user_requirement_is_candidate(self):
  self.text('按照用户要求突出优势，保持清晰排版。');self.assertTrue(self.audit()['regex_candidates'])
 def test_paraphrased_requirement_is_candidate(self):
  self.text('用户希望PPT采用丰富的图表。');self.assertTrue(self.audit()['regex_candidates'])
 def test_implicit_layout_instruction_is_candidate(self):
  self.text('请确保间距均衡并逐页验收。');self.assertTrue(self.audit()['regex_candidates'])
 def test_split_runs_keep_instruction_detection(self):
  s=self.text('');p=s.text_frame.paragraphs[0]
  for chunk in ('按照用','户要求','制作内容'):p.add_run().text=chunk
  self.assertTrue(self.audit()['regex_candidates'])
 def test_notes_are_checked(self):
  self.text('分子结构与气味');self.s.notes_slide.notes_text_frame.text='根据您的要求采用等宽字体。'
  self.assertTrue(any('/notesSlides/' in x['part'] for x in self.audit()['regex_candidates']))
 def test_table_text_is_checked(self):
  t=self.s.shapes.add_table(1,1,Pt(40),Pt(100),Pt(600),Pt(80)).table;t.cell(0,0).text='本页满足要求并完成验收。'
  self.assertTrue(self.audit()['regex_candidates'])
 def test_chart_cached_labels_are_checked(self):
  d=CategoryChartData();d.categories=['按照用户要求制作'];d.add_series('数量',[1])
  self.s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,Pt(40),Pt(80),Pt(500),Pt(300),d)
  self.assertTrue(any('/charts/' in x['part'] for x in self.audit()['regex_candidates']))
 def test_master_and_layout_instructions_are_checked(self):
  box=self.text('遵照客户要求制作本稿。');self.p.save(self.path)
  with ZipFile(self.path) as z:parts={n:z.read(n) for n in z.namelist()}
  for name in ('ppt/slideMasters/slideMaster1.xml','ppt/slideLayouts/slideLayout1.xml'):
   root=etree.fromstring(parts[name]);tree=root.xpath('//*[local-name()="spTree"]')[0]
   tree.append(copy.deepcopy(box._element));parts[name]=etree.tostring(root)
  with ZipFile(self.path,'w',ZIP_DEFLATED) as z:
   for n,data in parts.items():z.writestr(n,data)
  found={x['part'] for x in language.audit(self.path)['regex_candidates']}
  self.assertIn('ppt/slideMasters/slideMaster1.xml',found);self.assertIn('ppt/slideLayouts/slideLayout1.xml',found)
 def test_subject_requirements_remain_normal_content(self):
  self.text('系统需求：响应时间低于100毫秒。实验要求：温度保持25°C。')
  self.assertEqual(self.audit()['regex_candidates'],[])
 def test_subject_facts_author_and_conditions_remain_normal_content(self):
  self.text('作者：张三。2026年11月。323种评估分子中，53%的预测更接近评审组平均评分。受体响应依赖分子结构。')
  self.assertEqual(self.audit()['regex_candidates'],[])
 def test_quoted_prompt_candidate_retains_context_and_input(self):
  self.text('提示词教学示例：“请使用复杂图表”。分析该指令的表达结构。');self.p.save(self.path);before=self.path.read_bytes()
  report=language.audit(self.path);self.assertTrue(report['regex_candidates'])
  self.assertIn('提示词教学示例',report['regex_candidates'][0]['text']);self.assertEqual(before,self.path.read_bytes())
  self.assertEqual(report['status'],'language_review_required')
 def test_cli_candidate_then_repaired_text_returns_expected_status(self):
  box=self.text('按照用户要求保持间距均衡。');self.p.save(self.path)
  def run(name):
   return subprocess.run([sys.executable,'-B','-X','utf8',language.__file__,str(self.path),str(self.root/name)],capture_output=True,timeout=30)
  self.assertEqual(run('before.json').returncode,2)
  box.text='分子结构影响受体响应。';self.p.save(self.path)
  self.assertEqual(run('after.json').returncode,0)
  self.assertEqual(json.loads((self.root/'after.json').read_text('utf8'))['status'],'language_review_required')

if __name__=='__main__':unittest.main()
