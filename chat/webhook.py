"""Twilio SMS/MMS webhook handler for Modal."""

import os
from urllib.parse import parse_qs

import requests

from utils.sighting_confirmation import get_confirmation_data


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


def evaluate_and_save_badges(db, contributor_id: int) -> list[dict]:
    """
    Evaluate badges for a contributor and save any newly earned ones.

    This is a convenience wrapper around the shared utility function.

    Args:
        db: SightingsDatabase instance
        contributor_id: The contributor's ID

    Returns:
        List of badge dicts with name, display_name, description, emoji for newly earned badges
    """
    from utils.sighting_confirmation import evaluate_and_save_badges as _evaluate

    return _evaluate(db, contributor_id)


def spawn_background_processing(
    image_filename: str,
    plate: str,
    contributor_id: int,
    from_number: str,
    sighting_id: int | None = None,
):
    """
    Spawn background processing for a saved sighting.

    This spawns a Modal function to handle slow operations asynchronously,
    allowing the webhook to return the TwiML response immediately.

    Background tasks include:
    - Uploading web-optimized image to R2
    - Regenerating vehicles.json
    - Checking if batch post should be triggered
    - Sending admin notification

    Args:
        image_filename: The filename of the saved image
        plate: The validated license plate
        contributor_id: The contributor's database ID
        from_number: The contributor's phone number
        sighting_id: The sighting's database ID (optional, for fetching details)
    """
    try:
        from modal_app import process_sighting_background, volume

        # Commit volume changes before spawning so background task can see the files
        volume.commit()
        print("✓ Volume committed")

        process_sighting_background.spawn(
            image_filename=image_filename,
            plate=plate,
            contributor_id=contributor_id,
            from_number=from_number,
            sighting_id=sighting_id,
        )
        print("✓ Background processing spawned")
    except Exception as e:
        # Don't fail the webhook if background spawn fails
        print(f"⚠️ Failed to spawn background processing: {e}")


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
            from notify import send_admin_email

            display_name = contributor.get("preferred_name") or from_number
            send_admin_email(
                subject="New chat session",
                message=f"New chat session from {display_name}",
            )

    try:
        # Import extraction utilities
        from chat.extractors import extract_borough_from_text, extract_plate_from_text

        # State: IDLE - expecting photo (but can also extract plate/borough from text)
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

                # Process and save image (original + web version)
                from geolocate.exif import extract_image_timestamp_from_bytes
                from utils.image_processor import ImageProcessor

                processor = ImageProcessor(volume_path=volume_path)

                # Extract image timestamp from EXIF, fallback to now
                image_timestamp = extract_image_timestamp_from_bytes(image_data)
                if image_timestamp is None:
                    image_timestamp = datetime.now()

                # Use a temporary placeholder filename for now
                # Will be updated once we have the plate number
                temp_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                phone_suffix = from_number[-4:]
                temp_filename = f"pending_{temp_timestamp}_{phone_suffix}.jpg"

                # Process image: save original, create web version, upload to R2
                image_paths = processor.process_sighting_image(
                    image_data, temp_filename, upload_to_r2=False
                )

                # Use original path for hash calculation
                image_path = image_paths["original_path"]

                print(f"💾 Saved original: {image_path}")

                # Extract GPS coordinates and timestamp
                try:
                    from geolocate.exif import extract_image_metadata
                    from utils.image_hashing import check_exact_duplicate

                    metadata = extract_image_metadata(image_path)
                    print(f"🔍 Image metadata: {metadata}")

                    # Check for duplicate images BEFORE asking for plate
                    db = SightingsDatabase()
                    if metadata.get("image_hash_sha256"):
                        conn = db._get_connection()
                        duplicate = check_exact_duplicate(conn, metadata["image_hash_sha256"])
                        conn.close()

                        if duplicate:
                            print(f"⚠️ Duplicate image detected (sighting #{duplicate['id']})")
                            os.remove(image_path)  # Clean up the duplicate
                            session.reset()
                            return create_twiml_response(
                                "You've already submitted this exact photo. Send a new photo to log another sighting!"
                            )

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

                    # Try to extract plate and borough from the message body
                    extracted_plate = extract_plate_from_text(body) if body else None
                    extracted_borough = extract_borough_from_text(body) if body else None

                    if extracted_plate:
                        print(f"📝 Extracted plate from message: {extracted_plate}")
                    if extracted_borough:
                        print(f"📍 Extracted borough from message: {extracted_borough}")

                    # Validate plate if extracted
                    validated_plate = None
                    validated_vin = None
                    if extracted_plate:
                        from validate.tlc import validate_plate

                        is_valid, vehicle = validate_plate(extracted_plate)
                        if is_valid and vehicle:
                            validated_plate = extracted_plate
                            validated_vin = vehicle.get("vin") if vehicle else None
                            print(f"✓ Plate {validated_plate} validated (VIN: {validated_vin})")
                        else:
                            print(f"⚠️ Extracted plate {extracted_plate} not valid, will ask user")

                    # Update session with all available data
                    session.update(
                        state=ChatSession.AWAITING_PLATE,
                        pending_image_path=image_path,
                        pending_latitude=lat,
                        pending_longitude=lon,
                        pending_timestamp=sighting_time,
                        pending_plate=validated_plate,
                        pending_borough=extracted_borough,
                        pending_image_timestamp=image_timestamp,
                    )

                    # Determine what we're still missing and respond accordingly
                    has_plate = validated_plate is not None
                    has_location = lat is not None or extracted_borough is not None

                    # Get contributor name for personalized greeting
                    contributor = db.get_contributor(phone_number=from_number)
                    contributor_name = contributor.get("preferred_name") if contributor else None

                    # If we have everything, save immediately
                    if has_plate and has_location:
                        print("✓ All data collected, saving sighting")
                        contributor_id = db.get_or_create_contributor(phone_number=from_number)

                        # Generate unified filename and rename to final location
                        final_filename = processor.generate_filename(
                            validated_plate, image_timestamp
                        )
                        processor.rename_to_final(image_path, final_filename)

                        result = db.add_sighting(
                            license_plate=validated_plate,
                            timestamp=sighting_time,
                            latitude=lat,
                            longitude=lon,
                            contributor_id=contributor_id,
                            image_filename=final_filename,
                            borough=extracted_borough if not lat else None,
                            image_timestamp=image_timestamp,
                            vin=validated_vin,
                        )

                        if result is None:
                            print(f"⚠️ Duplicate image detected for plate {validated_plate}")
                            session.reset()
                            return create_twiml_response(
                                "You've already submitted this exact photo. Send a new photo to log another sighting!"
                            )

                        sighting_id = result["id"]
                        print(f"✅ Sighting saved for plate {validated_plate} (ID: {sighting_id})")

                        if result["duplicate_type"] == "similar":
                            dup_info = result["duplicate_info"]
                            print(
                                f"⚠️ Similar image detected (distance: {dup_info['distance']}), but allowing submission"
                            )

                        # Spawn background processing (R2 upload, web data gen, batch check, admin notification)
                        spawn_background_processing(
                            image_filename=final_filename,
                            plate=validated_plate,
                            contributor_id=contributor_id,
                            from_number=from_number,
                            sighting_id=sighting_id,
                        )

                        # Get confirmation data (stats + badges)
                        conf = get_confirmation_data(
                            db, validated_plate, contributor_id, validated_vin
                        )
                        vehicle_sighting_num = conf["vehicle_sighting_num"]
                        total_sightings = conf["total_sightings"]
                        contributor_sighting_num = conf["contributor_sighting_num"]
                        new_badges = conf["new_badges"]

                        contributor = db.get_contributor(contributor_id=contributor_id)
                        print(f"🔍 Contributor check: {contributor}")
                        if not contributor["preferred_name"]:
                            print("📝 Asking for preferred name")
                            session.update(state=ChatSession.AWAITING_NAME)
                            msg = messages.sighting_confirmed(
                                validated_plate,
                                vehicle_sighting_num,
                                total_sightings,
                                contributor_sighting_num,
                                new_badges,
                            )
                            msg += "\n\nWould you like to set a name for future posts? Reply with your name, or SKIP to remain anonymous."
                            return create_twiml_response(msg)

                        print("✅ Sending confirmation message")
                        session.reset()
                        confirmation_msg = messages.sighting_confirmed(
                            validated_plate,
                            vehicle_sighting_num,
                            total_sightings,
                            contributor_sighting_num,
                            new_badges,
                        )
                        print(f"📤 Confirmation message: {confirmation_msg}")
                        twiml_response = create_twiml_response(confirmation_msg)
                        print(f"📤 TwiML response length: {len(twiml_response)} bytes")
                        return twiml_response

                    # Otherwise, ask for what's missing (plate takes priority)
                    if not has_plate:
                        return create_twiml_response(messages.welcome_with_image(contributor_name))
                    # Has plate but no location
                    return create_twiml_response(messages.request_borough())

                except Exception as e:
                    print(f"❌ Error extracting metadata: {e}")
                    import traceback

                    traceback.print_exc()
                    os.remove(image_path)  # Clean up
                    return create_twiml_response(messages.error_general())
            else:
                return create_twiml_response(messages.help_message())

        # State: AWAITING_BOROUGH - expecting borough designation (plate already validated)
        elif state == ChatSession.AWAITING_BOROUGH:
            if not body:
                return create_twiml_response(messages.request_borough())

            # Try to extract borough from the message
            borough = extract_borough_from_text(body)

            if borough is None:
                # Invalid borough input, ask again
                return create_twiml_response(messages.invalid_borough())

            print(f"📍 Parsed borough: {borough}")

            # We have everything now - save the sighting
            from utils.image_processor import ImageProcessor

            db = SightingsDatabase()
            contributor_id = db.get_or_create_contributor(phone_number=from_number)

            plate = session_data["pending_plate"]

            # Re-validate plate to get VIN
            from validate.tlc import validate_plate

            _, vehicle_data = validate_plate(plate)
            vin = vehicle_data.get("vin") if vehicle_data else None

            image_timestamp = session_data.get("pending_image_timestamp")
            if image_timestamp is None:
                image_timestamp = datetime.now()

            # Generate unified filename and rename to final location
            processor = ImageProcessor(volume_path=volume_path)
            final_filename = processor.generate_filename(plate, image_timestamp)
            processor.rename_to_final(session_data["pending_image_path"], final_filename)

            result = db.add_sighting(
                license_plate=plate,
                timestamp=session_data["pending_timestamp"],
                latitude=None,  # No GPS data
                longitude=None,  # No GPS data
                contributor_id=contributor_id,
                image_filename=final_filename,
                borough=borough,
                image_timestamp=image_timestamp,
                vin=vin,
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

            # Spawn background processing (R2 upload, web data gen, batch check, admin notification)
            spawn_background_processing(
                image_filename=final_filename,
                plate=plate,
                contributor_id=contributor_id,
                from_number=from_number,
                sighting_id=sighting_id,
            )

            # Get confirmation data (stats + badges)
            conf = get_confirmation_data(db, plate, contributor_id, vin)
            vehicle_sighting_num = conf["vehicle_sighting_num"]
            total_sightings = conf["total_sightings"]
            contributor_sighting_num = conf["contributor_sighting_num"]
            new_badges = conf["new_badges"]

            # Check if contributor has a preferred name
            contributor = db.get_contributor(contributor_id=contributor_id)
            if not contributor["preferred_name"]:
                # Ask if they want to set a name
                session.update(state=ChatSession.AWAITING_NAME)
                msg = messages.sighting_confirmed(
                    plate,
                    vehicle_sighting_num,
                    total_sightings,
                    contributor_sighting_num,
                    new_badges,
                )
                msg += "\n\nWould you like to set a name for future posts? Reply with your name, or SKIP to remain anonymous."
                return create_twiml_response(msg)

            # Reset session
            session.reset()

            return create_twiml_response(
                messages.sighting_confirmed(
                    plate,
                    vehicle_sighting_num,
                    total_sightings,
                    contributor_sighting_num,
                    new_badges,
                )
            )

        # State: AWAITING_PLATE - expecting plate number (but can also extract borough)
        elif state == ChatSession.AWAITING_PLATE:
            if not body:
                return create_twiml_response(messages.request_plate())

            # Try to extract plate and borough from the message
            extracted_plate = extract_plate_from_text(body)
            extracted_borough = extract_borough_from_text(body)

            if extracted_plate:
                print(f"📝 Extracted plate from message: {extracted_plate}")
            if extracted_borough:
                print(f"📍 Extracted borough from message: {extracted_borough}")

            # Validate plate
            from validate.tlc import validate_plate

            plate = None
            vin = None
            if extracted_plate:
                is_valid, vehicle = validate_plate(extracted_plate)
                if is_valid and vehicle:
                    plate = extracted_plate
                    vin = vehicle.get("vin") if vehicle else None
                    print(f"✓ Plate {plate} validated (VIN: {vin})")

            if not plate:
                return create_twiml_response(
                    messages.plate_not_found(extracted_plate or body.strip().upper())
                )

            # Plate is valid! Check if we have all location data
            db = SightingsDatabase()

            # Check what location data we have
            has_gps = (
                session_data["pending_latitude"] is not None
                and session_data["pending_longitude"] is not None
            )

            # Update session with validated plate and any extracted borough
            final_borough = extracted_borough or session_data.get("pending_borough")
            if extracted_borough:
                session.update(pending_plate=plate, pending_borough=extracted_borough)
            else:
                session.update(pending_plate=plate)

            # If we have location data (GPS or borough), save immediately
            if has_gps or final_borough:
                print("✓ All data collected, saving sighting")
                from utils.image_processor import ImageProcessor

                contributor_id = db.get_or_create_contributor(phone_number=from_number)

                # Get image timestamp from session
                image_timestamp = session_data.get("pending_image_timestamp")
                if image_timestamp is None:
                    image_timestamp = datetime.now()

                # Generate unified filename and rename to final location
                processor = ImageProcessor(volume_path=volume_path)
                final_filename = processor.generate_filename(plate, image_timestamp)
                processor.rename_to_final(session_data["pending_image_path"], final_filename)

                result = db.add_sighting(
                    license_plate=plate,
                    timestamp=session_data["pending_timestamp"],
                    latitude=session_data["pending_latitude"],
                    longitude=session_data["pending_longitude"],
                    contributor_id=contributor_id,
                    image_filename=final_filename,
                    borough=final_borough if not has_gps else None,
                    image_timestamp=image_timestamp,
                    vin=vin,
                )

                if result is None:
                    print(f"⚠️ Duplicate image detected for plate {plate}")
                    session.reset()
                    return create_twiml_response(
                        "You've already submitted this exact photo. Send a new photo to log another sighting!"
                    )

                sighting_id = result["id"]
                print(f"✅ Sighting saved for plate {plate} (ID: {sighting_id})")

                if result["duplicate_type"] == "similar":
                    dup_info = result["duplicate_info"]
                    print(
                        f"⚠️ Similar image detected (distance: {dup_info['distance']}), but allowing submission"
                    )

                # Spawn background processing (R2 upload, web data gen, batch check, admin notification)
                spawn_background_processing(
                    image_filename=final_filename,
                    plate=plate,
                    contributor_id=contributor_id,
                    from_number=from_number,
                    sighting_id=sighting_id,
                )

                # Get confirmation data (stats + badges)
                conf = get_confirmation_data(db, plate, contributor_id, vin)
                vehicle_sighting_num = conf["vehicle_sighting_num"]
                total_sightings = conf["total_sightings"]
                contributor_sighting_num = conf["contributor_sighting_num"]
                new_badges = conf["new_badges"]

                contributor = db.get_contributor(contributor_id=contributor_id)
                if not contributor["preferred_name"]:
                    session.update(state=ChatSession.AWAITING_NAME)
                    msg = messages.sighting_confirmed(
                        plate,
                        vehicle_sighting_num,
                        total_sightings,
                        contributor_sighting_num,
                        new_badges,
                    )
                    msg += "\n\nWould you like to set a name for future posts? Reply with your name, or SKIP to remain anonymous."
                    return create_twiml_response(msg)

                session.reset()
                return create_twiml_response(
                    messages.sighting_confirmed(
                        plate,
                        vehicle_sighting_num,
                        total_sightings,
                        contributor_sighting_num,
                        new_badges,
                    )
                )

            # No location data - ask for borough
            print(f"✓ Plate {plate} validated, asking for borough")
            session.update(
                state=ChatSession.AWAITING_BOROUGH,
                pending_plate=plate,
            )
            return create_twiml_response(messages.request_borough())

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
