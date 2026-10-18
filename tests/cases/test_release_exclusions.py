import unittest,tempfile,json
from pathlib import Path
import local_update_guard as guard
class ReleaseExclusions(unittest.TestCase):
 def test_new_developer_artifacts_filtered(self):
  for rel in ('CHANGELOG.md','.gitignore','.gitattributes','scripts/test_new.py','scripts/test_new.ps1','scripts/example.pptx'):
   self.assertTrue(guard.release_artifact_excluded(rel),rel)
 def test_runtime_and_real_templates_retained(self):
  for rel in ('SKILL.md','LICENSE','NOTICE.md','scripts/verify_coverage_review.py','scripts/prepare_pptx_delivery.ps1','templates/demo/template.pptx','templates/demo/preview.png','references/test_methods.md'):
   self.assertFalse(guard.release_artifact_excluded(rel),rel)
 def test_user_protection_takes_priority_in_apply(self):
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);live=base/'live';candidate=base/'candidate';stage=base/'stage'
   for root in (live,candidate):
    (root/'scripts').mkdir(parents=True)
    (root/'SKILL.md').write_text('fixture entry')
    (root/'VERSION').write_text('1.0.0' if root==live else '1.0.1')
   rule='scripts/test_user_requirement.py'
   (live/rule).write_text('explicit user customization')
   (candidate/rule).write_text('upstream replacement')
   guard.prepare(live,stage,candidate)
   (stage/'review.json').write_text(json.dumps({'status':'approved_no_conflict','conflicts':[],'reviewed_by':'isolated fixture'}))
   guard.apply(live,stage)
   self.assertEqual((live/rule).read_text(),'explicit user customization')
