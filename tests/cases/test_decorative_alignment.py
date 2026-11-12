import json,unittest
from pptx import Presentation
from pptx.util import Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor
from audit_visual_components import scan_side_accents

class SideAccentTests(unittest.TestCase):
 def setUp(self):
  self.p=Presentation();self.p.slide_width=Pt(960);self.p.slide_height=Pt(540);self.s=self.p.slides.add_slide(self.p.slide_layouts[6])
 def bar(self,shapes=None):
  q=(shapes if shapes is not None else self.s.shapes).add_shape(MSO_SHAPE.RECTANGLE,Pt(36),Pt(86),Pt(8),Pt(283));q.fill.solid();q.fill.fore_color.rgb=RGBColor(195,80,60);return q
 def text(self,y,h=40,x=76,shapes=None):
  q=(shapes if shapes is not None else self.s.shapes).add_textbox(Pt(x),Pt(y),Pt(400),Pt(h));q.text='真实关联文字';return q
 def test_thin_bar_outside_text_is_discovered(self):
  b=self.bar();a=self.text(105,125);c=self.text(260);d=self.text(332,25);r=scan_side_accents(self.s,1,{})[0]
  self.assertEqual(r['shape_ids'],[b.shape_id,a.shape_id,c.shape_id,d.shape_id]);self.assertEqual(r['endpoint_deltas_pt'],[-19.,12.])
 def test_matching_center_does_not_hide_both_overhanging_ends(self):
  b=self.bar();self.text(105,245);r=scan_side_accents(self.s,1,{})[0]
  self.assertEqual(sum(r['endpoint_deltas_pt']),0);self.assertEqual(r['reason'],'decorative_anchor_relation_review')
 def test_matching_frame_still_requires_actual_ink_review(self):
  b=self.bar();self.text(86,283);r=scan_side_accents(self.s,1,{})[0]
  self.assertEqual(r['endpoint_deltas_pt'],[0.,0.]);self.assertIn('not painted ink',r['measurement_basis'])
 def test_decoration_name_does_not_exempt(self):
  b=self.bar();b.name='background:approved decoration';self.text(105);self.assertEqual(len(scan_side_accents(self.s,1,{})),1)
 def test_unrelated_lower_caption_is_not_silently_added(self):
  self.bar();a=self.text(105);cap=self.text(408);r=scan_side_accents(self.s,1,{})[0]
  self.assertEqual([x['shape_id'] for x in r['possible_text_members']],[a.shape_id]);self.assertNotIn(cap.shape_id,r['shape_ids'])
 def test_empty_association_remains_a_review_candidate(self):
  self.bar();r=scan_side_accents(self.s,1,{})[0];self.assertIsNone(r['text_union_bounds_pt']);self.assertEqual(r['possible_text_members'],[])
 def test_wide_card_is_not_classified_as_thin_side_accent(self):
  b=self.bar();b.width=Pt(100);self.text(105,x=160);self.assertEqual(scan_side_accents(self.s,1,{}),[])
 def test_grouped_accent_cannot_escape_discovery(self):
  g=self.s.shapes.add_group_shape();b=self.bar(g.shapes);self.text(105,shapes=g.shapes);r=scan_side_accents(self.s,1,{})[0]
  self.assertEqual(r['shape_ids'],[g.shape_id]);self.assertEqual(r['accent_shape_id'],b.shape_id);self.assertEqual(json.loads(json.dumps(r)),r)

if __name__=='__main__':unittest.main()
