# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
This project interfaces with the Duo Security Admin API to manage user accounts, specifically to identify and remove incorrectly created student accounts that were generated through inadvertent self-enrollment.

## Duo API Documentation Reference
Detailed API documentation is stored in `.claude/docs/DuoAPIdocs/`:
- `api-overview.md` - Complete API reference including authentication, endpoints, and rate limiting
- `student-cleanup-guide.md` - Specific guidance for the student account cleanup scenario

## Key Project Context
- **Problem**: Students (with 6-digit numeric usernames like `123456@eusd.org`) inadvertently created Duo accounts via self-enrollment
- **Goal**: Identify and delete these student accounts while preserving staff accounts
- **Pattern**: Student accounts follow pattern `^\d{6}@eusd.org$`, staff accounts use different naming

## Development Setup

### Python Environment (REQUIRED - Use uv)
```bash
# Initialize project
uv init

# Add required dependencies
uv add requests python-dateutil

# Run scripts
uv run python script_name.py

# Add new packages
uv add package_name
```

### PowerShell Environment
For Windows PowerShell scripts dealing with Active Directory and Duo API:
- Requires AD module: `Import-Module ActiveDirectory`
- Web requests use `Invoke-RestMethod`
- HMAC signing uses `System.Security.Cryptography.HMACSHA1`

## API Authentication Requirements
1. **Integration Key** (ikey) - Username for basic auth
2. **Secret Key** (skey) - Used to generate HMAC signature
3. **API Host** - Format: `api-XXXXXXXX.duosecurity.com`

### HMAC Signature Generation
```
Canonical string: Date\nMethod\nHost\nPath\nQuery
Signature: HMAC-SHA1(canonical_string, secret_key)
Auth header: Basic base64(ikey:signature)
```

## Critical Safety Measures
1. **Always implement dry-run mode first**
2. **Backup user data before deletion operations**
3. **Rate limit API calls** (800ms between calls recommended)
4. **Process in small batches** (50 operations max per bulk request)
5. **Log all operations for audit trail**

## API Endpoints Used

### User Operations
- `GET /admin/v1/users` - List/search users
- `GET /admin/v1/users?username=xxxxx` - Find specific user
- `DELETE /admin/v1/users/[user_id]` - Delete unmanaged user
- `POST /admin/v1/bulk` - Bulk operations (max 50)

### Directory Sync Detection
Check these fields to determine if user is sync-managed:
- `directory_key` - Not null if synced
- `external_id` - Not null if synced
- `last_directory_sync` - Not null if synced

**Important**: Sync-managed users cannot be deleted directly via API; must be removed from sync scope first.

## Common Development Tasks

### Find Student Accounts
```python
# Pattern for student accounts
import re
student_pattern = re.compile(r'^\d{6}$')
# Check: student_pattern.match(username_without_domain)
```

### Rate Limiting Strategy
- Implement exponential backoff on 429 responses
- Default delay: 800ms between API calls
- Batch operations: Max 50 per minute

### Error Handling
- Check response `stat` field: "OK" or "FAIL"
- Log error `code` and `message` fields
- Implement retry logic for transient failures

## Testing Approach
1. Test pattern matching locally first
2. Test API authentication with single user lookup
3. Test deletion on single test account
4. Implement dry-run for bulk operations
5. Process small batch before full cleanup

## Project Structure
```
DuoAPI_Interaction/
├── .claude/
│   ├── docs/
│   │   └── DuoAPIdocs/
│   │       ├── api-overview.md
│   │       └── student-cleanup-guide.md
│   └── settings.local.json
├── scripts/          # Python/PowerShell scripts
├── logs/            # Operation logs and audit trails
└── backups/         # User data backups before operations
```