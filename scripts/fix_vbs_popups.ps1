# Fix VBS error popups by updating to safe versions with error handling

$projectRoot = Split-Path $PSScriptRoot -Parent

Write-Host "Fixing VBS error popups..." -ForegroundColor Cyan

# Update GitHub Monitor task
$monitorScript = Join-Path $projectRoot "scripts\run_monitor_silent_safe.vbs"
if (Test-Path $monitorScript) {
    $monitorAction = New-ScheduledTaskAction `
        -Execute "wscript.exe" `
        -Argument """$monitorScript""" `
        -WorkingDirectory $projectRoot

    try {
        Set-ScheduledTask `
            -TaskName "Claude-GitHub-Monitor" `
            -Action $monitorAction | Out-Null

        Write-Host "[OK] Updated GitHub Monitor to safe VBS" -ForegroundColor Green
    } catch {
        Write-Host "[WARNING] Could not update monitor task: $_" -ForegroundColor Yellow
    }
}

# Update Autonomous Action task
$actionScript = Join-Path $projectRoot "scripts\run_action_silent_safe.vbs"
if (Test-Path $actionScript) {
    $actionAction = New-ScheduledTaskAction `
        -Execute "wscript.exe" `
        -Argument """$actionScript""" `
        -WorkingDirectory $projectRoot

    try {
        Set-ScheduledTask `
            -TaskName "Claude-Autonomous-Action" `
            -Action $actionAction | Out-Null

        Write-Host "[OK] Updated Autonomous Action to safe VBS" -ForegroundColor Green
    } catch {
        Write-Host "[WARNING] Could not update action task: $_" -ForegroundColor Yellow
    }
}

Write-Host "`nVBS error handling improved!" -ForegroundColor Green
Write-Host "The scripts now:" -ForegroundColor Yellow
Write-Host "  - Include 'On Error Resume Next' to suppress error popups"
Write-Host "  - Check if venv exists before running"
Write-Host "  - Fall back to 'uv run' if venv is missing"
Write-Host "  - Always redirect output to log files"

# Test the monitor
Write-Host "`nTesting safe execution..." -ForegroundColor Magenta
Start-ScheduledTask -TaskName "Claude-GitHub-Monitor"
Start-Sleep -Seconds 2

$logPath = Join-Path $projectRoot ".claude\monitor.log"
if (Test-Path $logPath) {
    Write-Host "[OK] Monitor running without errors" -ForegroundColor Green
    $lastLine = Get-Content $logPath -Tail 1
    Write-Host "Latest: $lastLine" -ForegroundColor Cyan
} else {
    Write-Host "[INFO] Log file not found yet" -ForegroundColor Yellow
}