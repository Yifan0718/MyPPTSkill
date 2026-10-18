import copy,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from verify_coverage_review import validate_center_alignment_review
from measurement_fallback import eligible_code

class CenterReviewGate(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name);self.page=r/'page.png';self.crop=r/'crop.png'
        im=Image.new('RGB',(400,300),'white');d=ImageDraw.Draw(im);d.ellipse((110,60,290,240),fill='navy');d.ellipse((140,90,260,210),fill='white');d.text((180,145),'12 kW',fill='navy');im.save(self.page);im.crop((100,50,300,250)).save(self.crop)
        self.f={'reason':'centered_text_visible_host_review','measurement_status':'measured_aligned','chart_audit_path':'3','text_audit_paths':['4'],'crop_box_px':[100,50,300,250],'delta_px':[0,0],'tolerance_px':2}
        self.r={'center_alignment_contract':{'chart_audit_path':'3','text_audit_paths':['4'],'reference':'visible_host_or_hole','center_observation':'Synthetic current-pixel protocol fixture, not a real PowerPoint visual signoff.','internal_group_observation':'The synthetic value and unit are reviewed together as one complete semantic label.'},'detail_evidence':{'path':str(self.crop),'crop_box_px':[100,50,300,250]}}
    def tearDown(self):self.tmp.cleanup()
    def check(self):return validate_center_alignment_review(self.f,self.r,self.page)
    def test_measured_alignment_and_current_crop(self):self.assertIsNone(self.check())
    def test_known_offset_cannot_be_waived(self):self.f['measurement_status']='measured_misalignment';self.r['object_relation']='data-positioned labels';self.assertIsNotNone(self.check())
    def test_claimed_aligned_with_bad_delta_still_fails(self):self.f['delta_px']=[0,14];self.assertIsNotNone(self.check())
    def test_frame_center_is_not_visible_center(self):self.r['center_alignment_contract']['reference']='PlotArea';self.assertIsNotNone(self.check())
    def test_missing_group_member_fails(self):self.f['text_audit_paths'].append('5');self.assertIsNotNone(self.check())
    def test_unrelated_local_pixels_fail(self):Image.new('RGB',(200,200),'white').save(self.crop);self.assertIsNotNone(self.check())
    def test_crop_cannot_omit_host(self):self.r['detail_evidence']['crop_box_px']=[150,100,250,200];self.assertIsNotNone(self.check())
    def test_unknown_is_pending_and_has_evidence_fallback(self):
        self.f['measurement_status']='manual_review_required';error=self.check()
        self.assertEqual(error,'Visible host contour or hosted text ink is unmeasurable');self.assertEqual(eligible_code('center',error),'uncertain_visible_center')

if __name__=='__main__':unittest.main()
