# 当前版本开发测试

此目录是发布资源中的独立测试套件，不属于 Skill 安装目录。只包含仍适用于本版的测试，不含旧稿依赖、历史日志或旧候选。Python测试自动生成所需合成夹具；PowerShell测试检查后台渲染与清理契约，默认不启动PowerPoint。

## 运行

在完整发布资源根目录运行：

```text
python -m pip install -r tests/requirements-test.txt
python tests/run_tests.py --output test-results/run-01
```

第一条是自行安装测试依赖的命令，不由Skill自动执行。需要Python 3.10或更新版本；本版验证使用附录环境中记录的版本。依赖清单记录本次实际使用的版本。

如果只下载测试包，先解压Skill安装包，然后显式指定：

```text
python tests/run_tests.py --skill-root /path/to/my-ppt-skill --output test-results/run-01
```

运行器将Skill及测试复制到临时目录，不把测试安装进原Skill，不改原文件。每轮使用新的输出目录；生成当前轮test-summary.json。失败、超时、缺PowerShell或缺失执行结果均不会标为全量通过。

无PowerShell环境可选用 `--python-only`，报告单独列出Python测试结果。完整测试使用默认命令运行Python与PowerShell检查。

## 自动测试与视觉复核

另提供真实PowerPoint端到端入口，验证元数据清理、首图准备、后台全页渲染、快照及缩略图／普通视图。它只修改工作副本，默认使用样本01：

```text
python tests/run_integration.py --output test-results/powerpoint-01
```

单独下载测试包时同时指定 `--skill-root` 和 `--input`。需要Windows PowerShell与已安装的PowerPoint。工具链完成后返回 `pipeline_checks_passed_visual_review_pending`，接着逐页／局部视觉复核。版式预检问题返回非零并保留报告，随后按Skill进行复核、修复或独立视觉闭环。

完整自动套件包含439项Skill Python测试、6项发布入口控制流测试，以及76项PowerShell契约检查。覆盖构建、图表、间距和像素对齐、连接、字号证据、独立视觉兜底、签核完整性、更新保护、错误传播、事务回滚、缩略图与后台准备。分组详见 [TEST_MATRIX.md](TEST_MATRIX.md)。

可同时生成两页可编辑复杂图表夹具：

```text
python tests/run_tests.py --output test-results/run-02 --visual-fixture test-results/complex.pptx
```

生成夹具后，使用Skill的prepare和真实render流程，再逐页查看成品并放大检查复杂区域。自动测试与实际视觉复核全部完成后签核。

最终十份真实样本见完整资源中的examples目录，其文件与已验收稿保持一致。测试套件自行生成所需夹具，样本可直接用于学习和效果对照。

测试代码中包含有意构造的失败输入和反例，例如路径拒绝、错误状态、布局冲突、异常中断；这些负向测试用于验证当前版本的拦截与恢复行为。版权和许可参见资源根目录licenses。

## 实际使用反馈的回归

`test_usage_components.py` 覆盖表格同类列/数字列差异、合并单元格及未知继承、图例与标签缺测/间距、连续模块、深浅底字色、首次阅读证据、案例来源、用户反馈、局部裁剪范围及错误传导。

使用全新工作目录生成八页正反视觉夹具：

```text
python tests/generate_usage_visual_fixture.py <fresh-directory>
powershell -NoProfile -File tests/prepare_usage_visual_fixture.ps1 -InputPptx <fresh-directory>/fixture.pptx
powershell -NoProfile -File skill/my-ppt-skill/scripts/render_powerpoint_audit.ps1 -InputPptx <fresh-directory>/fixture.pptx -OutputDir <fresh-directory>/render
```

夹具包含有意的反例和对应修复页。逐页及局部实际查看后回整页，记录具体发现；同时运行coverage比对候选，自动无报错也检查审美、裁图和首次理解。不要把含反例的测试稿签核为成品。

故障注入还覆盖八个CLI入口的输入/报告路径碰撞、间接引用保护、文件/像素在检查期间变化、极端裁剪、输出写入失败、异常子检查、超时进程树及运行记录拒绝。正常新路径、完整证据与合法预检复核保持可继续。
