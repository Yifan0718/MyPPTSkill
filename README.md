# MyPPTSkill

**当前版本：1.0** · [下载 Release](https://github.com/Yifan0718/MyPPTSkill/releases/tag/v1.0)

## TL;DR

**复杂 PPT，讲得漂亮，排得整齐。**

充分发挥多模态 AI 的视觉能力，不靠一遍直出：逐页看图、反复核验细节、修正后再检查，尽最大努力把排版打磨到完美。

- **摆脱 AI 味**：去掉免责声明、空洞套话、长篇赘述和小字堆砌，让表达自然、清楚、有判断。
- **告别排版错乱**：溢出、遮挡、挤压和悬空箭头，逐项找出、修正到位。
- **强迫症级对齐与统一**：从字形起点到图表边界，从横纵间距到跨页风格，细节逐一打磨。
- **复杂内容照样好看**：多图表、代码、公式和科研图文混排，兼顾信息密度与可读性。
- **你的规则，持续有效**：持续跟进上游 GordenPPTSkill 更新，自适应保留已固化的定制规则与修复。

**21 套中文模板 · 10 份实际样本 · 87 页成品展示 · 完整开发测试**

[安装与使用](skill/my-ppt-skill/README.md#安装与使用) · [查看成品](examples/README.md) · [87页预览](examples/all-samples-87-pages.pdf) · [完整差异](skill/my-ppt-skill/docs/UPSTREAM_DIFFERENCES.md)

## 直接看效果

| [多图表与科学混排](examples/01_scientific-charts/README.md) | [长稿与复杂图解](examples/05_inference-scaling/README.md) | [MATLAB源码与图像](examples/10_matlab-tiledlayout/README.md) |
|---|---|---|
| [![科学混排](examples/01_scientific-charts/preview.png)](examples/01_scientific-charts/README.md) | [![推理扩容](examples/05_inference-scaling/showcase.png)](examples/05_inference-scaling/README.md) | [![MATLAB教学](examples/10_matlab-tiledlayout/showcase.png)](examples/10_matlab-tiledlayout/README.md) |

以下展示成品中的实际内容页。[点击查看完整样本](examples/README.md)。全部10份样本包含科学混排、世界模型、Do-JEPA、电力转型、推理集群、C++、LaTeX和MATLAB主题。

## 快速开始

将 `skill/my-ppt-skill` 文件夹安装到工具的Skills目录，使用 `$my-ppt-skill` 调用：

```text
使用 $my-ppt-skill 制作6页MATLAB教学PPT，含独立封面。
使用数据可视化模板，包含源码与实际生成的图像。
作者“示例作者”，逐页检查后交付PPTX和PDF。
```

也支持用户自己的PPTX模板和完全原创设计。详细环境、需求确认与默认选项见 [Skill README](skill/my-ppt-skill/README.md)。

## 发布资源导航

| 内容 | 入口 |
|---|---|
| 安装目录与完整使用文档 | [Skill](skill/my-ppt-skill/README.md) |
| 额外要求、解决的问题与上游差异 | [差异说明](skill/my-ppt-skill/docs/UPSTREAM_DIFFERENCES.md) |
| 最终10份样本、87页及可用教学源码 | [样本目录](examples/README.md) |
| 当前适用测试与统一运行入口 | [开发测试](tests/README.md) |
| 本版验证摘要 | [验证结果](VALIDATION.md) |
| GitHub侧边简介与Topics文案 | [GitHub About](GITHUB_ABOUT.md) |

安装时只复制Skill目录；样本与开发测试作为独立发布资源使用。资源保留当前版本适用的文件，排除旧候选、迭代快照和原始开发日志。

## 开发与测试

项目开发与测试使用 **GPT6-Astra**，配合官方 **ChatGPT Desktop（Codex）Harness**。实际使用建议选择长程思维能力和多模态能力都较强的高级模型，充分发挥视觉观察、复杂推理和多轮迭代能力。

## Fork来源与许可

Fork自 **[GordenSun/GordenPPTSkill](https://github.com/GordenSun/GordenPPTSkill)**。定制维护者：**Yifan0718**（[liuyifan111111@gmail.com](mailto:liuyifan111111@gmail.com)）。新增和修改部分采用MIT，上游代码、模板与其他第三方素材按各自原许可处理。完整归属和授权范围见[许可说明](skill/my-ppt-skill/docs/LICENSE_SCOPE.md)。
