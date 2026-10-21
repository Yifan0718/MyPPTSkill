# 第一页缩略图与普通打开视图

## 默认与检查范围

- 所有成品PPTX的内嵌缩略图使用该文件**实际第一页的完整渲染图**，按比例缩小，不裁切、不加宣传叠层。禁止沿用模板的价格、定制服务、二维码、推广海报或其他旧缓存；文件名叫thumbnail不构成来源证明。
- 包级缩略图使用JPEG：微软SDK的[ThumbnailPartType](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.packaging.thumbnailparttype)列出JPEG/EMF/WMF，不列PNG；使用JPEG以保证PowerPoint包级缩略图兼容性。正文图片和外部`preview.png`可以使用PNG，不能把正文图片的格式支持套到包级缩略图。若默认缓存路径已被正文媒体复用，保留媒体并另建独立缩略图部件，不覆盖正文，也不死循环重试同一冲突路径。
- 模板选择用的`preview.png`也使用当前模板的实际第一页，不再使用旧拼图或广告封面。缺失或无法确认来源时，将模板复制到工作目录，实际导出第一页后显示；不能因为缺预览就停工，也不在普通使用任务中擅自修改安装版模板。
- 文件保存的默认视图为普通幻灯片视图，左侧幻灯片缩略图竖栏，右侧完整幻灯片并自动适应窗口。使用`viewPr@lastView=sldView`、`normalViewPr@preferSingleView=0`、两项BarState=`restored`，左右分隔约18%、上下约90%；`slideViewPr/cSldViewPr/cViewPr@varScale=1`。保留合法scale/origin、网格和参考线；`showOutlineIcons`不是缩略图/大纲选项的选择器。
- 不改用户的PowerPoint应用级偏好，不通过修改正文、页数、作者或普通属性来修复缓存。应用可能记住个人打开偏好，但文件自身必须保存上述值；必要时以独立副本重新打开检查普通视图和窗格。

## 顺序：先准备外壳，再最终渲染

1. 完成正文编辑与元数据清理。`strip_pptx_metadata.py`同时清除旧缩略图并规范打开视图，刚构建的中间稿允许没有缩略图。
2. 调用`prepare_pptx_delivery.ps1`，从稳定副本实际导出第一页，再写入320像素宽的兼容JPEG缩略图（首图仍以PNG实际导出）及普通视图。`-Width`须与后续全页渲染相同，默认1600，避免不同采样分辨率造成缩略图像素不一致。
3. 对已准备好的候选执行原来的只读全页渲染、内容/版式双遍、局部复核和最终证据校验。最终门槛将当前`slide-01.png`按同样的JPEG质量95、subsampling=0、baseline编码后，比较内嵌缩略图的全部解码像素，同时检查普通视图；初次coverage和渲染不因尚未准备缩略图而无法启动。
4. 如之后又编辑、重存或运行metadata清理，重新从第2步准备并完成适用范围的最终渲染；不能用旧图、改哈希或手补成功报告。已签核后用户只要求缩略图/视图修订时，保留原始文件与签核，证明正文/素材等未变，并单独记录外壳修订哈希和真实首图来源，不能伪改旧签核。

```powershell
python -X utf8 scripts/strip_pptx_metadata.py candidate.pptx --author "已确认的作者"
if ($LASTEXITCODE -ne 0) { throw '先解决元数据清理失败' }
python -X utf8 scripts/run_bounded.py --timeout 300 --status-report work/shell-tool-run.json -- powershell -NoProfile -ExecutionPolicy Bypass -File scripts/prepare_pptx_delivery.ps1 -InputPptx candidate.pptx -OutputDir work/shell-prep -PythonExe "当前可用Python路径" -Width 1600
if ($LASTEXITCODE -ne 0) { throw '读取失败记录并修复后重试首图准备' }
python -X utf8 scripts/run_bounded.py --timeout 300 --status-report work/final-render/tool-run.json -- powershell -NoProfile -ExecutionPolicy Bypass -File scripts/render_powerpoint_audit.ps1 -InputPptx candidate.pptx -OutputDir work/final-render -Width 1600 -ExportPdf
# 保留渲染返回码与原报告，按签核流程分类、交叉检查和闭环。
```

首次准备失败时读取对应run目录的错误，修复输入、运行时或渲染环境后重试；没有PowerPoint时可用实际可用渲染器导出当前第一页，并经`pptx_delivery_shell.py finalize`绑定真实源哈希。最终全页渲染仍需满足既有证据规范。不存在真实首图时不能用模板广告或空白图替代，也不能因此跳过其余可继续的工作。

## PowerPoint默认后台运行

- 正常构建、缩略图准备、渲染和导出均使用`Presentations.Open(..., ReadOnly=true, Untitled=false, WithWindow=false)`等后台方式；不设置Visible=true，不Activate、不切前台、不弹出演示窗口。
- 只关闭自动化自己打开的副本；不关闭用户已有文档、不结束其他PowerPoint进程、不改用户正在编辑的文件。遵守现有全局串行锁。
- 首图准备和最终只读渲染使用相同的后台预热：在全局锁内只读打开快照，实际导出一张临时首图，关闭该副本，再只读重开进行正式导出。仅打开关闭或等待不能替代实际预热导出。该步骤用于统一PowerPoint实例首次打开与后续打开的排版初始化状态。临时预热图不作审查证据，成功或异常均清理；预热后再次检查源文件和快照哈希。若正式两次渲染仍不一致，继续查明字体/运行时原因，不能降低缩略图匹配门槛。
- 必须使用可见窗口才能完成的必要UI验证，应先说明原因、尽量最小化并恢复原环境；不把这种例外变成普通渲染流程。后台失败先检查错误及替代方式，不默认改成弹窗模式。

## 更新后保留

已清理的模板PPTX、第一页preview、脚本和本规则纳入本地更新保护。上游新增/未保护模板在更新应用时先清广告缓存并规范视图；上游preview不直接用于展示，记录为待从第一页重新生成。使用时可以在工作副本生成预览再继续，不要求为缺少缓存再次确认用户权限。更新错误须回滚并传递非零退出码。

参考：微软[视图枚举](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.presentation.viewvalues)、[自动适配视图](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.presentation.commonviewproperties.variablescale)。
