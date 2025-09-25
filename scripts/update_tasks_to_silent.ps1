# Update scheduled tasks to use VBScript for completely silent execution

$projectRoot = Split-Path $PSScriptRoot -Parent

Write-Host "Updating scheduled tasks for silent execution..." -ForegroundColor Cyan

# Update GitHub Monitor task
$monitorScript = Join-Path $projectRoot "scripts\run_monitor_silent.vbs"
$monitorAction = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument """$monitorScript""" `
    -WorkingDirectory $projectRoot

# Get existing trigger and settings
$monitorTask = Get-ScheduledTask -TaskName "Claude-GitHub-Monitor" -ErrorAction SilentlyContinue
if ($monitorTask) {
    Set-ScheduledTask `
        -TaskName "Claude-GitHub-Monitor" `
        -Action $monitorAction | Out-Null

    Write-Host "[OK] Updated GitHub Monitor to use VBScript" -ForegroundColor Green
}

# Update Autonomous Action task
$actionScript = Join-Path $projectRoot "scripts\run_action_silent.vbs"
$actionAction = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument """$actionScript""" `
    -WorkingDirectory $projectRoot

$actionTask = Get-ScheduledTask -TaskName "Claude-Autonomous-Action" -ErrorAction SilentlyContinue
if ($actionTask) {
    Set-ScheduledTask `
        -TaskName "Claude-Autonomous-Action" `
        -Action $actionAction | Out-Null

    Write-Host "[OK] Updated Autonomous Action to use VBScript" -ForegroundColor Green
}

Write-Host "`nTasks updated successfully!" -ForegroundColor Green
Write-Host "The tasks will now run completely silently with no window popups." -ForegroundColor Yellow

# Test the monitor silently
Write-Host "`nTesting silent execution..." -ForegroundColor Magenta
Start-ScheduledTask -TaskName "Claude-GitHub-Monitor"
Start-Sleep -Seconds 2

# Check if it ran
$logPath = Join-Path $projectRoot ".claude\monitor.log"
if (Test-Path $logPath) {
    Write-Host "[OK] Silent execution confirmed - no window appeared" -ForegroundColor Green
    $lastLine = Get-Content $logPath -Tail 1
    Write-Host "Latest log: $lastLine" -ForegroundColor Cyan
} else {
    Write-Host "[WARNING] Could not verify execution - check logs manually" -ForegroundColor Yellow
}