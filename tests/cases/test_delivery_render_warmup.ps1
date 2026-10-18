# Test extracted production functions with mocks, never launch PowerPoint.
$ErrorActionPreference='Stop'
$count=0;$definitions=@()
function Assert-Warmup([bool]$Value,[string]$Message){if(-not $Value){throw $Message};$script:count++}
function New-WarmupMock([string]$Failure=''){
 $slide=[pscustomobject]@{Failure=$Failure;Width=0;Height=0}
 $slide|Add-Member ScriptMethod Export {param($path,$format,$width,$height) $this.Width=$width;$this.Height=$height;Set-Content -LiteralPath $path -Value 'fixture';if($this.Failure -eq 'export'){throw 'export failure'}}
 $slides=[pscustomobject]@{Count=1;Slide=$slide}
 $slides|Add-Member ScriptMethod Item {param($index) return $this.Slide}
 $deck=[pscustomobject]@{Slides=$slides;PageSetup=[pscustomobject]@{SlideHeight=540;SlideWidth=960};Closed=0;Failure=$Failure}
 $deck|Add-Member ScriptMethod Close {$this.Closed++;if($this.Failure -eq 'close'){throw 'close failure'}}
 $presentations=[pscustomobject]@{Deck=$deck;Failure=$Failure;Calls=0;Arguments=@()}
 $presentations|Add-Member ScriptMethod Open {param($path,$readOnly,$untitled,$withWindow) $this.Calls++;$this.Arguments=@($path,$readOnly,$untitled,$withWindow);if($this.Failure -eq 'open'){throw 'open failure'};return $this.Deck}
 return [pscustomobject]@{Presentations=$presentations}
}
$scratchDir=Join-Path ([IO.Path]::GetTempPath()) ('warmup-contract-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratchDir|Out-Null
try {
 foreach($file in @('prepare_pptx_delivery.ps1','render_powerpoint_audit.ps1')){
  $tokens=$null;$errors=$null
  $ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file),[ref]$tokens,[ref]$errors)
  Assert-Warmup ($errors.Count -eq 0) "$file parse"
  $function=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Initialize-DeliveryRender'},$true))
  Assert-Warmup ($function.Count -eq 1) "$file function count"
  $definitions+=$function[0].Extent.Text
  . ([scriptblock]::Create($function[0].Extent.Text))
  foreach($failure in @('','open','export','close')){
   $app=New-WarmupMock $failure;$scratch=Join-Path $scratchDir ([Guid]::NewGuid().ToString('N')+'.png');$threw=$false
   try {Initialize-DeliveryRender $app 'snapshot.pptx' $scratch 1600}catch{$threw=$true}
   Assert-Warmup ($threw -eq ($failure -ne '')) "$file propagates $failure"
   Assert-Warmup (-not (Test-Path -LiteralPath $scratch)) "$file cleans $failure"
   Assert-Warmup ($app.Presentations.Deck.Closed -eq $(if($failure -eq 'open'){0}else{1})) "$file closes only opened deck $failure"
   Assert-Warmup ($app.Presentations.Arguments[1] -eq $true -and $app.Presentations.Arguments[2] -eq $false -and $app.Presentations.Arguments[3] -eq $false) "$file background read-only $failure"
   if($failure -eq ''){Assert-Warmup ($app.Presentations.Deck.Slides.Slide.Width -eq 1600 -and $app.Presentations.Deck.Slides.Slide.Height -eq 900) "$file dimensions"}
  }
  $app=New-WarmupMock;$scratch=Join-Path $scratchDir 'existing.png';Set-Content -LiteralPath $scratch -Value 'keep'
  $threw=$false;try{Initialize-DeliveryRender $app 'snapshot.pptx' $scratch 1600}catch{$threw=$true}
  Assert-Warmup ($threw -and $app.Presentations.Calls -eq 0 -and (Get-Content -LiteralPath $scratch) -eq 'keep') "$file preserves existing scratch"
  Remove-Item -LiteralPath $scratch
 }
 Assert-Warmup ($definitions[0].Replace("`r`n","`n") -ceq $definitions[1].Replace("`r`n","`n")) 'Preparation and final renderer use identical warmup'
 Write-Output "PASS: $count warmup contracts"
} finally {
 # Directory is uniquely created by this test and must now be empty.
 Remove-Item -LiteralPath $scratchDir
}
