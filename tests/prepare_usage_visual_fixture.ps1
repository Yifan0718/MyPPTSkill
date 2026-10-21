param([Parameter(Mandatory=$true)][string]$InputPptx)
$ErrorActionPreference='Stop'
$src=(Resolve-Path -LiteralPath $InputPptx).Path
$lock=$null;$app=$null;$deck=$null
try {
 $lock=[System.IO.File]::Open((Join-Path $env:TEMP 'codex-gorden-powerpoint-render.lock'),[System.IO.FileMode]::OpenOrCreate,[System.IO.FileAccess]::ReadWrite,[System.IO.FileShare]::None)
 $app=New-Object -ComObject PowerPoint.Application
 $deck=$app.Presentations.Open($src,0,0,0)
 if ($deck.Slides.Count -ne 8) { throw 'Expected the generated eight-page diagnostic fixture' }
 $chart=$deck.Slides.Item(3).Shapes.Item(3).Chart
 $label=$chart.SeriesCollection().Item(1).Points().Item(1).DataLabel
 $chart.Legend.Left=[double]$label.Left-15
 $chart.Legend.Top=[double]$label.Top-2
 $deck.Save()
 Write-Output 'Prepared deliberately overlapping native legend on diagnostic page 3.'
} finally {
 if ($deck) {$deck.Close();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($deck)}
 if ($app) {$app.Quit();[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($app)}
 if ($lock) {$lock.Dispose()}
}
