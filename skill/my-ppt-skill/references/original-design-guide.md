# 模式 C：完全原创 PPT 设计原则

> **强制交付门槛：** 执行 [本地交付标准](local-delivery-quality.md)、[完整布局检查](layout-integrity.md) 和 [签核流程](signoff-workflow.md)。模板风格不能优先于可读性；签核默认全量，严格增量条件见签核流程。

当用户明确要求"不要用模板 / 原创设计 / 简单干净"时走本流程。

## 顶层原则

> **内容完整、可读、均衡；复杂度服务于表达。**

模式 C 按内容需要组织页面，允许复杂图标、可编辑多图表和分支流程，不以删减信息或大片空白换取排版方便。

## 不要做的事

- 复杂图标和图解可以使用；避免无信息价值的装饰堆砌
- 不要用超过 1 个主色 + 1 个强调色
- 不设每页 4 个信息点的硬限制；信息丰富时使用分栏、图解和层级组织
- 不要混搭风格（既复古又卡通）
- 不要用奇怪的字体（华文琥珀、隶书、楷体等装饰字体）
- 避免无意义卡片嵌套；必要技术层级可以使用真实容器表达，内外分别验收

## 推荐做的事

- 4:3 或 16:9 标准画布
- 均衡留白，外边距遵守本地标准；避免单侧大片闲置
- 每页保留完整逻辑，不因元素数量限制删掉必要例证与步骤
- 主色 1 个 (#1F3A68 / #2C3E50 / #B22222 之类的稳重色)
- 字体：
  - 中文：微软雅黑 / 思源黑体 CN
  - 英文：Inter / Helvetica / Arial
  - 代码、命令、配置和日志：可用 Consolas 等等宽字体，按语言合理高亮；保持缩进、对齐和对比度，详见本地交付标准的代码排版规则
  - 标题加粗，正文常规，不用斜体
- 页标题建议 26–32 pt，短标题 16–22 pt；正文通常 14–18 pt，密集页可用 12–14 pt，最低 12 pt；页码最低 10 pt；禁止其他页尾与脚注，来源放入备注。
- 颜色对比：纯白底 + 深色文字 / 深色底 + 纯白文字

## 推荐版式（按内容类型）

| 内容类型 | 版式 |
|---|---|
| 封面 | 已确认需要时制作；主标题，必要时补充日期/真实作者，副标题按需 |
| 目录 | 居中竖排：序号 + 章节名（无图标无装饰） |
| 章节扉页 | 全屏居中：超大序号 + 章节标题 |
| 单一观点 | 判断配必要证据，不靠一句话拆页稀释信息 |
| 3 个并列要点 | 横向 3 列（图标可选 + 标题 + 1-2 行说明） |
| 5+ 个并列要点 | 改成纵向列表（每行一个） |
| 对比 | 2 列对照（左 / 右）+ 中间分隔线 |
| 时间线 | 横向轴 + 节点 |
| 数据 | 按比较/趋势/关系选择图表，必要时搭配关键指标 |
| 结束 | 优先实质结论；用户需要且篇幅允许才采用致谢/交流页 |

## 代码模板

```python
from pptx import Presentation
from pptx.util import Cm, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

prs = Presentation()
prs.slide_width = Cm(33.87)   # 16:9
prs.slide_height = Cm(19.05)

PRIMARY = RGBColor(0x1F, 0x3A, 0x68)
GREY = RGBColor(0x66, 0x66, 0x66)

def add_textbox(slide, text, *, left, top, width, height,
                size_pt=24, bold=False, color=PRIMARY, align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(Cm(left), Cm(top), Cm(width), Cm(height))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = "Microsoft YaHei"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.color.rgb = color
    return tb

blank = prs.slide_layouts[6]  # blank layout

# 封面
s = prs.slides.add_slide(blank)
add_textbox(s, "2026 年度产品规划", left=4, top=7, width=26, height=2.5,
            size_pt=44, bold=True, align=PP_ALIGN.CENTER)
add_textbox(s, "ACME · 产品部 · 2026.05", left=4, top=10, width=26, height=1.2,
            size_pt=18, color=GREY, align=PP_ALIGN.CENTER)

# 3 列要点
s = prs.slides.add_slide(blank)
add_textbox(s, "本季度三大重点", left=2, top=1.5, width=29, height=1.5,
            size_pt=32, bold=True)
for i, (title, body) in enumerate([
    ("用户增长", "新增 200 万 DAU\n留存提升 8 pp"),
    ("商业化", "广告 ROI +20%\n会员转化 +15%"),
    ("效率", "迭代周期减少 30%\n生产事故 0 起"),
]):
    x = 2 + i * 10
    add_textbox(s, title, left=x, top=5, width=8, height=1.5, size_pt=22, bold=True)
    add_textbox(s, body, left=x, top=7, width=8, height=4, size_pt=18, color=GREY)

prs.save("out.pptx")
```

## 何时该提示用户考虑用模板

如果用户的需求是：
- 需要颜色丰富 / 插画风 / 漂亮的视觉
- 需要图标 / 装饰元素
- 需要展示给客户 / 领导（要"够格"）

用户尚未明确拒绝模板且该建议有实际帮助时，可建议（用户已明确选原创则直接执行）：

> "我手头有 21 套精心整理的模板（含党政、商务、教学、答辩、述职等），其中 X 风格 / Y 风格更适合您的场景。要不要先看一下预览图？"

内置模板是默认选项；用户明确选择原创后不重复要求改选模板。
