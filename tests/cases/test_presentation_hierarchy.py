import json,unittest
from pptx import Presentation
from pptx.util import Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.text import MSO_ANCHOR
from pptx.dml.color import RGBColor
from audit_visual_components import scan_hierarchy,scan_section_proximity

class HierarchyTests(unittest.TestCase):
 def setUp(self):
  self.p=Presentation();self.p.slide_width=Pt(960);self.p.slide_height=Pt(540);self.s=self.p.slides.add_slide(self.p.slide_layouts[6]);self.records=[]
 def text(self,x,y,w,h,value,pt=16,measured=True):
  s=self.s.shapes.add_textbox(Pt(x),Pt(y),Pt(w),Pt(h));s.text=value;s.text_frame.vertical_anchor=MSO_ANCHOR.MIDDLE
  s.text_frame.paragraphs[0].runs[0].font.size=Pt(pt)
  if measured:self.records.append({'slide':1,'audit_path':str(s.shape_id),'text':value,'font_pt':pt,'bound_left_pt':x,'bound_top_pt':y,'bound_width_pt':w,'bound_height_pt':h})
  return s
 def host(self,theme=False,x=60,y=200,w=700,h=72):
  s=self.s.shapes.add_shape(MSO_SHAPE.RECTANGLE,Pt(x),Pt(y),Pt(w),Pt(h));s.fill.solid()
  if theme:s.fill.fore_color.theme_color=MSO_THEME_COLOR.ACCENT_1
  else:s.fill.fore_color.rgb=RGBColor(225,240,232)
  return s
 def scan(self):return scan_hierarchy(self.s,1,{'text_records':self.records})
 def reasons(self):return [f['reason'] for f in self.scan()]
 def test_above_title_small_text_is_discovered_without_role_names(self):
  small=self.text(40,40,300,18,'重复的解释性小引题',14);self.text(40,70,600,40,'主标题',32)
  f=next(x for x in self.scan() if x['reason']=='floating_annotation_review');self.assertIn(small.shape_id,f['shape_ids']);self.assertEqual(f['candidates'][0]['position_hint'],'above_title')
 def test_detached_small_notes_checked_below_and_beside_content(self):
  self.text(40,40,600,40,'主标题',32);a=self.text(400,170,250,20,'在323种评估分子中',16);self.text(400,215,150,60,'53%',46);b=self.text(400,390,280,20,'附加的小字说明',16)
  f=next(x for x in self.scan() if x['reason']=='floating_annotation_review');self.assertEqual(set(f['shape_ids']),{a.shape_id,b.shape_id})
 def test_page_bottom_note_remains_reviewed(self):
  self.text(40,40,600,40,'主标题',32);s=self.text(40,470,600,25,'必要注释应集中在页面底部',16)
  f=next(x for x in self.scan() if x['reason']=='floating_annotation_review');self.assertEqual(f['candidates'][0]['position_hint'],'page_bottom');self.assertIn(s.shape_id,f['shape_ids'])
 def test_metric_context_inside_a_card_still_requires_review(self):
  self.text(40,40,600,40,'主标题',32);self.host(y=150,h=200);note=self.text(80,165,300,20,'在323种评估分子中',16);self.text(80,210,200,70,'53%',46)
  f=next(x for x in self.scan() if x['reason']=='floating_annotation_review');self.assertIn(note.shape_id,f['shape_ids'])
 def test_normal_body_and_page_counter_are_not_small_note_candidates(self):
  self.text(40,40,600,40,'主标题',32);self.text(40,180,700,80,'清楚的正常正文，提供必要内容。',22);self.text(870,500,40,14,'1/1',10)
  self.assertNotIn('floating_annotation_review',self.reasons())
 def test_centered_frames_do_not_hide_downward_text_union(self):
  host=self.host();a=self.text(80,215,420,20,'第一行',16);b=self.text(80,244,400,20,'第二行',16)
  f=next(x for x in self.scan() if x['reason']=='container_text_vertical_balance_review');self.assertEqual(f['shape_ids'],[host.shape_id,a.shape_id,b.shape_id]);self.assertEqual(f['top_gap_pt'],15);self.assertEqual(f['bottom_gap_pt'],8)
 def test_theme_fill_is_a_real_container_candidate(self):
  self.host(theme=True);self.text(80,215,420,20,'第一行',16);self.text(80,244,400,20,'第二行',16)
  self.assertIn('container_text_vertical_balance_review',self.reasons())
 def test_balanced_two_line_union_passes_geometry(self):
  self.host();self.text(80,212,420,20,'第一行',16);self.text(80,240,400,20,'第二行',16)
  self.assertNotIn('container_text_vertical_balance_review',self.reasons())
 def test_duplicate_backgrounds_cannot_remove_all_text_members(self):
  self.host();top=self.host();self.text(80,215,420,20,'第一行',16);self.text(80,244,400,20,'第二行',16)
  fs=[f for f in self.scan() if f['reason']=='container_text_vertical_balance_review'];self.assertEqual(len(fs),1);self.assertEqual(fs[0]['shape_ids'][0],top.shape_id)
 def test_missing_render_measurement_remains_manual(self):
  self.host();self.text(80,220,420,20,'未测量字形',16,False);self.assertIn('container_text_union_measurement_required',self.reasons())
 def test_mixed_diagram_does_not_center_only_its_text(self):
  self.host();self.text(80,244,25,20,'O',16);self.s.shapes.add_shape(MSO_SHAPE.HEXAGON,Pt(200),Pt(210),Pt(45),Pt(40))
  self.assertNotIn('container_text_vertical_balance_review',self.reasons());self.assertIn('container_text_union_measurement_required',self.reasons())
 def test_full_page_fill_not_treated_as_text_card(self):
  self.host(x=0,y=0,w=960,h=540);self.text(40,400,400,30,'独立正文',20)
  self.assertNotIn('container_text_vertical_balance_review',self.reasons())
 def test_low_body_with_large_header_gap_is_flagged(self):
  self.text(40,40,600,40,'主标题',32);self.text(40,245,780,220,'具有完整逻辑关系的主要内容',22)
  self.assertIn('page_content_low_review',self.reasons())
 def test_middle_body_not_flagged_as_bottom_heavy(self):
  self.text(40,40,600,40,'主标题',32);self.text(40,130,780,250,'具有完整逻辑关系的主要内容',22)
  self.assertNotIn('page_content_low_review',self.reasons())
 def test_large_empty_text_frame_cannot_hide_low_visible_content(self):
  self.text(40,40,600,40,'主标题',32);self.text(40,100,780,360,'真正的可见正文位于框的下部',22)
  self.records[-1].update(bound_top_pt=300,bound_height_pt=140)
  self.assertIn('page_content_low_review',self.reasons())
 def test_scientific_baseline_preserved_by_read_only_review(self):
  self.text(40,40,600,40,'化学符号',32);s=self.text(100,180,90,24,'SO4',16);s.text_frame.paragraphs[0].runs[0]._r.get_or_add_rPr().set('baseline','-25000')
  before=s._element.xml;self.scan();self.assertEqual(s._element.xml,before)
 def test_report_json_roundtrip_keeps_geometry(self):
  self.host(theme=True);self.text(80,215,420,20,'第一行',16);self.text(80,244,400,20,'第二行',16);data=self.scan();self.assertEqual(json.loads(json.dumps(data)),data)
 def test_low_cover_title_detected_without_name(self):
  title=self.text(48,122,432,125,'看结构式，能预测气味吗？',44)
  f=next(x for x in self.scan() if x['reason']=='title_entry_position_review');self.assertEqual(f['shape_ids'],[title.shape_id]);self.assertAlmostEqual(f['title_top_ratio'],122/540)
 def test_tightened_cover_title_not_flagged(self):
  self.text(48,78,432,125,'看结构式，能预测气味吗？',44);self.assertNotIn('title_entry_position_review',self.reasons())
 def test_frame_top_cannot_hide_low_actual_title(self):
  self.text(48,40,432,200,'居中后的实际标题',44);self.records[-1]['bound_top_pt']=125
  self.assertIn('title_entry_position_review',self.reasons())
 def test_missing_title_measurement_has_visual_recovery(self):
  self.text(48,130,432,125,'封面标题',44,False)
  f=next(x for x in self.scan() if x['reason']=='title_entry_position_review');self.assertEqual(f['measurement_basis'],'native_frame_requires_visual_measurement')
 def test_title_far_below_old_heading_search_band_still_reviewed(self):
  self.text(48,260,432,100,'下沉的标题',44);self.assertIn('title_entry_position_review',self.reasons())
 def test_numeric_metric_not_mistaken_for_main_title(self):
  self.text(48,38,800,48,'主标题',33);self.text(480,180,300,100,'53%',62);self.assertNotIn('title_entry_position_review',self.reasons())
 def test_background_cannot_hide_effective_content_start(self):
  self.text(40,40,600,40,'主标题',32);self.host(y=110,h=220);body=self.text(80,180,600,80,'正文实际到这里才开始',20)
  f=next(x for x in self.scan() if x['reason']=='effective_content_entry_gap_review');self.assertEqual(f['gap_pt'],100);self.assertIn(body.shape_id,f['shape_ids']);self.assertEqual(f['containing_backgrounds'][0]['inside_gap_pt'],70)
 def test_tight_effective_start_passes_entry_candidate(self):
  self.text(40,40,600,40,'主标题',32);self.host(y=96,h=150);self.text(80,108,600,110,'充分的内容',20);self.assertNotIn('effective_content_entry_gap_review',self.reasons())
 def test_centered_but_empty_card_requires_density_review(self):
  self.host(y=120,h=240);self.text(80,200,600,80,'少量内容',20);self.assertIn('text_container_excess_space_review',self.reasons());self.assertNotIn('container_text_vertical_balance_review',self.reasons())
 def test_compact_card_is_not_empty(self):
  self.host(y=120,h=112);self.text(80,136,600,80,'足够正文',20);self.assertNotIn('text_container_excess_space_review',self.reasons())
 def test_graphics_prevent_text_only_density_guess(self):
  self.host(y=120,h=240);self.text(80,200,80,20,'图内标签',20);self.s.shapes.add_shape(MSO_SHAPE.HEXAGON,Pt(200),Pt(150),Pt(80),Pt(140));self.assertNotIn('text_container_excess_space_review',self.reasons());self.assertIn('container_text_union_measurement_required',self.reasons())
 def test_missing_measurement_remains_recoverable(self):
  self.text(40,40,600,40,'主标题',32);self.host(y=110,h=220);self.text(80,180,600,80,'正文',20,False)
  f=next(x for x in self.scan() if x['reason']=='effective_content_entry_gap_review');self.assertIn('requires_local_and_full_page_review',f['measurement_basis'])
 def test_frame_cannot_advance_actual_body_start(self):
  self.text(40,40,600,40,'主标题',32);self.text(40,95,600,200,'下部正文',20);self.records[-1].update(bound_top_pt=190,bound_height_pt=60);self.assertIn('effective_content_entry_gap_review',self.reasons())
 def test_new_density_findings_roundtrip(self):
  self.text(40,40,600,40,'主标题',32);self.host(y=120,h=240);self.text(80,200,600,80,'正文',20);r=self.scan();self.assertEqual(r,json.loads(json.dumps(r)))

