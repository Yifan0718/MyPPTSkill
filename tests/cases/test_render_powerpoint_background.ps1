param([string]$AuditScript=(Join-Path $PSScriptRoot 'render_powerpoint_audit.ps1'))
# Contract tests only: extract function ASTs; never execute the audit entrypoint,
# create a COM application, render a deck, or write fixture files.
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($AuditScript,[ref]$tokens,[ref]$parseErrors)
if ($parseErrors.Count) {throw ($parseErrors | Out-String)}
$functions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true))
foreach ($name in @('Test-ProvenFullSlideBackground','Get-ProvenFullSlideBackgroundIds','Check-Shape')) {
    $definition=@($functions | Where-Object Name -EQ $name)
    if ($definition.Count -ne 1) {throw "Expected one function: $name"}
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
function Check-Text { } # Margin tests do not require rendered text measurement.
class MockShapeCollection {
    [object[]]$Items
    [int]$Count
    MockShapeCollection([object[]]$items) {$this.Items=$items;$this.Count=$items.Count}
    [object] Item([int]$position) {return $this.Items[$position-1]}
}
function New-MockRectangle([int]$Id=1,[int]$Position=1,[string]$Name='Plain rectangle') {
    return [pscustomobject]@{
        Id=$Id;ZOrderPosition=$Position;Name=$Name;Type=1;AutoShapeType=1;Visible=-1
        Left=0.0;Top=0.0;Width=960.0;Height=540.0;Rotation=0.0
        HasTextFrame=-1;TextFrame=[pscustomobject]@{HasText=0};HasTable=0;HasChart=0
        Line=[pscustomobject]@{Visible=0}
        Fill=[pscustomobject]@{Visible=-1;Type=1;Transparency=0.0;ForeColor=[pscustomobject]@{RGB=16777215}}
    }
}
function New-MockSlide([object[]]$Shapes) {
    return [pscustomobject]@{Shapes=[MockShapeCollection]::new($Shapes)}
}
$script:TestCount=0
function Assert-Contract([bool]$Condition,[string]$Name) {
    if (-not $Condition) {throw "FAIL: $Name"}
    $script:TestCount++
    Write-Output "PASS: $Name"
}
function Get-MarginIssues($Shape,$BackgroundIds) {
    $anchors=@{};$issues=[Collections.Generic.List[object]]::new()
    $reviews=[Collections.Generic.List[object]]::new();$chartGeometry=[Collections.Generic.List[object]]::new()
    Check-Shape $Shape 1 960.0 540.0 25.2 ([string]$Shape.Id) $BackgroundIds
    return @($issues.ToArray())
}

# Test the actual page-overlap scan body in isolation, using its parsed AST.
$overlapLoop=@($ast.FindAll({param($node)
    $node -is [Management.Automation.Language.ForEachStatementAst] -and
    $node.Variable.VariablePath.UserPath -eq 'other'
},$true))
if ($overlapLoop.Count -ne 1) {throw 'Expected the native page-number overlap scan'}
$pageOverlapProbe=[scriptblock]::Create($overlapLoop[0].Extent.Text)
function Get-PageOverlapIssues($Slide,$BackgroundIds) {
    $pageShape=[pscustomobject]@{Id=100;Name='page-number:1';Left=900.0;Top=500.0;Width=30.0;Height=15.0}
    $pl=897.0;$pt=497.0;$pr=933.0;$pb=518.0;$i=1
    # The original foreach expects COM enumeration. An array has the same
    # iteration semantics; collection indexing is tested separately above.
    $slide=[pscustomobject]@{Shapes=$Slide.Shapes.Items}
    $issues=[Collections.Generic.List[object]]::new()
    & $pageOverlapProbe
    return @($issues.ToArray())
}

$background=New-MockRectangle
$content=New-MockRectangle 2 2 'Content';$content.Left=100;$content.Top=100;$content.Width=200;$content.Height=100
$slide=New-MockSlide @($background,$content)
$ids=Get-ProvenFullSlideBackgroundIds $slide 960 540
Assert-Contract ($ids.Count -eq 1 -and $ids.ContainsKey(1)) 'unnamed white background is proven'
Assert-Contract (@(Get-MarginIssues $background $ids).Count -eq 0) 'proven background has no safe-margin error'
Assert-Contract (@(Get-PageOverlapIssues $slide $ids).Count -eq 0) 'proven background has no page-number overlap error'
$background.Fill.ForeColor.RGB=16250864
Assert-Contract ((Get-ProvenFullSlideBackgroundIds $slide 960 540).ContainsKey(1)) 'tinted background is proven without inspecting its name'
$background.Left=-10;$background.Top=-10;$background.Width=980;$background.Height=560
Assert-Contract ((Get-ProvenFullSlideBackgroundIds $slide 960 540).ContainsKey(1)) 'opaque full bleed background is proven'
$background=New-MockRectangle;$second=New-MockRectangle 2 2;$content.ZOrderPosition=3;$content.Id=3
$ids=Get-ProvenFullSlideBackgroundIds (New-MockSlide @($background,$second,$content)) 960 540
Assert-Contract ($ids.Count -eq 2 -and $ids.ContainsKey(1) -and $ids.ContainsKey(2)) 'consecutive background layers behind content are proven'
$custom=New-MockRectangle;$custom.Width=720;$custom.Height=405
Assert-Contract ((Get-ProvenFullSlideBackgroundIds (New-MockSlide @($custom)) 720 405).ContainsKey(1)) 'native custom slide dimensions are used'

$mutations=@{
    'local named proxy'={param($shape) $shape.Name='background:proxy';$shape.Left=900;$shape.Top=500;$shape.Width=40;$shape.Height=20}
    'one uncovered strip'={param($shape) $shape.Width=959.99}
    'transparent fill'={param($shape) $shape.Fill.Transparency=1.0}
    'partial alpha'={param($shape) $shape.Fill.Transparency=0.5}
    'missing opacity'={param($shape) $shape.Fill.PSObject.Properties.Remove('Transparency')}
    'nonfinite opacity'={param($shape) $shape.Fill.Transparency=[double]::NaN}
    'gradient fill'={param($shape) $shape.Fill.Type=3}
    'invisible fill'={param($shape) $shape.Fill.Visible=0}
    'hidden rectangle'={param($shape) $shape.Visible=0}
    'visible line'={param($shape) $shape.Line.Visible=-1}
    'mixed line state'={param($shape) $shape.Line.Visible=-2}
    'rotated rectangle'={param($shape) $shape.Rotation=1.0}
    'actual text'={param($shape) $shape.TextFrame.HasText=-1}
    'unknown text state'={param($shape) $shape.TextFrame.HasText=-2}
    'oval geometry'={param($shape) $shape.AutoShapeType=9}
    'group shape'={param($shape) $shape.Type=6}
    'nonfinite geometry'={param($shape) $shape.Width=[double]::PositiveInfinity}
}
foreach ($case in ($mutations.Keys | Sort-Object)) {
    $shape=New-MockRectangle
    & $mutations[$case] $shape
    $ids=Get-ProvenFullSlideBackgroundIds (New-MockSlide @($shape)) 960 540
    Assert-Contract ($ids.Count -eq 0) "$case is not exempt"
}

$local=New-MockRectangle 1 1 'background:proxy';$local.Left=900;$local.Top=500;$local.Width=40;$local.Height=20
$slide=New-MockSlide @($local);$ids=Get-ProvenFullSlideBackgroundIds $slide 960 540
Assert-Contract (@(Get-MarginIssues $local $ids).Count -eq 1) 'background name does not bypass safe margin'
Assert-Contract (@(Get-PageOverlapIssues $slide $ids).Count -eq 1) 'background name does not bypass page-number overlap'

$content=New-MockRectangle 1 1 'Content';$content.Left=100;$content.Top=100;$content.Width=200;$content.Height=100
$cover=New-MockRectangle 2 2 'background:cover';$slide=New-MockSlide @($content,$cover)
$ids=Get-ProvenFullSlideBackgroundIds $slide 960 540
Assert-Contract ($ids.Count -eq 0) 'foreground full-slide cover is not exempt'
Assert-Contract (@(Get-MarginIssues $cover $ids).Count -eq 1) 'foreground full-slide cover is checked for safe margin'
Assert-Contract (@(Get-PageOverlapIssues $slide $ids).Count -eq 1) 'foreground full-slide cover is checked for page-number overlap'

$base=New-MockRectangle 1 1;$content.Id=2;$content.ZOrderPosition=2;$cover.Id=3;$cover.ZOrderPosition=3
$ids=Get-ProvenFullSlideBackgroundIds (New-MockSlide @($base,$content,$cover)) 960 540
Assert-Contract ($ids.Count -eq 1 -and $ids.ContainsKey(1)) 'background prefix stops at the first content layer'
$badOrder=New-MockRectangle 1 2
Assert-Contract ((Get-ProvenFullSlideBackgroundIds (New-MockSlide @($badOrder)) 960 540).Count -eq 0) 'inconsistent native z-order fails closed'
Assert-Contract ((Get-ProvenFullSlideBackgroundIds (New-MockSlide @($base)) 0 540).Count -eq 0) 'invalid page dimensions fail closed'

$source=$ast.Extent.Text
Assert-Contract ($source -notmatch "(?i)\.Name\s+-\w*like\s+'background:\*'") 'no name-based background exemption remains'
Assert-Contract (([regex]::Matches($source,'\$backgroundIds=Get-ProvenFullSlideBackgroundIds \$slide \$sw \$shgt')).Count -eq 1) 'background IDs are collected once per page'
Assert-Contract ($source.Contains("reason='master_layout_visual_review'")) 'master and layout visual review remains mandatory'
Write-Output "All $script:TestCount PowerShell background contracts passed; no PowerPoint was started."
