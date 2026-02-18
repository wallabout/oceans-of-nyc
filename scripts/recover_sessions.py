#!/usr/bin/env python3
"""
Recover stuck chat sessions by manually completing missing data.

Iterates through chat_sessions that are not in 'idle' state, prompts the admin
to supply missing values, creates sighting records, and triggers post-submission
processes (web data generation).

Usage:
    uv run python scripts/recover_sessions.py
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def get_stuck_sessions(db_url: str) -> list[dict]:
    """Get all chat sessions that are not in 'idle' state."""
    with psycopg2.connect(db_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT cs.*, c.preferred_name, c.phone_number as contributor_phone
                FROM chat_sessions cs
                LEFT JOIN contributors c ON cs.phone_number = c.phone_number
                WHERE cs.state != 'idle'
                ORDER BY cs.updated_at DESC
            """)
            return [dict(row) for row in cur.fetchall()]


def display_session(session: dict) -> None:
    """Display session details to admin."""
    print("\n" + "=" * 60)
    print(f"Session ID: {session.get('id')}")
    print(f"Phone: {session['phone_number']}")
    print(f"Contributor: {session.get('preferred_name') or 'Anonymous'}")
    print(f"State: {session['state']}")
    print(f"Updated: {session.get('updated_at')}")
    print("-" * 60)
    print(f"Pending plate: {session.get('pending_plate') or '(missing)'}")
    print(f"Pending image: {session.get('pending_image_path') or '(missing)'}")
    print(f"Pending timestamp: {session.get('pending_timestamp') or '(missing)'}")
    print(f"Pending latitude: {session.get('pending_latitude') or '(none)'}")
    print(f"Pending longitude: {session.get('pending_longitude') or '(none)'}")
    print(f"Pending borough: {session.get('pending_borough') or '(none)'}")
    print("=" * 60)


def prompt_for_value(
    prompt: str, current_value: str | None, required: bool = True, validator=None
) -> str | None:
    """Prompt admin for a value, showing current value if available."""
    if current_value:
        response = input(f"{prompt} [{current_value}]: ").strip()
        if not response:
            return current_value
        return response

    while True:
        response = input(f"{prompt}: ").strip()
        if response:
            if validator and not validator(response):
                print("Invalid input. Try again.")
                continue
            return response
        if not required:
            return None
        print("This field is required.")


def validate_plate(plate: str) -> bool:
    """Validate plate exists in TLC database."""
    from validate.tlc import validate_plate as check_plate

    is_valid, _ = check_plate(plate.upper())
    return is_valid


def prompt_for_borough() -> str | None:
    """Prompt admin for borough selection."""
    print("\nSelect borough:")
    print("  B = Brooklyn")
    print("  M = Manhattan")
    print("  Q = Queens")
    print("  X = Bronx")
    print("  S = Staten Island")
    print("  (blank) = Skip/Unknown")

    while True:
        response = input("Borough [B/M/Q/X/S]: ").strip().upper()
        if not response:
            return None

        borough_map = {
            "B": "Brooklyn",
            "M": "Manhattan",
            "Q": "Queens",
            "X": "Bronx",
            "S": "Staten Island",
        }

        if response in borough_map:
            return borough_map[response]
        print("Invalid borough. Use B, M, Q, X, or S.")


