# Duo Admin API Documentation Overview

## API Versions
- **Admin API v1** (Legacy): Still supported but limited/deprecated for some endpoints
- **Admin API v2/v3**: Current recommended versions where available
- Recommendation: Use most current endpoints, migrate existing v1 implementations

## Base URL Format
```
https://api-XXXXXXXX.duosecurity.com/admin/v1/[endpoint]
```

## Authentication
### HMAC-SHA1 Signature Method
1. Create canonical request string:
   ```
   Date\nMethod\nHost\nPath\nQuery
   ```
   - Date: RFC 2822 format (e.g., "Tue, 21 Aug 2012 17:29:18 -0000")
   - Method: Uppercase HTTP method (GET, POST, DELETE)
   - Host: Lowercase API hostname
   - Path: API endpoint path
   - Query: URL-encoded parameters, lexicographically sorted

2. Compute HMAC-SHA1 using secret key
3. Use HTTP Basic Auth:
   - Username: Integration Key
   - Password: HMAC signature (hex encoded)

### Required Headers
- `Date`: RFC 2822 formatted date/time
- `Authorization`: Basic auth with integration key and HMAC signature
- `Host`: API hostname

## Rate Limiting
- General recommendation: No more than once per minute for log requests
- Bulk operations: 50 calls per minute
- Response code 429: Too many requests
- Built-in exponential backoff recommended

## User Management Endpoints

### List/Search Users
```
GET /admin/v1/users
Parameters:
- username: Search by specific username
- limit: Number of results to return
- offset: For pagination
```

### Get Single User
```
GET /admin/v1/users/[user_id]
```

### Create User
```
POST /admin/v1/users
Parameters:
- username: Required
- email: Optional
- status: active|bypass|disabled|locked_out
- aliases: Optional array of aliases
```

### Delete User
```
DELETE /admin/v1/users/[user_id]
```
- Permanently removes user immediately
- Requires "Grant resource - Write" API permission

### Bulk Operations
```
POST /admin/v1/bulk
```
- Maximum 50 operations per request
- Rate limited to 50 calls per minute

```
POST /admin/v1/users/bulk_create
```
- Create up to 100 users per request
- Rate limited to 50 calls per minute

## User Object Fields

### Directory Sync Indicators
Users managed by directory sync will have:
- `directory_key`: Identifies the source directory
- `external_id`: External unique identifier
- `last_directory_sync`: Timestamp of last sync

### User Status Values
- `active`: Normal active user
- `bypass`: Bypasses 2FA requirements
- `disabled`: Cannot authenticate
- `locked_out`: Temporarily locked

### Limitations
- Maximum 100 phones/tokens per user
- Directory-synced users have restrictions on direct status changes

## Error Handling
### Response Format
```json
{
  "stat": "OK" | "FAIL",
  "response": {...} | [...]  // For success
  "message": "Error description",  // For failures
  "code": 40001  // Error code
}
```

### Common Error Codes
- 400: Bad request
- 401: Unauthorized
- 403: Forbidden
- 404: Not found
- 429: Rate limited

## Best Practices
1. Always check `stat` field in response
2. Implement exponential backoff for rate limiting
3. Cache results when doing multiple analyses
4. Process large datasets in chunks
5. Test operations on single users before bulk operations
6. Capture state before making changes (backup)