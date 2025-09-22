#!/usr/bin/env python3
"""
Duo Student Account Cleanup Script
Identifies and removes student accounts that were inadvertently created in Duo
through self-enrollment when ADFS was misconfigured.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

import requests
from dateutil.tz import tzutc
from dotenv import load_dotenv


class DuoAdminAPI:
    """Client for Duo Admin API v1 operations"""

    def __init__(self, integration_key: str, secret_key: str, api_host: str):
        self.ikey = integration_key
        self.skey = secret_key
        self.host = api_host
        self.base_url = f"https://{api_host}"

    def _sign_request(self, method: str, path: str, params: Dict = None) -> Tuple[str, Dict]:
        """Generate HMAC-SHA1 signature for Duo API request"""
        # Format date
        date = datetime.now(tzutc()).strftime('%a, %d %b %Y %H:%M:%S %z')

        # Build canonical request
        canon = [
            date,
            method.upper(),
            self.host.lower(),
            path,
        ]

        # Add sorted parameters for non-GET/DELETE methods
        if params and method.upper() in ['GET', 'DELETE']:
            sorted_params = sorted(params.items())
            canon.append(urlencode(sorted_params))
        else:
            canon.append('')

        canon_string = '\n'.join(canon)

        # Calculate HMAC signature
        signature = hmac.new(
            self.skey.encode('utf-8'),
            canon_string.encode('utf-8'),
            hashlib.sha1
        ).hexdigest()

        # Build authorization header
        auth = base64.b64encode(f"{self.ikey}:{signature}".encode()).decode()

        headers = {
            'Date': date,
            'Authorization': f'Basic {auth}',
            'Host': self.host,
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        return date, headers

    def _request(self, method: str, endpoint: str, params: Dict = None) -> Dict:
        """Make authenticated request to Duo API"""
        path = f"/admin/v1{endpoint}"
        date, headers = self._sign_request(method, path, params)

        url = f"{self.base_url}{path}"

        try:
            if method.upper() in ['GET', 'DELETE']:
                if params:
                    url += '?' + urlencode(sorted(params.items()))
                response = requests.request(method, url, headers=headers)
            else:
                response = requests.request(method, url, headers=headers, data=params)

            response.raise_for_status()
            result = response.json()

            if result['stat'] != 'OK':
                raise Exception(f"API error: {result.get('message', 'Unknown error')}")

            return result.get('response', {})

        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {e}")

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        """Find user by username"""
        users = self._request('GET', '/users', {'username': username})
        return users[0] if users else None

    def delete_user(self, user_id: str) -> bool:
        """Delete a user by ID"""
        try:
            self._request('DELETE', f'/users/{user_id}')
            return True
        except Exception as e:
            print(f"Failed to delete user {user_id}: {e}")
            return False

    def list_users(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """List users with pagination"""
        return self._request('GET', '/users', {'limit': limit, 'offset': offset})


def is_student_account(username: str) -> bool:
    """Check if username matches student pattern (6 digits)"""
    # Remove domain if present
    username = username.split('@')[0]
    return bool(re.match(r'^\d{6}$', username))


def is_directory_managed(user: Dict) -> bool:
    """Check if user is managed by directory sync"""
    return any([
        user.get('directory_key'),
        user.get('external_id'),
        user.get('last_directory_sync')
    ])


def main():
    # Load environment variables
    load_dotenv()

    parser = argparse.ArgumentParser(description='Clean up Duo student accounts')
    parser.add_argument('--ikey', default=os.getenv('DUO_IKEY'), help='Duo Integration Key (or set DUO_IKEY env var)')
    parser.add_argument('--skey', default=os.getenv('DUO_SKEY'), help='Duo Secret Key (or set DUO_SKEY env var)')
    parser.add_argument('--host', default=os.getenv('DUO_HOST'), help='Duo API Host (or set DUO_HOST env var)')
    parser.add_argument('--dry-run', action='store_true', help='Preview actions without making changes')
    parser.add_argument('--rate-limit-ms', type=int, default=800, help='Milliseconds between API calls')
    parser.add_argument('--log-dir', default='logs', help='Directory for log files')
    parser.add_argument('--backup-dir', default='backups', help='Directory for backup files')
    parser.add_argument('--username-file', help='File containing list of usernames to check')
    parser.add_argument('--interactive', action='store_true', help='Confirm each deletion')

    args = parser.parse_args()

    # Validate credentials
    if not all([args.ikey, args.skey, args.host]):
        print("Error: Missing required credentials!")
        print("Provide via command line arguments or set in .env file:")
        print("  DUO_IKEY=your_integration_key")
        print("  DUO_SKEY=your_secret_key")
        print("  DUO_HOST=api-XXXXXXXX.duosecurity.com")
        return 1

    # Setup logging directories
    log_dir = Path(args.log_dir)
    backup_dir = Path(args.backup_dir)
    log_dir.mkdir(exist_ok=True)
    backup_dir.mkdir(exist_ok=True)

    # Initialize API client
    api = DuoAdminAPI(args.ikey, args.skey, args.host)

    # Create log files
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f"duo_cleanup_{timestamp}.log"
    backup_file = backup_dir / f"duo_users_backup_{timestamp}.json"
    results_file = log_dir / f"duo_cleanup_results_{timestamp}.csv"

    results = []

    # Get list of usernames to check
    usernames_to_check = []

    if args.username_file:
        # Read usernames from file
        with open(args.username_file) as f:
            usernames_to_check = [line.strip() for line in f if line.strip()]
        print(f"Loaded {len(usernames_to_check)} usernames from file")
    else:
        # Search for all users and filter by pattern
        print("Fetching all Duo users...")
        offset = 0
        all_users = []

        while True:
            batch = api.list_users(limit=100, offset=offset)
            if not batch:
                break
            all_users.extend(batch)
            offset += len(batch)
            print(f"  Fetched {len(all_users)} users...")
            time.sleep(args.rate_limit_ms / 1000)

        # Backup all users
        with open(backup_file, 'w') as f:
            json.dump(all_users, f, indent=2)
        print(f"Backed up {len(all_users)} users to {backup_file}")

        # Filter for student accounts
        for user in all_users:
            if is_student_account(user.get('username', '')):
                usernames_to_check.append(user['username'])

        print(f"Found {len(usernames_to_check)} student accounts")

    # Process each student account
    with open(log_file, 'w') as log:
        log.write(f"Duo Student Cleanup - {timestamp}\n")
        log.write(f"Dry Run: {args.dry_run}\n")
        log.write(f"Total accounts to check: {len(usernames_to_check)}\n\n")

        for username in usernames_to_check:
            print(f"\nProcessing: {username}")
            log.write(f"\n{datetime.now()}: Processing {username}\n")

            # Get user details
            user = api.get_user_by_username(username)

            if not user:
                result = {
                    'username': username,
                    'in_duo': False,
                    'managed_by_sync': None,
                    'action': 'None',
                    'result': 'Not found in Duo'
                }
                print(f"  -> Not found in Duo")
                log.write(f"  Not found in Duo\n")
            elif is_directory_managed(user):
                result = {
                    'username': username,
                    'in_duo': True,
                    'managed_by_sync': True,
                    'action': 'Skip',
                    'result': 'Managed by directory sync - remove from sync scope'
                }
                print(f"  -> Directory managed - skipping (remove from sync scope)")
                log.write(f"  Directory managed - skipping\n")
            else:
                # User is unmanaged and can be deleted
                if args.interactive:
                    response = input(f"  Delete user {username}? [y/N]: ")
                    if response.lower() != 'y':
                        result = {
                            'username': username,
                            'in_duo': True,
                            'managed_by_sync': False,
                            'action': 'Skip',
                            'result': 'User skipped deletion'
                        }
                        print(f"  -> Skipped")
                        log.write(f"  Skipped by user\n")
                        results.append(result)
                        continue

                if args.dry_run:
                    result = {
                        'username': username,
                        'in_duo': True,
                        'managed_by_sync': False,
                        'action': 'Would DELETE',
                        'result': 'Dry run - no action taken'
                    }
                    print(f"  -> Would delete (dry run)")
                    log.write(f"  Would delete (dry run)\n")
                else:
                    # Perform deletion
                    if api.delete_user(user['user_id']):
                        result = {
                            'username': username,
                            'in_duo': True,
                            'managed_by_sync': False,
                            'action': 'DELETED',
                            'result': 'Successfully deleted'
                        }
                        print(f"  -> DELETED")
                        log.write(f"  DELETED\n")
                    else:
                        result = {
                            'username': username,
                            'in_duo': True,
                            'managed_by_sync': False,
                            'action': 'ERROR',
                            'result': 'Deletion failed'
                        }
                        print(f"  -> ERROR during deletion")
                        log.write(f"  ERROR during deletion\n")

            results.append(result)

            # Rate limiting
            time.sleep(args.rate_limit_ms / 1000)

    # Write results CSV
    with open(results_file, 'w') as f:
        f.write("Username,In_Duo,Managed_By_Sync,Action,Result\n")
        for r in results:
            f.write(f"{r['username']},{r['in_duo']},{r['managed_by_sync']},{r['action']},{r['result']}\n")

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Total processed: {len(results)}")
    print(f"Not in Duo: {sum(1 for r in results if not r['in_duo'])}")
    print(f"Directory managed: {sum(1 for r in results if r.get('managed_by_sync'))}")
    print(f"Deleted: {sum(1 for r in results if r['action'] == 'DELETED')}")
    print(f"Would delete (dry run): {sum(1 for r in results if r['action'] == 'Would DELETE')}")
    print(f"Errors: {sum(1 for r in results if r['action'] == 'ERROR')}")
    print(f"\nLogs written to: {log_file}")
    print(f"Results CSV: {results_file}")
    if backup_file.exists():
        print(f"Backup file: {backup_file}")


if __name__ == '__main__':
    main()