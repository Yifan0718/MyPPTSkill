# 模式 B：用户自带 PPT 模板

> **强制交付门槛：** 执行 [本地交付标准](local-delivery-quality.md)、[完整布局检查](layout-integrity.md) 和 [签核流程](signoff-workflow.md)。模板风格不能优先于可读性；签核默认全量，严格增量条件见签核流程。

当用户提供一份自己的 `.pptx`，希望以它为基底产出新 PPT 时按本流程走。

## 核心原则

- **永远不直接修改用户原文件**，所有产出写到新路径
- **每页都先看渲染图**，再凭文本与形状信息推断页面角色
- 对模板里"宣传 / 介绍模板自身"的页面（"稻壳儿 / 模板使用说明 / 感谢下载"等）一律跳过
- 默认保留模板视觉系统；不当换行、过小字号、错位或溢出必须调整布局、框宽及同级字号，不能保留模板缺陷

## 步骤

### B1. 渲染用户模板，目测每页

```bash
USR_PPTX="<user-provided.pptx>"
WORK=work/user-template

python3 scripts/render_slides.py "$USR_PPTX" "$WORK/renders" --dpi 144
# 产出 $WORK/renders/slide-XX.png
```

逐张看图，给每页打标签：cover / agenda / section_divider / content / ending / template_promo。

### B2. 用 python-pptx 现场探查 shape & run 结构

模式 B 没有现成的 `detail.json`，AI 需要直接用 `python-pptx` 读取每页的 shape_id / paragraph / run 结构，定位想要修改的文本。

```python
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def walk(shapes, indent=0):
    for sh in shapes:
        tag = "GROUP" if sh.shape_type == MSO_SHAPE_TYPE.GROUP else "SHAPE"
        text = sh.text_frame.text if sh.has_text_frame else ""
        print(f"{'  '*indent}{tag} id={sh.shape_id} {text[:40]!r}")
        if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
            walk(sh.shapes, indent + 1)


prs = Presentation("user.pptx")
for i, slide in enumerate(prs.slides, 1):
    print(f"\n=== slide {i} ===")
    walk(slide.shapes)
```

把这个输出 + 每页渲染图发给 AI（或自己看），就能锁定要改的 `shape_id / paragraph / run`。

### B3. 直接用 explicit address 写 edits.json

对模式 B，**跳过 `slot_id`**，直接在 edits 里写 `address`：

```json
{
  "selected_slides": [1, 4, 7, 9],
  "edits": [
    {
      "slide": 1,
      "address": {"shape_id": 12, "paragraph": 0, "run": 0},
      "expected_text": "PPT 模板标题",
      "new_text": "2026 年度战略规划"
    }
  ]
}
```

完整 schema 见 `references/pptx-edit-schema.md`。

### B4. 应用

```bash
python3 scripts/build_pptx.py "$USR_PPTX" edits.json output.pptx --strict
python3 scripts/render_slides.py output.pptx work/preview --dpi 144
# 看每页确认无误
```

## 启发式：怎么判断角色

| 页面特征 | 大概率角色 |
|---|---|
| 只有一个大标题 + 一段副标，居中布满 | cover / section_divider / ending |
| 出现 "目录 / Contents / Agenda" + 多个章节编号 | agenda |
| 文字含 "稻壳儿 / WPS / 模板 / 下载" 等 | template_promo（不要用） |
| 顶部小字章节标题 + 主体多列结构 | content（章节内页面） |
| Thank / 感谢 / 结束 | ending |

把握不准的页面：**保守跳过**，只选你能 100% 看懂的页。

## 关于"识别每一页 PPT 模板的排版"

用户带来的模板，AI 需要分析 **每页的版式特征**，包括：

- 主要文字块数量（1 / 2-3 / 4+ / 多列）
- 是否有图片占位、图标
- 文字的相对面积占比（满版文字 vs 小标题 + 大图）
- 装饰元素（线条 / 形状 / 背景图案）

参考内置模板的 `intro.md` 与 `detail.json` 的写法，给自己留一份简短的笔记，再写 edits.json。
