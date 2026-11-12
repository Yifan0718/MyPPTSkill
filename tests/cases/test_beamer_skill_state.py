import tempfile
import unittest
from pathlib import Path
import skill_state

class BeamerState(unittest.TestCase):
    def test_theme_and_data_edits_invalidate_frozen_skill(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)/'skill'; root.mkdir()
            (root/'SKILL.md').write_text('rules')
            for name in ('theme.tex','drawing.tikz','theme.sty','data.csv','latexmkrc'):
                (root/name).write_text('before')
            lock = Path(td)/'lock.json'; skill_state.snapshot(lock,root)
            self.assertEqual(skill_state.check(lock,root)['status'],'unchanged')
            for name in ('theme.tex','drawing.tikz','theme.sty','data.csv','latexmkrc'):
                (root/name).write_text('after')
            result = skill_state.check(lock,root)
            self.assertEqual(result['status'],'changed')
            self.assertEqual(set(result['changed_files']),{'theme.tex','drawing.tikz','theme.sty','data.csv','latexmkrc'})

    def test_generated_log_does_not_change_rule_lock(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'skill'; root.mkdir();(root/'SKILL.md').write_text('rules')
            lock=Path(td)/'lock.json';skill_state.snapshot(lock,root)
            (root/'deck.log').write_text('warning')
            self.assertEqual(skill_state.check(lock,root)['status'],'unchanged')

    def test_bundled_font_binary_and_license_are_frozen(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'skill';font=root/'assets/fonts/a.otf';font.parent.mkdir(parents=True)
            font.write_bytes(b'font bytes');license=font.parent/'COPYING';license.write_text('license')
            lock=Path(td)/'lock.json';skill_state.snapshot(lock,root)
            font.write_bytes(b'changed font');license.write_text('changed license')
            self.assertEqual(set(skill_state.check(lock,root)['changed_files']),{'assets/fonts/a.otf','assets/fonts/COPYING'})

if __name__=='__main__': unittest.main()
