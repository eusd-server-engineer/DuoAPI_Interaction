# Windows Secret Management Tools

## Open Source Command-Line Secret Managers for Windows

### 1. **KeePassXC** (Recommended for Windows)
**Command-line tool**: `keepassxc-cli`
- **Install**: `winget install KeePassXC.KeePassXC` or download from https://keepassxc.org
- **Features**:
  - Full command-line interface
  - Strong encryption (AES-256)
  - Cross-platform (Windows, Mac, Linux)
  - Can integrate with browsers
  - Supports TOTP/2FA codes

**Basic usage**:
```bash
# Create database
keepassxc-cli db-create secrets.kdbx

# Add entry
keepassxc-cli add secrets.kdbx -u DUO_IKEY -p

# Get password
keepassxc-cli show secrets.kdbx DUO_IKEY -a password

# List all entries
keepassxc-cli ls secrets.kdbx
```

### 2. **Bitwarden CLI**
**Command-line tool**: `bw`
- **Install**: `npm install -g @bitwarden/cli` or `winget install Bitwarden.CLI`
- **Features**:
  - Cloud sync (optional self-hosted)
  - Team sharing capabilities
  - Free tier available
  - API access

**Basic usage**:
```bash
# Login
bw login

# Create item
bw get template item | bw create item

# Get secret
bw get item "Duo API" | jq '.login.password'

# Store in env variable
$env:DUO_SKEY = bw get password "Duo API Secret"
```

### 3. **Pass for Windows** (via WSL or Git Bash)
**Command-line tool**: `pass`
- **Install**: Requires WSL or Git Bash, then install pass
- **Features**:
  - Git integration
  - GPG encryption
  - Unix philosophy (simple)

### 4. **GoPass** (Native Windows Support)
**Command-line tool**: `gopass`
- **Install**: `scoop install gopass` or download binary
- **Features**:
  - Compatible with pass
  - Native Windows support
  - Git integration
  - Multi-user support

**Basic usage**:
```bash
# Initialize
gopass init

# Add secret
gopass insert duo/api/ikey

# Get secret
gopass show duo/api/ikey

# Use in script
$env:DUO_IKEY = gopass show -o duo/api/ikey
```

### 5. **Mozilla SOPS** (Secrets OPerationS)
**Command-line tool**: `sops`
- **Install**: Download from GitHub releases or `scoop install sops`
- **Features**:
  - Encrypts files (JSON, YAML, ENV)
  - Integrates with cloud KMS (AWS, Azure, GCP)
  - Version control friendly

**Basic usage**:
```bash
# Encrypt .env file
sops -e .env > .env.encrypted

# Decrypt and load
sops -d .env.encrypted > .env

# Edit encrypted file
sops .env.encrypted
```

### 6. **git-secret**
**Command-line tool**: `git-secret`
- **Install**: Via WSL/Git Bash
- **Features**:
  - Encrypts files in git repos
  - GPG based
  - Team collaboration

## Native Windows Solutions

### 7. **Windows Credential Manager** (Built-in)
**Command-line tool**: `cmdkey`
- **Features**:
  - Built into Windows
  - No installation needed
  - PowerShell integration

**PowerShell usage**:
```powershell
# Store credential
$cred = Get-Credential
$cred | Export-Clixml -Path "$env:USERPROFILE\.duo\creds.xml"

# Retrieve credential
$cred = Import-Clixml -Path "$env:USERPROFILE\.duo\creds.xml"
$ikey = $cred.UserName
$skey = $cred.GetNetworkCredential().Password

# Using Windows Credential Manager directly
cmdkey /add:DuoAPI /user:YOUR_IKEY /pass:YOUR_SKEY
cmdkey /list:DuoAPI
```

### 8. **Azure Key Vault** (Cloud-based)
**Command-line tool**: `az keyvault`
- **Install**: `winget install Microsoft.AzureCLI`
- **Features**:
  - Enterprise-grade
  - Cloud storage
  - Access policies
  - Audit logs

