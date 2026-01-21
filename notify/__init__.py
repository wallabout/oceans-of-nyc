"""Notification utilities for Oceans of NYC."""

from notify.email import send_admin_email
from notify.sms import send_admin_notification

__all__ = ["send_admin_email", "send_admin_notification"]
