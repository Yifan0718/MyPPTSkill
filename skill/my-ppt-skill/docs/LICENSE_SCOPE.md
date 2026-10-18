# Fork 来源、版权与许可范围

## 项目来源

**MyPPTSkill 是 [GordenSun/GordenPPTSkill](https://github.com/GordenSun/GordenPPTSkill) 的 fork。**

- 上游作者：GordenSun。
- 本次对照基线：1.0.20。
- 上游基线提交：[7d4a61cbd8363b92e4a30784f8ca460a0a2b0a33](https://github.com/GordenSun/GordenPPTSkill/tree/7d4a61cbd8363b92e4a30784f8ca460a0a2b0a33)。
- 定制维护者及修改版权署名：**Yifan0718**。
- 联系邮箱：[liuyifan111111@gmail.com](mailto:liuyifan111111@gmail.com)。

上游身份、版权和许可不会因重命名而移除。功能差异见[完整差异说明](UPSTREAM_DIFFERENCES.md)，发布文件的来源分类见[文件来源清单](SOURCE_MAP.md)。

## 分层许可

| 内容 | 权利归属与适用许可 |
|---|---|
| 继承的上游代码、规则及技能元数据 | 保留 GordenSun 的原版权和 [LICENSE](../LICENSE) 中的 MIT 条款 |
| 上游文件中的新增与修改部分 | Yifan0718 有权许可的贡献采用 MIT，见 [LICENSE-MODIFICATIONS](../LICENSE-MODIFICATIONS)；同一文件中的上游部分继续保留原归属 |
| 本 fork 新增的代码、规则、文档与配置 | Yifan0718 有权许可的部分采用 [MIT](../LICENSE-MODIFICATIONS) |
| 模板的 intro.md、detail.json 等结构化资料 | 上游 [NOTICE.md](../NOTICE.md) 将这些资料列为 MIT；继承部分保留上游归属，新增修改按本 fork 的 MIT 许可 |
| 模板 PPTX 内的视觉设计、插画及装饰素材 | 归原模板作者，继续遵守上游 [NOTICE.md](../NOTICE.md) 及适用的原素材授权，不纳入本 fork 对新增代码的 MIT 授权 |
| 从模板渲染的 preview、缩略图 | 仍含原模板视觉素材，不能因重新渲染而改称本 fork 独占所有或自动适用 MIT |
| 模板的缩略图、视图等封装调整 | 调整工具的代码按对应 MIT 许可；调整不改变模板原内容的权利归属，也不授予整份模板新的使用权 |
| 其他第三方依赖、字体、论文图片、用户输入素材 | 继续适用各自许可和权利范围，不因被工具使用而自动成为本项目 MIT 内容 |

这是两个贡献来源使用相同 MIT 条款的组合，不是删除原作者后把整项目重新归为 Yifan0718。上游 LICENSE 和 NOTICE 保持原文；本文件说明本 fork 的边界，不替代它们。

## 你的修改采用 MIT，意味着什么

MIT 允许接收者使用、复制、修改、合并、发布、分发、再许可和销售获授权的代码及文档，包括用于商业项目。接收者必须在相应副本或实质性部分中保留版权和许可声明。MIT 不要求接收者公开修改后的源码，并包含无担保及责任限制条款；正式英文文本见 [LICENSE-MODIFICATIONS](../LICENSE-MODIFICATIONS)。

因此，使用或分发包含两方贡献的代码／规则时，应保留上游 LICENSE、你的 LICENSE-MODIFICATIONS，以及适用的来源说明。不能只保留自己的姓名而删除 GordenSun；也不能保留 GordenSun 后省略本 fork 修改部分的版权声明。

对你的新增规则采用 MIT，并不等于这些规则中的功能约束自动取消：Agent 执行 Skill 时仍须遵循其工作规范。许可决定他人可如何复制、修改和分发这些内容，执行规范决定当前 Skill 如何完成任务。

## 模板不能按代码许可处理

上游 LICENSE 明确把源代码 MIT 与模板的单独非商业声明分开；NOTICE 说明原视觉素材仍归原作者，维护者不能代替原作者授予商业许可。上游 README 另有“禁止任何二次分发／商业使用”的表述。本 fork 保留这些限制，不将代码 MIT 扩展到模板视觉资产，也不自行放宽上游声明。

公开发布代码、规则和文档，与再分发包含第三方视觉素材的完整模板包，是不同范围。发布包含模板素材的包前，应确认原素材许可或取得相应授权；清除广告缓存、改页码、修改视图、增加自己的代码，都不改变这一点。

## 更新后保持归属

README、差异说明、来源清单及本 fork 的许可文件纳入定制更新保护。上游更新不能用新的作者声明覆盖本 fork 的贡献归属，也不能删除既有许可说明。合入新上游内容时仍保留其归属，按实际文件更新来源清单；发现许可或规则明显冲突时先明确处理，不以自动更新默许改许可。
