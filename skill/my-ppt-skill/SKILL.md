---
name: my-ppt-skill
description: >-
  制作与编辑 PowerPoint、LaTeX Beamer 演示稿，支持21套内置中文PPT模板、自带模板和原创设计，复杂图表、代码、公式混排，实际渲染并逐页视觉验收。用户明确要求时，为两种Slides制作多语言Word或LaTeX配套讲稿；LaTeX成果交付PDF与可编译源码。当用户需要PPT、幻灯片、Beamer、教学课件、研究或项目演示，或基于Slides的讲稿时使用。Use for PowerPoint/PPTX or LaTeX Beamer decks, template-based or original presentations, and explicitly requested multilingual speaker manuscripts in Word or LaTeX, with rendered visual review.
---

# MyPPTSkill

> **上游基线版本** 见同目录 [`VERSION`](./VERSION)；定制规则以当前安装内容为准。

---

## 输出格式与执行路线

**Office工具最高优先级：** 本机安装了对应Microsoft Office应用时，Office文件的打开、排版、渲染和导出使用MS Office，执行[Office优先级与恢复流程](references/office-runtime.md)。失败先恢复原生路径；其他兼容办公套件仅在对应MS Office未安装时使用。

所有LaTeX成果执行[PDF与原始源码交付规则](references/latex-delivery.md)：必须同时提供已编译PDF和原始源码，最终回复必须列出PDF文件的直达打开链接。

普通PPT／PowerPoint请求默认PPTX；明确要求LaTeX、Beamer或已有Beamer工程时，执行[Beamer完整流程](references/beamer-workflow.md)，交付PDF与可编译源码。新建和重做整套演示默认16:9。两条路线共用需求、语言、内容、精调与视觉标准；构建、对象寻址和文件验收按格式执行。Beamer不调用PPTX专用COM/XML校验器。

Beamer未指定其他风格时，直接采用已确认的[BIO0507默认风格](references/beamer-default-style.md)：Boadilla＋beaver、常规字重、紧凑页脚；加载配套样式文件后实际试排。其他风格按用户要求选择。

默认风格字体按[受控字体资源](references/bundled-fonts.md)自动配置同一字体文件；该字体包的获取与用户级安装已获长期授权，其他软件/依赖仍按其授权范围处理。