def recover_session(session: dict, db_url: str) -> bool:
    """
    Recover a single stuck session by prompting for missing data and creating sighting.

    Returns True if session was recovered, False if skipped.
    """
    from database import SightingsDatabase
    from web.generate_data import generate_web_data

    display_session(session)

    # Check if there's an image
    if not session.get("pending_image_path"):
        print("\n⚠️  No pending image found for this session.")
        response = input("Skip this session? [Y/n]: ").strip().lower()
        if response != "n":
            return False

    # Ask what to do
    print("\nOptions:")
    print("  r = Recover (complete the sighting)")
    print("  s = Skip (leave as-is)")
    print("  d = Delete (reset session to idle)")

    while True:
        action = input("Action [r/s/d]: ").strip().lower()
        if action in ("r", "s", "d"):
            break
        print("Invalid action. Use r, s, or d.")

    if action == "s":
        print("Skipping session.")
        return False

    if action == "d":
        # Reset session to idle
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET state = 'idle',
                        pending_image_path = NULL,
                        pending_plate = NULL,
                        pending_latitude = NULL,
                        pending_longitude = NULL,
                        pending_timestamp = NULL,
                        pending_borough = NULL,
                        pending_image_timestamp = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE phone_number = %s
                """,
                    (session["phone_number"],),
                )
                conn.commit()
        print("✓ Session reset to idle.")
        return False

    # Recover - collect missing data
    print("\n--- Completing sighting data ---")

    # License plate
    plate = session.get("pending_plate")
    if not plate:
        while True:
            plate = prompt_for_value("License plate (e.g., T123456C)", None, required=True)
            if plate:
                plate = plate.upper()
                # Normalize 6-digit plates
                if plate.isdigit() and len(plate) == 6:
                    plate = f"T{plate}C"
                if validate_plate(plate):
                    print(f"✓ Plate {plate} validated")
                    break
                print(
                    f"⚠️  Plate {plate} not found in TLC database. Enter again or try different plate."
                )

    # Timestamp
    timestamp = session.get("pending_timestamp")
    if not timestamp:
        timestamp_str = prompt_for_value(
            "Sighting timestamp (YYYY-MM-DD HH:MM:SS)",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            required=True,
        )
        if timestamp_str:
            try:
                timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                timestamp = datetime.now()
                print(f"Using current time: {timestamp}")
        else:
            timestamp = datetime.now()

    # Borough (if no GPS)
    lat = session.get("pending_latitude")
    lon = session.get("pending_longitude")
    borough = session.get("pending_borough")

    if lat is None or lon is None:
        if not borough:
            borough = prompt_for_borough()
            if borough:
                print(f"✓ Borough: {borough}")

    # Image paths
    image_path = session.get("pending_image_path")
    image_timestamp = session.get("pending_image_timestamp")

    if not image_path:
        print("\n⚠️  No image path found. This session cannot be recovered without an image.")
        return False

    # Confirm before saving
    print("\n--- Summary ---")
    print(f"Plate: {plate}")
    print(f"Timestamp: {timestamp}")
    print(f"Location: {f'{lat}, {lon}' if lat and lon else f'{borough or 'Unknown'}'}")
    print(f"Image: {image_path}")

    confirm = input("\nSave this sighting? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("Cancelled.")
        return False

    # Save the sighting
    try:
        db = SightingsDatabase()

        # Get or create contributor from the session's phone number
        contributor_id = db.get_or_create_contributor(phone_number=session["phone_number"])

        # Generate image filename and rename to final location
        from utils.image_processor import ImageProcessor

        processor = ImageProcessor()
        if image_timestamp is None:
            image_timestamp = timestamp if isinstance(timestamp, datetime) else datetime.now()
        image_filename = processor.generate_filename(plate, image_timestamp)
        processor.rename_to_final(image_path, image_filename)

        # Ensure timestamp is a datetime object
        if not isinstance(timestamp, datetime):
            try:
                timestamp = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            except ValueError:
                timestamp = datetime.now()

        result = db.add_sighting(
            license_plate=plate,
            timestamp=timestamp,
            latitude=lat,
            longitude=lon,
            contributor_id=contributor_id,
            image_filename=image_filename,
            borough=borough,
            image_timestamp=image_timestamp,
        )

        if result is None:
            print("⚠️  Sighting could not be created (possible duplicate image).")
            # Still reset the session
        else:
            sighting_id = result["id"]
            print(f"\n✓ Sighting created (ID: {sighting_id})")

            # Get stats
            vehicle_sighting_num = db.get_sighting_count(plate)
            total_sightings = db.get_total_sighting_count()
            contributor_sighting_num = db.get_contributor_sighting_count(contributor_id)
            print(f"  - {vehicle_sighting_num}x sighting of this vehicle")
            print(f"  - {total_sightings} total Ocean sightings")
            print(f"  - {contributor_sighting_num}x contribution from this user")

        # Reset the session
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE chat_sessions
                    SET state = 'idle',
                        pending_image_path = NULL,
                        pending_plate = NULL,
                        pending_latitude = NULL,
                        pending_longitude = NULL,
                        pending_timestamp = NULL,
                        pending_borough = NULL,
                        pending_image_timestamp = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE phone_number = %s
                """,
                    (session["phone_number"],),
                )
                conn.commit()

        print("✓ Session reset to idle")

        # Trigger web data generation
        print("\n🔄 Regenerating web data...")
        try:
            result = generate_web_data(upload_to_r2=True)
            if result["status"] == "success":
                print(f"✓ Web data updated: {result['sighted']}/{result['total']} vehicles sighted")
            else:
                print(f"⚠️  Web data generation returned: {result}")
        except Exception as e:
            print(f"⚠️  Failed to regenerate web data: {e}")

        return True

    except Exception as e:
        print(f"❌ Error creating sighting: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print("🔍 Finding stuck chat sessions...")
    sessions = get_stuck_sessions(db_url)

    if not sessions:
        print("✓ No stuck sessions found!")
        return

    print(f"Found {len(sessions)} stuck session(s)\n")

    recovered = 0
    for i, session in enumerate(sessions, 1):
        print(f"\n[{i}/{len(sessions)}]")
        if recover_session(session, db_url):
            recovered += 1

    print(f"\n{'=' * 60}")
    print(f"Done! Recovered {recovered} of {len(sessions)} session(s)")


if __name__ == "__main__":
    main()