## Recommended Setup for Your Project

### Option 1: Simple - KeePassXC (Local)
```bash
# Install
winget install KeePassXC.KeePassXC

# Create database for API keys
keepassxc-cli db-create ~/duo-secrets.kdbx

# Add your secrets
keepassxc-cli add ~/duo-secrets.kdbx DUO_IKEY -u DI7LH25VCGTWU1XCHNUE
keepassxc-cli add ~/duo-secrets.kdbx DUO_SKEY -p
keepassxc-cli add ~/duo-secrets.kdbx DUO_HOST -u api-8c9f60b5.duosecurity.com

# Create script to load into environment
# load-secrets.ps1:
$env:DUO_IKEY = keepassxc-cli show ~/duo-secrets.kdbx DUO_IKEY -a username -q
$env:DUO_SKEY = keepassxc-cli show ~/duo-secrets.kdbx DUO_SKEY -a password -q
$env:DUO_HOST = keepassxc-cli show ~/duo-secrets.kdbx DUO_HOST -a username -q
```

### Option 2: Team-Friendly - Bitwarden
```bash
# Install
npm install -g @bitwarden/cli

# Login
bw login

# Create items
bw get template item | jq '.name="Duo API" | .login.username="'$DUO_IKEY'" | .login.password="'$DUO_SKEY'"' | bw encode | bw create item

# Script to load secrets
# load-secrets.ps1:
bw unlock --check || bw login
$session = bw unlock --raw
$env:BW_SESSION = $session
$env:DUO_IKEY = bw get username "Duo API"
$env:DUO_SKEY = bw get password "Duo API"
```

### Option 3: Developer-Friendly - SOPS
```bash
# Install
scoop install sops

# Create key (one time)
gpg --gen-key

# Encrypt your .env file
sops -e .env > .env.enc

# Decrypt when needed
sops -d .env.enc > .env

# Or load directly into environment (PowerShell)
sops -d .env.enc | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2])
    }
}
```

## Integration with Your Python Script

Update your script to support multiple secret sources:

```python
import os
from pathlib import Path
import subprocess
import json

def load_secrets():
    """Load secrets from various sources"""

    # 1. Try .env file first
    if Path('.env').exists():
        from dotenv import load_dotenv
        load_dotenv()
        return

    # 2. Try KeePassXC
    try:
        ikey = subprocess.run(
            ['keepassxc-cli', 'show', '~/duo-secrets.kdbx', 'DUO_IKEY', '-a', 'username', '-q'],
            capture_output=True, text=True
        ).stdout.strip()
        if ikey:
            os.environ['DUO_IKEY'] = ikey
            # ... repeat for other secrets
            return
    except:
        pass

    # 3. Try Bitwarden
    try:
        result = subprocess.run(
            ['bw', 'get', 'item', 'Duo API'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            os.environ['DUO_IKEY'] = data['login']['username']
            os.environ['DUO_SKEY'] = data['login']['password']
            return
    except:
        pass

    # 4. Fall back to encrypted .env
    if Path('.env.enc').exists():
        subprocess.run(['sops', '-d', '.env.enc'],
                      stdout=open('.env', 'w'))
        from dotenv import load_dotenv
        load_dotenv()
```

## Security Best Practices

1. **Never commit secrets** to version control
2. **Use different secrets** for dev/test/prod
3. **Rotate secrets regularly** (every 90 days)
4. **Limit secret access** to those who need it
5. **Audit secret usage** when possible
6. **Use encryption at rest** for secret storage
7. **Implement secret scanning** in CI/CD

## Quick Recommendation

For your use case, I recommend:
- **Individual use**: KeePassXC (simple, secure, offline)
- **Team use**: Bitwarden (cloud sync, sharing)
- **CI/CD integration**: SOPS or Azure Key Vault