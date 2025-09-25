#!/usr/bin/env python3
"""
Autonomous Action System - Processes pending work and creates PRs
This script runs after the monitor finds work, automatically creating branches
and launching agents to implement solutions.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Try to import email notifier if available
try:
    from email_notifier import EmailNotifier
    EMAIL_AVAILABLE = True
except ImportError:
    EMAIL_AVAILABLE = False
    EmailNotifier = None

# Configuration
PENDING_FILE = Path(".claude/pending_work.md")
ACTION_STATE_FILE = Path(".claude/action_state.json")
ACTION_LOG_FILE = Path(".claude/action_log.txt")
REPO = "eusd-server-engineer/DuoAPI_Interaction"


class AutonomousActionSystem:
    """Processes pending work and creates PRs automatically"""

    def __init__(self):
        self.state = self.load_state()
        self.notifier = self.init_email_notifier()

    def load_state(self) -> Dict:
        """Load previous state from file"""
        if ACTION_STATE_FILE.exists():
            with open(ACTION_STATE_FILE) as f:
                return json.load(f)
        return {
            "processed_work": [],
            "active_branches": [],
            "created_prs": []
        }

    def save_state(self):
        """Save current state to file"""
        ACTION_STATE_FILE.parent.mkdir(exist_ok=True)
        with open(ACTION_STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def init_email_notifier(self) -> Optional[EmailNotifier]:
        """Initialize email notifier if configured"""
        if not EMAIL_AVAILABLE:
            return None
        try:
            if all(os.getenv(k) for k in ['SMTP_SERVER', 'SMTP_USER', 'SMTP_PASSWORD']):
                return EmailNotifier()
            return None
        except:
            return None

    def log_action(self, message: str):
        """Log an action to the log file"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] {message}\n"

        ACTION_LOG_FILE.parent.mkdir(exist_ok=True)
        with open(ACTION_LOG_FILE, 'a') as f:
            f.write(log_entry)

        print(log_entry.strip())

    def run_command(self, cmd: List[str]) -> Optional[str]:
        """Run a command and return output"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.log_action(f"Command failed: {' '.join(cmd)}")
            self.log_action(f"Error: {e.stderr}")
            return None

    def parse_pending_work(self) -> List[Dict]:
        """Parse the pending work file"""
        if not PENDING_FILE.exists():
            return []

        with open(PENDING_FILE) as f:
            content = f.read()

        work_items = []

        # Parse issues
        issue_pattern = r'\[ISSUE\] Issue #(\d+): (.+)'
        for match in re.finditer(issue_pattern, content):
            issue_num = match.group(1)
            title = match.group(2)
            work_items.append({
                'type': 'issue',
                'number': issue_num,
                'title': title,
                'id': f"issue_{issue_num}"
            })

        # Parse comments
        comment_pattern = r'\[COMMENT\] Comment on #(\d+)'
        for match in re.finditer(comment_pattern, content):
            issue_num = match.group(1)
            work_items.append({
                'type': 'comment',
                'issue_number': issue_num,
                'id': f"comment_issue_{issue_num}"
            })

        # Parse PRs
        pr_pattern = r'\[PR\] PR #(\d+): (.+)'
        for match in re.finditer(pr_pattern, content):
            pr_num = match.group(1)
            title = match.group(2)
            work_items.append({
                'type': 'pr',
                'number': pr_num,
                'title': title,
                'id': f"pr_{pr_num}"
            })

        return work_items

    def create_branch_name(self, work_item: Dict) -> str:
        """Generate a branch name for the work item"""
        if work_item['type'] == 'issue':
            # Sanitize title for branch name
            title_part = re.sub(r'[^a-zA-Z0-9]+', '-', work_item['title'].lower())[:30]
            return f"fix-issue-{work_item['number']}-{title_part}".rstrip('-')
        elif work_item['type'] == 'comment':
            return f"respond-issue-{work_item['issue_number']}-comment"
        else:
            return f"fix-pr-{work_item['number']}"

    def create_agent_prompt(self, work_item: Dict) -> str:
        """Create a prompt for the Claude agent"""
        if work_item['type'] == 'issue':
            issue_num = work_item['number']

            # Get full issue details
            issue_json = self.run_command(['gh', 'issue', 'view', issue_num, '--json',
                                          'title,body,comments,labels'])
            if not issue_json:
                return None

            issue_data = json.loads(issue_json)

            prompt = f"""You are working on GitHub Issue #{issue_num}: {issue_data['title']}

Issue Description:
{issue_data.get('body', 'No description')}

Comments mentioning @claude:
"""
            for comment in issue_data.get('comments', []):
                if '@claude' in comment.get('body', '').lower():
                    prompt += f"\n- {comment['body']}\n"

            prompt += """
Please implement a complete solution for this issue:
1. Analyze the requirements
2. Create or modify necessary files
3. Add tests if applicable
4. Ensure the solution is production-ready

Work in the current branch and commit your changes when done.
"""
            return prompt

        elif work_item['type'] == 'comment':
            # Handle comment response
            issue_num = work_item['issue_number']
            return f"""Review issue #{issue_num} and the @claude comment, then take appropriate action.
