# Beamer 主题选择

未指定其他风格时直接采用已确认的[BIO0507默认风格](beamer-default-style.md)。用户要求其他风格或希望选主题时，展示实际编译的候选页，选择后固定版本、字体和宏配置；内容布局按论证职责调整。

| 候选 | 适用价值 | 接入注意 |
|---|---|---|
| Boadilla（Beamer内置） | 用户偏好的学术汇报结构；beaver、seahorse等配色可结合内容选择 | 优先列入候选；借鉴BIO0507的常规字重标题、颜色层级和紧凑贴底页脚，按本稿内容精调，不带入私人样本素材 |
| [内置起步工程](../assets/beamer-starter/) | 紧凑16:9、可调语义字体、原生公式与多图表 | 复制到工作目录，按主题替换完整示例内容，再做逐页验收 |
| [Moloch](https://github.com/jolars/moloch) | 现代学术与标题边距配置 | 固定版本，按当前公开接口调整标题高度；源码按CC BY-SA许可处理 |
| [Metropolis](https://github.com/matze/mtheme) | 简洁结构、进度条、既有项目维护 | 与Moloch按设计谱系选择；保留其主题许可 |
| [Auriga](https://github.com/anishathalye/auriga) | 图文讲述、按页源文件与notes组织 | 检查LuaTeX、字体及中文适配；MIT主题 |
| [beamertheme-tcolorbox](https://github.com/samcarter/beamertheme-tcolorbox) | 可组合的定理、方法和结论块 | 属于内部组件，和外层主题、字体、页脚合测；LPPL |
| [Argüelles](https://github.com/piazzai/arguelles) | 字体层级与数字样式 | 可用noalegre接管字体；核对列表overlay及中文字体形状；MIT |
| [Focus](https://github.com/pcafrica/focus-beamertheme) | 技术演讲与强调页 | 可用nofirafonts接管字体；检查中文small-caps与字重；GPL |
| [Spectrum](https://github.com/samcarter/beamertheme-spectrum) | 大图封面、章节叙事 | 密集正文调整标题区，不保留过高空档；LPPL |
| [thubeamer](https://github.com/YangLaTeX/thubeamer) | 中文学术与机构导航 | 按项目选择标识和导航、预检字体与预载包；LPPL |

外部候选按需获取和核对当前源码、许可及依赖；它们不是本Skill内置的八套现成模板。已有可用主题不必全部下载，也不因主题列表安装新软件。默认字体由受控清单自动配置；外部主题的指定字体单独核对同一字体的资源与许可，不因环境缺失静默换家族。配置后实际查看中英文、数学、代码、图表、长标题及overlay。

用户提供的主题可沿用其公共宏、布局与手工微调。逐处理解用途，按当前16:9页面重排；私人样本、照片、署名和机构标识不自动加入公开模板资源。
