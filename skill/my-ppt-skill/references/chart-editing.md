# 编辑图表数据

## 三种"图表"形态

| 形态 | 怎么识别 | 能不能改 |
|---|---|---|
| **原生 PPT 图表** (`shape.has_chart == True`) | python-pptx 能读到 `chart` 对象，包括 series / categories / values | **可以**，用本文方法 |
| **装饰形状组**（环形 / 旗帜 / 进度条 / 箭头流程） | 由 `<p:grpSp>` 或一堆 `<p:sp>` 拼成，没有 chart 对象 | **不会随文本自动更新**；有定量含义时必须同步重建正确图形。详见 [SKILL.md 编辑铁律 #5](../SKILL.md) |
| **图片图表**（截图 / 嵌入的 .png） | shape_type=PICTURE | 不能用原生 chart_data 接口改数据；可按真实数据源重绘并替换图片，或重建为可编辑图表 |

对每个模板，原生图表会在 `detail.json` 的 `data_charts` 数组里列出；装饰形状会通过 `shape_caution_pages` 标记。

## 编辑原生图表

本地构建工具支持下述 `edits[].chart_data` 分类图表数据格式，没有 `--chart-data` 命令行选项。XY 散点图和气泡图需要分别使用 `XyChartData` / `BubbleChartData`，构建工具会拒绝将分类数据写入它们。仅替换数据不能证明图表正确，仍须检查坐标范围、数字格式、单位、缓存的自定义标签，并实际渲染验收。

### 在 edits.json 里写

```json
{
  "slide": 8,
  "address": {"shape_id": 12},          // 仅 shape_id，不写 paragraph
  "chart_data": {
    "categories": ["Q1", "Q2", "Q3", "Q4"],
    "series": [
      {"name": "营收", "values": [120, 145, 168, 192]},
      {"name": "利润", "values": [30, 38, 45, 56]}
    ]
  }
}
```

`build_pptx.py` 看到 `chart_data` 字段会调用 python-pptx 的 `chart.replace_data(CategoryChartData)` 替换数据。**注意**：
- 类别数（categories 长度）建议 ≤ detail.json 里的 `max_categories`，超过会挤；少于也可，会变短
- 简化替换接口继承模板类型；换图型或不兼容系列结构时使用下节原生 API 或选择合适页面
- 颜色 / 标签字体仍然继承模板

### 编辑后预期效果

- 柱状图 / 折线图 / 饼图 的数据点会按新值重画
- 类别名（X 轴标签 / 饼图扇区标签）会替换
- 图例（legend）跟着 series.name 走
- 图表标题如果是 `<c:title>` 嵌入图表内部，可以通过 `chart_title` 字段单独改

### chart_data 简化接口之外的图表操作

- 改坐标轴范围 / 网格线
- 改单个数据点的颜色
- 添加 / 删除 series
- 改图表类型（柱 ↔ 饼）

上述是构建器简化数据接口的边界，不是 Skill 整体能力限制。Agent 应使用可用的原生图表 API、PowerPoint 自动化或科学绘图工具完成变更，再实际渲染核验，不把常规修复转交用户。

## 装饰形状的情况

很多模板的"图表"其实是设计师手绘的形状组合，例如：

- 圆环进度条：两条 `<a:arc>` 拼成
- 旗帜路线图：4 个 `<a:flag>` + 一条 `<a:bezier>` 曲线
- 流程箭头：连续 `<a:rightArrow>` 串
- 柱状图风格的色块：固定高度的 `<a:rect>` 数列

这些**形状不会自动随数据变化**。如果你改了"85%" → "92%"，但环形依然显示 85% 的弧度。

**处理策略**：
- 在 detail.json 里把这页放进 `shape_caution_pages` 并写明 cautions
- 任何有定量含义的弧长、柱高、面积或位置都必须与数据一致，不设“偏差 5% 可容忍”例外。
- 形状无法同步时，重建正确比例的可编辑图形、改用原生图表或适当科学绘图工具；不能保留错误比例再加说明补救。纯装饰图形不得冒充定量编码。

## 图片图表

如果模板某页放了一张已经渲染好的图表 .png，那只能：

1. 让 AI 用 matplotlib / plotly / 其他方式画一张新图，存成 .png
2. 用 python-pptx 的图片对象/关系 API 正确插入并替换旧图片，保留位置与比例；不能直接把图片字节当 XML element 替换
3. 核对新图数据及实际渲染；按需要使用科学工具，不因复杂度放弃必要图表

## 检测当前模板有没有原生图表

```bash
python3 -c "
from pptx import Presentation
p = Presentation('templates/<slug>/template.pptx')
for i, s in enumerate(p.slides, 1):
    for sh in s.shapes:
        if getattr(sh, 'has_chart', False):
            print(f'slide {i} shape {sh.shape_id}: {sh.chart.chart_type}')
"
```
