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

        try:
            ACTION_LOG_FILE.parent.mkdir(exist_ok=True)
            with open(ACTION_LOG_FILE, 'a') as f:
                f.write(log_entry)
        except (PermissionError, IOError) as e:
            # If we can't write to the log file, just continue
            print(f"Warning: Could not write to log file: {e}")

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

        # Create work instruction file for reference
        work_file = Path(f".claude/work_{work_item['id']}.md")
        work_file.parent.mkdir(exist_ok=True)

        with open(work_file, 'w') as f:
            f.write(f"# Autonomous Work Assignment\n\n")
            f.write(f"**Branch**: {branch_name}\n")
            f.write(f"**Work Item**: {work_item['id']}\n")
            f.write(f"**Created**: {datetime.now()}\n\n")
            f.write("## Instructions\n\n")
            f.write(prompt)

        self.log_action(f"Created work instructions at {work_file}")

        # Send immediate notification
        if self.notifier:
            self.send_work_notification(work_item, branch_name, work_file)

        # Launch actual Claude agent to implement the solution
        try:
            agent_prompt = self.build_agent_execution_prompt(work_item, branch_name, prompt)

            # Write agent execution plan that can be picked up by a monitoring process
            agent_plan_file = Path(f".claude/agent_plan_{work_item['id']}.md")
            with open(agent_plan_file, 'w') as f:
                f.write(agent_prompt)

            # Create agent request file for Claude Code to process
            agent_request_file = Path(f".claude/agent_requests/{work_item['id']}.json")
            agent_request_file.parent.mkdir(exist_ok=True)

            request_data = {
                'work_id': work_item['id'],
                'work_type': work_item.get('type'),
                'branch': branch_name,
                'title': work_item.get('title', ''),
                'number': work_item.get('number'),
                'status': 'pending',
                'created_at': datetime.now().isoformat(),
                'prompt_file': str(agent_plan_file),
                'work_file': str(work_file)
            }

            with open(agent_request_file, 'w') as f:
                json.dump(request_data, f, indent=2)

            self.log_action(f"Created agent request at {agent_request_file}")
            self.log_action(f"Agent execution queued for {work_item['id']}")

            # Agent will be picked up by the agent_executor monitoring process
            return True

        except Exception as e:
            self.log_action(f"Failed to launch agent: {e}")
            return False

    def build_agent_execution_prompt(self, work_item: Dict, branch_name: str, task_prompt: str) -> str:
        """Build comprehensive prompt for agent execution"""

        work_type = work_item.get('type', 'unknown')
        work_id = work_item['id']

        execution_prompt = f"""# Autonomous Agent Task Execution

## Context
You are an autonomous agent working on a GitHub issue. Your goal is to implement a complete, production-ready solution.

**Work Item ID**: {work_id}
**Work Type**: {work_type}
**Branch**: {branch_name}
**Repository**: eusd-server-engineer/DuoAPI_Interaction

## Task Requirements
{task_prompt}

## Execution Instructions

### Phase 1: Setup and Analysis
1. Switch to the working branch: `git checkout {branch_name}`
2. Read and analyze the existing codebase to understand:
   - Project structure and conventions
   - Code style and patterns
   - Existing similar implementations
   - Dependencies and frameworks in use
3. Review the requirements carefully and plan your implementation

### Phase 2: Implementation
1. Create or modify necessary files following project conventions
2. Ensure code quality:
   - Follow existing code style
   - Add proper error handling
   - Use existing utilities and patterns
   - Add type hints where appropriate
3. Write clean, maintainable, production-ready code
4. Add comments only where necessary for complex logic

### Phase 3: Testing
1. Check if tests exist in the project
2. Run existing tests to ensure nothing breaks: `uv run pytest tests/ -v` (if tests exist)
3. Create new tests if the project has a test framework
4. Verify the implementation manually if possible

### Phase 4: Documentation
1. Create a work summary file at `.claude/agent_summary_{work_id}.md` with:
   - Overview of changes made
   - Files created/modified
   - Key decisions and rationale
   - Testing performed
   - Any issues encountered and how resolved
   - Recommendations or future improvements

### Phase 5: Commit and PR
1. Stage all changes: `git add .`
2. Create descriptive commit message following this format:
"""

        if work_type == 'issue':
            execution_prompt += f"""
   Implement: {work_item.get('title', 'Solution for issue')}

   [Detailed description of what was implemented]

   Fixes #{work_item.get('number', 'N/A')}

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>
"""
        else:
            execution_prompt += f"""
   Fix: {work_item.get('title', 'Automated fix')}

   [Detailed description of what was fixed]

   🤖 Generated with [Claude Code](https://claude.ai/code)

   Co-Authored-By: Claude <noreply@anthropic.com>
"""

        execution_prompt += """
3. Commit changes with the commit message
4. Push the branch: `git push -u origin """ + branch_name + """` (if not already pushed)
5. Create pull request with detailed description using:
   ```bash
   gh pr create --title "[Title]" --body "[Description]"
   ```

## Important Guidelines

### Do NOT:
- Create unnecessary files or documentation
- Make changes outside the scope of the issue
- Break existing functionality
- Commit secrets or sensitive data
- Use placeholder/mock data in production code

### DO:
- Follow project conventions religiously
- Test your changes thoroughly
- Write production-ready code
- Create comprehensive work summary
- Make atomic, focused changes
- Handle errors gracefully
- Log important operations

## Success Criteria
Your implementation is complete when:
1. ✅ All requirements from the issue are implemented
2. ✅ Code follows project conventions and style
3. ✅ Tests pass (if applicable)
4. ✅ Work summary file is created
5. ✅ Changes are committed and pushed
6. ✅ Pull request is created with good description
7. ✅ No linting or type errors

## Work Summary Template
Your `.claude/agent_summary_{work_id}.md` file MUST include:

```markdown
# Agent Work Summary: {work_id}

## Overview
[Brief description of the task and solution]

## Changes Made

### Files Created
- [List each file with brief purpose]

### Files Modified
- [List each file with what changed]

## Implementation Details

### Key Decisions
[Explain major design decisions and why you made them]

### Challenges Encountered
[Any issues you ran into and how you solved them]

### Testing Performed
[What testing did you do? Manual? Automated?]

## Code Quality Checklist
- [ ] Follows project code style
- [ ] Error handling implemented
- [ ] No hardcoded values
- [ ] Type hints added (if applicable)
- [ ] Functions are focused and single-purpose
- [ ] Comments added where needed

## Integration Notes
[How does this integrate with existing code? Any dependencies?]

## Future Improvements
[Suggestions for future enhancements or known limitations]

## Verification Steps
[How can a reviewer verify this works correctly?]

## Time Spent
[Approximate time spent on implementation]
```

## Final Notes
You are an autonomous agent. Work independently, make good decisions, and deliver production-quality code. Your work will be reviewed, but aim to make it merge-ready on first attempt.

Good luck!
"""

        return execution_prompt

    def send_work_notification(self, work_item: Dict, branch_name: str, work_file: Path):
        """Send immediate email notification when work is assigned"""
        work_type = work_item.get('type', 'unknown')

        if work_type == 'issue':
            subject = f"🤖 Work Assigned: Issue #{work_item['number']} - {work_item['title']}"
            body = f"""Autonomous Action System has assigned you work!

Issue: #{work_item['number']} - {work_item['title']}
Branch: {branch_name}
Work Instructions: {work_file}

To start working on this:
1. git checkout {branch_name}
2. Review instructions at {work_file}
3. Implement the solution
4. Create a PR when done

View issue: gh issue view {work_item['number']}

🤖 Generated with Claude Code (https://claude.ai/code)
"""
        elif work_type == 'workflow':
            subject = f"⚠️ Workflow Failed: {work_item['name']}"
            body = f"""Autonomous Action System detected a workflow failure!

Workflow: {work_item['name']}
Run ID: {work_item['run_id']}
Reason: {work_item['reason']}

To investigate:
gh run view {work_item['run_id']} --log-failed

🤖 Generated with Claude Code (https://claude.ai/code)
"""
        else:
            subject = f"🤖 Work Assigned: {work_item.get('title', 'New Work')}"
            body = f"""Autonomous Action System has assigned you work!

Work Item: {work_item['id']}
Branch: {branch_name}
Work Instructions: {work_file}

Review {work_file} for details.

🤖 Generated with Claude Code (https://claude.ai/code)
"""

        self.notifier.send_email(
            subject=subject,
            body_text=body,
            to_email="admin@eusd.org"
        )

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