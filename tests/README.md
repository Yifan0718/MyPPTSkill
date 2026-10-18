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

无PowerShell环境可以明确选用 `--python-only`，结果标为Python范围通过，不声称完成PowerShell检查。

## 自动测试与视觉测试的边界

另提供真实PowerPoint端到端入口，验证元数据清理、首图准备、后台全页渲染、快照及缩略图／普通视图。它只修改工作副本，默认使用样本01：

```text
python tests/run_integration.py --output test-results/powerpoint-01
```

单独下载测试包时同时指定 `--skill-root` 和 `--input`。需要Windows PowerShell与已安装的PowerPoint。成功状态为 `pipeline_checks_passed_visual_review_pending`，只表示真实工具链完成，仍须逐页／局部视觉复核；版式预检问题返回非零并保留报告，按照Skill复核，不直接停工或自动豁免。

完整自动套件包含333项Skill Python测试、6项发布入口控制流测试，以及76项PowerShell契约检查。覆盖构建、图表、间距和像素对齐、连接、字号证据、独立视觉兜底、签核完整性、更新保护、错误传播、事务回滚、缩略图与后台准备。分组详见 [TEST_MATRIX.md](TEST_MATRIX.md)。

可同时生成两页可编辑复杂图表夹具：

```text
python tests/run_tests.py --output test-results/run-02 --visual-fixture test-results/complex.pptx
```

生成夹具不等于视觉通过。需要用Skill的prepare和真实render流程检查该文件，再逐页和局部查看。图像不能以代码示意替代；自动测试不能替代真实PPT签核。

最终十份真实样本见完整资源中的examples目录，其文件与已验收稿保持一致。它们是现成示例，不是当前套件运行时必须依赖的旧夹具。

测试代码中包含有意构造的失败输入和反例，例如路径拒绝、错误状态、布局冲突、异常中断；这些是现行负向测试，不是历史失败稿。版权和许可参见资源根目录licenses。
