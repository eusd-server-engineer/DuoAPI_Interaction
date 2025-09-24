# Claude Work Trigger

## How This Works

1. **GitHub Monitor** runs every 5 minutes (via scheduled task)
2. It checks for:
   - New issues mentioning @claude
   - PRs with failing CI checks
   - Comments asking for help
3. When found, it writes to `.claude/pending_work.md`
4. You open Claude Code and say: "Check pending work"
5. Claude reads the file and takes action

## Quick Commands

### Check if there's work waiting:
```
Check .claude/pending_work.md
```

### Process all pending work:
```
Work on all items in pending work file
```

### Check specific issue/PR:
```
Work on issue #3
Fix PR #2 failing checks
```

## Automation Levels

### Level 1: Manual Check (Current)
- You manually tell Claude to check

### Level 2: Semi-Automatic (With Monitor)
- Script checks GitHub every 5 minutes
- You see notification/file
- You tell Claude to work

### Level 3: Full Automation (Possible Future)
- GitHub webhook → Azure Function/Lambda
- Calls Claude API directly
- Creates PRs automatically
- Sends you summary email

## Sample Workflow

When the monitor finds work, it creates a report like:

```markdown
# GitHub Monitor Report
**Time**: 2025-09-23 10:30:00
**Repository**: eusd-server-engineer/DuoAPI_Interaction

## Actionable Items Found:

### 🎯 Issue #3: Add email notifications
- **Action**: implement
- **Reason**: Contains Claude mention
- **Command**: `gh issue view 3`

### 🔧 PR #2: Enhanced error handling
- **Action**: fix_checks
- **Reason**: CI checks are failing
- **Command**: `gh pr checks 2`
```

Then you just tell Claude: "Work on the pending items" and Claude will:
1. Read the report
2. Investigate each item
3. Create PRs or fix issues
4. Report back to you