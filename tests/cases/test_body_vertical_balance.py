"""Actual PDFs exercise both directions and avoid treating empty frames as ink."""
import tempfile
import unittest
from pathlib import Path
from reportlab.pdfgen import canvas
import audit_beamer_layout as audit


class BodyVerticalBalanceTests(unittest.TestCase):
    def render(self, y, band=True, backdrop=False, transparent=None, size=(960,540), card=None):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'page.pdf';c=canvas.Canvas(str(p),pagesize=size)
            scale=size[1]/540;c.scale(scale,scale)
            if band:
                c.setFillColorRGB(.94,.94,.94);c.rect(0,498,960,42,fill=1,stroke=0)
                c.setFillColorRGB(.2,.2,.2);c.setFont('Helvetica',24);c.drawString(36,510,'Title')
            c.setFillColorRGB(.8,.8,.8);c.rect(0,0,960,20,fill=1,stroke=0)
            c.setFillColorRGB(.2,.2,.2);c.setFont('Helvetica',12);c.drawString(450,5,'1/1')
            if backdrop:
                c.setFillColorRGB(.96,.96,.96);c.rect(0,20,960,478,fill=1,stroke=0)
            if card:
                c.setFillColorRGB(.93,.93,.93)
                c.rect(60,400 if card=='compact' else 70,800,80 if card=='compact' else 410,fill=1,stroke=0)
                if card=='graphic':
                    c.setFillColorRGB(.2,.5,.7);c.rect(120,120,500,250,fill=1,stroke=0)
                if card=='full':
                    c.setFillColorRGB(.1,.1,.1);c.setFont('Helvetica',20)
                    for row in (400,350,300,250,200,150,110):c.drawString(80,row,'Actual explanatory content')
            c.setFillColorRGB(.1,.1,.1);c.setFont('Helvetica',20);c.drawString(80 if card else 36,y,'Actual body text')
            if transparent:
                c.saveState()
                if transparent=='fill':
                    c.setFillAlpha(0);c.rect(400,50,20,20,fill=1,stroke=0)
                else:
                    c.setStrokeAlpha(0);c.rect(400,50,20,20,fill=0,stroke=1)
                c.restoreState()
            c.showPage();c.save();return audit.audit_pdf(p)

    def test_top_heavy_body_is_retained_as_candidate(self):
        r=self.render(440);f=next(x for x in r['findings'] if x['category']=='body_vertical_balance_candidate')
        self.assertEqual(f['vertical_balance']['direction'],'top_heavy')
        self.assertEqual(f['status'],'pending_visual_review')
        self.assertFalse(r['signed_off'])

    def test_bottom_heavy_body_is_retained_as_candidate(self):
        r=self.render(70);f=next(x for x in r['findings'] if x['category']=='body_vertical_balance_candidate')
        self.assertEqual(f['vertical_balance']['direction'],'bottom_heavy')

    def test_centered_body_still_needs_visual_review(self):
        r=self.render(260);m=r['pages'][0]['measurements']['body_vertical_balance']
        self.assertFalse(m['candidate']);self.assertEqual(m['status'],'measured_pending_visual_review')
        self.assertEqual(r['visual_review'],'pending')

    def test_large_empty_background_cannot_hide_bias(self):
        r=self.render(440,backdrop=True)
        self.assertIn('body_vertical_balance_candidate',[x['category'] for x in r['findings']])

    def test_cover_without_band_keeps_visual_route(self):
        r=self.render(350,band=False)
        self.assertEqual(r['pages'][0]['measurements']['body_vertical_balance']['status'],'visual_review_required')
        self.assertNotIn('body_vertical_balance_candidate',[x['category'] for x in r['findings']])

    def test_threshold_normalizes_beamer_page_units(self):
        a=self.render(440);b=self.render(440,size=(480,270))
        x=a['pages'][0]['measurements']['body_vertical_balance'];y=b['pages'][0]['measurements']['body_vertical_balance']
        self.assertAlmostEqual(x['gap_difference_normalized_540'],y['gap_difference_normalized_540'],places=2)
        self.assertEqual(x['direction'],y['direction'])

    def test_transparent_fill_cannot_hide_bias(self):
        r=self.render(440,transparent='fill')
        self.assertTrue(r['pages'][0]['measurements']['body_vertical_balance']['candidate'])

    def test_transparent_stroke_cannot_hide_bias(self):
        r=self.render(440,transparent='stroke')
        self.assertTrue(r['pages'][0]['measurements']['body_vertical_balance']['candidate'])

    def test_800pt_card_cannot_hide_sparse_top_text(self):
        r=self.render(440,card='sparse')
        self.assertFalse(r['pages'][0]['measurements']['body_vertical_balance']['candidate'])
        f=next(x for x in r['findings'] if x['category']=='body_container_content_review')
        self.assertTrue(f['container_balance']['candidate'])
        self.assertGreater(f['container_balance']['lower_gap_pt'],300)
        self.assertEqual(f['status'],'pending_visual_review')

    def test_filled_text_container_keeps_visual_review_without_false_bias(self):
        r=self.render(440,card='full')
        self.assertNotIn('body_container_content_review',[x['category'] for x in r['findings']])
        self.assertTrue(r['pages'][0]['measurements']['body_content_containers'])
        self.assertEqual(r['visual_review'],'pending')

    def test_graphic_inside_card_is_preserved_and_independently_reviewed(self):
        r=self.render(440,card='graphic')
        f=next(x for x in r['findings'] if x['category']=='body_container_content_review')
        self.assertTrue(f['container_balance']['graphic_object_ids'])
        paths=r['pages'][0]['inventory']['paths']
        self.assertTrue(set(f['container_balance']['graphic_object_ids']).issubset({x['id'] for x in paths}))
        self.assertFalse(f['container_balance']['candidate'])

    def test_centered_sparse_text_card_still_gets_content_candidate(self):
        r=self.render(260,card='sparse')
        f=next(x for x in r['findings'] if x['category']=='body_container_content_review')
        self.assertFalse(f['container_balance']['vertical_bias_candidate'])
        self.assertTrue(f['container_balance']['sparse_text_candidate'])
        self.assertEqual(f['status'],'pending_visual_review')

    def test_compact_text_card_does_not_get_large_empty_region_candidate(self):
        r=self.render(440,card='compact')
        self.assertNotIn('body_container_content_review',[x['category'] for x in r['findings']])
        m=r['pages'][0]['measurements']['body_content_containers'][0]
        self.assertFalse(m['sparse_text_candidate'])
        self.assertEqual(m['status'],'measured_pending_visual_review')

if __name__=='__main__':unittest.main()
