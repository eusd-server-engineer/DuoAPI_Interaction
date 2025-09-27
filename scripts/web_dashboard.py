#!/usr/bin/env python3
"""
Duo Student Cleanup Web Dashboard
A web interface for monitoring and triggering Duo cleanup operations.
"""

import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from pathlib import Path
from threading import Thread, Lock
from typing import Dict, List, Optional
from urllib.parse import quote, urlencode

import requests
from dateutil.tz import tzutc
from flask import Flask, request, render_template_string, jsonify, send_file, redirect, url_for, flash, session
from flask_httpauth import HTTPBasicAuth
from waitress import serve
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Generate a secure secret key if not provided
import secrets
app.secret_key = os.environ.get('FLASK_SECRET_KEY', secrets.token_hex(32))
auth = HTTPBasicAuth()

# Global variables for operation tracking
current_operation = None
operation_lock = Lock()

# Database setup
DB_PATH = Path('dashboard.db')

class DuoAdminAPI:
    """Client for Duo Admin API v1 operations"""

    def __init__(self, integration_key: str, secret_key: str, api_host: str):
        self.ikey = integration_key
        self.skey = secret_key
        self.host = api_host
        self.base_url = f"https://{api_host}"

    def _sign_request(self, method: str, path: str, params: Dict = None) -> tuple:
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

        # Add sorted parameters for GET/DELETE methods
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
                response = requests.request(method, url, headers=headers, timeout=30)
            else:
                response = requests.request(method, url, headers=headers, data=params, timeout=30)

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

    def update_user_status(self, user_id: str, status: str) -> bool:
        """Update user status (Active, Bypass, Disabled, Locked Out)"""
        try:
            self._request('POST', f'/users/{user_id}', {'status': status})
            return True
        except Exception as e:
            print(f"Failed to update user {user_id} status to {status}: {e}")
            return False

