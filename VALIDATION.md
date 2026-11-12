# MyPPTSkill 2.0 验证摘要

## 当前测试

| 检查 | 结果 |
|---|---:|
| Skill Python回归 | 815 / 815通过 |
| 发布入口控制流测试 | 6 / 6通过 |
| PowerShell后台渲染与清理流程 | 2 / 2通过 |
| 跳过 | 0 |

测试覆盖规则与视觉闭环的正反路径、原始证据保留、图片像素与联合覆盖、字体配置、执行超时、错误传导、更新回滚及首图/普通视图。运行方式见[测试入口](tests/README.md)。

本版验证环境：Windows，Python 3.12.14，Microsoft PowerPoint／Word原生渲染，TeX Live 2026。依赖版本见[测试依赖](tests/requirements-test.txt)。

## 旗舰作品

| 作品 | Slides | 讲稿 |
|---|---:|---|
| 中文：从梯度下降到共轭梯度 | 20页Beamer PDF＋源码 | 7页LaTeX PDF＋源码 |
| 中文：从传感器数据到可信频谱 | 20页PPTX＋PDF | 6页Word讲稿＋PDF |
| English: Kalman Filtering | 20页Beamer PDF＋源码 | 7页LaTeX PDF＋源码 |
| English: Database Indexes | 20页PPTX＋PDF | 5页Word讲稿＋PDF |

四套作品均来自当前选定的最终签核文件。发布整理核对文件哈希、20页页序、讲稿对应关系、源码、原图、实际第一页预览和正文展示页；80页合订PDF保留原页面，提供四个章节书签。公开资源使用相对路径及SHA-256清单，便于完整下载和复核。

## 安装与更新保护

安装包保留完整Skill目录、21套模板、公共脚本、参考规范及字体准备资源。定制规则、脚本与资源纳入更新保护注册表，更新按检查、暂存、审查、应用执行。
