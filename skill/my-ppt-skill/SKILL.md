---
name: my-ppt-skill
description: >-
  用 21 套内置中文 PPT 模板（或用户自带的 .pptx 模板）生成与编辑 PowerPoint 演示文稿：保留模板风格，修复不当换行、过小字号及对齐问题，必须实际渲染并逐页验收；也支持完全原创的简洁版式。当用户要"做 / 生成 / 制作 / 编辑一份 PPT / 演示文稿 / 幻灯片 / .pptx"，或需要工作汇报、年终与季度总结、述职竞聘、项目复盘、开题答辩、商务提案、教学课件、数据可视化等成品 PPTX 时使用。Use when the user wants to create or edit a PowerPoint / PPT / slides / .pptx deck, pick from built-in templates, or apply their own template with readable typography and verified layouts.
---

# MyPPTSkill

> **上游基线版本** 见同目录 [`VERSION`](./VERSION)；定制规则以当前安装内容为准。

---

## 执行顺序与规则入口

本 Skill 保留模板风格，但不保留模板缺陷。以下本地定制优先于模板或上游资料中的“不改排版”“保持原字号”“轻微超框”“渲染可选”等冲突建议。用户当前明确要求优先；普通单稿反馈不自动成为长期规则。

1. **确认需求与选模板。** 制作整套前，未明确的封面、篇幅必须询问；大纲仅在实质不清楚时询问，已知信息不重复问。执行下文三模式与 [本地交付标准](references/local-delivery-quality.md) 的需求、内容、字号、边距和元数据规则。不得删关键内容或机械增页规避排版。
2. **检查更新并冻结版本。** 本会话首次使用执行 `python scripts/check_update.py`；失败不得称“已是最新”。更新仅用保护入口，规则冲突显式向用户确认；参见 [更新保护](references/local-delivery-quality.md#更新时保留本地规则)。最终迭代前按 [冻结流程](references/layout-integrity.md#冻结skill后再迭代和签核) 建立版本锁。
3. **规划内容和布局。** 先按[首次阅读与案例](references/audience-and-evidence.md)建立读者可理解的术语、指标和代表性示例，并用[修订闭环](references/revision-control.md)追踪用户反馈及影响范围。 叙事按用途参照 [叙事选择流程](references/narrative-reference.md)，不机械写成宣传稿。执行 [全页覆盖与反规避验收](references/layout-integrity.md)：统一锚点、真实间距、所有位置可见字形边缘、混合字体局部检查；不得自授免检。分析型多页稿搭配多种有任务的图表和图标，科研绘图按需读 [工具选择](references/scientific-visualization.md)。
4. **渲染、修复、反复核验。** 最终渲染前按 [第一页缩略图与普通视图](references/delivery-shell.md) 准备交付外壳；PowerPoint默认后台无窗口运行。 所有页面初始 `suspected_unverified`。必须规则与视觉交叉检查；所有原生连线、箭头及图内连接按 [连接完整性](references/connector-integrity.md) 逐根逐端检查。自动通过不能代替局部和整页可视化。版式规则未通过或测不准时，保留原结果，执行 [局部＋整页独立视觉兜底](references/signoff-workflow.md#版式规则未通过时的视觉兜底)；真实视觉合格且独立复核完成可以关闭对应拦截，不要求所有版式数值机械通过。实际可见缺陷须修正，未解决项不得签核；拦截必须接续复核、修复或替代流程，不能作为停工理由。
5. **签核后交付。** 最终使用 `scripts/verify_delivery.py` 同时汇总版式证据和首次阅读证据；原 `verify_coverage_review.py` 继续作为版式证据检查器。 按 [签核范围与证据流程](references/signoff-workflow.md) 处理错误、版本、全量双遍视觉检查及发布。默认必须全量所有页；仅已全量签核后用户指出局部问题的修订可按该文件的严格增量条件处理。缺证据、未解决项、失败或未知状态均不得发布。

以上引用按对应阶段开始前读取并执行；仅调研、讨论或生成待确认大纲时，执行需求/叙事/读者准备规范，暂不启动依赖最终PPTX的渲染与签核。实际制作交付时完整执行全部阶段，不能以准备阶段例外跳过成品检查。技术能力说明不改变质量门槛。字号 12/10/8 pt 的适用范围及 8 pt 先实际尝试 10 pt 的证据链，统一以 [字号和可读性](references/local-delivery-quality.md#字号和可读性) 为准。验收日志仅留工作目录，不能写入 PPT 或备注。

> **模板素材许可**：内置 PPT 模板视觉素材仅供上游许可范围内的个人学习和研究，禁止未经授权的商业使用；分发须遵守上游及原作者限制。代码、规则与文档按各自 MIT 许可处理，不能把代码许可扩展到模板素材。Fork 来源及许可分层见 [许可说明](docs/LICENSE_SCOPE.md)。

## 何时使用本 Skill

当用户的需求满足下列任何一项就调用本 Skill：

- 需要"做一份 PPT / 演示文稿 / 幻灯片"，无论是工作汇报、年终总结、季度复盘、项目提案、述职竞聘、教学课件、开题答辩、读书报告……
- 用户给了文字大纲或一段描述，希望"做成 PPT"
- 用户拿来一份 .pptx 文件，希望"按这个模板做一份新的"
- 用户希望"调整 / 编辑 PPT 的某些文字"，且要求"不破坏排版"
- 用户希望对比多个 PPT 模板，选一个合适的

## 三种模式

收到用户需求后，先判断走哪种模式：

### 模式 A：从内置模板里挑

**默认走这条路。** 21 套内置模板覆盖了绝大多数中文场景。

1. **读 [`templates/INDEX.md`](./templates/INDEX.md)** ——一份精简清单，列出每套模板的风格、主色、适用场景、页数。
2. **匹配用户输入** —— 把用户描述（场景、风格关键词、所需页面类型、颜色偏好）和每个模板的 intro.md 对比。
3. **选模板的决策规则**：
   - **用户已明确指定模板** → 直接用。
   - **你高度确信只有 1 个模板最合适**（场景 + 风格 + 主色都强匹配，且明显优于其它）→ 可直接用，但开工前一句话告诉用户你选了哪个、为什么，给用户一个否决的机会。
   - **其余所有情况（用户没指定，或你不能完全把握哪个最合适）→ 必须让用户来选**：
     - 用当前可用的用户询问工具（无该工具则直接提问）通常提供 **3 个**候选模板，每个附上一句话理由（风格 / 适用场景 / 页数），并**把对应的 `templates/<slug>/preview.png` 一并展示**给用户看图决策。剩余有效候选不足 3 个时展示实际数量，不重复或虚构模板凑数。
     - 有更多候选时额外提供「都不满意，换一批」。用户选它时，再按匹配度给出最多 3 个没出现过的候选（同样附预览图）。候选用尽时进入下一条，不提供无法兑现的换批选项。
     - 候选都用尽仍不满意 → 询问用户更具体的偏好（风格 / 颜色 / 场景），或转模式 C 原创。
   - ⚠️ 不要在没让用户看预览图的情况下，仅凭模糊匹配就自作主张定一个模板。
4. **拿到目标模板后**：
   - 读 `templates/<slug>/intro.md`（高度浓缩，告诉你这个模板的特性）
   - 读 `templates/<slug>/detail.json`（结构化数据，告诉你每页 / 每个文本位的细节）
   - 按 [模式 A 工作流](./references/workflow.md#mode-a) 选页、写 `edits.json`、跑 `build_pptx.py`

### 模式 B：用户自己带 PPT 模板

当用户提供了 .pptx 文件且明确希望以它作模板时：

1. 把用户的 pptx 当作"未知模板"
2. 用 `scripts/render_slides.py` 把每页渲染成 PNG，再用 `python-pptx` 现场探查每页的 shape / paragraph / run 结构（无需额外脚本）
3. 自己看每页（PNG + shape 输出）：
   - 推断每页是什么角色（封面 / 目录 / 章节扉页 / 内容页 / 结束 / 模板宣传）
   - 推断每页适合放什么内容
   - 跳过模板宣传 / "稻壳儿" / 感谢下载 之类
4. 按 [模式 B 工作流](./references/custom-template-workflow.md) 用 explicit `address` 写 `edits.json` 选页 + 文字替换
5. **不要修改用户模板原文件**；所有改动写到新的 output.pptx

### 模式 C：完全原创（不基于任何模板）

当用户明确要求"原创设计 / 不用模板 / 简单干净的样式"时：

1. **按内容组织版式** —— 内容充实、对齐严格、留白均衡，不默认追求极简
2. 不限制为 4 个元素；允许复杂图标、图表和图解，保证信息层级与视觉均衡
3. 字体：英文 Arial / Helvetica；中文 微软雅黑 / 思源黑体；标题加粗即可
4. 主色 1 个，可有 1 个必要强调色，加灰阶和白底；不要拼凑多种风格
5. 用 `python-pptx` 直接代码生成，参考 [`references/original-design-guide.md`](./references/original-design-guide.md)

## 编辑铁律（所有模式通用）

1. **保留视觉风格，修复可读性** —— 默认保留模板风格；遇到不当换行、过小字号、溢出或错位，按本地交付标准调整框宽、列宽、同级字号和对齐，不保留模板缺陷。
2. **所有占位文字必须替换** —— 模板里的 "Question 1" / "Vivamus..." / "Key Words Here" / "项目名称" 等占位文本都必须用真实内容替换。一份完成的 PPT 里不应出现任何示例占位词。
3. **`max_chars` 是软性参考，不是硬性上限；严禁用省略号截断** —— detail.json 每个 slot 的 `max_chars` / `chars_per_line` / `max_lines` 是按文本框尺寸估算的容量，**仅供参考**，帮助你把握"这格大概能放多少字"。
   - 优先写**自然、完整、精炼**的文字。允许超过估算字符容量，但真实渲染不得溢出；容量估计不是可见边界。
   - **绝对禁止为了凑数而砍掉后半句、在结尾加 `...` / `…` / `等等` 来硬凑长度** —— 截断与实际超框都不能通过验收。
   - 真的太长时，按优先级处理：① 用更精炼的措辞**重写**（真正的概括，不是切断）；② 合并重复表达而保留全部必要信息，或换更大空间的版式；③ 仍放不下时调整布局或换页型，必须消除实际溢出，不得截断或省略。
   - `build_pptx.py` 的出框检测**只是提示、不阻断**保存。`--strict` 仅校验 expected_text 是否与模板一致，不负责判断实际超框。`capacity_unknown:true` 的槽测不准，凭目测把握。
4. **装饰序号默认保留，事实与页码必须同步** —— `editable: false` 是模板编辑提示，不可用于保留错误页码、数据或章节顺序；页码按本地规则重算 `x/y`，有事实含义的数字随内容同步，纯装饰编号无变更需求时保持。
5. **图形 / 图表通常无法同步** —— 装饰性的进度条 / 圆环 / 旗帜路径 / 流程箭头是固定形状；改了百分比文字不会改弧长。每个模板 detail.json 里如有这类页面会在 `cautions` 字段列出。
6. **真实数据图表才能改数据** —— 对 PPT 原生分类图表，在 edits.json 的编辑项内提供 `chart_data`，由 `build_pptx.py` 更新；没有 `--chart-data` 命令行参数。XY 散点图使用 `XyChartData`，不走分类数据接口。更新后核查刻度、单位、标签和注释；详见 [`references/chart-editing.md`](./references/chart-editing.md)。
7. **章节名前后呼应** —— 改了目录章节名，对应的分章扉页 + 内容页面包屑文字都要同步改。
8. **封面按已确认需求，其他页面按内容组织** ——
   - 制作前确认是否需要独立封面。需要时优先使用 `page_roles.cover`；模板没有封面时，根据正文配色、字体、比例及视觉语言生成独立封面，不随意从其他模板拼接。用户不需要时跳过封面。不能把一张正文页冒充封面。
   - 如果 `ending` 数组为空，**直接以最后一张内容页收尾**，不要硬造"感谢聆听"。
   - 同理，`agenda` 空 → 不强加目录；`section_divider` 空 → 不强加分章扉页。
   - 封面计入已确认总页数，除非用户明确要求“正文 N 页另加封面”。独立封面与正文一起参与全页渲染、逐页检查和 signoff；同样遵守页尾、语言与排版规则。
9. **同级标题字号必须一致，不要逐处改字号** ——
   - detail.json 顶部有 `type_scale`（字号层级表，level 1 = 最大），每个 slot 标了 `level`。**同一 level 的文字使用一致字号；模板字号过小时按本地默认下限统一调整。**
   - 某处文字偏长时，用**更精炼的措辞重写**来控制长度（见第 3 条），**不要把这一处字号改小**，也不要截断加省略号；必须保留全文时加宽文本框并修复相邻对齐。
   - 选多页拼一份 PPT 时，让各页同 level 的标题用词长度相近，整体才齐整。

## 最小构建示例（不是签核流程）

```bash
# 1. 从 templates/INDEX.md 选定一个模板，例如 minimal-business-summary
TEMPLATE=templates/minimal-business-summary

# 2. 读两个文件
#    - $TEMPLATE/intro.md     -> 模板风格 / 适用场景 / 结构概述
#    - $TEMPLATE/detail.json  -> 每页 / 每个文本位的详细描述

# 3. 自己决定要用哪些页（用 detail.json 的 page.role 和 use_for）
#    生成 edits.json：
#    {
#      "template_slug": "minimal-business-summary",
#      "selected_slides": [1, 2, 3, 5, 7, 9, 10, 12, 13, 14, 16],
#      "edits": [
#        {"slide": 1, "slot_id": "cover_title_cn", "new_text": "2026 年度复盘"},
#        ...
#      ]
#    }

# 4. 跑构建（--strict 校验 expected_text；长度估算只作提示，实际超框必须渲染修复）
python3 scripts/build_pptx.py \
    $TEMPLATE/template.pptx \
    edits.json \
    out/final.pptx \
    --detail $TEMPLATE/detail.json

# 5. 必须渲染最终候选 PPTX 的全部页面并逐页检查；修复后重新渲染
python3 scripts/render_slides.py out/final.pptx out/renders --dpi 144
```

## 目录结构

```
my-ppt-skill/
├── SKILL.md               ← 本文件
├── VERSION                ← 当前版本号
├── updates.json           ← 机器可读版本增量索引
├── manifest.json          ← 所有文件的 sha256 与版本归属
├── README.md              ← 仓库概览（用户阅读）
├── scripts/
│   ├── build_pptx.py          # 按 edits.json 选页 + 换字 → 输出 pptx（含出框检测）
│   ├── render_slides.py       # pptx → PDF → 每页 PNG（预览/自检）
│   ├── compute_capacity.py    # 由 template.pptx 计算每个 slot 的容量字段（数据准备）
│   ├── check_update.py        # 检查远端是否有更新
│   ├── apply_update.py        # 暂存、审查并保护本地定制的更新入口
│   └── build_manifest.py      # 重建 manifest.json
├── references/
│   ├── workflow.md
│   ├── pptx-edit-schema.md
│   ├── custom-template-workflow.md
│   ├── chart-editing.md
│   └── original-design-guide.md
└── templates/
    ├── INDEX.md
    └── <slug>/
        ├── template.pptx
        ├── intro.md       # 高度浓缩简介
        ├── detail.json    # 详细页面 / slot 数据（含容量字段 + type_scale）
        └── preview.png    # 当前模板第一页实际渲染图
```

## 关键脚本一句话说明

| 脚本 | 干嘛用 |
|---|---|
| `build_pptx.py` | 按 `edits.json`（选页 + 文字替换）从模板生成最终 pptx；带长度估算提示；`--strict` 校验 expected_text；任何定位/修改失败均非零退出 |
| `render_slides.py` | 把任意 pptx 渲染成每页一张 PNG（用 LibreOffice + pdftoppm），用于预览 / 自检 |
| `compute_capacity.py` | 由 template.pptx 算出每个 slot 的 `chars_per_line/max_lines/max_chars` 等容量字段（自带模板已算好，仅在加新模板时需要） |
| `check_update.py` | 对比本地 VERSION 和远端 updates.json，告诉你要不要更新 |
| `apply_update.py` | 保护入口：prepare 暂存差异、审查后 apply；保留授权本地规则，禁止覆盖式更新 |
| `build_manifest.py` | 重新计算 manifest.json |

## 字体说明

模板 XML 里大量使用 `微软雅黑`。如果运行环境没有该字体，配合 `~/.config/fontconfig/fonts.conf` 把它别名到本地已安装的字体（推荐顺序：WenQuanYi Micro Hei → DengXian → Noto Sans SC → PingFang SC）。预览图正是用这条 fallback 链渲染的。

最终交给用户的 .pptx 在 PowerPoint / WPS / Keynote 里打开时会自动用宿主机的字体渲染，仍需检查字体替换后的文字宽度、换行和字号；不能据此跳过实际渲染。

## 一些常见误区

- **不要**只改文字不改章节名一致性 —— 改 agenda 必须同步改分章扉页
- **不要**在装饰图上加文字以为是真图表
- **不要**把 lorem ipsum 留在最终 PPT 里
- **不要**把 `max_chars` 的软性估计当成真实布局已通过
- **不要**修改用户原始模板文件 —— 所有产出都到新文件
- **不要**用本 Skill 做商业项目 —— 见顶部声明
