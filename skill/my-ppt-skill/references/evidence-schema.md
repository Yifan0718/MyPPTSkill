# 机器证据接口

本文件只定义技术字段。质量与范围以 [签核流程](signoff-workflow.md) 为准；任何 pending 状态不是发布许可。校验文件一致性不能证明实际看过图，禁止提前填写通过观察。

## 渲染报告 v2

`render_powerpoint_audit.ps1` 写出 `schema: render-evidence/v2`、当前PPTX及实际快照哈希、每页PNG的 `raster_hashes`、`render_started_utc/render_finished_utc`、`text_records`、`chart_geometry_records` 和 `manual_review`。

- 每个原生非空文本必须有唯一 `slide + audit_path`：顶层形状为其ID字符串；组内为 `父路径/group/子ID`；单元格为 `表格路径/table/行/列`，行列从1起。
- 记录包含实际文本、文字边界、每个非空run的有效 `run_font_sizes_pt`。混合字号不能只看整框Font.Size；任何run低于适用下限都失败，取不到有效字号也不能自动通过。
- 图表必须有实际plot边界，或明确 `native_plot_bounds_unavailable` 人工检查项；缺失记录不等于没有图表。图片、组、图表及每页母版/布局均有对应人工复查项。
- `manual_review` 的 `review_id` 唯一且按m1…mn编号。母版路径为 `master-layout`。任何未知、重复、漏项、过期快照/图片、非有限几何值均阻断。
- 渲染器通过机器级PowerPoint锁避免不同目录并发；输入快照锁及目录锁继续保留。失败不能复用旧报告。

`verify_coverage_review.py` 先独立核对PPTX、快照、图片哈希和递归对象清单，再重新计算coverage。旧版无v2字段的报告不能手补哈希冒充新证据；已验收历史稿保留原版本及记录，新任务采用当前协议。LibreOffice辅助脚本只输出图片，不生成v2对象证据；可用于观察/预览，但完整签核须补足等效真实测量及验证，不能伪造COM记录。

## 人工复查的逐项关闭

`coverage-review.json.render_manual_reviews` 精确覆盖所有renderer人工项。每项包括 `review_id, slide, audit_path, decision:"verified_in_context", observation, image_sha256, crop_box_px:[l,t,r,b], crop_path, returned_to_full_page:true`。

裁剪必须是当前真实PNG的原像素区域，覆盖实际对象及问题范围；校验器逐像素比较，不接受无关白块。无法解析几何时用当前整页裁剪并补 `detail_crop_box_px/detail_crop_path`；母版检查必须看整页。chart-error仅表示需要人工验证，不是已关闭。规则发现的 `items` 与renderer人工项是两份独立必填清单，不能互相替代。

原生纯色图片另须显式 `detail_crop_box_px/detail_crop_path`：非整页裁剪，包含图片四边及紧邻背景。校验器从实际内嵌源图确认全不透明恒定色、当前对象像素匹配且四边可见；透明/不可见白块、颜色不符、缺上下文继续失败。仍需具体观察及整页回看。

## 版式规则失败与不确定项的视觉闭环

通用版式复核按签核流程处理所有实际版式规则失败，不按图型或错误全文白名单授予资格；原检查必须执行，原报告、数值及阈值完整保留。执行/完整性/内容错误另行修复。下列 `measurement_fallback.py` 专用协议继续用于已有测量不确定项，不能把其有限类型误读成通用视觉兜底的范围。不得提前填写通过，也不能对已通过的检查制造多余兜底。

### 通用版式规则复核

`layout_visual_review.py` 提供 `layout_context(finding, slide, render, image_path, rule_failures)` 与 `validate_layout_visual_review(...)`。调用者先执行原规则并分类，只有版式判定交给通用适配器；完整性、执行、内容、字体例外等失败不转为版式。扫描结果保持原样，复核记录单独绑定。

入口位置：coverage 的 `items[*]`；原间距失败的 `gap_audit.layout_reviews[*]`（finding_id 为 `gap-raw:原issues序号`）；独立图表间距的 `gap_audit.visible_reviews[*]`；渲染预检的 `render_preflight_reviews[*]`（`render-preflight:原issues序号`）；连线端点的 `connector_reviews[*].endpoints[*].layout_visual_review`。各入口生成的完整原 finding 与原失败列表必须传给同一适配器，不手抄删减后的版本。

