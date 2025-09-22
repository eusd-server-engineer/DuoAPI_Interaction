# Duo Student Account Cleanup Guide

## Problem Statement
- Students inadvertently accessed Duo login flow
- Duo's "New user policy" was set to "Require enrollment"
- This allowed unknown users to self-enroll, creating hundreds of student accounts
- Student accounts follow pattern: `xxxxxx@eusd.org` (6 numerical digits)
- Staff accounts use different naming convention

## Root Cause: Inline Self-Enrollment
When an application's **New user policy** is set to **Require enrollment**, any user who reaches the Duo prompt with an unknown username will be walked through inline self-enrollment, automatically creating a Duo user record.

## Prevention Strategies

### 1. Change New User Policy
**Location**: Admin Panel → Applications → [App] → Policy → New user policy

Options:
- **Deny access** (Recommended): Unknown users cannot enroll or authenticate
- **Require enrollment**: Allows self-enrollment (caused the problem)

### 2. Restrict Access by Group
**Location**: Admin Panel → Applications → [App] → User access

Settings:
- Set "Permitted groups" to staff-only groups
- This prevents students from even reaching the Duo flow

### 3. Authentication Policy Override
**Location**: Admin Panel → Applications → [App] → Authentication policy

For temporary bypass during pilots:
- Apply "Bypass 2FA" to specific allowlist group
- This also disables inline self-enrollment for that app
- **WARNING**: Don't apply globally

## Detection Methods

### 1. Check Authentication Logs
- Look for enrollment events
- "portal" in Application column indicates enrollment portal flow

### 2. Identify Student Accounts
```powershell
# Pattern matching for 6-digit usernames
$students = Get-DuoUsers | Where-Object { $_.username -match '^\d{6}$' }
```

## Cleanup Strategies

### For Unmanaged Users
Users created through self-enrollment are typically unmanaged and can be deleted directly via API:

```
DELETE /admin/v1/users/[user_id]
```

### For Directory-Synced Users
If users were created via directory sync, they cannot be deleted directly while managed.

Detection fields:
- `directory_key` - not null
- `external_id` - not null
- `last_directory_sync` - not null

Removal process:
1. Remove students from all AD groups in Duo sync scope
2. Run directory sync
3. Users will be moved to trash per retention policy
4. After retention period, users are permanently deleted

**Nuclear option** (use with caution):
- Delete the directory sync configuration
- This converts all synced objects to unmanaged
- Then delete via API
- **WARNING**: Affects ALL synced users, not just students

## API Implementation Considerations

### Rate Limiting
- API calls limited to ~50 per minute for bulk operations
- Implement delays between operations (800ms recommended)
- Use exponential backoff on 429 errors

### Batch Processing
- Process users in chunks
- Track progress and errors
- Save results for audit trail

### Safety Measures
1. **Always backup first**:
   - Export current user list
   - Save user details before deletion

2. **Implement dry-run mode**:
   - Test pattern matching
   - Verify user selection
   - Preview operations before execution

3. **Logging**:
   - Track all operations
   - Export results to CSV
   - Maintain audit trail

## Sample Workflow
1. Query AD for 6-digit sAMAccountNames
2. Check each user in Duo via API
3. Determine if managed or unmanaged
4. For unmanaged: Delete via API
5. For managed: Add to removal list for directory sync
6. Generate audit report

## Post-Cleanup Verification
1. Verify all student accounts removed
2. Confirm policy changes applied
3. Test authentication flow with test accounts
4. Document changes and lessons learned