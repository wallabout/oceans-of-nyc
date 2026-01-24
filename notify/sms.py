"""SMS notification utilities using Twilio."""

import os

from twilio.rest import Client


def send_sms(to_number: str, message: str) -> bool:
    """
    Send an SMS message to a phone number via Twilio API.

    Args:
        to_number: The recipient's phone number (E.164 format)
        message: The message to send

    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_PHONE_NUMBER")

        if not all([account_sid, auth_token, from_number]):
            print("⚠️ Missing Twilio credentials - cannot send SMS")
            return False

        client = Client(account_sid, auth_token)
        client.messages.create(body=message, from_=from_number, to=to_number)

        print(f"📤 Sent SMS to {to_number}: {message[:50]}...")
        return True

    except Exception as e:
        print(f"❌ Error sending SMS: {e}")
        return False


def send_admin_notification(message: str, admin_contributor_id: int = 1) -> bool:
    """
    Send an SMS notification to the admin user (contributor id=1).

    Args:
        message: The message to send
        admin_contributor_id: The contributor ID to send to (default: 1)

    Returns:
        True if message was sent successfully, False otherwise
    """
    try:
        # Get Twilio credentials from environment
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        from_number = os.getenv("TWILIO_PHONE_NUMBER")

        if not all([account_sid, auth_token, from_number]):
            print("⚠️ Missing Twilio credentials - skipping notification")
            return False

        # Get admin phone number from database
        from database import SightingsDatabase

        db = SightingsDatabase()
        admin = db.get_contributor(contributor_id=admin_contributor_id)

        if not admin or not admin.get("phone_number"):
            print(f"⚠️ Admin contributor {admin_contributor_id} not found or has no phone number")
            return False

        to_number = admin["phone_number"]

        # Send SMS via Twilio
        client = Client(account_sid, auth_token)
        client.messages.create(body=message, from_=from_number, to=to_number)

        print(f"✅ Sent notification to {to_number}: {message}")
        return True

    except Exception as e:
        print(f"❌ Error sending notification: {e}")
        return False