首次计算、绘图或编译前先执行[环境选择](references/scientific-visualization.md#先探测后选择)：确认实际解释器、已有库、字体和工具链，优先使用可用环境或替代工具。安装范围以用户明确授权为准；仅补字体的授权不扩大到Python包、TeX宏包或其他软件。不得先安装后补读规则。

Beamer依次读取通用写作、需求与层级规则、[文字与空间精调](references/precision-layout.md)、[图表处理](references/beamer-charts.md)，使用构建工具并完成全部实际页的规则＋视觉检查，再签核交付。下面五步中的PPTX脚本、缩略图和普通视图要求属于PowerPoint路线；Beamer使用专用流程对应的构建、逐页图像、证据检查及签核。

用户明确要求配套讲稿时，执行[讲稿流程](references/speaker-notes.md)。PowerPoint与Beamer共用，默认中文；格式按用户指定，未指定先询问，无回复时优先可用LaTeX，否则Word。仅制作Slides时不自动生成讲稿。

## 执行顺序与规则入口

本 Skill 保留模板风格，但不保留模板缺陷。以下本地定制优先于模板或上游资料中的“不改排版”“保持原字号”“轻微超框”“渲染可选”等冲突建议。用户当前明确要求优先；普通单稿反馈不自动成为长期规则。

用户的任务要求、偏好和制作约束仅指导执行，成品讲述主题内容。按[制作指令与成品内容分离](references/local-delivery-quality.md#制作指令与成品内容分离)检查并清理混入正文、注释、附录、备注及导出产物的指令和执行自述。

**通用写作必读：** PowerPoint与Beamer的所有主题、用途、自然语言及模板模式，从构思/材料筛选、大纲/文稿、图表组件生成、每次排版改写到签核与输出，全流程执行[Affirmative-First Writing](references/affirmative-first-writing.md)。直接展开事实、机制和信息增量，逐句及整篇清理防御性否定、虚构反方和伪反驳。发布会原则继续按用途选择叙事方式，通用写作规范贯穿全部表达模式。

1. **确认需求与选模板。** 制作整套前，未明确的封面、篇幅必须询问；大纲仅在实质不清楚时询问，已知信息不重复问。执行下文三模式与 [本地交付标准](references/local-delivery-quality.md) 的需求、内容、字号、边距和元数据规则。不得删关键内容或机械增页规避排版。
2. **轻量检查更新并冻结版本。** 本会话首次启用执行`python -B -X utf8 scripts/startup_update.py`，按[启动更新流程](references/startup-update.md)处理：确认有更新才询问是否更新；无更新、断网、超时或检查异常直接沿用本机版本继续制作，不因更新检查阻塞任务。未答复时也沿用当前版本，明确同意后才进入保护更新。规则冲突显式确认，额外要求按[更新保护](references/local-delivery-quality.md#更新时保留本地规则)保留。最终迭代前按[冻结流程](references/layout-integrity.md#冻结skill后再迭代和签核)建立版本锁。
3. **规划内容和布局。** 执行[文字、空间与光学精调](references/precision-layout.md)，内容和等义措辞与列宽、行距、字号联动迭代。 按[标题、注释与字号](references/presentation-hierarchy.md)检查全部悬浮小字、页底注释、整块文字居中、页面重心及信息密度，建立语义字号基准。 先按[首次阅读与案例](references/audience-and-evidence.md)建立读者可理解的术语、指标和代表性示例，并用[修订闭环](references/revision-control.md)追踪用户反馈及影响范围。 叙事按用途参照 [叙事选择流程](references/narrative-reference.md)，不机械写成宣传稿。执行 [全页覆盖与反规避验收](references/layout-integrity.md)：统一锚点、真实间距、所有位置可见字形边缘、混合字体局部检查；不得自授免检。分析型多页稿搭配多种有任务的图表和图标，科研绘图按需读 [工具选择](references/scientific-visualization.md)。
4. **渲染、修复、反复核验。** 按[原图保留](references/scientific-visualization.md#原图保留与大图选择)保持正文图片；自定义PPTX在首次PowerPoint保存前用`pptx_image_fidelity.py prepare`生成关闭自动压缩的候选，已有build_pptx输出自动设置。 最终渲染前按 [第一页缩略图与普通视图](references/delivery-shell.md) 准备交付外壳；PowerPoint默认后台无窗口运行。 所有页面初始 `suspected_unverified`。必须规则与视觉交叉检查；所有原生连线、箭头及图内连接按 [连接完整性](references/connector-integrity.md) 逐根逐端检查。自动通过不能代替局部和整页可视化。版式规则未通过或测不准时，保留原结果，执行 [局部＋整页独立视觉兜底](references/signoff-workflow.md#版式规则未通过时的视觉兜底)；真实视觉合格且独立复核完成可以关闭对应拦截，不要求所有版式数值机械通过。实际可见缺陷须修正，未解决项不得签核；拦截必须接续复核、修复或替代流程，不能作为停工理由。
5. **签核后交付。** 最终使用 `scripts/verify_delivery.py` 同时汇总版式证据和首次阅读证据；原 `verify_coverage_review.py` 继续作为版式证据检查器。 按 [签核范围与证据流程](references/signoff-workflow.md) 处理错误、版本、全量双遍视觉检查及发布。默认必须全量所有页；仅已全量签核后用户指出局部问题的修订可按该文件的严格增量条件处理。缺证据、未解决项、失败或未知状态均不得发布。

以上引用按对应阶段开始前读取并执行；仅调研、讨论或生成待确认大纲时，执行需求/叙事/读者准备规范，暂不启动依赖最终PPTX的渲染与签核。实际制作交付时完整执行全部阶段，不能以准备阶段例外跳过成品检查。技术能力说明不改变质量门槛。字号 12/10/8 pt 的适用范围及 8 pt 先实际尝试 10 pt 的证据链，统一以 [字号和可读性](references/local-delivery-quality.md#字号和可读性) 为准。验收日志仅留工作目录，不能写入 PPT 或备注。

> **模板素材许可**：内置 PPT 模板视觉素材仅供上游许可范围内的个人学习和研究，禁止未经授权的商业使用；分发须遵守上游及原作者限制。代码、规则与文档按各自 MIT 许可处理，不能把代码许可扩展到模板素材。Fork 来源及许可分层见 [许可说明](docs/LICENSE_SCOPE.md)。

## 何时使用本 Skill

PowerPoint与Beamer的装饰元素均执行[装饰与参照对象验收](references/precision-layout.md#装饰元素与参照对象一起验收)：核对真实关联对象、两端/边缘、间隙和视觉重量；“装饰”用途与封面留白例外均不豁免位置和对齐检查。

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
3. 字体：英文 Arial / Helvetica；中文 微软雅黑 / 思源黑体；按实际字体校准字重，层级由字号、颜色、间距与必要强调共同建立，不默认所有标题加粗
4. 按内容选择协调的主题色、强调色及中性色，不设颜色数量硬上限；保持视觉主次、可读性和跨页颜色映射一致
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
9. **同页同层级完全统一，跨页保持基准，模板可以调整** —— 按[语义字号与少数页调整](references/presentation-hierarchy.md#语义字号体系与少数页调整)建立主标题、正文、注释等基准。可调整模板字号及布局；少数页偏离须有基准字号的实际渲染问题、具体原因与修改后复验记录。同页普通非标题最小/最大字号比例至少50%、优先75%；唯一比例例外为[大数字强调＋较小辅助文字](references/presentation-hierarchy.md#同页字号比例与同层级一致性两种格式共用)，其余文字继续执行比例、字号下限与可读性检查，防止超小字免责声明和防御性备注。保持必要内容与信息密度，并继续遵守图内辅助文字的既有例外。

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
| `render_slides.py` | 检测MS PowerPoint并用原生后台渲染；未安装时才使用兼容套件，用于逐页预览与自检 |
| `compute_capacity.py` | 由 template.pptx 算出每个 slot 的 `chars_per_line/max_lines/max_chars` 等容量字段（自带模板已算好，仅在加新模板时需要） |
| `check_update.py` | 对比本地 VERSION 和远端 updates.json，告诉你要不要更新 |
| `apply_update.py` | 保护入口：prepare 暂存差异、审查后 apply；保留授权本地规则，禁止覆盖式更新 |
| `build_manifest.py` | 重新计算 manifest.json |

## 字体说明

模板 XML 常用`微软雅黑`，优先使用本机已获许可的原字体。默认Beamer所需Fandol与Latin Modern按[受控字体资源](references/bundled-fonts.md)自动配置。制作前确认所选主题的确切字体、样式及可用来源；缺失时先修复原字体的安装与发现路径。受控包之外的字体按其许可和授权取得，不能以名称相近的字体别名静默替换。

PowerPoint、WPS、Keynote及TeX的字体发现机制不同，按实际输出环境检查字符、字重、宽度、换行和基线。用户明确批准改换字体时，统一更新相关语义角色并重新渲染全部受影响页面。

## 一些常见误区

- **不要**只改文字不改章节名一致性 —— 改 agenda 必须同步改分章扉页
- **不要**在装饰图上加文字以为是真图表
- **不要**把 lorem ipsum 留在最终 PPT 里
- **不要**把 `max_chars` 的软性估计当成真实布局已通过
- **不要**修改用户原始模板文件 —— 所有产出都到新文件
- **不要**用本 Skill 做商业项目 —— 见顶部声明