def init_db():
    """Initialize SQLite database for operation history"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            dry_run BOOLEAN NOT NULL,
            status TEXT NOT NULL,
            total_processed INTEGER DEFAULT 0,
            deleted_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            log_file TEXT,
            results_file TEXT,
            backup_file TEXT,
            duration INTEGER DEFAULT 0,
            user_triggered TEXT
        )
    ''')

    # Add table for bypass management audit log
    conn.execute('''
        CREATE TABLE IF NOT EXISTS bypass_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            username TEXT NOT NULL,
            user_id TEXT,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            success BOOLEAN NOT NULL,
            error_message TEXT,
            triggered_by TEXT NOT NULL,
            ip_address TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Authentication setup
users = {
    os.environ.get('DASHBOARD_USER', 'admin'): generate_password_hash(os.environ.get('DASHBOARD_PASSWORD', 'admin123'))
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username
    return None

class OperationStatus:
    """Track the status of cleanup operations"""
    def __init__(self):
        self.is_running = False
        self.start_time = None
        self.operation_type = None
        self.dry_run = False
        self.progress = {}
        self.logs = []
        self.error = None

    def start(self, operation_type: str, dry_run: bool = False):
        self.is_running = True
        self.start_time = datetime.now()
        self.operation_type = operation_type
        self.dry_run = dry_run
        self.progress = {'total': 0, 'processed': 0, 'deleted': 0, 'errors': 0}
        self.logs = []
        self.error = None

    def update_progress(self, **kwargs):
        self.progress.update(kwargs)

    def add_log(self, message: str):
        self.logs.append(f"{datetime.now().strftime('%H:%M:%S')}: {message}")

    def finish(self, error: str = None):
        self.is_running = False
        self.error = error

def run_cleanup_operation(dry_run: bool = False, username_file: str = None, user_triggered: str = "system"):
    """Run the duo cleanup script in a separate thread"""
    global current_operation

    with operation_lock:
        if current_operation and current_operation.is_running:
            return False, "Operation already in progress"

        current_operation = OperationStatus()
        current_operation.start("duo_cleanup", dry_run)

    def _run():
        try:
            # Build command
            cmd = [sys.executable, "scripts/duo_student_cleanup.py"]
            if dry_run:
                cmd.append("--dry-run")
            if username_file:
                cmd.append(f"--username-file={username_file}")

            current_operation.add_log(f"Starting cleanup operation (dry_run={dry_run})")

            # Run the cleanup script
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                universal_newlines=True
            )

            # Monitor output
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    current_operation.add_log(output.strip())
                    # Parse progress from output
                    if "Processing:" in output:
                        current_operation.progress['processed'] += 1
                    elif "DELETED" in output:
                        current_operation.progress['deleted'] += 1
                    elif "ERROR" in output:
                        current_operation.progress['errors'] += 1

            # Get final result
            return_code = process.poll()
            stderr = process.stderr.read()

            if return_code == 0:
                current_operation.add_log("Operation completed successfully")

                # Save to database
                save_operation_to_db(
                    operation_type="duo_cleanup",
                    dry_run=dry_run,
                    status="completed",
                    total_processed=current_operation.progress.get('processed', 0),
                    deleted_count=current_operation.progress.get('deleted', 0),
                    error_count=current_operation.progress.get('errors', 0),
                    duration=int((datetime.now() - current_operation.start_time).total_seconds()),
                    user_triggered=user_triggered
                )

                current_operation.finish()
            else:
                error_msg = f"Operation failed with return code {return_code}: {stderr}"
                current_operation.add_log(error_msg)
                current_operation.finish(error_msg)

                save_operation_to_db(
                    operation_type="duo_cleanup",
                    dry_run=dry_run,
                    status="failed",
                    error_count=1,
                    duration=int((datetime.now() - current_operation.start_time).total_seconds()),
                    user_triggered=user_triggered
                )

        except Exception as e:
            error_msg = f"Exception occurred: {str(e)}"
            current_operation.add_log(error_msg)
            current_operation.finish(error_msg)

            save_operation_to_db(
                operation_type="duo_cleanup",
                dry_run=dry_run,
                status="error",
                error_count=1,
                duration=int((datetime.now() - current_operation.start_time).total_seconds()) if current_operation.start_time else 0,
                user_triggered=user_triggered
            )

    thread = Thread(target=_run)
    thread.daemon = True
    thread.start()
    return True, "Operation started"

def save_operation_to_db(**kwargs):
    """Save operation results to database"""
    conn = sqlite3.connect(DB_PATH)
    # Use parameterized query to prevent SQL injection
    allowed_columns = ['operation_type', 'dry_run', 'status', 'total_processed',
                      'deleted_count', 'error_count', 'log_file', 'results_file',
                      'backup_file', 'duration', 'user_triggered']

    # Filter kwargs to only allowed columns
    safe_data = {k: v for k, v in kwargs.items() if k in allowed_columns}

    if safe_data:
        columns = ', '.join(safe_data.keys())
        placeholders = ', '.join('?' * len(safe_data))
        query = f'INSERT INTO operations (timestamp, {columns}) VALUES (?, {placeholders})'
        conn.execute(query, [datetime.now().isoformat()] + list(safe_data.values()))
    else:
        # Just save timestamp if no valid columns
        conn.execute('INSERT INTO operations (timestamp, status) VALUES (?, ?)',
                    [datetime.now().isoformat(), 'unknown'])

    conn.commit()
    conn.close()

def get_operation_history(limit: int = 50) -> List[Dict]:
    """Get operation history from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute('''
        SELECT * FROM operations
        ORDER BY timestamp DESC
        LIMIT ?
    ''', (limit,))

    columns = [description[0] for description in cursor.description]
    operations = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()
    return operations

