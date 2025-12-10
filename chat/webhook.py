"""Twilio SMS/MMS webhook handler for Modal."""

import os
from urllib.parse import parse_qs
from typing import Optional
import requests


def parse_twilio_request(body: bytes) -> dict:
    """Parse incoming Twilio webhook request body."""
    parsed = parse_qs(body.decode('utf-8'))
    # parse_qs returns lists, extract single values
    return {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}


def download_media(media_url: str, auth: tuple) -> Optional[bytes]:
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
    escaped = (message
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
        .replace("'", '&apos;'))

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
    from chat.session import ChatSession
    from chat import messages
    from validate import validate_plate, get_potential_matches
    from geolocate import extract_gps_from_exif, extract_timestamp_from_exif
    from database import SightingsDatabase
    from datetime import datetime

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

                    if gps_coords is None:
                        print("⚠️ No GPS data in image - asking user for location")
                        # Save image and ask for location
                        session.update(
                            state=ChatSession.AWAITING_LOCATION,
                            pending_image_path=image_path,
                            pending_timestamp=sighting_time,
                        )
                        return create_twiml_response(messages.welcome_with_image_no_gps())

                    # GPS data found
                    lat, lon = gps_coords
                    print(f"📍 GPS: {lat}, {lon}")

                    # Update session with GPS data, proceed to plate
                    session.update(
                        state=ChatSession.AWAITING_PLATE,
                        pending_image_path=image_path,
                        pending_latitude=lat,
                        pending_longitude=lon,
                        pending_timestamp=sighting_time,
                    )

                    return create_twiml_response(messages.welcome_with_image())

                except Exception as e:
                    print(f"❌ Error extracting metadata: {e}")
                    import traceback
                    traceback.print_exc()
                    os.remove(image_path)  # Clean up
                    return create_twiml_response(messages.error_general())
            else:
                return create_twiml_response(messages.help_message())

        # State: AWAITING_LOCATION - expecting location text
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

            # Update session with geocoded location
            session.update(
                state=ChatSession.AWAITING_PLATE,
                pending_latitude=lat,
                pending_longitude=lon,
            )

            return create_twiml_response(messages.request_plate())

        # State: AWAITING_PLATE - expecting plate number
        elif state == ChatSession.AWAITING_PLATE:
            if not body:
                return create_twiml_response(messages.request_plate())

            plate = body.strip().upper()

            # Validate plate
            is_valid, vehicle = validate_plate(plate)

            if is_valid and vehicle:
                # Get sighting count for this plate
                db = SightingsDatabase()
                count = db.get_posted_sighting_count(plate)

                # Update session with plate
                session.update(
                    state=ChatSession.AWAITING_CONFIRMATION,
                    pending_plate=plate,
                )

                return create_twiml_response(messages.confirm_sighting(plate, vehicle, count))
            else:
                # Try to find similar plates
                suggestions = get_potential_matches(plate, max_results=5)
                return create_twiml_response(messages.plate_not_found(plate, suggestions))

        # State: AWAITING_CONFIRMATION - expecting YES or plate number
        elif state == ChatSession.AWAITING_CONFIRMATION:
            if not body:
                return create_twiml_response(messages.invalid_response())

            response_upper = body.strip().upper()

            if response_upper == "YES":
                # Save sighting to database
                db = SightingsDatabase()
                db.add_sighting(
                    license_plate=session_data["pending_plate"],
                    timestamp=session_data["pending_timestamp"],
                    latitude=session_data["pending_latitude"],
                    longitude=session_data["pending_longitude"],
                    image_path=session_data["pending_image_path"],
                    contributed_by=from_number,
                )

                print(f"✅ Sighting saved for plate {session_data['pending_plate']}")

                # Reset session
                session.reset()

                return create_twiml_response(messages.sighting_saved())
            else:
                # Assume they're sending a corrected plate number
                plate = body.strip().upper()
                is_valid, vehicle = validate_plate(plate)

                if is_valid and vehicle:
                    db = SightingsDatabase()
                    count = db.get_posted_sighting_count(plate)

                    session.update(pending_plate=plate)

                    return create_twiml_response(messages.confirm_sighting(plate, vehicle, count))
                else:
                    suggestions = get_potential_matches(plate, max_results=5)
                    return create_twiml_response(messages.plate_not_found(plate, suggestions))

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
