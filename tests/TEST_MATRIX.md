# 本版测试覆盖

此处只记录当前套件内容及本版验证结果，不包含历史运行日志。

| Python模块 | 测试数 | 覆盖重点 |
|---|---:|---|
| `test_axis_region_scope.py` | 3 | 轴刻度区域与下方说明的关系 |
| `test_builder_console.py` | 4 | 构建输出与编码 |
| `test_center_alignment.py` | 15 | 圆环中心及可见宿主 |
| `test_center_review_gate.py` | 8 | 中心文字证据门槛 |
| `test_connector_integrity.py` | 13 | 线端、笔画、时间轴及关系线 |
| `test_exit_regressions.py` | 7 | 容量错误及外壳提交回滚 |
| `test_gap_audit_gate.py` | 10 | 原始间距与覆盖完整性 |
| `test_gate_visual_resolution.py` | 21 | 通用视觉兜底接入 |
| `test_interstitial_spacing.py` | 45 | 中间说明行与上下间距 |
| `test_layout_safety.py` | 4 | 布局及碰撞候选保留 |
| `test_layout_visual_review.py` | 28 | 独立局部＋整页复核证据 |
| `test_measurement_fallback.py` | 31 | 测量不确定项证据 |
| `test_pptx_delivery_shell.py` | 22 | 第一页缩略图与普通视图 |
| `test_relation_contracts.py` | 10 | 组件和对齐关系契约 |
| `test_release_exclusions.py` | 3 | 开发文件过滤与用户保护优先 |
| `test_render_evidence.py` | 9 | 真实渲染、快照和对象完整性 |
| `test_shell_update_guard.py` | 4 | 更新时模板和预览处理 |
| `test_static_safety.py` | 9 | 签核范围、字体例外及状态检查 |
| `test_transaction_recovery.py` | 18 | 更新事务、中断、超时与元数据并发保护 |
| `test_uniform_picture.py` | 20 | 纯色图片及局部视觉证据 |
| `test_update_safety.py` | 14 | 更新计划、冲突、删除项、失败与回滚 |
| `test_visible_chart_spacing.py` | 27 | 图表实际可见边界和邻接间距 |
| `test_white_container.py` | 8 | 白色容器与真实边界 |

Python合计333项，全部通过。

| PowerShell脚本 | 检查数 | 覆盖重点 |
|---|---:|---|
| `test_render_powerpoint_background.ps1` | 35 | 背景、页码保护和对象边界契约 |
| `test_delivery_render_warmup.ps1` | 41 | 后台预热、失败清理及错误传递 |

`test_complex_visuals.py` 是两页可编辑视觉夹具生成器，不冒充自动视觉验收。真实样本的局部和整页观察不能由上述自动计数替代。

发布入口另有6项控制流测试（tests/test_entrypoints.py），验证缺输入、禁止写入安装目录、执行失败不被完整报告遮掩、预检待复核及不冒充视觉签核；统一入口会同时运行。

run_integration.py提供真实PowerPoint端到端检查，本版实际完成3页输入的元数据→首图→后台渲染→快照／外壳校验，仍明确保留视觉复核待办状态。
