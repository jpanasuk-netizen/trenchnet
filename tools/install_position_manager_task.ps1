$ErrorActionPreference = "Stop"
$repo = "C:\Users\jpana\Documents\HermesTools\trenchnet"
$pyw = Join-Path $repo ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = Join-Path $repo ".venv\Scripts\python.exe" }
$task = "TRENCHNET Position Manager"
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-u -m trenchnet.cli position-manager --interval 15" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -Hidden
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $task
Get-ScheduledTask -TaskName $task | Format-List TaskName, State
Write-Output "INSTALLED $task"
