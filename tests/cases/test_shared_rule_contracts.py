"""Cross-entrypoint contracts for user requirements shared by both backends."""
import json
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
def read(name):return (ROOT/name).read_text(encoding='utf-8-sig')

class SharedRuleContracts(unittest.TestCase):
    def test_speaker_numeric_notation_is_checked_in_source_and_render(self):
        text=read('references/speaker-notes.md')
        self.assertIn('数值、数量、页码和步骤编号直接使用阿拉伯数字',text)
        self.assertIn('阿拉伯数字写法与数值',text)
        self.assertIn('再核对数字写法',text)

    def test_font_failure_route_preserves_exact_font_policy(self):
        main=read('SKILL.md');workflow=read('references/workflow.md')
        self.assertIn('不能以名称相近的字体别名静默替换',main)
        self.assertNotIn('配置 fontconfig 别名',workflow)
        self.assertIn('原字体文件、安装与发现路径',workflow)
        self.assertIn('bundled-fonts.md',workflow)

    def test_both_slide_backends_reach_shared_hierarchy(self):
        self.assertIn('presentation-hierarchy.md',read('SKILL.md'))
        self.assertIn('presentation-hierarchy.md',read('references/beamer-workflow.md'))
        hierarchy=read('references/presentation-hierarchy.md')
        for required in ('50%','75%','同一语义层级统一字体家族、字形样式和字号','页码的10pt绝对下限不构成比例豁免'):
            self.assertIn(required,hierarchy)
        self.assertIn('投影字号比例约束只用于Slides',read('references/speaker-notes.md'))

    def test_auxiliary_notes_do_not_reclassify_essential_explanations(self):
        hierarchy=read('references/presentation-hierarchy.md')
        for required in ('关键口径','API缩写释义','集中页底','不能局部缩小一段正文','真实特殊对象'):
            self.assertIn(required,hierarchy)

    def test_cover_density_exception_keeps_visual_checks(self):
        text=read('references/presentation-hierarchy.md')
        self.assertIn('部分豁免正文页的信息密度和空区约束',text)
        self.assertIn('色块内的字形居中',text)
        self.assertIn('不能把此例外扩展到正文页',text)

    def test_latex_routes_require_pdf_direct_link_and_source(self):
        for name in ('SKILL.md','references/speaker-notes.md'):
            self.assertIn('latex-delivery.md',read(name))
        text=read('references/latex-delivery.md')
        self.assertIn('PDF的直达打开链接',text)
        self.assertIn('原始可编辑源码',text)

    def test_shared_user_rules_stay_in_update_protection(self):
        registry=json.loads(read('local-overrides/registry.json'))
        for path in ('references/workflow.md','references/speaker-notes.md','references/presentation-hierarchy.md','references/latex-delivery.md','references/scientific-visualization.md','references/affirmative-first-writing.md','references/bundled-fonts.md'):
            self.assertIn(path,registry['protected_paths'])

    def test_original_design_uses_widescreen_default(self):
        text=read('references/original-design-guide.md')
        self.assertIn('新建和重做整套默认采用16:9画布',text)
        self.assertNotIn('4:3 或 16:9',text)

    def test_unknown_template_layout_preserves_required_content(self):
        text=read('references/custom-template-workflow.md')
        self.assertNotIn('保守跳过',text)
        self.assertIn('用户要求保留的内容须迁移并核对完整性',text)
        self.assertIn('不能仅凭',text)

if __name__=='__main__':unittest.main()
