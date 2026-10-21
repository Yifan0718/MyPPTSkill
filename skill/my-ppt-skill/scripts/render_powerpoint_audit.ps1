param(
    [Parameter(Mandatory=$true)][string]$InputPptx,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [int]$Width=1600,
    [switch]$ExportPdf
)
# Windows + Microsoft PowerPoint. Read-only input; render and collect evidence.
# This is a preflight, not a substitute for visual review. Unknown/mixed fonts
# and chart internals are explicitly sent to manual review.
$ErrorActionPreference='Stop'
function Get-AuditHash([string]$Path) {
    $stream=[IO.File]::OpenRead($Path)
    $algorithm=[Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','') }
    finally { $algorithm.Dispose();$stream.Dispose() }
}
function Test-ProvenFullSlideBackground($Shape,[double]$SlideWidth,[double]$SlideHeight) {
    # COM values prove paint and geometry. Names never grant an exemption.
    # msoAutoShape=1; msoShapeRectangle=1; msoFillSolid=1; msoTrue=-1.
    try {
        if ($Shape.Type -ne 1 -or $Shape.AutoShapeType -ne 1 -or $Shape.Visible -ne -1) {return $false}
        if ($Shape.HasTextFrame -ne -1 -or $Shape.TextFrame.HasText -ne 0) {return $false}
        if ($Shape.Line.Visible -ne 0 -or $Shape.Fill.Visible -ne -1 -or $Shape.Fill.Type -ne 1) {return $false}
        $values=@($SlideWidth,$SlideHeight,$Shape.Left,$Shape.Top,$Shape.Width,$Shape.Height,$Shape.Rotation,$Shape.Fill.Transparency)
        foreach ($value in $values) {
            if ($null -eq $value -or [double]::IsNaN([double]$value) -or [double]::IsInfinity([double]$value)) {return $false}
        }
        if ($SlideWidth -le 0 -or $SlideHeight -le 0 -or $Shape.Width -le 0 -or $Shape.Height -le 0) {return $false}
        if ([double]$Shape.Rotation -ne 0 -or [double]$Shape.Fill.Transparency -ne 0) {return $false}
        # No margin tolerance: a rectangle leaving any uncovered strip is not
        # proven full-slide paint. Full bleed beyond the slide is supported.
        return ([double]$Shape.Left -le 0 -and [double]$Shape.Top -le 0 -and
            ([double]$Shape.Left+[double]$Shape.Width) -ge $SlideWidth -and
            ([double]$Shape.Top+[double]$Shape.Height) -ge $SlideHeight)
    } catch {return $false}
}
function Get-ProvenFullSlideBackgroundIds($Slide,[double]$SlideWidth,[double]$SlideHeight) {
    $backgroundIds=@{}
    try {
        # Shapes.Item(1) is the bottom native layer. Only its consecutive
        # qualifying prefix is behind every local object, including page text.
        for ($position=1;$position -le $Slide.Shapes.Count;$position++) {
            $shape=$Slide.Shapes.Item($position)
            if ($shape.ZOrderPosition -ne $position) {return @{}}
            if (-not (Test-ProvenFullSlideBackground $shape $SlideWidth $SlideHeight)) {break}
            if ($null -eq $shape.Id -or [int]$shape.Id -le 0 -or $backgroundIds.ContainsKey([int]$shape.Id)) {return @{}}
            $backgroundIds[[int]$shape.Id]=$true
        }
        return $backgroundIds
    } catch {return @{}}
}
$src=[System.IO.Path]::GetFullPath($InputPptx)
$out=[System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $out | Out-Null
$outputLock=[IO.File]::Open((Join-Path $out '.render.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
$records=[System.Collections.Generic.List[object]]::new()
$issues=[System.Collections.Generic.List[object]]::new()
$reviews=[System.Collections.Generic.List[object]]::new()
$chartLabels=[System.Collections.Generic.List[object]]::new()
$chartGeometry=[System.Collections.Generic.List[object]]::new()
$chartLegends=[System.Collections.Generic.List[object]]::new()
$rasterHashes=@{}
$renderStartedUtc=[DateTimeOffset]::UtcNow.ToString('o')
$anchors=@{}
function Check-Text($sh,$slideNo,$kind,$auditPath) {
    if ($sh.HasTextFrame -ne -1 -or $sh.TextFrame.HasText -ne -1) { return }
    $tf=$sh.TextFrame; $tr=$tf.TextRange
    $font=[double]$tr.Font.Size
    $isPageNumber=$tr.Text.Trim() -match '^[1-9][0-9]*/[1-9][0-9]*$'
    $isFooter=($sh.Name -match '^(footer|footnote|page-number):') -or ($sh.Top -ge $script:SlideHeight*.90)
    if ($isFooter -and -not $isPageNumber) {
        $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='non_page_number_footer_forbidden';text=$tr.Text})
    }
    $minimum=12*$script:FontScale
    if ($kind -eq 'table-compact') {
        $minimum=10*$script:FontScale
        $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='compact_data_table_10pt_requires_layout_reason_and_visual_review'})
    }
    elseif ($kind -eq 'table') { $minimum=12*$script:FontScale }
    elseif ($isFooter -and $isPageNumber) { $minimum=10*$script:FontScale }
    elseif ($sh.Name -like 'chart-note:compact:*') {
        $minimum=10*$script:FontScale
        $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='auxiliary_chart_note_10pt_requires_justification_and_visual_review'})
    }
    elseif ($sh.Name -like 'chart-note:dense:*') {
        $minimum=8*$script:FontScale
        $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='auxiliary_chart_note_8pt_requires_major_layout_difficulty_and_visual_review'})
    }
    $r=[ordered]@{slide=$slideNo;shape=$sh.Name;kind=$kind;text=$tr.Text;font_pt=$font;minimum_pt=$minimum;left_pt=[double]$sh.Left;top_pt=[double]$sh.Top;width_pt=[double]$sh.Width;height_pt=[double]$sh.Height;bound_width_pt=[double]$tr.BoundWidth;bound_height_pt=[double]$tr.BoundHeight}
    $r['shape_id']=[int]$sh.Id
    $r['audit_path']=[string]$auditPath
    $runFonts=[System.Collections.Generic.List[double]]::new()
    $nativeRuns=$tr.Runs()
    for($ri=1;$ri -le $nativeRuns.Count;$ri++) {
        $run=$tr.Runs($ri,1)
        if(-not $run.Text.Trim()){continue}
        $runSize=[double]$run.Font.Size
        $runFonts.Add($runSize)
        if($runSize -le 0){$reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='unresolved_run_font';run=$ri})}
        elseif($runSize -lt $minimum){$issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='run_font_too_small';run=$ri;actual=$runSize;minimum=$minimum})}
    }
    $r['run_font_sizes_pt']=@($runFonts.ToArray())
    $r['font_name']=[string]$tr.Font.Name
    $r['font_bold']=[int]$tr.Font.Bold
    $r['font_italic']=[int]$tr.Font.Italic
    $r['paragraph_alignment']=[int]$tr.ParagraphFormat.Alignment
    $r['bound_left_pt']=[double]$tr.BoundLeft
    $r['bound_top_pt']=[double]$tr.BoundTop
    try {
        $firstLine=$tr.Lines(1,1)
        $r['first_line_bounds_pt']=@([double]$firstLine.BoundLeft,[double]$firstLine.BoundTop,[double]$firstLine.BoundWidth,[double]$firstLine.BoundHeight)
    } catch {
        $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='first_line_bounds_unavailable'})
    }
    $records.Add([pscustomobject]$r)
    try {
        $lineCount=$tr.Lines().Count
        for ($lineNo=1;$lineNo -le $lineCount;$lineNo++) {
            $lineText=$tr.Lines($lineNo,1).Text.Trim()
            if ($lineCount -gt 1 -and $lineText -match '^[\uFF0C\u3002\uFF1B\uFF1A\uFF01\uFF1F\u3001,.!?;:\uFF09\u3011\u300B\u201D\u2019\u300D\u300F]+$') {
                $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='punctuation_only_line';line=$lineNo;text=$lineText})
            }
        }
        if ($lineCount -gt 1) {
            $last=$tr.Lines($lineCount,1).Text.Trim();$previous=$tr.Lines($lineCount-1,1).Text.Trim()
            if ($last.Length -le 2 -and $previous.Length -ge 8 -and $last -match '[\u4e00-\u9fff]') {
                $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='short_chinese_orphan_last_line';text=$last})
            }
        }
    } catch { $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='rendered_line_geometry_unavailable'}) }
    if ($font -le 0) { $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='mixed_or_unknown_font'}) }
    elseif ($font -lt $minimum) { $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='font_too_small';actual=$font;minimum=$minimum}) }
    if ($tr.BoundHeight -gt ($sh.Height-$tf.MarginTop-$tf.MarginBottom+2)) { $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='text_height_overflow'}) }
    if ($tr.BoundWidth -gt ($sh.Width-$tf.MarginLeft-$tf.MarginRight+2)) { $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='text_width_overflow'}) }
    if ($sh.Name -like 'short:*' -and $font -gt 0 -and $tr.BoundHeight -gt ($font*1.6)) { $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='short_label_wrapped'}) }
}
function Check-Shape($sh,$slideNo,$sw,$shgt,$margin,$auditPath,$backgroundIds,$nested=$false) {
    if ($sh.Name -like 'title:*' -or $sh.Name -like 'subtitle:*') {
        $role=($sh.Name -split ':',2)[0]
        if (-not $anchors.ContainsKey($role)) { $anchors[$role]=@([double]$sh.Left,[double]$sh.Top) }
        elseif ([Math]::Abs($sh.Left-$anchors[$role][0]) -gt 1 -or [Math]::Abs($sh.Top-$anchors[$role][1]) -gt 1) {
            $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='cross_slide_frame_anchor_requires_optical_review';role=$role;frame_left=[double]$sh.Left;frame_top=[double]$sh.Top;reference_frame=$anchors[$role]})
        }
    }
    if (-not $nested -and -not $backgroundIds.ContainsKey([int]$sh.Id)) {
        if ($sh.Left -lt $margin-.6 -or ($sw-$sh.Left-$sh.Width) -lt $margin-.6 -or ($shgt-$sh.Top-$sh.Height) -lt $margin-.6) {
            $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='outside_safe_margin';minimum_pt=$margin;left_pt=[double]$sh.Left;right_pt=[double]($sw-$sh.Left-$sh.Width);bottom_pt=[double]($shgt-$sh.Top-$sh.Height)})
        }
    }
    if ($sh.Type -eq 6) {
        $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='group_geometry_requires_visual_review'})
        foreach ($child in $sh.GroupItems) { Check-Shape $child $slideNo $sw $shgt $margin ($auditPath+'/group/'+$child.Id) $backgroundIds $true }
    }
    if ($sh.Type -eq 13 -or $sh.Type -eq 11) { $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='picture_internal_visual_review'}) }
    if ($sh.HasTable -eq -1) {
        for ($row=1;$row -le $sh.Table.Rows.Count;$row++) {
            for ($col=1;$col -le $sh.Table.Columns.Count;$col++) {
                $tableKind=if ($sh.Name -like 'table:compact:*') {'table-compact'} else {'table'}
                Check-Text $sh.Table.Cell($row,$col).Shape $slideNo $tableKind ($auditPath+'/table/'+$row+'/'+$col)
            }
        }
    } else { Check-Text $sh $slideNo 'text' $auditPath }
    if ($sh.HasChart -eq -1) {
        $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='chart_axes_curves_annotations_require_visual_review'})
        try {
            $plot=$sh.Chart.PlotArea
            $chartGeometry.Add(@{slide=$slideNo;shape_id=[int]$sh.Id;shape=$sh.Name;audit_path=$auditPath;plot_bounds_pt=@(([double]$sh.Left+[double]$plot.InsideLeft),([double]$sh.Top+[double]$plot.InsideTop),([double]$sh.Left+[double]$plot.InsideLeft+[double]$plot.InsideWidth),([double]$sh.Top+[double]$plot.InsideTop+[double]$plot.InsideHeight))})
        } catch { $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='native_plot_bounds_unavailable'}) }
        try {
            if ($sh.Chart.HasLegend) {
                try {
                    $legend=$sh.Chart.Legend
                    $chartLegends.Add(@{slide=$slideNo;shape_id=[int]$sh.Id;audit_path=$auditPath;bounds_pt=@(([double]$sh.Left+[double]$legend.Left),([double]$sh.Top+[double]$legend.Top),([double]$sh.Left+[double]$legend.Left+[double]$legend.Width),([double]$sh.Top+[double]$legend.Top+[double]$legend.Height))})
                } catch { $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='native_legend_geometry_unavailable'}) }
            }
            $labels=[System.Collections.Generic.List[object]]::new()
            $series=$sh.Chart.SeriesCollection()
            for ($si=1;$si -le $series.Count;$si++) {
                $points=$series.Item($si).Points()
                for ($pi=1;$pi -le $points.Count;$pi++) {
                    $point=$points.Item($pi)
                    if ($point.HasDataLabel) {
                        $d=$point.DataLabel
                        $item=@{slide=$slideNo;chart=$sh.Name;series=$si;point=$pi;text=$d.Text;left=[double]$d.Left;top=[double]$d.Top;width=[double]$d.Width;height=[double]$d.Height}
                        $item['audit_path']=$auditPath
                        $item['bounds_pt']=@(([double]$sh.Left+$item.left),([double]$sh.Top+$item.top),([double]$sh.Left+$item.left+$item.width),([double]$sh.Top+$item.top+$item.height))
                        $labels.Add($item);$chartLabels.Add($item)
                    }
                }
            }
            for ($a=0;$a -lt $labels.Count;$a++) {
                for ($b=$a+1;$b -lt $labels.Count;$b++) {
                    $u=$labels[$a];$v=$labels[$b]
                    $iw=[Math]::Min($u.left+$u.width,$v.left+$v.width)-[Math]::Max($u.left,$v.left)
                    $ih=[Math]::Min($u.top+$u.height,$v.top+$v.height)-[Math]::Max($u.top,$v.top)
                    if ($iw -gt 1 -and $ih -gt 1) {
                        $issues.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='native_chart_data_labels_overlap';label_a=$u;label_b=$v})
                    }
                }
            }
        } catch { $reviews.Add(@{slide=$slideNo;shape=$sh.Name;audit_path=$auditPath;reason='native_chart_data_label_geometry_unavailable';detail=$_.Exception.Message}) }
    }
}
function Initialize-DeliveryRender($Application,[string]$Snapshot,[string]$ScratchPath,[int]$Width) {
 # First-open punctuation layout can differ from later opens in PowerPoint.
 # A real disposable export followed by reopen initializes that layout state.
 if(Test-Path -LiteralPath $ScratchPath){throw 'Warmup scratch path already exists'}
 $warmupDeck=$null
 try {
  $warmupDeck=$Application.Presentations.Open($Snapshot,$true,$false,$false)
  if($warmupDeck.Slides.Count -lt 1){throw 'Warmup needs a first slide'}
  $warmupHeight=[int][Math]::Round($Width*[double]$warmupDeck.PageSetup.SlideHeight/[double]$warmupDeck.PageSetup.SlideWidth)
  $warmupDeck.Slides.Item(1).Export($ScratchPath,'PNG',$Width,$warmupHeight)
 } finally {
  try {if($warmupDeck){$warmupDeck.Close()}}
  finally {if(Test-Path -LiteralPath $ScratchPath){Remove-Item -LiteralPath $ScratchPath -Force}}
 }
}
$app=$null;$deck=$null;$globalRenderLock=$null
try {
    $globalRenderLock=[IO.File]::Open((Join-Path ([IO.Path]::GetTempPath()) 'codex-gorden-powerpoint-render.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    @{source=$src;status='rendering_not_valid_for_signoff'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out 'audit.json') -Encoding utf8
    if ($Width -le 0) {throw 'Width must be positive'}
    # Copy under a source read lock that denies concurrent write/delete.
    $snapshot=Join-Path $out ('input-snapshot-'+[guid]::NewGuid().ToString()+'.pptx')
    $sourceStream=$null;$targetStream=$null
    try {
        $sourceStream=[IO.File]::Open($src,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
        $sourceHashBefore=(Get-AuditHash $src)
        $targetStream=[IO.File]::Open($snapshot,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        $sourceStream.CopyTo($targetStream)
    } finally { if($targetStream){$targetStream.Dispose()};if($sourceStream){$sourceStream.Dispose()} }
    $snapshotHash=(Get-AuditHash $snapshot)
    if($snapshotHash -ne $sourceHashBefore){throw 'Snapshot hash mismatch'}
    @{source=$src;sha256=$snapshotHash;snapshot=$snapshot;status='rendering_not_valid_for_signoff'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $out 'audit.json') -Encoding utf8
    $app=New-Object -ComObject PowerPoint.Application
    Initialize-DeliveryRender $app $snapshot (Join-Path $out ('warmup-'+[Guid]::NewGuid().ToString('N')+'.png')) $Width
    if((Get-AuditHash $src) -ne $sourceHashBefore -or (Get-AuditHash $snapshot) -ne $snapshotHash){throw 'Source or snapshot changed during render warmup'}
    $deck=$app.Presentations.Open($snapshot,$true,$false,$false)
    $sw=[double]$deck.PageSetup.SlideWidth; $shgt=[double]$deck.PageSetup.SlideHeight
    $script:FontScale=$shgt/540.0
    $script:SlideHeight=$shgt
    $margin=$shgt*(.35/7.5);$height=[int][Math]::Round($Width*$shgt/$sw)
    for ($i=1;$i -le $deck.Slides.Count;$i++) {
        $slide=$deck.Slides.Item($i)
        $slide.Export((Join-Path $out ('slide-{0:00}.png' -f $i)),'PNG',$Width,$height)
        $rasterHashes[[string]$i]=Get-AuditHash (Join-Path $out ('slide-{0:00}.png' -f $i))
        $reviews.Add(@{slide=$i;audit_path='master-layout';reason='master_layout_visual_review'})
        $backgroundIds=Get-ProvenFullSlideBackgroundIds $slide $sw $shgt
        foreach ($shape in $slide.Shapes) { Check-Shape $shape $i $sw $shgt $margin ([string]$shape.Id) $backgroundIds }
        $pageNumberCount=0
        foreach ($pageShape in $slide.Shapes) {
            if ($pageShape.HasTextFrame -ne -1 -or $pageShape.TextFrame.HasText -ne -1) {continue}
            $pageText=$pageShape.TextFrame.TextRange.Text.Trim()
            if (($pageShape.Name -like 'page-number:*' -or $pageShape.Top -ge $shgt*.9) -and $pageText -match '^[1-9][0-9]*/[1-9][0-9]*$') {
                $pageNumberCount++
                $expectedPageNumber=('{0}/{1}' -f $i,$deck.Slides.Count)
                if ($pageText -ne $expectedPageNumber) {
                    $issues.Add(@{slide=$i;shape=$pageShape.Name;reason='page_number_sequence_or_total_wrong';actual=$pageText;expected=$expectedPageNumber})
                }
                $pad=3*$script:FontScale
                $pl=$pageShape.Left-$pad;$pt=$pageShape.Top-$pad
                $pr=$pageShape.Left+$pageShape.Width+$pad;$pb=$pageShape.Top+$pageShape.Height+$pad
                foreach ($other in $slide.Shapes) {
                    if ($other.Id -eq $pageShape.Id -or $backgroundIds.ContainsKey([int]$other.Id)) {continue}
                    if ($other.Left -lt $pr -and ($other.Left+$other.Width) -gt $pl -and $other.Top -lt $pb -and ($other.Top+$other.Height) -gt $pt) {
                        $issues.Add(@{slide=$i;shape=$pageShape.Name;reason='page_number_zone_overlap';overlapping_shape=$other.Name})
                    }
                }
            }
        }
        if ($pageNumberCount -ne 1) { $issues.Add(@{slide=$i;reason='page_number_missing_or_duplicate';count=$pageNumberCount;expected=('{0}/{1}' -f $i,$deck.Slides.Count)}) }
    }
    if ($ExportPdf) { $deck.SaveAs((Join-Path $out 'preview.pdf'),32) }
    $snapshotHashAfter=(Get-AuditHash $snapshot)
    $sourceHashAfter=if(Test-Path -LiteralPath $src){(Get-AuditHash $src)}else{$null}
    if($sourceHashAfter -ne $sourceHashBefore -or $snapshotHashAfter -ne $snapshotHash){$issues.Add(@{reason='input_changed_during_render';before=$sourceHashBefore;after=$sourceHashAfter;snapshot_after=$snapshotHashAfter})}
    $report=@{source=$src;sha256=$snapshotHash;source_hash_before=$sourceHashBefore;source_hash_after=$sourceHashAfter;snapshot=$snapshot;snapshot_hash_after=$snapshotHashAfter;slide_count=$deck.Slides.Count;width_pt=$sw;height_pt=$shgt;minimum_margin_pt=$margin;issues=@($issues.ToArray());manual_review=@($reviews.ToArray());text_records=@($records.ToArray());chart_label_records=@($chartLabels.ToArray());status=$(if($issues.Count){'failed_preflight'}else{'rendered_pending_visual_review'})}
    $report['chart_geometry_records']=@($chartGeometry.ToArray())
    $report['chart_legend_records']=@($chartLegends.ToArray())
    $report['schema']='render-evidence/v2'
    $toolRunPath=Join-Path $out 'tool-run.json'
    if(Test-Path -LiteralPath $toolRunPath) {$toolRun=Get-Content -LiteralPath $toolRunPath -Raw | ConvertFrom-Json;$report['bounded_run_id']=$toolRun.run_id}
    $report['raster_hashes']=$rasterHashes
    $report['render_started_utc']=$renderStartedUtc
    $report['render_finished_utc']=[DateTimeOffset]::UtcNow.ToString('o')
    for($mi=0;$mi -lt $reviews.Count;$mi++) {$reviews[$mi]['review_id']='m'+($mi+1)}
    $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $out 'audit.json') -Encoding utf8
    Write-Output "Rendered $($deck.Slides.Count) slides; issues=$($issues.Count); manual_review=$($reviews.Count)."
} catch {
    @{source=$src;status='failed_render';issues=@(@{reason='render_exception';detail=$_.Exception.Message})} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $out 'audit.json') -Encoding utf8
    throw
} finally {
    try { if ($deck) {$deck.Close()} } finally {
        try { if ($app -and $app.Presentations.Count -eq 0) {$app.Quit()} } finally { if($globalRenderLock){$globalRenderLock.Dispose()};$outputLock.Dispose() }
    }
}
if ($issues.Count -gt 0) {exit 2}
exit 0