def log_bypass_audit(username: str, user_id: str, action: str, old_status: str = None,
                     new_status: str = None, success: bool = True, error_message: str = None,
                     triggered_by: str = None, ip_address: str = None):
    """Log bypass management actions for audit trail"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        INSERT INTO bypass_audit (
            timestamp, username, user_id, action, old_status, new_status,
            success, error_message, triggered_by, ip_address
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().isoformat(),
        username,
        user_id,
        action,
        old_status,
        new_status,
        success,
        error_message,
        triggered_by,
        ip_address
    ))
    conn.commit()
    conn.close()

def get_duo_api_client():
    """Create and return Duo API client with credentials from environment"""
    ikey = os.environ.get('DUO_IKEY')
    skey = os.environ.get('DUO_SKEY')
    host = os.environ.get('DUO_HOST')

    if not all([ikey, skey, host]):
        raise ValueError("Missing Duo API credentials. Check DUO_IKEY, DUO_SKEY, and DUO_HOST environment variables.")

    return DuoAdminAPI(ikey, skey, host)

def get_status_badge_class(status: str) -> str:
    """Get Bootstrap badge class for user status"""
    status_lower = status.lower()
    if status_lower == 'active':
        return 'success'
    elif status_lower == 'bypass':
        return 'warning'
    elif status_lower == 'disabled':
        return 'danger'
    elif status_lower == 'locked out':
        return 'info'
    else:
        return 'secondary'

def get_stats() -> Dict:
    """Get dashboard statistics"""
    conn = sqlite3.connect(DB_PATH)

    # Total operations
    total_ops = conn.execute('SELECT COUNT(*) FROM operations').fetchone()[0]

    # Recent operations (last 30 days)
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
    recent_ops = conn.execute(
        'SELECT COUNT(*) FROM operations WHERE timestamp > ?',
        (thirty_days_ago,)
    ).fetchone()[0]

    # Total deletions
    total_deleted = conn.execute(
        'SELECT SUM(deleted_count) FROM operations WHERE status = "completed"'
    ).fetchone()[0] or 0

    # Success rate
    successful_ops = conn.execute(
        'SELECT COUNT(*) FROM operations WHERE status = "completed"'
    ).fetchone()[0]
    success_rate = (successful_ops / total_ops * 100) if total_ops > 0 else 0

    # Bypass management stats
    total_bypass_actions = conn.execute('SELECT COUNT(*) FROM bypass_audit').fetchone()[0]
    recent_bypass_actions = conn.execute(
        'SELECT COUNT(*) FROM bypass_audit WHERE timestamp > ?',
        (thirty_days_ago,)
    ).fetchone()[0]

    conn.close()

    return {
        'total_operations': total_ops,
        'recent_operations': recent_ops,
        'total_deleted': total_deleted,
        'success_rate': round(success_rate, 1),
        'total_bypass_actions': total_bypass_actions,
        'recent_bypass_actions': recent_bypass_actions
    }

# HTML Template
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Duo Cleanup Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        :root {
            --primary-color: #0066cc;
            --primary-dark: #004c99;
            --secondary-color: #00a8cc;
            --success-color: #00a878;
            --warning-color: #f39c12;
            --danger-color: #e74c3c;
            --light-bg: #f4f7fa;
            --card-shadow: 0 2px 8px rgba(0, 102, 204, 0.1);
        }

        body {
            background-color: var(--light-bg);
        }

        .navbar {
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-dark) 100%) !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }

        .card {
            border: none;
            box-shadow: var(--card-shadow);
            transition: transform 0.2s, box-shadow 0.2s;
        }

        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 102, 204, 0.15);
        }

        .card-header {
            background-color: var(--primary-color);
            color: white;
            font-weight: 600;
            border-bottom: none;
        }

        .btn-primary {
            background-color: var(--primary-color);
            border-color: var(--primary-color);
        }

        .btn-primary:hover {
            background-color: var(--primary-dark);
            border-color: var(--primary-dark);
        }

        .status-running {
            color: var(--warning-color);
            font-weight: 600;
        }

        .status-completed {
            color: var(--success-color);
            font-weight: 600;
        }

        .status-failed, .status-error {
            color: var(--danger-color);
            font-weight: 600;
        }

        .log-container {
            background-color: #ffffff;
            border: 1px solid #e0e6ed;
            border-radius: 0.5rem;
            padding: 1rem;
            font-family: 'Courier New', monospace;
            font-size: 0.9rem;
            white-space: pre-wrap;
            max-height: 300px;
            overflow-y: auto;
            box-shadow: inset 0 1px 3px rgba(0,0,0,0.05);
        }

        .card-stats {
            background: linear-gradient(135deg, var(--secondary-color) 0%, var(--primary-color) 100%);
            color: white;
            border: none;
        }

        .card-stats .card-body {
            padding: 1.5rem;
        }

        .card-stats h3 {
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }

        .operation-status {
            position: sticky;
            top: 20px;
        }

        .table {
            background-color: white;
        }

        .table thead {
            background-color: var(--primary-color);
            color: white;
        }

        .badge {
            padding: 0.5em 0.75em;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark bg-dark">
        <div class="container-fluid">
            <span class="navbar-brand">
                <i class="fas fa-shield-alt me-2"></i>
                Duo Student Cleanup Dashboard
            </span>
            <span class="navbar-text">
                <i class="fas fa-user me-2"></i>{{ auth.current_user() }}
            </span>
        </div>
    </nav>

    <div class="container-fluid mt-4">
        <!-- Statistics Cards -->
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card card-stats text-center">
                    <div class="card-body">
                        <i class="fas fa-tasks fa-2x mb-2"></i>
                        <h3 class="card-title">{{ stats.total_operations }}</h3>
                        <p class="card-text">Total Operations</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-success text-white text-center">
                    <div class="card-body">
                        <i class="fas fa-user-minus fa-2x mb-2"></i>
                        <h3 class="card-title">{{ stats.total_deleted }}</h3>
                        <p class="card-text">Total Deleted</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-info text-white text-center">
                    <div class="card-body">
                        <i class="fas fa-chart-line fa-2x mb-2"></i>
                        <h3 class="card-title">{{ stats.success_rate }}%</h3>
                        <p class="card-text">Success Rate</p>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card bg-warning text-dark text-center">
                    <div class="card-body">
                        <i class="fas fa-clock fa-2x mb-2"></i>
                        <h3 class="card-title">{{ stats.recent_operations }}</h3>
                        <p class="card-text">Recent (30d)</p>
                    </div>
                </div>
            </div>
        </div>

        <div class="row">
            <!-- Operation Controls -->
            <div class="col-md-8">
                <!-- Bypass Management Card -->
                <div class="card mb-4">
                    <div class="card-header">
                        <h5><i class="fas fa-user-shield me-2"></i>Bypass Management</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-8">
                                <div class="input-group mb-3">
                                    <input type="text" id="usernameSearch" class="form-control"
                                           placeholder="Enter username (e.g., jdoe or jdoe@eusd.org)"
                                           aria-label="Username">
                                    <button class="btn btn-primary" type="button" id="searchUserBtn">
                                        <i class="fas fa-search me-1"></i>Search User
                                    </button>
                                </div>
                            </div>
                        </div>

                        <!-- User Info Display -->
                        <div id="userInfo" class="d-none">
                            <div class="card border-info">
                                <div class="card-body">
                                    <div class="row">
                                        <div class="col-md-6">
                                            <h6 class="card-title">User Information</h6>
                                            <p class="mb-1"><strong>Username:</strong> <span id="userUsername"></span></p>
                                            <p class="mb-1"><strong>Name:</strong> <span id="userName"></span></p>
                                            <p class="mb-1"><strong>Email:</strong> <span id="userEmail"></span></p>
                                            <p class="mb-1"><strong>Enrolled:</strong> <span id="userEnrolled"></span></p>
                                        </div>
                                        <div class="col-md-6">
                                            <h6>Current Status</h6>
                                            <p class="mb-3">
                                                <span id="userStatusBadge" class="badge fs-6"></span>
                                            </p>

                                            <div class="mb-3">
                                                <label for="newStatus" class="form-label">Change Status To:</label>
                                                <select class="form-select" id="newStatus">
                                                    <option value="">Select new status...</option>
                                                    <option value="Active">Active</option>
                                                    <option value="Bypass">Bypass</option>
                                                    <option value="Disabled">Disabled</option>
                                                    <option value="Locked Out">Locked Out</option>
                                                </select>
                                            </div>

                                            <button id="updateStatusBtn" class="btn btn-warning w-100" disabled>
                                                <i class="fas fa-edit me-1"></i>Update Status
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <!-- Loading indicator -->
                        <div id="loadingIndicator" class="d-none text-center">
                            <div class="spinner-border text-primary" role="status">
                                <span class="visually-hidden">Loading...</span>
                            </div>
                            <p class="mt-2 text-muted">Searching user...</p>
                        </div>
                    </div>
                </div>

                <!-- Cleanup Operations Card -->
                <div class="card mb-4">
                    <div class="card-header">
                        <h5><i class="fas fa-play-circle me-2"></i>Cleanup Operations</h5>
                    </div>
                    <div class="card-body">
                        {% if current_operation and current_operation.is_running %}
                            <div class="alert alert-info">
                                <i class="fas fa-spinner fa-spin me-2"></i>
                                Operation in progress: {{ current_operation.operation_type }}
                                {% if current_operation.dry_run %} (DRY RUN){% endif %}
                            </div>
                        {% else %}
                            <div class="row">
                                <div class="col-md-6">
                                    <button id="dryRunBtn" class="btn btn-warning btn-lg w-100 mb-2">
                                        <i class="fas fa-eye me-2"></i>Run Dry Run
                                    </button>
                                    <small class="text-muted">Preview changes without making modifications</small>
                                </div>
                                <div class="col-md-6">
                                    <button id="fullRunBtn" class="btn btn-danger btn-lg w-100 mb-2"
                                            onclick="return confirm('Are you sure you want to run the full cleanup? This will DELETE student accounts.')">
                                        <i class="fas fa-trash me-2"></i>Run Full Cleanup
                                    </button>
                                    <small class="text-muted">Execute actual deletions</small>
                                </div>
                            </div>
                        {% endif %}
                    </div>
                </div>

                <!-- Operation History -->
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5><i class="fas fa-history me-2"></i>Operation History</h5>
                        <button class="btn btn-sm btn-outline-primary" onclick="location.reload()">
                            <i class="fas fa-refresh me-1"></i>Refresh
                        </button>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Timestamp</th>
                                        <th>Type</th>
                                        <th>Status</th>
                                        <th>Processed</th>
                                        <th>Deleted</th>
                                        <th>Errors</th>
                                        <th>Duration</th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for op in history %}
                                    <tr>
                                        <td>{{ op.timestamp[:19] }}</td>
                                        <td>
                                            {{ op.operation_type }}
                                            {% if op.dry_run %}<span class="badge bg-secondary">DRY</span>{% endif %}
                                        </td>
                                        <td><span class="status-{{ op.status }}"><i class="fas fa-circle me-1"></i>{{ op.status.title() }}</span></td>
                                        <td>{{ op.total_processed or 0 }}</td>
                                        <td>{{ op.deleted_count or 0 }}</td>
                                        <td>{{ op.error_count or 0 }}</td>
                                        <td>{{ op.duration or 0 }}s</td>
                                        <td>
                                            {% if op.results_file %}
                                            <a href="/download/{{ op.id }}" class="btn btn-sm btn-outline-primary">
                                                <i class="fas fa-download"></i>
                                            </a>
                                            {% endif %}
                                        </td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Operation Status -->
            <div class="col-md-4">
                <div class="card operation-status">
                    <div class="card-header">
                        <h5><i class="fas fa-monitor me-2"></i>Current Operation</h5>
                    </div>
                    <div class="card-body">
                        {% if current_operation and current_operation.is_running %}
                            <div class="mb-3">
                                <strong>Status:</strong> <span class="text-warning">Running</span><br>
                                <strong>Type:</strong> {{ current_operation.operation_type }}<br>
                                <strong>Mode:</strong> {% if current_operation.dry_run %}Dry Run{% else %}Full Run{% endif %}<br>
                                <strong>Started:</strong> {{ current_operation.start_time.strftime('%H:%M:%S') if current_operation.start_time }}<br>
                            </div>

                            <div class="mb-3">
                                <div class="row text-center">
                                    <div class="col-4">
                                        <strong>{{ current_operation.progress.get('processed', 0) }}</strong><br>
                                        <small>Processed</small>
                                    </div>
                                    <div class="col-4">
                                        <strong>{{ current_operation.progress.get('deleted', 0) }}</strong><br>
                                        <small>Deleted</small>
                                    </div>
                                    <div class="col-4">
                                        <strong>{{ current_operation.progress.get('errors', 0) }}</strong><br>
                                        <small>Errors</small>
                                    </div>
                                </div>
                            </div>

                            <div class="mb-3">
                                <h6>Live Log:</h6>
                                <div class="log-container" id="liveLog">
                                    {% for log in current_operation.logs[-10:] %}{{ log }}
{% endfor %}
                                </div>
                            </div>

                            <script>
                                // Auto-refresh during operation
                                setTimeout(() => location.reload(), 5000);
                            </script>
                        {% else %}
                            <p class="text-muted">No operation currently running.</p>
                            {% if current_operation and current_operation.error %}
                                <div class="alert alert-danger">
                                    <strong>Last operation failed:</strong><br>
                                    {{ current_operation.error }}
                                </div>
                            {% endif %}
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Toast container for notifications -->
    <div class="toast-container position-fixed bottom-0 end-0 p-3">
        <div id="successToast" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header bg-success text-white">
                <i class="fas fa-check-circle me-2"></i>
                <strong class="me-auto">Success</strong>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
            <div class="toast-body" id="successToastBody">
            </div>
        </div>
        <div id="errorToast" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="toast-header bg-danger text-white">
                <i class="fas fa-exclamation-circle me-2"></i>
                <strong class="me-auto">Error</strong>
                <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
            <div class="toast-body" id="errorToastBody">
            </div>
        </div>
    </div>

    <!-- Confirmation Modal -->
    <div class="modal fade" id="confirmModal" tabindex="-1" aria-labelledby="confirmModalLabel" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="confirmModalLabel">Confirm Status Change</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body" id="confirmModalBody">
                </div>
                <div class="modal-footer">
                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                    <button type="button" class="btn btn-warning" id="confirmUpdateBtn">Update Status</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        let currentUser = null;

        // Helper functions
        function showToast(type, message) {
            const toastElement = document.getElementById(type + 'Toast');
            const toastBody = document.getElementById(type + 'ToastBody');
            toastBody.textContent = message;
            const toast = new bootstrap.Toast(toastElement);
            toast.show();
        }

        function getStatusBadgeClass(status) {
            switch(status.toLowerCase()) {
                case 'active': return 'bg-success';
                case 'bypass': return 'bg-warning text-dark';
                case 'disabled': return 'bg-danger';
                case 'locked out': return 'bg-info';
                default: return 'bg-secondary';
            }
        }

        function updateActionButton() {
            const newStatus = document.getElementById('newStatus').value;
            const updateBtn = document.getElementById('updateStatusBtn');

            if (newStatus && currentUser && newStatus !== currentUser.status) {
                updateBtn.disabled = false;
                updateBtn.innerHTML = `<i class="fas fa-edit me-1"></i>Set ${newStatus}`;
            } else {
                updateBtn.disabled = true;
                updateBtn.innerHTML = '<i class="fas fa-edit me-1"></i>Update Status';
            }
        }

        // Bypass Management Event Listeners
        document.getElementById('searchUserBtn').addEventListener('click', function() {
            const username = document.getElementById('usernameSearch').value.trim();
            if (!username) {
                showToast('error', 'Please enter a username');
                return;
            }

            // Show loading
            document.getElementById('loadingIndicator').classList.remove('d-none');
            document.getElementById('userInfo').classList.add('d-none');

            fetch(`/api/user/bypass?username=${encodeURIComponent(username)}`)
            .then(response => response.json())
            .then(data => {
                document.getElementById('loadingIndicator').classList.add('d-none');

                if (data.success) {
                    currentUser = data.user;

                    // Populate user info
                    document.getElementById('userUsername').textContent = data.user.username;
                    document.getElementById('userName').textContent =
                        (data.user.firstname || '') + ' ' + (data.user.lastname || '');
                    document.getElementById('userEmail').textContent = data.user.email || 'N/A';
                    document.getElementById('userEnrolled').textContent = data.user.is_enrolled ? 'Yes' : 'No';

                    // Update status badge
                    const statusBadge = document.getElementById('userStatusBadge');
                    statusBadge.textContent = data.user.status;
                    statusBadge.className = `badge fs-6 ${getStatusBadgeClass(data.user.status)}`;

                    // Reset form
                    document.getElementById('newStatus').value = '';
                    updateActionButton();

                    // Show user info
                    document.getElementById('userInfo').classList.remove('d-none');
                } else {
                    showToast('error', data.error);
                }
            })
            .catch(error => {
                document.getElementById('loadingIndicator').classList.add('d-none');
                showToast('error', 'Network error: ' + error.message);
            });
        });

        // Allow Enter key to trigger search
        document.getElementById('usernameSearch').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                document.getElementById('searchUserBtn').click();
            }
        });

        // Update button when status selection changes
        document.getElementById('newStatus').addEventListener('change', updateActionButton);

        // Handle status update
        document.getElementById('updateStatusBtn').addEventListener('click', function() {
            const newStatus = document.getElementById('newStatus').value;
            if (!newStatus || !currentUser) return;

            // Show confirmation modal
            document.getElementById('confirmModalBody').innerHTML =
                `Are you sure you want to change <strong>${currentUser.username}</strong>'s status from <span class="badge ${getStatusBadgeClass(currentUser.status)}">${currentUser.status}</span> to <span class="badge ${getStatusBadgeClass(newStatus)}">${newStatus}</span>?`;

            const confirmModal = new bootstrap.Modal(document.getElementById('confirmModal'));
            confirmModal.show();
        });

        // Handle confirmation
        document.getElementById('confirmUpdateBtn').addEventListener('click', function() {
            const newStatus = document.getElementById('newStatus').value;
            if (!newStatus || !currentUser) return;

            const confirmModal = bootstrap.Modal.getInstance(document.getElementById('confirmModal'));
            confirmModal.hide();

            // Disable button during update
            const updateBtn = document.getElementById('updateStatusBtn');
            updateBtn.disabled = true;
            updateBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Updating...';

            fetch('/api/user/bypass', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: currentUser.username,
                    status: newStatus
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (data.no_change) {
                        showToast('error', data.message);
                    } else {
                        showToast('success', data.message);

                        // Update current user status
                        currentUser.status = newStatus;

                        // Update status badge
                        const statusBadge = document.getElementById('userStatusBadge');
                        statusBadge.textContent = newStatus;
                        statusBadge.className = `badge fs-6 ${getStatusBadgeClass(newStatus)}`;

                        // Reset form
                        document.getElementById('newStatus').value = '';
                    }
                } else {
                    showToast('error', data.error);
                }
                updateActionButton();
            })
            .catch(error => {
                showToast('error', 'Network error: ' + error.message);
                updateActionButton();
            });
        });

        // Cleanup Operations Event Listeners
        document.getElementById('dryRunBtn').addEventListener('click', function() {
            fetch('/api/run-cleanup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({dry_run: true})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Failed to start operation: ' + data.error);
                }
            })
            .catch(error => {
                alert('Error: ' + error);
            });
        });

        document.getElementById('fullRunBtn').addEventListener('click', function() {
            fetch('/api/run-cleanup', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({dry_run: false})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Failed to start operation: ' + data.error);
                }
            })
            .catch(error => {
                alert('Error: ' + error);
            });
        });
    </script>
</body>
</html>
'''

# Routes
@app.route('/')
@auth.login_required
def dashboard():
    """Main dashboard page"""
    return render_template_string(DASHBOARD_HTML,
                                  current_operation=current_operation,
                                  history=get_operation_history(),
                                  stats=get_stats(),
                                  auth=auth)

@app.route('/api/run-cleanup', methods=['POST'])
@auth.login_required
def api_run_cleanup():
    """API endpoint to start cleanup operation"""
    data = request.get_json() or {}
    dry_run = data.get('dry_run', True)
    username_file = data.get('username_file')

    success, message = run_cleanup_operation(dry_run, username_file, auth.current_user())
    return jsonify({'success': success, 'message': message})

@app.route('/api/status')
@auth.login_required
def api_status():
    """API endpoint to get current operation status"""
    if current_operation:
        return jsonify({
            'is_running': current_operation.is_running,
            'operation_type': current_operation.operation_type,
            'dry_run': current_operation.dry_run,
            'progress': current_operation.progress,
            'logs': current_operation.logs[-10:],  # Last 10 log entries
            'error': current_operation.error
        })
    else:
        return jsonify({'is_running': False})

@app.route('/api/user/bypass', methods=['GET'])
@auth.login_required
def api_get_user_bypass():
    """API endpoint to get user bypass status"""
    username = request.args.get('username')
    if not username:
        return jsonify({'success': False, 'error': 'Username is required'}), 400

    try:
        api = get_duo_api_client()
        user = api.get_user_by_username(username)

        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        # Log the lookup
        log_bypass_audit(
            username=username,
            user_id=user.get('user_id'),
            action='lookup',
            triggered_by=auth.current_user(),
            ip_address=request.remote_addr
        )

        return jsonify({
            'success': True,
            'user': {
                'user_id': user.get('user_id'),
                'username': user.get('username'),
                'status': user.get('status'),
                'email': user.get('email'),
                'firstname': user.get('firstname'),
                'lastname': user.get('lastname'),
                'created': user.get('created'),
                'last_login': user.get('last_login'),
                'is_enrolled': user.get('is_enrolled'),
                'phones': user.get('phones', []),
                'tokens': user.get('tokens', [])
            }
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        # Log the error
        log_bypass_audit(
            username=username,
            user_id=None,
            action='lookup',
            success=False,
            error_message=str(e),
            triggered_by=auth.current_user(),
            ip_address=request.remote_addr
        )
        return jsonify({'success': False, 'error': f'API error: {str(e)}'}), 500

@app.route('/api/user/bypass', methods=['POST'])
@auth.login_required
def api_update_user_bypass():
    """API endpoint to update user bypass status"""
    data = request.get_json() or {}
    username = data.get('username')
    new_status = data.get('status')

    if not username or not new_status:
        return jsonify({'success': False, 'error': 'Username and status are required'}), 400

    # Validate status
    valid_statuses = ['Active', 'Bypass', 'Disabled', 'Locked Out']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}), 400

    try:
        api = get_duo_api_client()
        user = api.get_user_by_username(username)

        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        user_id = user.get('user_id')
        old_status = user.get('status')

        # Check if status is actually changing
        if old_status == new_status:
            return jsonify({'success': True, 'message': f'User status is already {new_status}', 'no_change': True})

        # Update the user status
        success = api.update_user_status(user_id, new_status)

        if success:
            # Log successful update
            log_bypass_audit(
                username=username,
                user_id=user_id,
                action='status_update',
                old_status=old_status,
                new_status=new_status,
                success=True,
                triggered_by=auth.current_user(),
                ip_address=request.remote_addr
            )

            return jsonify({
                'success': True,
                'message': f'User status updated from {old_status} to {new_status}',
                'old_status': old_status,
                'new_status': new_status
            })
        else:
            # Log failed update
            log_bypass_audit(
                username=username,
                user_id=user_id,
                action='status_update',
                old_status=old_status,
                new_status=new_status,
                success=False,
                error_message='API update failed',
                triggered_by=auth.current_user(),
                ip_address=request.remote_addr
            )
            return jsonify({'success': False, 'error': 'Failed to update user status'}), 500

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    except Exception as e:
        # Log the error
        log_bypass_audit(
            username=username,
            user_id=None,
            action='status_update',
            old_status=None,
            new_status=new_status,
            success=False,
            error_message=str(e),
            triggered_by=auth.current_user(),
            ip_address=request.remote_addr
        )
        return jsonify({'success': False, 'error': f'API error: {str(e)}'}), 500

@app.route('/download/<int:operation_id>')
@auth.login_required
def download_results(operation_id):
    """Download operation results CSV"""
    # Find the most recent CSV file in logs directory
    logs_dir = Path('logs')
    if logs_dir.exists():
        csv_files = list(logs_dir.glob('duo_cleanup_results_*.csv'))
        if csv_files:
            latest_file = max(csv_files, key=lambda f: f.stat().st_mtime)
            return send_file(latest_file, as_attachment=True)

    flash('No results file found for this operation', 'error')
    return redirect(url_for('dashboard'))

@app.route('/logs')
@auth.login_required
def view_logs():
    """View recent log files"""
    logs_dir = Path('logs')
    log_files = []

    if logs_dir.exists():
        for log_file in logs_dir.glob('duo_cleanup_*.log'):
            stat = log_file.stat()
            log_files.append({
                'name': log_file.name,
                'path': str(log_file),
                'size': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })

    log_files.sort(key=lambda x: x['modified'], reverse=True)

    # Simple logs template
    logs_html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Operation Logs</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    </head>
    <body>
        <div class="container mt-4">
            <h2>Operation Logs</h2>
            <a href="/" class="btn btn-primary mb-3">Back to Dashboard</a>

            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>File Name</th>
                            <th>Size</th>
                            <th>Last Modified</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for log in logs %}
                        <tr>
                            <td>{{ log.name }}</td>
                            <td>{{ log.size }} bytes</td>
                            <td>{{ log.modified }}</td>
                            <td>
                                <a href="/download-log?file={{ log.name }}" class="btn btn-sm btn-outline-primary">Download</a>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(logs_html, logs=log_files)

@app.route('/download-log')
@auth.login_required
def download_log():
    """Download a specific log file"""
    filename = request.args.get('file')
    if not filename:
        flash('No file specified', 'error')
        return redirect(url_for('view_logs'))

    log_file = Path('logs') / filename
    if not log_file.exists():
        flash('File not found', 'error')
        return redirect(url_for('view_logs'))

    return send_file(log_file, as_attachment=True)

def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Duo Cleanup Web Dashboard')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')

    args = parser.parse_args()

    # Initialize database
    init_db()

    print(f"Starting Duo Cleanup Dashboard...")
    print(f"Access the dashboard at: http://{args.host}:{args.port}")
    print(f"Default credentials: {os.environ.get('DASHBOARD_USER', 'admin')} / {os.environ.get('DASHBOARD_PASSWORD', 'admin123')}")

    if args.debug:
        app.run(host=args.host, port=args.port, debug=True)
    else:
        serve(app, host=args.host, port=args.port)

if __name__ == '__main__':
    main()