每个通用 disposition 添加 `visual_fallback`：

- `code:layout_rule_visual_resolution`、当前 `pptx_sha256/image_sha256`、真实 `author_id` 位于 review 顶层。
- `machine_context` 必须等于工具基于当前文件与原失败重算的完整返回：含 `original_finding`、全部 `rule_failures`、全页对象/路径清单、目标及周边对象、原生几何、当前文字/像素测量和必需局部范围。作者不能改阈值、数值或挑选有利对象。
- `measurement_limitation/local_observation/global_observation` 具体说明规则与图像的差异；`target_observations` 对工具发现的每个上下文对象给出实际观察。只有真正通过后才填写 `local_result/global_result:pass`、`returned_to_full_page/normal_size_viewed/no_visible_layout_defect:true`、`unresolved:[]` 及带时区 `reviewed_at`。
- `details` 数组每项含 `path,sha256,crop_box_px`，必须为当前整页的原像素局部，完整覆盖工具发现的对象与上下文。范围很大时可用多个真实局部拼合覆盖；不能把整页重命名为局部。整页另外实际查看。
- `independent_review:{path,sha256}` 指向另一位实际复核者生成的记录。它绑定 `finding_id,slide,code,pptx_sha256,image_sha256,machine_context,local_views`，其中 `local_views` 保留每个局部的哈希与范围；还须实际 `reviewer_id,review_source,reviewed_at`、局部/整页观察、逐对象 `context_observations`、`decision:visually_resolved`、完成查看与零未解决项。
- 独立记录的 `rule_assessments` 按原失败顺序逐项写 `original_error,why_rule_failed_but_visual_passed,no_visible_layout_defect:true`；`relationship_assessment` 明确 `same_alignment_group,same_metric_group,structural_explanation`。确属同组时不能谎称不同组；如果实际视觉合格而数值失败，应说明真实的光学或测量差异。独立复核发现可见缺陷则不通过，继续修复。

校验器复算上下文、核对原像素/哈希/全部对象及时间顺序，保留原失败并返回 `visually_resolved_pending_signoff`。它验证证据一致性，不能代替真实看图；禁止作者伪造另一个复核者。该结果只关闭对应版式项，其余检查及最终全页双遍仍执行。

### 既有测量不确定项的专用协议

需要使用既有专用协议时，review 顶层填写真实 `author_id`，对应 finding 的 disposition 添加 `visual_fallback`：

- `code, original_error`：分别使用工具的分类与原错误全文；`pptx_sha256, image_sha256` 绑定当前文件及整页；`page_object_ids` 完整列出当前页全部原生顶层对象。
- `measurement_limitation, local_observation, global_observation`：具体原因和实际观察；`target_observations` 用字符串 shape_id 映射每个关系成员及被报障碍对象的观察。`local_result/global_result:"pass", unresolved:[], returned_to_full_page:true, normal_size_viewed:true` 仅在真正完成检查后记录。
- `detail:{path,sha256,crop_box_px:[l,t,r,b]}`：当前真实 PNG 的原像素局部裁剪，包含全部关系对象及边界上下文，不能仅含整页或无关空白。
- `visible_measurements`：间距项用 `vertical_edges_px:[前排底边,中间字形顶边,中间字形底边,后方容器顶边]`；保留原有 ≥12pt 与均衡阈值。图表/表格边缘及字形项用 `anchor` 和 `anchors_px:{shape_id:可见锚点x}`，必须覆盖全部对象、维持原对齐准则与阈值。人工测量不是自动真值，独立复核者必须对照原图核实。
- `independent_review:{path,sha256}` 与带时区 `reviewed_at`。复核 JSON 记录不同的实际 `reviewer_id`，并绑定 `finding_id,slide,code,original_error,pptx_sha256,image_sha256,detail_sha256,visible_measurements`；含 `decision:"visually_resolved",unresolved:[],local_viewed:true,full_page_viewed:true`、具体 `local_observation/global_observation`、实际消息/工具记录来源 `review_source` 和 `reviewed_at`。顺序必须为渲染完成→独立查看→作者收口；不得编造身份/来源。

最终报告保留 `visual_resolutions`（原 finding/error、复核者及图像/复核记录哈希），继续校验全页双遍、字体、连接、其他发现和最终签核。该字段不会删除原 coverage，也不构成发布许可。

### 图内中心文字

