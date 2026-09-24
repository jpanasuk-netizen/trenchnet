$ErrorActionPreference = 'SilentlyContinue'
$edge = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if (-not (Test-Path $edge)) { $edge = 'C:\Program Files\Microsoft\Edge\Application\msedge.exe' }
Set-Location 'C:\Users\jpana\Documents\HermesTools\trenchnet'
$base = 'http://127.0.0.1:8788/'
$shots = @(
  @{ w = 3440; h = 1440; out = 'out\dashboard_3440.png' },
  @{ w = 1920; h = 1080; out = 'out\dashboard_1920.png' },
  @{ w = 1280; h = 800;  out = 'out\dashboard_1280.png' }
)
foreach ($s in $shots) {
  & $edge --headless=new --disable-gpu --hide-scrollbars "--window-size=$($s.w),$($s.h)" "--screenshot=$PWD\$($s.out)" $base | Out-Null
  Start-Sleep -Seconds 2
}
Get-ChildItem out\dashboard_*.png | Select-Object Name, Length
