"""Twilio SMS/MMS webhook handler for Modal."""

import os
from urllib.parse import parse_qs

import requests


def parse_twilio_request(body: bytes) -> dict:
    """Parse incoming Twilio webhook request body."""
    parsed = parse_qs(body.decode("utf-8"))
    # parse_qs returns lists, extract single values
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def download_media(media_url: str, auth: tuple) -> bytes | None:
    """
    Download media from Twilio.

    Args:
        media_url: Twilio media URL
        auth: Tuple of (account_sid, auth_token)

    Returns:
        Media bytes or None if download fails
    """
    try:
        response = requests.get(media_url, auth=auth, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"Error downloading media: {e}")
        return None


def create_twiml_response(message: str) -> str:
    """Create a TwiML response to send an SMS reply."""
    # Escape XML special characters
    escaped = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{escaped}</Message>
</Response>"""


def handle_incoming_sms(
    from_number: str,
    body: str,
    num_media: int = 0,
    media_urls: list[str] = None,
    media_types: list[str] = None,
    volume_path: str = "/data",
    channel_type: str = "sms",
) -> str:
    """
    Handle an incoming SMS/MMS message with conversation flow.

    Flow:
    1. User sends photo → Extract GPS, save to volume, ask for plate
    2. User sends plate → Validate against TLC, ask for confirmation
    3. User confirms → Save sighting to database

    Args:
        from_number: Sender's phone number
        body: Text content of the message
        num_media: Number of media attachments
        media_urls: List of media URLs
        media_types: List of media content types
        volume_path: Path to Modal volume for image storage

    Returns:
        TwiML response string
    """
    from datetime import datetime

    from chat import messages
    from chat.session import ChatSession
    from database import SightingsDatabase
    from geolocate import extract_gps_from_exif, extract_timestamp_from_exif
    from validate import get_potential_matches, validate_plate

    print(f"📱 Incoming message from {from_number}")
    print(f"   Channel: {channel_type.upper()}")
    print(f"   Body: {body}")
    print(f"   Media count: {num_media}")

    # Handle HELP and CANCEL commands
    body_upper = body.strip().upper() if body else ""
    if body_upper == "HELP":
        return create_twiml_response(messages.help_message())
    if body_upper == "CANCEL":
        session = ChatSession(from_number)
        session.get()
        session.reset()
        return create_twiml_response(messages.sighting_cancelled())

    # Get or create session
    session = ChatSession(from_number)
    session_data = session.get()
    state = session_data.get("state", ChatSession.IDLE)

    # Send notification for new chat sessions (non-admin contributors only)
    if session.is_new_session():
        from database import SightingsDatabase

        db = SightingsDatabase()
        contributor = db.get_contributor(phone_number=from_number)

        # Only notify if contributor exists and is not admin (id != 1)
        if contributor and contributor.get("id") != 1:
            from notify import send_admin_notification

            display_name = contributor.get("preferred_name") or from_number
            send_admin_notification(f"New chat session from {display_name}")

    try:
        # State: IDLE - expecting photo
        if state == ChatSession.IDLE:
            if num_media > 0 and media_urls:
                # Download and process first image
                media_url = media_urls[0]
                twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID")
                twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN")

                print(f"📥 Downloading image from {media_url}")
                print(f"   Image sent via: {channel_type.upper()}")
                image_data = download_media(media_url, (twilio_account_sid, twilio_auth_token))

                if not image_data:
                    return create_twiml_response(messages.error_general())

                # Save image to volume
                images_path = f"{volume_path}/images"
                os.makedirs(images_path, exist_ok=True)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                phone_suffix = from_number[-4:]
                filename = f"sighting_{timestamp}_{phone_suffix}.jpg"
                image_path = f"{images_path}/{filename}"

                with open(image_path, "wb") as f:
                    f.write(image_data)

                print(f"💾 Saved image to {image_path}")

                # Extract GPS coordinates and timestamp
                try:
                    from geolocate.exif import extract_image_metadata

                    metadata = extract_image_metadata(image_path)
                    print(f"🔍 Image metadata: {metadata}")

                    gps_coords = extract_gps_from_exif(image_path)
                    timestamp_result = extract_timestamp_from_exif(image_path)

                    # timestamp is returned as ISO string, convert to datetime
                    try:
                        sighting_time = datetime.fromisoformat(timestamp_result)
                    except (ValueError, TypeError):
                        sighting_time = datetime.now()

                    # Extract GPS if available
                    lat, lon = None, None
                    if gps_coords is not None:
                        lat, lon = gps_coords
                        print(f"📍 GPS: {lat}, {lon}")
                    else:
                        print("⚠️ No GPS data in image - will ask for location after plate")

                    # Always proceed to AWAITING_PLATE state
                    # Store GPS if found (None if not - we'll ask for location later)
                    session.update(
                        state=ChatSession.AWAITING_PLATE,
                        pending_image_path=image_path,
                        pending_latitude=lat,
                        pending_longitude=lon,
                        pending_timestamp=sighting_time,
                    )

                    # Get contributor name for personalized greeting
                    db = SightingsDatabase()
                    contributor = db.get_contributor(phone_number=from_number)
                    contributor_name = contributor.get("preferred_name") if contributor else None

                    # Always greet and ask for plate first
                    return create_twiml_response(messages.welcome_with_image(contributor_name))

                except Exception as e:
                    print(f"❌ Error extracting metadata: {e}")
                    import traceback

                    traceback.print_exc()
                    os.remove(image_path)  # Clean up
                    return create_twiml_response(messages.error_general())
            else:
                return create_twiml_response(messages.help_message())

        # State: AWAITING_LOCATION - expecting location text (plate already validated)
        elif state == ChatSession.AWAITING_LOCATION:
            if not body:
                return create_twiml_response(messages.request_location())

            location_text = body.strip()
            print(f"📍 User provided location: {location_text}")

            # Try to geocode the location
            from geolocate.geocoding import geocode_address

            coords = geocode_address(location_text)

            if coords is None:
                # Geocoding failed, ask again
                return create_twiml_response(
                    "Sorry, I couldn't find that location. Please try a street address or neighborhood in NYC (e.g., 'Astoria' or '123 Main St, Brooklyn')"
                )

            lat, lon = coords
            print(f"📍 Geocoded to: {lat}, {lon}")

            # We have everything now - save the sighting
            db = SightingsDatabase()
            contributor_id = db.get_or_create_contributor(phone_number=from_number)

            plate = session_data["pending_plate"]
            result = db.add_sighting(
                license_plate=plate,
                timestamp=session_data["pending_timestamp"],
                latitude=lat,
                longitude=lon,
                image_path=session_data["pending_image_path"],
                contributor_id=contributor_id,
            )

            if result is None:
                # Image already exists in database (exact duplicate)
                print(f"⚠️ Duplicate image detected for plate {plate}")
                session.reset()
                return create_twiml_response(
                    "You've already submitted this exact photo. Send a new photo to log another sighting!"
                )

            sighting_id = result["id"]
            print(f"✅ Sighting saved for plate {plate} (ID: {sighting_id})")

            # Warn if similar image detected
            if result["duplicate_type"] == "similar":
                dup_info = result["duplicate_info"]
                print(
                    f"⚠️ Similar image detected (distance: {dup_info['distance']}), but allowing submission"
                )

            # Send notification for successful submission (non-admin contributors only)
            if contributor_id != 1:
                from notify import send_admin_notification

                contributor = db.get_contributor(contributor_id=contributor_id)
                display_name = contributor.get("preferred_name") or from_number
                send_admin_notification(f"Successful submission from {display_name}")

            # Get stats for the confirmation message
            vehicle_sighting_num = db.get_sighting_count(plate)
            total_sightings = db.get_total_sighting_count()
            contributor_sighting_num = db.get_contributor_sighting_count(contributor_id)

            # Check if contributor has a preferred name
            contributor = db.get_contributor(contributor_id=contributor_id)
            if not contributor["preferred_name"]:
                # Ask if they want to set a name
                session.update(state=ChatSession.AWAITING_NAME)
                msg = messages.sighting_confirmed(
                    plate, vehicle_sighting_num, total_sightings, contributor_sighting_num
                )
                msg += "\n\nWould you like to set a name for future posts? Reply with your name, or SKIP to remain anonymous."
                return create_twiml_response(msg)

            # Reset session
            session.reset()

            return create_twiml_response(
                messages.sighting_confirmed(
                    plate, vehicle_sighting_num, total_sightings, contributor_sighting_num
                )
            )

        # State: AWAITING_PLATE - expecting plate number
        elif state == ChatSession.AWAITING_PLATE:
            if not body:
                return create_twiml_response(messages.request_plate())

            plate = body.strip().upper()

            # Normalize plate format: if user sends just 6 digits, add T prefix and C suffix
            # Valid format is T######C (e.g., T123456C)
            if plate.isdigit() and len(plate) == 6:
                plate = f"T{plate}C"
                print(f"📝 Normalized plate format: {plate}")

            # Validate plate
            is_valid, vehicle = validate_plate(plate)

            if is_valid and vehicle:
                # Plate is valid! Check if we have GPS or need to ask for location
                db = SightingsDatabase()

                # Check if GPS exists in session
                has_gps = (
                    session_data["pending_latitude"] is not None
                    and session_data["pending_longitude"] is not None
                )

                if not has_gps:
                    # No GPS - save plate and ask for location
                    print(f"✓ Plate {plate} validated, asking for location")
                    session.update(
                        state=ChatSession.AWAITING_LOCATION,
                        pending_plate=plate,
                    )
                    return create_twiml_response(messages.request_location_after_plate())

                # GPS exists - save sighting immediately
                # Get or create contributor
                contributor_id = db.get_or_create_contributor(phone_number=from_number)

                result = db.add_sighting(
                    license_plate=plate,
                    timestamp=session_data["pending_timestamp"],
                    latitude=session_data["pending_latitude"],
                    longitude=session_data["pending_longitude"],
                    image_path=session_data["pending_image_path"],
                    contributor_id=contributor_id,
                )

                if result is None:
                    # Image already exists in database (exact duplicate)
                    print(f"⚠️ Duplicate image detected for plate {plate}")
                    session.reset()
                    return create_twiml_response(
                        "You've already submitted this exact photo. Send a new photo to log another sighting!"
                    )

                sighting_id = result["id"]
                print(f"✅ Sighting saved for plate {plate} (ID: {sighting_id})")

                # Warn if similar image detected
                if result["duplicate_type"] == "similar":
                    dup_info = result["duplicate_info"]
                    print(
                        f"⚠️ Similar image detected (distance: {dup_info['distance']}), but allowing submission"
                    )

                # Send notification for successful submission (non-admin contributors only)
                if contributor_id != 1:
                    from notify import send_admin_notification

                    contributor = db.get_contributor(contributor_id=contributor_id)
                    display_name = contributor.get("preferred_name") or from_number
                    send_admin_notification(f"Successful submission from {display_name}")

                # Get stats for the confirmation message
                vehicle_sighting_num = db.get_sighting_count(plate)
                total_sightings = db.get_total_sighting_count()
                contributor_sighting_num = db.get_contributor_sighting_count(contributor_id)

                # Check if contributor has a preferred name
                contributor = db.get_contributor(contributor_id=contributor_id)
                if not contributor["preferred_name"]:
                    # Ask if they want to set a name
                    session.update(state=ChatSession.AWAITING_NAME)
                    msg = messages.sighting_confirmed(
                        plate, vehicle_sighting_num, total_sightings, contributor_sighting_num
                    )
                    msg += "\n\nWould you like to set a name for future posts? Reply with your name, or SKIP to remain anonymous."
                    return create_twiml_response(msg)

                # Reset session
                session.reset()

                return create_twiml_response(
                    messages.sighting_confirmed(
                        plate, vehicle_sighting_num, total_sightings, contributor_sighting_num
                    )
                )

            # Try to find similar plates
            suggestions = get_potential_matches(plate, max_results=5)
            return create_twiml_response(messages.plate_not_found(plate, suggestions))

        # State: AWAITING_NAME - user can set their preferred name
        elif state == ChatSession.AWAITING_NAME:
            if not body:
                session.reset()
                return create_twiml_response(
                    "No problem, you'll remain anonymous. Send a new photo anytime!"
                )

            if body.strip().upper() == "SKIP":
                session.reset()
                return create_twiml_response(
                    "No problem, you'll remain anonymous. Send a new photo anytime!"
                )

            # Set the preferred name
            preferred_name = body.strip()
            if len(preferred_name) > 50:
                return create_twiml_response(
                    "Name is too long (max 50 characters). Please try again or reply SKIP."
                )

            db = SightingsDatabase()
            contributor = db.get_contributor(phone_number=from_number)

            if contributor:
                db.update_contributor_name(contributor["id"], preferred_name)
                session.reset()
                return create_twiml_response(
                    f"Great! Future posts will credit you as '{preferred_name}'. Send a new photo anytime!"
                )
            session.reset()
            return create_twiml_response("Error setting name. Send a new photo anytime!")

        else:
            # Unknown state, reset
            session.reset()
            return create_twiml_response(messages.help_message())

    except Exception as e:
        print(f"❌ Error processing message: {e}")
        import traceback

        traceback.print_exc()
        session.reset()
        return create_twiml_response(messages.error_general())
