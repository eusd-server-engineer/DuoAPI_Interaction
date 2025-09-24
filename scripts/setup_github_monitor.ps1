# PowerShell script to set up GitHub monitoring as Windows Scheduled Task
# Run as Administrator for system-wide task, or regular user for user task

$scriptPath = Join-Path $PSScriptRoot "github_monitor.py"
$pythonPath = "python"  # Or full path to python.exe
$workingDir = Split-Path $PSScriptRoot -Parent

# Task settings
$taskName = "Claude-GitHub-Monitor"
$description = "Monitor GitHub for issues and PRs that need Claude's attention"

# Create the action (what to run)
$action = New-ScheduledTaskAction `
    -Execute $pythonPath `
    -Argument "$scriptPath --once" `
    -WorkingDirectory $workingDir

# Create triggers (when to run)
# Option 1: Every 5 minutes
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 365)

# Option 2: At startup and every 5 minutes
# $trigger = @(
#     New-ScheduledTaskTrigger -AtStartup
#     New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
# )

# Task settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -DontStopOnIdleEnd

# Register the task
try {
    # Check if task exists
    $existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    if ($existingTask) {
        Write-Host "Task '$taskName' already exists. Updating..." -ForegroundColor Yellow
        Set-ScheduledTask `
            -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings
    } else {
        Write-Host "Creating new task '$taskName'..." -ForegroundColor Green
        # Register as current user (no admin needed)
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

        Register-ScheduledTask `
            -TaskName $taskName `
            -Description $description `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal
    }

    Write-Host "`n✅ GitHub Monitor scheduled task created successfully!" -ForegroundColor Green
    Write-Host "`nTask will check GitHub every 5 minutes for:"
    Write-Host "  - New issues mentioning @claude"
    Write-Host "  - PRs with failing checks"
    Write-Host "  - Comments requesting Claude's help"
    Write-Host "`nCheck results will be saved to: .claude/pending_work.md"
    Write-Host "`nTo manage the task:"
    Write-Host "  View:    Get-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
    Write-Host "  Disable: Disable-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
    Write-Host "  Enable:  Enable-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
    Write-Host "  Remove:  Unregister-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan
    Write-Host "  Run now: Start-ScheduledTask -TaskName '$taskName'" -ForegroundColor Cyan

} catch {
    Write-Host "❌ Error creating task: $_" -ForegroundColor Red
    Write-Host "`nYou may need to run PowerShell as Administrator" -ForegroundColor Yellow
}