class ProximityTests(unittest.TestCase):
 def items(self,inner=14,outer=10):
  def t(i,y,h,font,x=40):return {'shape_id':i,'bounds_pt':[x,y,x+400,y+h],'font_pt':font,'text':'标题' if font==24 else '正文','measured':True}
  return [t(1,100,28,24),t(2,128+inner,52,20),t(3,180+inner+outer,28,24)]
 def test_body_closer_to_next_title_is_flagged(self):self.assertEqual(len(scan_section_proximity(self.items())),1)
 def test_clear_inner_outer_hierarchy_not_flagged(self):self.assertEqual(scan_section_proximity(self.items(8,26)),[])
 def test_equal_gaps_still_need_semantic_review(self):self.assertEqual(len(scan_section_proximity(self.items(14,14))),1)
 def test_other_column_not_joined(self):
  v=self.items();v[2]['bounds_pt']=[500,204,900,232];self.assertEqual(scan_section_proximity(v),[])
 def test_missing_measurement_preserves_review_path(self):
  v=self.items();v[1]['measured']=False;self.assertEqual(scan_section_proximity(v)[0]['measurement_basis'],'partial_geometry_requires_visual_review')
 def test_measured_report_roundtrip(self):
  v=scan_section_proximity(self.items());self.assertEqual(v,json.loads(json.dumps(v)))

if __name__=='__main__':unittest.main()