独立 coverage 对原生环图中央文字产生 `centered_text_visible_host_misaligned` 或 `centered_text_visible_host_review`；平铺记录 `chart_audit_path,text_audit_paths,measurement_status,crop_box_px` 和当前可见 host/hole/text_group 的 bbox、中心与偏移。实际子对象使用 audit_path，shape_ids 保留顶层 owner；图片和复杂未解析图仍按图内局部规范检查。

- `measured_misalignment` 保留为原测量失败：实际可见错位须修复重渲染；局部及整页视觉合格时可走通用独立复核。不能改用文本框或 PlotArea 中点、改名或仅以数据位置声明放行。
- 使用中心专用路径时，disposition 含 `center_alignment_contract:{chart_audit_path,text_audit_paths,reference:"visible_host_or_hole",center_observation,internal_group_observation}`；完整覆盖所有文字成员。`detail_evidence` 另含整数 `crop_box_px`，当前原像素裁剪须覆盖机器给出的宿主/孔洞与文字区域；不接受整页代替局部或只裁出数字。照常回到整页并检查组内行距、单位和碰撞。使用通用视觉闭环时，以完整 `machine_context`、`details` 和独立实际复核替代该专用证据结构，不重复要求两套互斥字段。
- 自动不确定项可用上文 `visual_fallback` 的 `code:"uncertain_visible_center"`；`visible_measurements` 为 `{reference:"visible_hole",host_bbox_px,hole_bbox_px,text_group_bbox_px}`，由另一个实际复核者对照当前局部和整页确认。机器已稳定取得的 bbox（`measurement_known_fields`）不能重填；字形仍须位于孔洞内并满足原中心精度。缺可选图像测量依赖只进入待复核，不使整个 coverage 崩溃。

逐页内容遍的 `checks` 增加必填 `quantity_unit_pairing`，具体记录数字与对应单位是否同行或共用明确单位表头/轴标题，不能填空、pass 或不适用。此项绑定每页真实 PNG，与原内容和版式双遍一起闭环；机器字段完整不能代替真正查看换行。

## 字号例外

`font_exceptions` 精确对应所有低于标准12pt的必要文本区域（合规页码除外），无例外填空数组。每项含 `exception_id, slide, audit_path, content_role, justification, final_visual_observation`。普通数据表格角色为 `ordinary_data_table`，只能低至10pt；必要图内辅助文字为 `complex_graph_auxiliary`，正文不得借标签名缩字。

低于10pt的局部辅助文字还须 `observed_10pt_conflict, content_must_remain, layout_and_split_analysis, attempts`。每次attempt记录 `pptx, render_dir, slide, audit_path, observed_conflict, layout_action, crop_box_px, crop_path`。至少保留初次和合理布局调整后的两个不同10pt实际渲染；目标文字相同，实际字号为10pt，目标页布局确有变化，不能只改元数据凑两次。先前失败preflight可作为10pt困难证据，历史试验不能替代最终候选的验收。未经闭环的失败preflight不能签核；当前候选的版式失败可按通用独立视觉流程关闭，字号例外证据仍完整执行。两个试验必须早于最终渲染；时间戳只是顺序辅助，实际快照、字体、内容及局部图证据同样必需。

原生图表内部与图片内字体仍按完整视觉规则逐项登记检查，不能因不属于独立文本框而免检，也不能仅靠提取器宣称已覆盖其所有字体。

## 间距与对齐的有效关系

窄单位/说明框只要共享同列锚点，就必须进入整组检查，不能因宽比超过3倍而遗漏第三项。侧栏优先比对当前实际plot的中轴；有可靠plot证据且局部/整页核验通过时，不以图表外框误差强制改坏布局。

`header_body_boundary_review` 的两个全局间隔不属同一层级时，可提供 `spacing_contract:{kind:interstitial_text,middle_shape_id,before_shape_ids,after_shape_id,hierarchy_observation}`。校验器独立寻找真实最近前排和后方容器，用中间字形边界计算上下gap，要求前排ID完整、没有遗漏夹入对象、两侧≥12pt且符合既有均衡阈值；不读取自填25/25作为证明。前排可含当前真实字形边界的行名。支持边界可验证的原生不透明矩形；不可验证轮廓不猜测，需补等效真实测量或改用可核验布局。该项必须有当前局部证据并回到整页。

## 原始间距报告与可见图表边界

