#!/usr/bin/env python3
"""
Email notification module for Duo cleanup operations
Sends summary emails after cleanup script completes
"""

import os
import smtplib
import json
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Dict, List, Optional
import socket


class EmailNotifier:
    """Handle email notifications for Duo cleanup operations"""

    def __init__(
        self,
        smtp_server: str = None,
        smtp_port: int = None,
        smtp_user: str = None,
        smtp_password: str = None,
        use_tls: bool = True,
        from_address: str = None
    ):
        """
        Initialize email notifier

        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port (587 for TLS, 465 for SSL)
            smtp_user: SMTP username (often same as from_address)
            smtp_password: SMTP password
            use_tls: Use TLS encryption (True) or SSL (False)
            from_address: Sender email address
        """
        # Try to load from environment variables if not provided
        # EUSD mail server defaults: mail.eusd.org:25 with no auth
        self.smtp_server = smtp_server or os.getenv('SMTP_SERVER', 'mail.eusd.org')
        self.smtp_port = smtp_port or int(os.getenv('SMTP_PORT', '25'))
        self.smtp_user = smtp_user or os.getenv('SMTP_USER')
        self.smtp_password = smtp_password or os.getenv('SMTP_PASSWORD')
        # Port 25 typically doesn't use TLS
        self.use_tls = use_tls if smtp_port != 25 else False
        self.from_address = from_address or os.getenv('EMAIL_FROM', 'automation@eusd.org')

    def create_summary_html(self, results: Dict) -> str:
        """Create HTML formatted summary of cleanup results"""

        # Calculate statistics
        total_processed = results.get('total_processed', 0)
        deleted = results.get('deleted', 0)
        failed = results.get('failed', 0)
        skipped = results.get('skipped', 0)
        duration = results.get('duration', 'unknown')

        # Create HTML
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h2 {{ color: #333; }}
                .summary {{
                    background-color: #f0f0f0;
                    padding: 15px;
                    border-radius: 5px;
                    margin: 20px 0;
                }}
                .success {{ color: #28a745; font-weight: bold; }}
                .error {{ color: #dc3545; font-weight: bold; }}
                .warning {{ color: #ffc107; font-weight: bold; }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #4CAF50;
                    color: white;
                }}
                tr:nth-child(even) {{
                    background-color: #f2f2f2;
                }}
                .footer {{
                    margin-top: 30px;
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <h2>Duo Student Cleanup Report</h2>

            <div class="summary">
                <h3>Summary</h3>
                <p><strong>Execution Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                <p><strong>Duration:</strong> {duration}</p>
                <p><strong>Total Accounts Processed:</strong> {total_processed}</p>
            </div>

            <h3>Results</h3>
            <table>
                <tr>
                    <th>Action</th>
                    <th>Count</th>
                    <th>Status</th>
                </tr>
                <tr>
                    <td>Successfully Deleted</td>
                    <td>{deleted}</td>
                    <td class="success">✓</td>
                </tr>
                <tr>
                    <td>Failed to Delete</td>
                    <td>{failed}</td>
                    <td class="{'error' if failed > 0 else 'success'}">{'✗' if failed > 0 else '✓'}</td>
                </tr>
                <tr>
                    <td>Skipped (Directory Managed)</td>
                    <td>{skipped}</td>
                    <td class="warning">⚠</td>
                </tr>
            </table>
        """

        # Add errors section if there were failures
        if failed > 0 and 'error_details' in results:
            html += """
            <h3 class="error">Errors Encountered</h3>
            <ul>
            """
            for error in results['error_details'][:10]:  # Limit to 10 errors
                html += f"<li>{error}</li>"
            if len(results['error_details']) > 10:
                html += f"<li>... and {len(results['error_details']) - 10} more</li>"
            html += "</ul>"

        # Add footer
        html += f"""
            <div class="footer">
                <p>Report generated by Duo API Interaction Tool</p>
                <p>Server: {socket.gethostname()}</p>
                <p>For more details, see the attached CSV file or check the logs directory.</p>
            </div>
        </body>
        </html>
        """

        return html

    def send_notification(
        self,
        to_addresses: List[str],
        subject: str,
        results: Dict,
        attachments: List[str] = None,
        send_on_success: bool = True,
        send_on_error: bool = True
    ) -> bool:
        """
        Send email notification with results

        Args:
            to_addresses: List of recipient email addresses
            subject: Email subject line
            results: Dictionary containing cleanup results
            attachments: List of file paths to attach
            send_on_success: Send email even if all operations succeeded
            send_on_error: Send email if any errors occurred

        Returns:
            True if email sent successfully, False otherwise
        """

        # Check if we should send based on results
        has_errors = results.get('failed', 0) > 0

        if has_errors and not send_on_error:
            print("Skipping email (errors occurred but send_on_error=False)")
            return False

        if not has_errors and not send_on_success:
            print("Skipping email (no errors but send_on_success=False)")
            return False

        # Validate configuration
        if not all([self.smtp_server, self.smtp_port, self.from_address]):
            print("Email configuration incomplete. Set SMTP_SERVER, SMTP_PORT, EMAIL_FROM")
            return False

        if not to_addresses:
            print("No recipient addresses provided")
            return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_address
            msg['To'] = ', '.join(to_addresses)

            # Add timestamp to subject if errors
            if has_errors:
                msg['Subject'] = f"[ERRORS] {subject}"

            # Create text and HTML parts
            text_part = MIMEText(self._create_text_summary(results), 'plain')
            html_part = MIMEText(self.create_summary_html(results), 'html')

            msg.attach(text_part)
            msg.attach(html_part)

            # Add attachments
            if attachments:
                for filepath in attachments:
                    if Path(filepath).exists():
                        self._attach_file(msg, filepath)

            # Send email
            self._send_email(msg, to_addresses)

            print(f"Email notification sent to: {', '.join(to_addresses)}")
            return True

        except Exception as e:
            print(f"Failed to send email: {e}")
            return False

    def _create_text_summary(self, results: Dict) -> str:
        """Create plain text summary for email"""
        text = f"""
Duo Student Cleanup Report
{'='*40}

Execution Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Duration: {results.get('duration', 'unknown')}

Results:
- Total Processed: {results.get('total_processed', 0)}
- Successfully Deleted: {results.get('deleted', 0)}
- Failed: {results.get('failed', 0)}
- Skipped (Directory Managed): {results.get('skipped', 0)}

"""
        if results.get('failed', 0) > 0:
            text += "Errors occurred during processing. Check logs for details.\n"

        text += f"\nServer: {socket.gethostname()}"

        return text

    def _attach_file(self, msg: MIMEMultipart, filepath: str):
        """Attach a file to the email"""
        try:
            with open(filepath, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={Path(filepath).name}'
                )
                msg.attach(part)
        except Exception as e:
            print(f"Could not attach file {filepath}: {e}")

    def _send_email(self, msg: MIMEMultipart, to_addresses: List[str]):
        """Send the email via SMTP"""
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            # Only use TLS if not on port 25 (EUSD mail server doesn't use TLS)
            if self.use_tls and self.smtp_port != 25:
                server.starttls()

            # Login if credentials provided (EUSD doesn't require auth)
            if self.smtp_user and self.smtp_password:
                server.login(self.smtp_user, self.smtp_password)

            server.send_message(msg)


def load_config(config_file: str = "config.yaml") -> Dict:
    """Load email configuration from YAML file"""
    try:
        import yaml
        with open(config_file) as f:
            config = yaml.safe_load(f)
        return config.get('notifications', {}).get('email', {})
    except:
        return {}


# Example usage
if __name__ == "__main__":
    # Test email
    notifier = EmailNotifier()

    test_results = {
        'total_processed': 80,
        'deleted': 75,
        'failed': 2,
        'skipped': 3,
        'duration': '2 minutes 15 seconds',
        'error_details': [
            'Failed to delete user 123456: Permission denied',
            'Failed to delete user 789012: User not found'
        ]
    }

    # Send test email
    success = notifier.send_notification(
        to_addresses=[os.getenv('EMAIL_TO', 'server_engineer@eusd.org')],
        subject='Duo Cleanup Report - Test',
        results=test_results,
        attachments=['logs/duo_cleanup_results_20250922_144738.csv'] if Path('logs/duo_cleanup_results_20250922_144738.csv').exists() else None
    )

    if success:
        print("Test email sent successfully!")
    else:
        print("Failed to send test email. Check configuration.")