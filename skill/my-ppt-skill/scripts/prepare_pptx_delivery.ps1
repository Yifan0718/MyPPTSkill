param(
 [Parameter(Mandatory=$true)][string]$InputPptx,
 [Parameter(Mandatory=$true)][string]$OutputDir,
 [string]$PythonExe='python',
 [ValidateRange(320,10000)][int]$Width=1600
)
# Prepare derived thumbnail and saved view before the final read-only full render.
$ErrorActionPreference='Stop'
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
function Get-DeliveryHash([string]$Path) {
 $stream=[IO.File]::OpenRead($Path);$algorithm=[Security.Cryptography.SHA256]::Create()
 try {return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','')}
 finally {$algorithm.Dispose();$stream.Dispose()}
}
$src=[IO.Path]::GetFullPath($InputPptx)
$base=[IO.Path]::GetFullPath($OutputDir)
$run=Join-Path $base ('run-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $run | Out-Null
$lock=$null;$app=$null;$deck=$null
try {
 $lock=[IO.File]::Open((Join-Path ([IO.Path]::GetTempPath()) 'codex-gorden-powerpoint-render.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
 $hash=Get-DeliveryHash $src
 $snapshot=Join-Path $run 'source-snapshot.pptx'
 Copy-Item -LiteralPath $src -Destination $snapshot
 if((Get-DeliveryHash $snapshot) -ne $hash){throw 'Snapshot changed while copying; retry from a stable candidate'}
 $app=New-Object -ComObject PowerPoint.Application
 Initialize-DeliveryRender $app $snapshot (Join-Path $run ('warmup-'+[Guid]::NewGuid().ToString('N')+'.png')) $Width
 if((Get-DeliveryHash $src) -ne $hash -or (Get-DeliveryHash $snapshot) -ne $hash){throw 'Source or snapshot changed during render warmup'}
 $deck=$app.Presentations.Open($snapshot,$true,$false,$false)
 if($deck.Slides.Count -lt 1){throw 'A presentation needs a first slide'}
 $height=[int]([double]$Width*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth)
 $png=Join-Path $run 'slide-01.png'
 $deck.Slides.Item(1).Export($png,'PNG',$Width,$height)
 $deck.Close();$deck=$null
 if((Get-DeliveryHash $src) -ne $hash){throw 'Source changed during export; preparation cancelled'}
 if((Get-DeliveryHash $snapshot) -ne $hash){throw 'Render snapshot changed; preparation cancelled'}
 & $PythonExe -X utf8 (Join-Path $PSScriptRoot 'pptx_delivery_shell.py') finalize --pptx $src --expected-sha256 $hash --first-slide $png --proof (Join-Path $run 'shell-proof.json')
 $childExit=$LASTEXITCODE
 if($childExit -ne 0){throw "Shell finalization failed (Python exit $childExit); read the error and retry after fixing the input"}
 Write-Output "PREPARED: $src"
 Write-Output "Evidence: $run"
} catch {
 @{status='failed';source=$src;error=$_.Exception.Message;recovery='Fix the reported input/environment issue, then rerun preparation in a fresh run; do not sign off an incomplete file.'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run 'failure.json') -Encoding UTF8
 Write-Error $_
 exit 1
} finally {
 try {if($deck){$deck.Close()}}
 finally {
  try {if($app -and $app.Presentations.Count -eq 0){$app.Quit()}}
  finally {if($lock){$lock.Dispose()}}
 }
}
