#!/usr/bin/env pwsh
# Setup auto-start for Kraken Trader using Windows Task Scheduler

param(
    [switch]$Remove
)

$taskName = "KrakenTraderServer"
$scriptPath = Join-Path $PSScriptRoot "start-server-fixed.ps1"

if ($Remove) {
    Write-Host "Removing scheduled task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Task removed." -ForegroundColor Green
    return
}

Write-Host "Setting up Kraken Trader auto-start..." -ForegroundColor Green

# Create the action
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    -WorkingDirectory $PSScriptRoot

# Create the trigger (at startup with 30 second delay)
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 3

# Create the task
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Register the task
try {
    $task = Register-ScheduledTask -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Starts the Kraken Trader server automatically" `
        -Force
    
    Write-Host "✓ Scheduled task created successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Task Details:" -ForegroundColor Cyan
    Write-Host "  Name: $taskName"
    Write-Host "  Trigger: At system startup (30s delay)"
    Write-Host "  Script: $scriptPath"
    Write-Host ""
    Write-Host "To test now: Start-ScheduledTask -TaskName $taskName" -ForegroundColor Yellow
    Write-Host "To remove: .\setup-autostart.ps1 -Remove" -ForegroundColor Yellow
} catch {
    Write-Host "Error creating scheduled task: $_" -ForegroundColor Red
    Write-Host "You may need to run this script as Administrator" -ForegroundColor Yellow
}