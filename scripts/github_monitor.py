#!/usr/bin/env python3
"""
GitHub Monitor - Autonomous issue/PR checker for Claude Code
Monitors GitHub for new issues and PRs that need attention
"""

import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Configuration
REPO = "eusd-server-engineer/DuoAPI_Interaction"
CHECK_INTERVAL = 300  # 5 minutes
STATE_FILE = Path(".claude/github_monitor_state.json")
KEYWORDS = ["@claude", "claude:", "for claude", "claude please", "ai:", "bot:"]


class GitHubMonitor:
    """Monitor GitHub for actionable items"""

    def __init__(self):
        self.state = self.load_state()
        self.repo = REPO

    def load_state(self) -> Dict:
        """Load previous state from file"""
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                return json.load(f)
        return {
            "last_check": None,
            "processed_issues": [],
            "processed_prs": [],
            "processed_comments": []
        }

    def save_state(self):
        """Save current state to file"""
        STATE_FILE.parent.mkdir(exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2, default=str)

    def gh_command(self, *args) -> Optional[str]:
        """Execute gh CLI command"""
        try:
            result = subprocess.run(
                ["gh"] + list(args),
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error running gh command: {e}")
            return None

    def check_new_issues(self) -> List[Dict]:
        """Check for new issues that need attention"""
        actionable = []

        # Get open issues
        issues_json = self.gh_command("issue", "list", "--json", "number,title,body,author,createdAt,labels")
        if not issues_json:
            return actionable

        issues = json.loads(issues_json)

        for issue in issues:
            issue_num = issue['number']

            # Skip if already processed
            if issue_num in self.state['processed_issues']:
                continue

            # Check if issue mentions Claude or has specific labels
            body_lower = (issue.get('body', '') + issue.get('title', '')).lower()
            has_keyword = any(kw in body_lower for kw in KEYWORDS)
            has_label = any(label['name'] in ['claude', 'ai', 'automation']
                          for label in issue.get('labels', []))

            if has_keyword or has_label:
                actionable.append({
                    'type': 'issue',
                    'number': issue_num,
                    'title': issue['title'],
                    'action': 'implement',
                    'reason': 'Contains Claude mention or automation label'
                })

        return actionable

    def check_pr_reviews(self) -> List[Dict]:
        """Check for PRs that need review or have failing checks"""
        actionable = []

        # Get open PRs
        prs_json = self.gh_command("pr", "list", "--json", "number,title,author,isDraft,checksState")
        if not prs_json:
            return actionable

        prs = json.loads(prs_json)

        for pr in prs:
            pr_num = pr['number']

            # Skip drafts
            if pr.get('isDraft'):
                continue

            # Check for failing checks
            if pr.get('checksState') == 'FAILURE':
                if f"pr_{pr_num}_fix" not in self.state['processed_prs']:
                    actionable.append({
                        'type': 'pr',
                        'number': pr_num,
                        'title': pr['title'],
                        'action': 'fix_checks',
                        'reason': 'CI checks are failing'
                    })

            # Check for review requests
            reviews_json = self.gh_command("pr", "view", str(pr_num), "--json", "reviewRequests")
            if reviews_json:
                reviews = json.loads(reviews_json)
                if reviews.get('reviewRequests'):
                    if f"pr_{pr_num}_review" not in self.state['processed_prs']:
                        actionable.append({
                            'type': 'pr',
                            'number': pr_num,
                            'title': pr['title'],
                            'action': 'review',
                            'reason': 'Review requested'
                        })

        return actionable

    def check_comments(self) -> List[Dict]:
        """Check for new comments mentioning Claude"""
        actionable = []

        # Get recent issue and PR comments
        # This is harder with gh CLI, so we'll check last few issues/PRs

        for issue_num in range(1, 10):  # Check last 10 issues/PRs
            comments_json = self.gh_command("issue", "view", str(issue_num), "--json", "comments")
            if not comments_json:
                continue

            try:
                data = json.loads(comments_json)
                comments = data.get('comments', [])

                for comment in comments:
                    comment_id = f"issue_{issue_num}_{comment.get('id', '')}"
                    if comment_id in self.state['processed_comments']:
                        continue

                    body_lower = comment.get('body', '').lower()
                    if any(kw in body_lower for kw in KEYWORDS):
                        actionable.append({
                            'type': 'comment',
                            'issue_number': issue_num,
                            'comment_id': comment_id,
                            'action': 'respond',
                            'reason': 'Comment mentions Claude',
                            'comment_snippet': comment.get('body', '')[:100]
                        })
            except:
                pass

        return actionable

    def generate_report(self, actionable_items: List[Dict]) -> str:
        """Generate a report of actionable items"""
        if not actionable_items:
            return "No new actionable items found."

        report = [
            "# GitHub Monitor Report",
            f"**Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Repository**: {self.repo}",
            "",
            "## Actionable Items Found:",
            ""
        ]

        for item in actionable_items:
            if item['type'] == 'issue':
                report.append(f"### [ISSUE] Issue #{item['number']}: {item['title']}")
                report.append(f"- **Action**: {item['action']}")
                report.append(f"- **Reason**: {item['reason']}")
                report.append(f"- **Command**: `gh issue view {item['number']}`")

            elif item['type'] == 'pr':
                report.append(f"### [PR] PR #{item['number']}: {item['title']}")
                report.append(f"- **Action**: {item['action']}")
                report.append(f"- **Reason**: {item['reason']}")
                if item['action'] == 'fix_checks':
                    report.append(f"- **Command**: `gh pr checks {item['number']}`")

            elif item['type'] == 'comment':
                report.append(f"### [COMMENT] Comment on #{item['issue_number']}")
                report.append(f"- **Action**: Respond to comment")
                report.append(f"- **Snippet**: {item['comment_snippet']}")

            report.append("")

        report.append("## Suggested Actions:")
        report.append("1. Review each item above")
        report.append("2. Use the provided commands to investigate")
        report.append("3. Create appropriate PRs or responses")

        return "\n".join(report)

    def mark_processed(self, items: List[Dict]):
        """Mark items as processed"""
        for item in items:
            if item['type'] == 'issue':
                self.state['processed_issues'].append(item['number'])
            elif item['type'] == 'pr':
                self.state['processed_prs'].append(f"pr_{item['number']}_{item['action']}")
            elif item['type'] == 'comment':
                self.state['processed_comments'].append(item['comment_id'])

    def run_check(self) -> str:
        """Run a single check cycle"""
        print(f"[CHECK] Checking GitHub at {datetime.now()}")

        # Collect actionable items
        actionable = []
        actionable.extend(self.check_new_issues())
        actionable.extend(self.check_pr_reviews())
        actionable.extend(self.check_comments())

        # Generate report
        report = self.generate_report(actionable)

        # Update state
        self.state['last_check'] = datetime.now().isoformat()
        if actionable:
            self.mark_processed(actionable)
        self.save_state()

        return report

    def run_continuous(self):
        """Run continuous monitoring"""
        print(f"[START] Starting GitHub Monitor for {self.repo}")
        print(f"[TIME] Checking every {CHECK_INTERVAL} seconds")
        print("Press Ctrl+C to stop\n")

        while True:
            try:
                report = self.run_check()

                if "No new actionable items" not in report:
                    print("\n" + "="*60)
                    print(report)
                    print("="*60 + "\n")

                    # Could trigger Claude here or save to file
                    with open(".claude/pending_work.md", "w") as f:
                        f.write(report)
                else:
                    print("[OK] No new items")

                time.sleep(CHECK_INTERVAL)

            except KeyboardInterrupt:
                print("\n[STOP] Stopping monitor")
                break
            except Exception as e:
                print(f"[ERROR] Error: {e}")
                time.sleep(CHECK_INTERVAL)


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Monitor GitHub for Claude-actionable items')
    parser.add_argument('--once', action='store_true', help='Run once instead of continuous')
    parser.add_argument('--reset', action='store_true', help='Reset processed items state')

    args = parser.parse_args()

    monitor = GitHubMonitor()

    if args.reset:
        monitor.state = {
            "last_check": None,
            "processed_issues": [],
            "processed_prs": [],
            "processed_comments": []
        }
        monitor.save_state()
        print("[OK] State reset")
        return

    if args.once:
        report = monitor.run_check()
        print(report)
    else:
        monitor.run_continuous()


if __name__ == '__main__':
    main()