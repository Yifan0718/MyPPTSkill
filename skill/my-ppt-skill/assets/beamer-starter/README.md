# Beamer 起步工程

默认使用[BIO0507轻量学术风](../../references/beamer-default-style.md)：在theme.tex之后加载bio0507-style.tex。用户指定其他主题时保留基础工程并按所选主题调整。

三页二次函数梯度下降示例覆盖递推推导、数值核对、双面板图、代码和停止条件。数据来自明确公式；无需下载图片、运行外部高亮器或生成数据文件。曲线的可编辑计算源在 `figures/convergence.tex`。

## 文件与依赖

| 文件 | 作用 |
|---|---|
| `main.tex` | 正文、公式、表格、代码及稳定 frame 标签 |
| `fonts.tex` | 加载受控清单生成的精确字体配置 |
| `theme.tex` | 颜色、边距、语义字号、图表样式及页脚 |
| `figures/convergence.tex` | 两组公式曲线及完整坐标轴 |

使用已安装的 XeLaTeX 或 LuaLaTeX，宏包为 Beamer、fontspec、ctex、amsmath、booktabs、TikZ 和 PGFplots（支持 `compat=1.18`）。宏包与字体需在当前环境中实际可用。字体由受控清单固定为Fandol与Latin Modern，build_beamer自动配置同一字体文件；源码按生成的myppt-fonts.tex直接加载。中文代码角色使用FandolFang，西文代码使用LM Mono。详情见[自动字体配置](../../references/bundled-fonts.md)。

## 构建

推荐从工作副本使用Skill的`build_beamer.py`完成隔离构建、逐页渲染和哈希记录，再按[Beamer流程](../../references/beamer-workflow.md)核验签核。手动调用编译器时，先用setup_fonts.py --project-dir 当前工程目录生成字体配置；然后运行以下基础命令，输出目录先创建：

```sh
xelatex -halt-on-error -interaction=nonstopmode -output-directory=build main.tex
xelatex -halt-on-error -interaction=nonstopmode -output-directory=build main.tex
```

Windows PowerShell 可先执行 `New-Item -ItemType Directory -Force build`；其他 shell 使用对应的建目录命令。可以用 `lualatex` 替换 `xelatex`。第二遍用于刷新总页数和交叉引用。运行时生成的`myppt-fonts.tex`直接指向本机已验证的字体缓存。

源码交付前用`setup_fonts.py --project-dir 当前工程目录 --export-bootstrap`加入独立字体准备入口。接收者运行`python prepare-fonts.py`后编译；源码包包含`font-support/`，排除本机生成的`myppt-fonts.tex`及安装报告。完整方法见[字体资源](../../references/bundled-fonts.md#工作工程与源码交付)。

## 调整与验证

正文直接从第一项论证开始。需要封面、目录、章节过渡或附录时，在 `main.tex` 中明确添加相应 frame。画布为 16:9；页脚 `x/y` 统计实际 PDF 页，overlay 的每个输出状态也计数。

先在 `theme.tex` 调整正文、辅助文字、代码、图内标签等语义字体角色，再用实际内容试排。这里的字号是原生 Beamer 画布上的 TeX pt；最终显示尺寸和外层缩放仍须核查。图内字号独立设置，图框宽度包含 PGFplots 的整体估计尺寸，实际标签边界要看最终 PDF。

编译后渲染全部 PDF 页并逐页查看中文、公式、表格、图内标签、代码缩进和页脚；局部问题修正后重新编译及渲染。质量依据见 [Beamer 图表实践](../../references/beamer-charts.md)、[内容与证据](../../references/audience-and-evidence.md)、[布局完整性](../../references/layout-integrity.md)及[签核流程](../../references/signoff-workflow.md)。编译日志用于定位问题，视觉复核记录和构建产物留在实际任务的工作目录。