最终 review 必填 `gap_audit:{layout_path,layout_sha256,report_path,report_sha256,visible_reviews:[...]}`。layout 和 report 分别为原布局计划及原始 `audit_layout_gaps.py` 输出；校验器重新计算并要求报告完全一致、覆盖全部页，不接受删掉原 issues 的“通过报告”。普通无误且未发现特殊关系时，`visible_reviews` 为空数组。

校验器另从真实对象独立发现高置信“原生图表→紧邻独立短说明→有色结论容器”三对象结构，不读取作者 layout，名字不授予排除。**框距已通过也必须检查已发现关系**；未被该专用检测器识别的图表/图片内部与其他版式仍执行完整视觉验收。原模块内部的紧凑布局不机械套成三个独立模块，禁止通过合并或伪装模块规避检查。

可先生成定位报告：

```powershell
python -X utf8 scripts/visible_chart_spacing.py candidate.pptx render visible-spacing.json
```

exit 2 表示发现待核查关系，含可靠测量结果或未知项；数值失败须修复或完成通用独立视觉复核，不能忽略。exit 3 为执行/证据失败；0 仅没有该专用关系，不能代替全页视觉检查。`discover_relations` 返回真实比较组，`measure_relation` 不接受作者自填边缘，使用当前整个图表的可见像素、说明字形及后方容器，保留原生框值、阈值稳定性和部分已知量。

每项 `visible_reviews` 包括 `slide,comparison_name,measurement_path,measurement_sha256,decision:"verified_in_context",observation,image_sha256,returned_to_full_page:true,detail_evidence:{path,sha256,source_image_sha256,crop_box_px}`。comparison_name 使用独立发现的稳定名称，必须完整覆盖发现清单。将 `measure_relation` 的完整返回单独存入 measurement_path；校验器重算并逐字段比较。局部原像素裁剪必须覆盖完整三对象及上下文，再返回整页；不能只截有利的图例片段。

- `measured_valid_pending_visual_review`：当前可见间距须满足不低于12pt及均衡要求，并保留匹配原计划的更严格 minimum；局部/全页合格后才能关闭该组。
- `measured_defect`：保留原数值，修复实际可见问题，或在当前局部＋整页实际合格时完成通用独立复核。`invalid_relation` 若属于证据/输入不完整则先修输入；不得改原状态或用作者声明覆盖。
- `manual_review_required`：保留未知量和 known_edge_indices，用 `visual_fallback` 的 `code:"uncertain_chart_spacing"` 接独立局部＋全局复核；`visible_measurements.vertical_edges_px` 为图表可见底、说明字形顶/底、后容器可见顶。已知边缘与更严格下限不可改写。

原框距的 `gap_below_minimum_or_overlap/peer_gap_imbalance` 只有与独立发现的完整三对象组一致，且当前像素证据通过时才可关闭；结构错误、遗漏轴向、未知对象等不能借此消除。最终报告的 `visible_gap_resolutions` 保留原告警和实际可见测量，不要求为满足错误的框模型而把正确页面改坏。

## 全量与增量范围

`check_signoff_scope.py candidate.pptx scope.json scope-check.json` 只核验范围，成功仍为 `scope_valid_pending_quality_checks`。

- 全量：`mode:full,sha256,checked_slides`；必须完整覆盖含封面的全部页。
- 增量：`mode:amendment,sha256,checked_slides,baseline_pptx,baseline_signoff,baseline_signoff_sha256,user_reported_issue`。基线记录须已 `status:signed_off,mode:full,unresolved:[]`，有实际基线文件哈希、完整checked_slides和带时区signed_at。用户指正含 `source:user,reference,quote,reported_at`，时间必须在全量签核之后；引用须核对真实用户消息，不能自行编造。
- 工具追踪前后包成员及关系依赖，母版/布局/主题/共享资源和页序变化扩大范围；未复查任何受影响页都失败。无法确定的外部视觉资源或未知全局变更不能缩小范围。
- 范围检查不校验视觉质量，不可替代受影响页的预检、规则、内容遍/版式遍、语言及局部证据。当前全量coverage校验器只接受完整v2报告；若采用增量，必须保留有效基线并提供可验证的逐页证据组合，不能把局部图片塞入旧全量报告或改旧哈希。缺少等效验证时不得签核。

## 首次阅读与反馈证据

`audience-review.json` 顶层为 `schema:audience-review/v1, sha256, audience, expression_mode, chapter_navigation, pages, definitions, examples, feedback, unresolved:[]`。

