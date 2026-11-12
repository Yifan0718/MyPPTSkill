# Beamer 证据与签核接口

与[制作流程](beamer-workflow.md)一起使用。机器核对文件、覆盖范围和证据关联，执行者负责真实内容与视觉判断。记录保存在工作目录；模板不会替执行者看图或填通过。

## 从构建到签核

```sh
python scripts/skill_state.py snapshot work/skill-lock.json
python scripts/build_beamer.py work/main.tex --output-dir work/build --engine latexmk --latexmk-engine xelatex
python scripts/verify_beamer_review.py --template work/build/run-ID/build-report.json work/review.json
# 实际逐页查看后填写 review.json；保存真实局部、独立复核和问题修复记录。
python scripts/verify_beamer_review.py work/build/run-ID/build-report.json work/review.json work/evidence-check.json
```

用构建输出的实际`report_path`替换示例run-ID；工具不覆盖旧run或已有review/check文件。修订使用新路径。构建器参数见`--help`，已有latexmkrc、字体配置和工具路径可显式传入；读取已有配置再使用，不因默认`-norc`丢弃项目必需步骤。

构建会快照`--source-root`内的文件，并排除`--output-dir`。源根用于稳定的源稿与资源；持续写入的stdout日志、review、测试报告和签核记录放在源根之外，或本次输出目录内，避免记录更新使输入哈希失效。若已出现失效，保留旧报告，固定源文件后在新run重建并关联当前证据；渲染未变页可按实际逐页哈希和既有查看记录复用。不要改写构建快照来消除哈希错误。

构建成功状态为`pending_visual_review`。未填写的review模板包含`unreviewed`、`pending_visual_review`和空观察，校验器会拒绝。完成实际观察后设置review和已查页为`reviewed`、填写实际作者/复核者身份与受众，逐项解决`unresolved`。证据通过返回`evidence_complete_pending_visual_signoff`，然后由真实执行者完成签核记录，无额外用户审批步骤。

## 逐页记录

模板自动关联构建报告与各页render哈希。每个实际PDF页需要一条记录，包括所有overlay状态。`visual_checks`的14项沿用现有内容与布局规则：

顶层`skill_lock:{path,sha256}`引用当前安装的规则快照。规则或脚本修改后核对变化、重新冻结，并按新规则复查；不要改写旧锁假装未变化。构建报告必须绑定`layout_audit:{path,sha256}`；校验器核对其PDF、全页inventory及findings均进入主报告，不能删掉审计记录获得通过。

| 字段 | 实际观察 |
|---|---|
| content_reading | 新知识、证据、术语、图表与语言，清理制作指令 |
| layout | 页面分区、阅读顺序和横纵对齐 |
| local_detail | 复杂图、公式、代码、混合字号及细部 |
| full_page_return | 放大后回整页的清晰度与协调性 |
| cross_page | 同类组件、字号、图例、颜色和导航一致性 |
| palette | 文字与底色对比、冷暖和主次 |
| floating_notes | 悬浮小字是否有必要及其处理 |
| container_balance | 多行内容组在容器中的真实上下左右余量 |
| density_and_balance | 主体重心、有效密度与空/挤位置 |
| typography_consistency | 语义字号、实际缩放及例外依据 |
| effective_content_spacing | 标题到有效内容、图内白边、内外累计空隙 |
| content_sufficiency | 本页实质含量和论证职责，实际补充或重组 |
| regional_balance | 四角、左右和上下的局部空洞与偏重；正文分别检查上聚下空和下沉上空，封面另查题名的视觉重量 |
| grouping_and_spacing | 完整宏观块、嵌套关系、组内紧/组间松 |

每页另填`optical_and_connectors`，核对字形起点/中轴、图像有效区域及全部相关连线端点和路径。确实没有某类对象时描述实际结构，不为填字段添加多余对象。`closeups`用数组，复杂区域必须有当前真实裁图，普通页没有局部需求时可为空并说明原因。

`body_vertical_balance`量测在识别到标题背景时比较正文对象包围盒到标题/页脚的上下余量；`body_vertical_balance_candidate`仅提示较强偏置，保留原数值并通过独立局部＋整页视觉复核处理。背景框、图片白边和对象框不能证明真实重心，未识别到标题背景的页面同样执行上述双向视觉检查。封面大留白与正文内容密度分别判断。

关闭正文重心或容器内容候选时，独立局部图须覆盖告警`bounds`对应的完整比较区，包含两端和全部相关内容；按实际PDF尺寸与渲染DPI换算像素裁区，整页回看另行记录。可保留单张`closeup`，也可用`closeups`数组中的多张当前原像素局部联合覆盖，尤其容器延伸至整页时使用分区局部。每张局部均须真实查看且不等于整页，联合覆盖不能漏掉中间区域。裁区不足时补充正确局部图及实际复核，再继续校验。

有标题条、页脚或导航色带时，`container_balance`单独描述各自完整字形组的上下余量、色带到页面边和正文到色带的关系；标题条必须逐页看真实局部并回整页。不能只检查正文卡片。`typography_consistency`与`palette`同时观察实际字重是否过重、标题和block是否机械普遍加粗，按所选字体和主题调整。

