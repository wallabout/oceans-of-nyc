"""Notification utilities for Oceans of NYC."""

from notify.email import send_admin_email, send_submission_notification
from notify.sms import send_admin_notification

__all__ = ["send_admin_email", "send_admin_notification", "send_submission_notification"]
