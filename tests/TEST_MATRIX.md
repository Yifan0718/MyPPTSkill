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
| `test_layout_visual_review.py` | 47 | 独立局部＋整页复核证据、旧间距告警闭环、大空档与容器内部扫描 |
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
| `test_usage_components.py` | 71 | 表格/图例/间距/配色与JSON往返、首次阅读/案例/反馈证据、防绕过、更新保护 |
| `test_report_io.py` | 13 | 原子报告、直接/间接输入保护、硬链接、写入失败与BOM |
| `test_bounded_rendering.py` | 22 | 超时、进程树、运行记录、备用渲染隔离与恢复 |
| `test_upstream_issue_regressions.py` | 7 | 更新源空值/类型、快照PDF选择、容量工具异常输入及正常空框 |
| `test_presentation_hierarchy.py` | 37 | 全位置悬浮小字、主题色容器联合居中、混合图文、重心与JSON往返 |

| `test_production_instructions.py` | 12 | 制作指令候选、全域文本提取、主题语义与修正继续路径 |

当前Python套件共815项，涵盖上表、双后端与字体模块、正文重心和内部空档的正反回归。

| PowerShell脚本 | 检查数 | 覆盖重点 |
|---|---:|---|
| `test_render_powerpoint_background.ps1` | 35 | 背景、页码保护和对象边界契约 |
| `test_delivery_render_warmup.ps1` | 41 | 后台预热、失败清理及错误传递 |

`test_complex_visuals.py` 生成两页可编辑视觉夹具；生成后按实际渲染逐页检查，并记录局部与整页观察。

发布入口另有6项控制流测试（tests/test_entrypoints.py），验证缺输入、禁止写入安装目录、执行失败不被完整报告遮掩、预检待复核与实际视觉签核的状态区分；统一入口会同时运行。

run_integration.py提供真实PowerPoint端到端检查，本版实际完成3页输入的元数据→首图→后台渲染→快照／外壳校验，仍明确保留视觉复核待办状态。

## 后端与执行恢复模块

| 模块 | 当前测试数 | 覆盖 |
|---|---:|---|
| test_beamer_build.py | 30 | 隔离构建、依赖、失败恢复、字体准备与字体文件变更检测 |
| test_beamer_review.py | 63 | 完整证据、规则锁、独立视觉、整页容器的局部联合覆盖、重心及容器上下文恢复、字号例外 |
| test_beamer_layout.py | 23 | 实际PDF字形、标题条/页脚联合余量、图形候选与解析兜底 |
| test_body_vertical_balance.py | 13 | 真实PDF上下偏置、居中稀疏/充实容器、内部图形、背景框及透明路径反规避、封面分支及单位换算 |
| test_startup_update.py | 32 | 两条版本线、确认/跳过/未回复、断网/限流/异常元数据、慢流/DNS总时限、报告保护及取消 |
| test_beamer_skill_state.py | 3 | TeX/图源、字体字节及许可变更进入规则锁 |
| test_image_fidelity.py | 9 | 原图字节、20MB阈值与压缩关闭 |
| test_pdf_generator_metadata.py | 11 | 生成身份清理、页面树/版本/图像和链接保留 |
| test_font_setup.py | 35 | 固定字体校验、三平台配置分支、具体字形验证、冲突保护、退出码与独立源码准备入口 |
| test_font_download_recovery.py | 19 | HTTP中断、DNS/慢读硬超时、镜像总预算、UTF-8诊断、缓存隔离恢复及原子复制 |
| test_font_entrypoint_recovery.py | 9 | CLI/源码入口状态传播、报告写入失败、原配置保留、OS累计预算和取消 |
| test_band_ink.py | 17 | 实际色带像素、三段文字、末行白边、抗锯齿不确定性与报告保护 |
| test_update_transport.py | 7 | HTTP截断、慢流/DNS硬超时、大小界限与状态分类 |
| test_update_git_transport.py | 4 | Git检查与暂存的真实父子进程清理、文件日志、临时目录释放与无关进程保留 |
| test_shared_rule_contracts.py | 9 | 双后端共同约束、讲稿数字、字体恢复、16:9、内容保留与更新保护 |

| test_decorative_alignment.py | 8 | 细侧条、两端同时伸出、完整文字组、组合与装饰名称反规避 |
| test_office_priority.py | 9 | MS Office优先、错误码、原生失败不回退、WSL宿主检测及未知状态 |
