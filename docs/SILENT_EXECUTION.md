# Silent Execution for Windows Scheduled Tasks

## Overview
This document describes the silent execution setup for the GitHub monitoring and autonomous action system on Windows. The system runs scheduled tasks without any visible terminal windows or popups.

## Problem
PowerShell's `-WindowStyle Hidden` parameter still briefly shows a window when launched from Task Scheduler, causing unwanted terminal popups every 5-10 minutes.

## Solution
Use Windows Script Host (wscript.exe) with VBScript wrappers to achieve completely invisible execution.

## Components

### VBScript Wrappers
Located in `scripts/` directory:

1. **run_monitor_silent.vbs**
   - Runs GitHub monitor completely silently
   - Executes: `python scripts/github_monitor.py --once`
   - Logs output to: `.claude/monitor.log`

2. **run_action_silent.vbs**
   - Runs autonomous action processor silently
   - Executes: `python scripts/autonomous_action.py`
   - Logs output to: `.claude/action_log.txt`

### Scheduled Tasks

| Task Name | Frequency | Script | Purpose |
|-----------|-----------|--------|---------|
| Claude-GitHub-Monitor | Every 5 minutes | run_monitor_silent.vbs | Detects @claude mentions |
| Claude-Autonomous-Action | Every 10 minutes | run_action_silent.vbs | Processes pending work |

## Setup Instructions

### Initial Setup
```powershell
# Set up GitHub monitor (runs every 5 minutes)
powershell -ExecutionPolicy Bypass -File "scripts\setup_silent_monitor_final.ps1"

# Set up autonomous actions (runs every 10 minutes)
powershell -ExecutionPolicy Bypass -File "scripts\setup_autonomous_action.ps1"
```

### Update Existing Tasks to Silent Mode
If tasks are already created but showing windows:
```powershell
powershell -ExecutionPolicy Bypass -File "scripts\update_tasks_to_silent.ps1"
```

## How It Works

1. **Task Scheduler** triggers `wscript.exe` with the VBS file
2. **VBScript** uses `WScript.Shell.Run` with window mode `0` (hidden)
3. **Python** executes with all output redirected to log files
4. **No window** appears at any point in the process

### VBScript Window Modes
- `0` = Hidden window (used in our scripts)
- `1` = Normal window
- `2` = Minimized window

## Monitoring and Logs

### Check Task Status
```powershell
Get-ScheduledTask -TaskName "Claude-*" | Select-Object TaskName, State, LastRunTime
```

### View Logs
```powershell
# Monitor log (last 20 lines)
Get-Content .claude\monitor.log -Tail 20

# Action log (last 20 lines)
Get-Content .claude\action_log.txt -Tail 20
```

### Test Silent Execution
```powershell
# Test monitor
Start-ScheduledTask -TaskName "Claude-GitHub-Monitor"

# Test actions
Start-ScheduledTask -TaskName "Claude-Autonomous-Action"
```

## Troubleshooting

### Tasks Still Showing Windows
1. Verify tasks are using wscript.exe:
   ```powershell
   (Get-ScheduledTask -TaskName "Claude-GitHub-Monitor").Actions
   ```
   Should show: `Execute: wscript.exe`

2. Re-run the update script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "scripts\update_tasks_to_silent.ps1"
   ```

### Tasks Not Running
1. Check if Python virtual environment exists:
   ```powershell
   Test-Path .venv\Scripts\python.exe
   ```

2. Verify VBS files exist:
   ```powershell
   Test-Path scripts\run_monitor_silent.vbs
   Test-Path scripts\run_action_silent.vbs
   ```

3. Check logs for errors:
   ```powershell
   Get-Content .claude\monitor.log -Tail 50
   ```

### Manual Testing
Run VBS files directly (should see no window):
```cmd
wscript scripts\run_monitor_silent.vbs
wscript scripts\run_action_silent.vbs
```

## Benefits
- **No interruptions**: Tasks run completely invisibly
- **Continuous monitoring**: GitHub checked every 5 minutes
- **Automatic processing**: Work items handled every 10 minutes
- **Full logging**: All output captured in log files
- **Easy maintenance**: Simple VBScript wrappers

## Related Files
- `scripts/run_monitor_silent.vbs` - Monitor wrapper
- `scripts/run_action_silent.vbs` - Action wrapper
- `scripts/update_tasks_to_silent.ps1` - Updates existing tasks
- `scripts/setup_silent_monitor_final.ps1` - Creates monitor task
- `scripts/setup_autonomous_action.ps1` - Creates action task
- `.claude/monitor.log` - Monitor output log
- `.claude/action_log.txt` - Action processing log