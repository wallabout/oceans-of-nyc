"""Response message templates for SMS conversations."""


def welcome_with_image(contributor_name: str = None):
    """Message when user sends first image with GPS."""
    if contributor_name:
        return f"Nice spot, {contributor_name}! What's the plate number?"
    return "Great photo! What's the license plate number?"


def welcome_with_image_no_gps():
    """Message when user sends first image without GPS."""
    return "Great photo! Where did you see this vehicle? (Send a street address or neighborhood in NYC)"


def request_location():
    """Prompt user for location when missing."""
    return "Where did you see this vehicle? (Send a street address or neighborhood in NYC)"


def request_plate():
    """Prompt user for license plate."""
    return "Please send the license plate number."


def plate_not_found(plate: str, suggestions: list[str] = None):
    """Message when plate is not in TLC database."""
    msg = f"Plate {plate} not found in the NYC TLC database."

    if suggestions:
        msg += "\n\nDid you mean one of these?\n"
        for i, suggestion in enumerate(suggestions[:5], 1):
            msg += f"{i}. {suggestion}\n"
        msg += "\nReply with the number or send the correct plate."
    else:
        msg += " Please double-check and send the correct plate number."

    return msg


def sighting_confirmed(
    plate: str, vehicle_sighting_num: int, total_sightings: int, contributor_sighting_num: int
):
    """Confirmation that sighting was validated and saved."""
    msg = "License plate validated, and sighting logged! This is"
    msg += f"\n- the {_ordinal(vehicle_sighting_num)} sighting of this vehicle"
    msg += f"\n- the {_ordinal(total_sightings)} Ocean sighting overall"
    msg += f"\n- your {_ordinal(contributor_sighting_num)} contribution. Thanks!!"

    return msg


def _ordinal(n: int) -> str:
    """Convert number to ordinal string (1st, 2nd, 3rd, etc.)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def sighting_cancelled():
    """Message when user cancels."""
    return "Sighting cancelled. Send a new photo anytime!"


def invalid_response():
    """Message for unexpected input."""
    return "Sorry, I didn't understand. Reply YES to confirm or CANCEL to abort."


def error_no_gps():
    """Message when photo has no GPS data."""
    return "This photo doesn't have location data. Please make sure location services are enabled when taking the photo, then send a new one."


def error_general():
    """Generic error message."""
    return "Sorry, something went wrong. Please try again or contact support."


def help_message():
    """Help text."""
    return """Fisker Ocean Sightings Bot

Send a photo of a Fisker Ocean to log a sighting. I'll extract the location and ask you for the license plate.

Commands:
- Send a photo to start
- Reply CANCEL to abort
- Reply HELP for this message"""
