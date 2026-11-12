# 固定字体资源与自动配置

默认Beamer风格使用清单锁定的Fandol与Latin Modern，按具体文件加载；各文件、版本、字体角色与SHA-256见[fonts.json](../assets/fonts/fonts.json)。字体配置不依赖找到名称相近的替代家族。

## 自动使用

默认起步工程带有managed-font-entry，`build_beamer.py`在输入快照之前自动配置字体、生成`myppt-fonts.tex`，并绑定实际字体文件的哈希。也可单独执行：

```text
python scripts/setup_fonts.py --project-dir work/source --report work/font-setup.json
```

- Latin Modern原始字体和完整上游包随Skill提供。
- Fandol优先复用本机或缓存中SHA完全相同的文件；缺失时自动取得清单锁定的CTAN官方包，验证包及字体后缓存。`--offline`仅使用已有精确资源。
- Windows在当前用户字体目录和HKCU注册并通知字体变化；Linux/macOS走用户级字体目录和可用注册/缓存机制。报告记录实际成功、冲突或未验证状态。
- Beamer直接从精确缓存文件加载。OS注册未成功、缓存已就绪时可继续Beamer构建；PowerPoint还需核对系统字体实际可用。Windows使用报告中的`windows_family`名称，随后实际渲染验证，不把仅复制文件称为字体已经生效。
- 配置退出0为缓存配置及OS可用；2为精确缓存配置可用而OS未就绪；1为参数、资源、配置或报告写入失败。结合当前报告中的cache_ready、stage和errors判断，保留具体错误并修复，继续不依赖该字体的文稿/计算工作；不能悄悄更换字体。
- 缓存损坏时保留诊断、隔离有问题的托管副本并恢复同一版本。已有同名不同内容的用户字体或配置保持不变；不要覆盖其他字体或关闭用户未保存的应用。

此受控字体包的自动取得与用户级配置已获长期授权；额外软件、TeX宏包及Python依赖仍按各自授权处理。

## 下载与配置失败后的恢复

下载使用可终止子进程：每个固定镜像最多20秒，整次下载总预算60秒，连接/DNS、重定向和慢速读取均在父进程时限内。镜像失败后尝试下一固定镜像，完整包及字体均校验SHA-256；本机字体探测总预算20秒。系统注册逐项记录，累计预算耗尽时保留精确缓存并返回2，Beamer可继续按文件加载。

| 情况 | 恢复动作 |
|---|---|
| 断网、超时、传输中断、包校验失败 | 读取error_code、errors和recovery，恢复网络或提供同版本已验证资源后再重试；完整缓存可直接离线使用 |
| 托管缓存中出现半包、损坏字体或解压文件 | 工具将损坏副本隔离到quarantine并保存诊断，再从已验证来源原子恢复；源码和用户已安装字体保持原样 |
| 缓存不可写、目录/链接冲突 | 用setup_fonts的--cache-dir或build_beamer的--font-cache-dir指定新的可写目录，保留原冲突路径 |
| --offline且没有精确资源 | 返回1并说明缺失；恢复联网准备或指向已准备的缓存，再继续构建 |
| 原配置或用户字体同名不同内容 | 保留用户文件；在新工作副本解决配置或修复原字体安装，不覆盖或自动换字体 |
| 配置成功但报告无法写入 | 返回1，stdout保留配置结果和report-write错误；换新的可写--report路径重试 |

每次失败先改变具体故障条件再重试，避免原样循环调用。构建报告保留字体阶段的原始状态和恢复建议；字体缺失时先恢复有效输出，再继续规则与视觉核验。保持原大纲、数据、公式与实例，环境修复不能通过删减关键内容完成。

## 字体角色

| 用途 | 确定的字体 |
|---|---|
| 中文正文、标题 | FandolHei Regular；需要真实粗体时用FandolHei Bold |
| 中文强调、等宽角色 | FandolKai、FandolFang，按清单指定样式使用 |
| 西文正文、无衬线、代码 | LM Roman 10、LM Sans 10、LM Mono 10；粗体/斜体使用清单列出的真实字形文件 |
| 可选OpenType数学 | Latin Modern Math；项目主动启用unicode-math时才切换数学后端 |

不请求清单中未支持的样式来制造强调；字体缺字或形状替换定位到实际字符/位置并修复。普通标题优先常规字重，遵守默认风格与全稿语义字号。

## 工作工程与源码交付

`myppt-fonts.tex`是可再生运行配置，含当前机器缓存路径。换电脑后运行字体配置或Skill构建入口重新生成。源码包保留源稿、字体配置入口、锁定清单/许可和复现步骤；排除机器路径配置、OS安装记录及Fandol下载缓存。接收者按同一清单自动取得原字体，无须自行选择替代。

交付源码前导出独立准备入口：

```text
python scripts/setup_fonts.py --project-dir work/source --export-bootstrap
```

它生成`prepare-fonts.py`和`font-support/`，只复制公开资源；已有不同内容的同名文件会被保留并报告冲突。接收者在源码目录执行`python prepare-fonts.py`，再运行XeLaTeX或LuaLaTeX。入口仅需Python标准库，支持`--offline`、`--cache-dir`及`--no-install`，并保留0／2／1退出状态。只使用TeX文件加载时，退出2且缓存已就绪即可继续编译。源码压缩包排除`myppt-fonts.tex`、字体安装报告和构建日志；在工作副本重新准备、编译并检查，验证可移植性。

## 许可与来源

| 资源 | 来源与版本 | 分发方式 |
|---|---|---|
| Latin Modern | [CTAN lm](https://ctan.org/pkg/lm)，2.005 | OTF、完整官方ZIP和GUST Font License随包 |
| Latin Modern Math | [CTAN lm-math](https://ctan.org/pkg/lm-math)，1.959 | OTF、完整官方ZIP和GUST Font License随包 |
| Fandol | [CTAN fandol](https://ctan.org/pkg/fandol)，0.3 | 使用机器直接取得固定官方包；Skill保存许可、来源及校验清单 |

Fandol采用GPLv3及文档嵌入例外。当前官方发布包含OTF、README与COPYING，对应编辑源的完整性尚未确认，因此公开Skill采用官方自动获取方案；用户缓存保留完整原包与许可。生成文档的字体嵌入按其例外处理。

第三方字体沿用各自许可。原始版权/许可材料在`assets/fonts/licenses/`，LM完整发布包在`assets/fonts/upstream/`；新增配置工具采用本项目MIT许可。字体文件保持原始字节。