Get the issue details and implement what was requested in the comment."""

        else:
            # Handle PR fixes
            return f"""Review PR #{work_item['number']} and fix any failing checks or implement requested changes."""

    def launch_claude_agent(self, work_item: Dict, branch_name: str) -> bool:
        """Launch a Claude agent to work on the task"""
        self.log_action(f"Launching Claude agent for {work_item['id']}")

        # Create the prompt
        prompt = self.create_agent_prompt(work_item)
        if not prompt:
            self.log_action(f"Failed to create prompt for {work_item['id']}")
            return False

        # For now, we'll create a work instruction file that you can use
        # In a real implementation, this would use Claude's API
        work_file = Path(f".claude/work_{work_item['id']}.md")
        work_file.parent.mkdir(exist_ok=True)

        with open(work_file, 'w') as f:
            f.write(f"# Autonomous Work Assignment\n\n")
            f.write(f"**Branch**: {branch_name}\n")
            f.write(f"**Work Item**: {work_item['id']}\n")
            f.write(f"**Created**: {datetime.now()}\n\n")
            f.write("## Instructions\n\n")
            f.write(prompt)
            f.write("\n\n## Commands to execute:\n\n")
            f.write("```bash\n")
            f.write(f"git checkout {branch_name}\n")
            f.write("# Implement the solution\n")
            f.write("git add .\n")
            f.write("git commit -m 'Implement solution for issue'\n")
            f.write("gh pr create --title 'Fix issue' --body 'Automated fix'\n")
            f.write("```\n")

        self.log_action(f"Created work instructions at {work_file}")

        # Simulate agent work (in reality, this would call Claude API)
        # For now, we'll just log that work needs to be done
        return True

    def process_work_item(self, work_item: Dict) -> bool:
        """Process a single work item"""
        work_id = work_item['id']

        # Skip if already processed
        if work_id in self.state['processed_work']:
            self.log_action(f"Skipping already processed: {work_id}")
            return True

        self.log_action(f"Processing: {work_id}")

        # Create branch
        branch_name = self.create_branch_name(work_item)

        # Check if branch already exists locally or remotely
        local_branches = self.run_command(['git', 'branch'])
        remote_branches = self.run_command(['git', 'branch', '-r'])

        branch_exists_local = local_branches and branch_name in local_branches
        branch_exists_remote = remote_branches and f"origin/{branch_name}" in remote_branches

        if branch_exists_local:
            # Switch to existing local branch
            if not self.run_command(['git', 'checkout', branch_name]):
                self.log_action(f"Failed to checkout existing branch: {branch_name}")
                return False
            self.log_action(f"Using existing local branch: {branch_name}")
        elif branch_exists_remote:
            # Checkout remote branch
            if not self.run_command(['git', 'checkout', '-b', branch_name, f'origin/{branch_name}']):
                self.log_action(f"Failed to checkout remote branch: {branch_name}")
                return False
            self.log_action(f"Checked out remote branch: {branch_name}")
        else:
            # Create and checkout new branch
            if not self.run_command(['git', 'checkout', '-b', branch_name]):
                self.log_action(f"Failed to create branch: {branch_name}")
                return False
            self.log_action(f"Created new branch: {branch_name}")

            self.state['active_branches'].append(branch_name)

        # Launch Claude agent
        if self.launch_claude_agent(work_item, branch_name):
            self.state['processed_work'].append(work_id)
            self.save_state()

            # Switch back to master
            self.run_command(['git', 'checkout', 'master'])
            return True

        return False

    def send_summary_email(self, work_items: List[Dict]):
        """Send email summary of actions taken"""
        if not self.notifier or not work_items:
            return

        subject = f"Autonomous Action Report - {len(work_items)} items processed"

        body_text = f"""Autonomous Action System Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Processed {len(work_items)} work items:

"""
        for item in work_items:
            body_text += f"- {item['id']}: {item.get('title', 'No title')}\n"

        body_text += f"\n\nActive branches: {', '.join(self.state['active_branches'])}"
        body_text += f"\n\nCheck the repository for generated work instructions."

        body_html = f"""<html>
<body>
<h2>Autonomous Action System Report</h2>
<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
<p>Processed {len(work_items)} work items:</p>
<ul>
"""
        for item in work_items:
            body_html += f"<li><strong>{item['id']}</strong>: {item.get('title', 'No title')}</li>"

        body_html += f"""</ul>
<p><strong>Active branches:</strong> {', '.join(self.state['active_branches'])}</p>
<p>Check the repository for generated work instructions.</p>
</body>
</html>"""

        # Send to configured recipients
        recipients = os.getenv('EMAIL_RECIPIENTS', '').split(',')
        if recipients and recipients[0]:
            try:
                self.notifier.send_notification(
                    to_addresses=recipients,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html
                )
                self.log_action(f"Sent summary email to {', '.join(recipients)}")
            except Exception as e:
                self.log_action(f"Failed to send email: {e}")

    def run(self):
        """Main execution"""
        self.log_action("Starting Autonomous Action System")

        # Check for pending work
        if not PENDING_FILE.exists():
            self.log_action("No pending work file found")
            return

        # Parse work items
        work_items = self.parse_pending_work()
        if not work_items:
            self.log_action("No work items found in pending file")
            return

        self.log_action(f"Found {len(work_items)} work items")

        # Process each item
        processed = []
        for item in work_items:
            if self.process_work_item(item):
                processed.append(item)

        # Send summary email
        if processed:
            self.send_summary_email(processed)

        # Clean up pending file (rename it to processed)
        if processed:
            processed_file = PENDING_FILE.with_suffix('.processed')
            PENDING_FILE.rename(processed_file)
            self.log_action(f"Moved pending work to {processed_file}")

        self.log_action(f"Completed - processed {len(processed)}/{len(work_items)} items")


def main():
    """Main entry point"""
    system = AutonomousActionSystem()
    system.run()


if __name__ == '__main__':
    main()