"""Email notification utilities using Resend."""

import os

import resend


def send_admin_email(subject: str, message: str, admin_email: str | None = None) -> bool:
    """
    Send an email notification to the admin.

    Args:
        subject: The email subject line
        message: The message body (plain text)
        admin_email: Optional override for admin email address

    Returns:
        True if email was sent successfully, False otherwise
    """
    try:
        # Get Resend API key from environment
        api_key = os.getenv("RESEND_API_KEY")
        if not api_key:
            print("Missing RESEND_API_KEY - skipping email notification")
            return False

        resend.api_key = api_key

        # Get admin email from environment or parameter
        to_email = admin_email or os.getenv("ADMIN_EMAIL")
        if not to_email:
            print("Missing ADMIN_EMAIL - skipping email notification")
            return False

        # Send email via Resend
        params: resend.Emails.SendParams = {
            "from": "Oceans of NYC <oceansofnyc@notifications.wallabout.studio>",
            "to": [to_email],
            "subject": subject,
            "text": message,
        }

        resend.Emails.send(params)

        print(f"Sent email to {to_email}: {subject}")
        return True

    except Exception as e:
        print(f"Error sending email: {e}")
        return False