- `expression_mode`：`advantages / advantage_led / academic / objective`；`chapter_navigation` 含 `mode:none / section_first / divider / persistent`、`basis:user / inferred / delegated`、具体 `description`。任务要求以真实用户输入为准，字段不能冒充用户同意。
- `pages` 精确覆盖最终全部页面，各项含 `slide,image_sha256,kind:general / result / comparison / example,purpose,plain_language,operation_or_reading,metrics_or_symbols,evidence_to_conclusion,evidence,result:pass,unresolved:[]`。五段文字写实际复述；通用页面也解释页面职责和符号读法，不填空或通用pass。
- `evidence` 引用当前真实渲染对象：`{slide,audit_path,quote}`，quote必须出现在渲染text_records对应对象；图片内说明使用 `{slide,image_sha256,crop_path,crop_sha256,crop_box_px,observation}` 原像素裁剪。每页至少一项当前页证据，前置定义可额外引用此前页，不能以作者聊天替代。
- `definitions` 仅追踪需要解释的概念，含 `term,display_name,introduced_on,used_on,evidence`；首次介绍在使用之前或同页。列表为空须经过实际术语检查，不表示通用符号也必须逐一登记。
- `examples` 与标为example的页对应，含 `slide,purpose,selection_scope,source_path,source_sha256,source_locator,why_representative,what_visible,claim_check,alternatives_considered`。最后字段是实际比较过的候选说明列表；只有一份来源则写清具体情况及适用判断。所有判断必须来自研究和实际查看，不以填写文件证明代表性。
- `feedback` 含 `id,category,issue,affected_slides,similar_checked_slides,changes,observation,status:resolved`。changes使用与evidence相同格式，覆盖受影响页；即使检查后无需修改，也指向现有正确对象并说明理由。内容反馈改到成品并重读后关闭；无反馈可为空列表。
- 每页的复述、案例判断、实际问题关闭由真实阅读完成；校验器检查一致性和遗漏，不能替代语义判断。记录独立阅读者及实际结论到工作目录，严禁虚构；通用版式兜底继续绑定原独立复核协议。

`verify_readability_review.py candidate.pptx render audience-review.json audience-check.json` 成功返回 `audience_evidence_complete_pending_semantic_signoff`；失败返回非零并列出遗漏。最终统一运行 `verify_delivery.py`，两个子检查均执行并保留原错误，任一失败/未知均非零。新入口不自动补通过、不忽略异常；补齐有效证据或修复成品后重试。

组件审计新增表格单元格对齐/内距、图例与数据标签、表格—说明—后续模块间距及色块文字配色候选。前3类实际几何/样式冲突须修复或通用独立视觉闭环；未知测量与配色候选须当前局部证据和整页观察。配色是审美候选，不将比率或彩色文字当成必然缺陷。渲染报告可附 `chart_legend_records` 与带audit_path、页面坐标bounds_pt的chart_label_records，无法取得时继续局部复核。

每页另填 `visual_checks:{content_reading,layout,local_detail,full_page_return,cross_page,palette}` 的具体看图观察，`visual_targets_reviewed` 完整覆盖当前页原生表格、图表、图片和组合（递归audit_path），`local_views` 使用上述图像证据结构，复杂对象至少有实际局部图。局部图须来自当前页且不是整页；检查记录与既有coverage局部证据可复用，避免重复生成。此处记录所有阶段的视觉判断，包括灰色说明、色块底色和字色；不能只抄自动测量值。纯文字页也记录实际观察，可无复杂对象局部裁剪。

格式校验会定位非法页码、对象路径类型、术语名称及反馈类别，并保留同轮已收集的哈希等错误。文字证据与图片证据使用各自完整字段；局部图须联合覆盖对应原生组件范围。色块文字对比度4.5及RGB通道差32是提示复核的内部启发值，实际审美判断按局部和整页效果完成。

有界渲染可附`bounded_run_id`，与渲染目录tool-run.json中的`schema:bounded-run/v1,run_id,status,exit_code`匹配。status必须finished；允许exit_code=0，或exit_code=2且原渲染状态为failed_preflight并继续独立视觉闭环。缺失、运行中、超时、取消、其他退出码或身份不匹配均需修复执行链后重跑。旧的无运行标记证据保持原协议，新任务按有界执行入口操作。报告输出保护和恢复见签核规范。