每页另有`container_checks`数组，覆盖当前layout-audit中`footer_containers`与`title_containers`列出的每个`container_id`，一段一个条目：`{container_id, observation, local_view:{path,sha256,render_sha256,crop_box}, full_page_return:true}`。模板自动生成pending骨架，实际检查后填写具体观察并改为reviewed；缺段、重复ID、错图或裁图未覆盖完整容器均不能通过。三段页脚可以共用整条真实裁图，但作者、题名、页码必须分别描述。

`audit_band_ink.py BUILD_REPORT --output NEW.json`可提供当前PNG的实际背景行与前景余量；正常测量也保留人工复核，复杂背景或抗锯齿敏感性不能当作平衡结论。未识别的容器继续由14项视觉观察和必要独立复核覆盖，不能以机器清单为空免检。内部旧签核基线按原证据合同核验；新全量稿和本次重新审核页执行当前逐容器记录。

局部证据结构：`{path, sha256, render_sha256, crop_box:[left,top,right,bottom], observation}`。路径为绝对路径，坐标为当前整页PNG的整数像素，右/下端不含在裁区内。校验器核对裁图像素与整页对应区域，保存时不要重采样该局部；正常显示尺度的可读性仍回整页判断。

局部视图须截取实际对象及必要邻域，完整整页图不能同时冒充局部证据；整页返回另行执行。测量不可用的页必须保留对应缺测finding，审计覆盖、逐页状态和全局告警一致，再完成真实独立局部＋整页复核。检查结束时再次核对当前规则锁，避免验收途中规则变化被当作稳定结果。

## 日志、规则与视觉兜底

含装饰线、色带、边框、角标或几何点缀时，在`optical_and_connectors`及既有`grouping_and_spacing`中核对装饰的实际参照、两端/边缘与净距。侧线对应完整文字组时，局部图同时覆盖侧线和全部组成员，比较实际字形上下界；封面也执行。TikZ坐标、盒高度和样式名称不构成放行证据，按[共用装饰规范](precision-layout.md#装饰元素与参照对象一起验收)完成局部及整页观察。

`diagnostics`逐项对应构建报告中的`warnings`或`findings`，用`group`和从0开始的`index`定位。warning经实际核查后可标`visually_checked`，记录具体影响或为何无可见问题；无需消除正常警告。规则finding及需要独立关闭的版式疑点采用`independently_resolved`。

独立记录是单独文件，主review通过`independent_review:{path,sha256}`引用。文件字段：

```text
schema: beamer-independent-review/v1
reviewer: 真实独立复核者，与作者及主复核者区分
reference: 实际消息/任务/用户复核记录引用
build_report_sha256, pdf_sha256
diagnostic: {group, index}
page, render_sha256
closeup: 当前局部证据结构（正文重心/容器内容候选也可用closeups数组联合覆盖）
local_viewed: true（实际查看后）
full_page_viewed: true（实际查看后）
local_observation, full_page_observation
decision: visually_resolved（实际确认后）
unresolved: []（全部问题闭环后）
```

独立复核者先看当前图，再读作者解释和告警。单独文件与身份字段不能证明实际独立查看，仍须有真实工具/用户复核来源，禁止伪造。疑点涉及多页或对象群时覆盖全部关联页和局部；不以一处裁图覆盖整稿。可见缺陷继续修复，输入失效或缺页恢复完整产物后再验收。

## 字号例外

`font_exceptions`无例外时为空。每项含`id,page,component`与具体的`ten_equivalent_render_problem`、`ten_equivalent_target`、`ten_equivalent_method`、`measurement_uncertainty`、`necessity`、`layout_and_split_attempts`、`final_visual_observation`。

文件链包括`ten_equivalent_build:{path,sha256}`、`ten_equivalent_page`、`ten_equivalent_pdf`、`ten_equivalent_closeup`、`final_closeup`；基准源快照为`ten_equivalent_source:{path,sha256,original_path,location}`。基准构建本身必须输入稳定、PDF完整且图像对应。先实际渲染等效10pt并定位冲突，再决定最终必要局部的等效8pt；不能预写理由。机器核对证据链，实际字号、语义必要性和布局尝试由当前图像与源位置共同确认。

## 全量与已签核后的局部修订

首次使用`scope:full`，所有物理页真实检查。已全量签核后用户指出局部问题，才可用`scope:amendment`并提供`user_reported_issue`及`baseline:{build,review,signoff}`三份带path/hash的旧证据。旧signoff必须是完整全量且绑定旧PDF、build和review。

未改变页可用`status:inherited`引用同页旧render哈希；其当前真实PNG必须与完整基线一致，旧观察和局部证据完整有效。受影响页仍按完整标准实际查看。页数变化或无法可靠界定影响范围时全量；不能在首次签核前通过局部模式跳页。

最终signoff记录`status:signed_off`、`scope`、实际`reviewer`、时间及`reference`、`build_report_sha256`、`review_sha256`、`pdf_sha256`、实际页范围、字号exception IDs与`unresolved:[]`，保存本次通过的检查报告引用。签核后输出文件与已核验文件一致；源码或资源变化后重新构建、按影响范围复核。
