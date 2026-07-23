"""Email notification utilities using Resend."""

import os

import resend


def _ordinal(n: int) -> str:
    """Convert number to ordinal string (1st, 2nd, 3rd, etc.)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


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


def send_submission_notification(
    contributor_name: str,
    plate: str,
    borough: str | None,
    vehicle_sighting_num: int,
    total_sightings: int,
    contributor_sighting_num: int,
    image_url: str | None = None,
    new_badges: list[dict] | None = None,
    admin_email: str | None = None,
    contributor_vehicle_sighting_num: int | None = None,
) -> bool:
    """
    Send a detailed submission notification to the admin.

    Args:
        contributor_name: Display name or phone number of the contributor
        plate: The license plate number
        borough: NYC borough (or None if unknown)
        vehicle_sighting_num: Number of times this vehicle has been sighted
        total_sightings: Total sightings across all vehicles
        contributor_sighting_num: Number of sightings by this contributor
        image_url: Optional URL to the web-accessible image
        new_badges: Optional list of newly earned badge dicts
        admin_email: Optional override for admin email address
        contributor_vehicle_sighting_num: How many times this contributor has sighted this
            specific vehicle (only shown when greater than 1)

    Returns:
        True if email was sent successfully, False otherwise
    """
    # Build the email message
    subject = f"New submission: {plate} from {contributor_name}"

    # Submission data section
    message = "=== SUBMISSION DATA ===\n"
    message += f"Contributor: {contributor_name}\n"
    message += f"Plate Number: {plate}\n"
    message += f"Borough: {borough or 'Unknown'}\n"

    # Confirmation stats section
    message += "\n=== SIGHTING STATS ===\n"
    message += "This is:\n"
    message += f"  • the {_ordinal(vehicle_sighting_num)} sighting of this vehicle\n"
    message += f"  • the {_ordinal(total_sightings)} Ocean sighting overall\n"
    if contributor_vehicle_sighting_num and contributor_vehicle_sighting_num > 1:
        message += (
            f"  • their {_ordinal(contributor_vehicle_sighting_num)} time spotting this Ocean\n"
        )
    message += f"  • their {_ordinal(contributor_sighting_num)} contribution\n"

    # Badges section (if any earned)
    if new_badges:
        message += "\n=== NEW BADGES EARNED ===\n"
        for badge in new_badges:
            message += f"  🏆 {badge['display_name']}\n"
            message += f"     {badge['description']}\n"

    # Image URL section (if available)
    if image_url:
        message += f"\n=== IMAGE ===\n{image_url}\n"

    return send_admin_email(subject=subject, message=message, admin_email=admin_email)
