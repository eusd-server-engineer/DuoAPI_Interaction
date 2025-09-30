#!/usr/bin/env python3
"""
Agent Executor - Processes agent execution requests
This script is meant to be run BY Claude Code, not as a standalone script,
so it can access the Task tool for launching agents.
"""

import json
from pathlib import Path
from datetime import datetime

def check_for_pending_requests():
    """Check for pending agent execution requests"""
    requests_dir = Path(".claude/agent_requests")

    if not requests_dir.exists():
        return []

    pending_requests = []
    for request_file in requests_dir.glob("*.json"):
        try:
            with open(request_file) as f:
                request_data = json.load(f)

            if request_data.get('status') == 'pending':
                pending_requests.append({
                    'file': request_file,
                    'data': request_data
                })
        except Exception as e:
            print(f"Error reading {request_file}: {e}")

    return pending_requests

def main():
    """Main execution - called by Claude Code"""
    print("[AGENT EXECUTOR] Checking for pending agent requests...")

    pending = check_for_pending_requests()

    if not pending:
        print("[AGENT EXECUTOR] No pending requests found")
        return

    print(f"[AGENT EXECUTOR] Found {len(pending)} pending request(s)")

    for request in pending:
        work_id = request['data']['work_id']
        prompt_file = request['data']['prompt_file']

        print(f"[AGENT EXECUTOR] Processing {work_id}")
        print(f"[AGENT EXECUTOR] Prompt file: {prompt_file}")
        print(f"[AGENT EXECUTOR] This request needs to be processed by Claude Code with Task tool")
        print(f"[AGENT EXECUTOR] Request data: {json.dumps(request['data'], indent=2)}")

if __name__ == '__main__':
    main()