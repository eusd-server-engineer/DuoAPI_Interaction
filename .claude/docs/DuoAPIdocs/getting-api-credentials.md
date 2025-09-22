# Getting Duo API Credentials

## Prerequisites
- You must be a Duo administrator with **Owner** role
- Only Owner role admins can create or view Admin API applications

## Steps to Get API Credentials

### 1. Log into Duo Admin Panel
- Go to: https://admin.duosecurity.com
- Sign in with your admin credentials

### 2. Navigate to Applications
- In the left sidebar, click **Applications**
- Click **Protect an Application**

### 3. Search for Admin API
- In the search box, type "Admin API"
- Find **Admin API** in the results
- Click **Protect** next to Admin API

### 4. Get Your Credentials
Once you protect the Admin API application, you'll see:

- **Integration key (ikey)**: A 20-character string like `DIXXXXXXXXXXXXXXXXXX`
- **Secret key (skey)**: A 40-character string (keep this SECRET!)
- **API hostname**: Format: `api-XXXXXXXX.duosecurity.com`

### 5. Save Credentials Securely
Copy these three values and store them securely. You'll need all three to authenticate.

⚠️ **IMPORTANT SECURITY NOTES**:
- The secret key is shown only once when first created
- Treat the secret key like a password - never share or commit it
- If compromised, regenerate keys immediately

## Permission Settings

### Required Permissions
For the student cleanup script, ensure your Admin API application has:
- **Grant resource** - Read (to list/search users)
- **Grant resource** - Write (to delete users)

### To Check/Modify Permissions:
1. Go to **Applications** → **Admin API**
2. Click on your Admin API application
3. Under **Admin API Permissions**, verify:
   - ✅ Grant users - Read
   - ✅ Grant users - Write

## Finding Existing Admin API Application
If an Admin API was already created:

1. Go to **Applications** in Duo Admin Panel
2. Look for applications named "Admin API" or similar
3. Click on the application name
4. You'll see the Integration key and API hostname
5. The Secret key is NOT visible after creation (you may need to reset it)

### If You Need to Reset Keys:
1. Click on your Admin API application
2. Click **Reset Secret Key**
3. Confirm the reset
4. Copy the new secret key immediately (shown only once)

## Troubleshooting

### "No Admin API application found"
- You need Owner role to see/create Admin API apps
- Ask another Owner admin to create one for you

### "Permission denied" errors
- Verify your API application has Write permissions
- Check under Admin API Permissions section

### Can't find API hostname
- It's shown in the Admin API application details
- Format: `api-[8 chars].duosecurity.com`
- Same hostname for all API apps in your account

## Example Credentials (Format Only)
```
Integration Key: DIXXXXXXXXXXXXXXXXXX    (20 characters)
Secret Key: YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY    (40 characters)
API Host: api-12ab34cd.duosecurity.com
```

## Quick Test
After getting credentials, test them:
```bash
# Test with dry-run (won't delete anything)
uv run python scripts/duo_student_cleanup.py \
  --ikey DIXXXXXXXXXXXXXXXXXX \
  --skey YYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY \
  --host api-12ab34cd.duosecurity.com \
  --dry-run
```

If authentication works, you'll see users being fetched. If not, you'll get an authentication error.