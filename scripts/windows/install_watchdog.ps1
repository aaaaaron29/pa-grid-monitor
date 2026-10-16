<#
.SYNOPSIS
  Registers (or removes) the scheduled task that runs scripts\windows\watchdog.ps1 at logon
  and every 2 minutes after that.

.PARAMETER Uninstall
  Remove the task. The pipeline processes it started keep running.

.PARAMETER IntervalMinutes
  How often a pass runs. Default 2.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install_watchdog.ps1
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [int]$IntervalMinutes = 2
)

$ErrorActionPreference = 'Stop'
$TaskName = 'pa-grid-monitor-watchdog'
$Watchdog = (Resolve-Path (Join-Path $PSScriptRoot 'watchdog.ps1')).Path
$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed $TaskName."
    } else {
        Write-Host "$TaskName is not installed."
    }
    return
}

# conhost --headless runs PowerShell with no console window, so a pass every two minutes does
# not flash a window on screen.
$argLine = '--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $Watchdog
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument $argLine -WorkingDirectory $Repo

$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$repeating = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -Hidden

# Interactive so the Windows notification can appear on your desktop.
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atLogon, $repeating) `
    -Settings $settings -Principal $principal -Force `
    -Description 'Keeps the pa-grid-monitor pipeline running and alerts when data stops arriving.' | Out-Null

Write-Host "Installed ${TaskName}: runs at logon and every $IntervalMinutes minutes."
Write-Host "Check it any time with:  powershell -File `"$Watchdog`" -Status"
Write-Host "Log: $env:USERPROFILE\pjm-logs\watchdog.log"
