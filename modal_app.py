"""
Modal app for automated Bluesky posting of Fisker Ocean sightings.

This serverless app runs scheduled batch posts to Bluesky.
Images are stored in a Modal volume for persistent access.
"""

import contextlib

import modal

# Create Modal app
app = modal.App("oceans-of-nyc")

# Define the container image with all dependencies and source code
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "psycopg2-binary>=2.9.11",
        "pillow>=10.0.0",
        "requests>=2.31.0",
        "atproto>=0.0.55",
        "python-dotenv>=1.0.0",
        "staticmap>=0.5.7",
        "fastapi>=0.115.0",
        "twilio>=9.0.0",
        "imagehash>=4.3.1",
        "boto3>=1.42.23",
        "python-multipart>=0.0.6",
        "resend>=2.0.0",
    )
    .add_local_python_source("badges")
    .add_local_python_source("database")
    .add_local_python_source("validate")
    .add_local_python_source("geolocate")
    .add_local_python_source("post")
    .add_local_python_source("chat")
    .add_local_python_source("notify")
    .add_local_python_source("utils")
    .add_local_python_source("web")
)

# Define secrets
# To set these up, run:
# modal secret create bluesky-credentials BLUESKY_HANDLE=<handle> BLUESKY_PASSWORD=<password>
# modal secret create neon-db DATABASE_URL=<connection-string>
# modal secret create twilio-credentials TWILIO_ACCOUNT_SID=<sid> TWILIO_AUTH_TOKEN=<token> TWILIO_PHONE_NUMBER=<number>
# modal secret create cloudflare-r2 CLOUDFLARE_ACCOUNT_ID=<id> R2_ACCESS_KEY_ID=<key> R2_SECRET_ACCESS_KEY=<secret> R2_BUCKET_NAME=<bucket> R2_PUBLIC_URL_BASE=<url>
# modal secret create resend-email RESEND_API_KEY=<key> ADMIN_EMAIL=<email>
secrets = [
    modal.Secret.from_name("bluesky-credentials"),
    modal.Secret.from_name("neon-db"),
    modal.Secret.from_name("twilio-credentials"),
    modal.Secret.from_name("cloudflare-r2"),
    modal.Secret.from_name("resend-email"),
]

# Create a persistent volume for images and maps
volume = modal.Volume.from_name("oceans-of-nyc", create_if_missing=True)
VOLUME_PATH = "/data"
IMAGES_PATH = f"{VOLUME_PATH}/images"
MAPS_PATH = f"{VOLUME_PATH}/maps"
TLC_PATH = f"{VOLUME_PATH}/tlc"


def run_post_submission_hooks(
    plate: str,
    contributor_id: int,
    contributor_name: str,
    borough: str | None,
    image_filename: str | None,
    sighting_id: int | None = None,
):
    """
    Run all post-submission hooks after a sighting is saved.

    This is called by both SMS and web submission paths to ensure
    consistent behavior across all submission interfaces.

    Handles:
    - Web data regeneration (vehicles.json, badges.json)
    - Batch post trigger checking
    - Admin email notifications (for non-admin contributors)

    Args:
        plate: The validated license plate
        contributor_id: The contributor's database ID
        contributor_name: Display name for the contributor
        borough: NYC borough (or None if unknown)
        image_filename: The filename of the saved image (or None)
        sighting_id: The sighting's database ID (optional, for fetching details)
    """
    import os

    from database import SightingsDatabase
    from utils.sighting_confirmation import get_confirmation_data
    from web.generate_data import generate_web_data as gen_web_data

    db = SightingsDatabase()

    # Get VIN for confirmation data
    vin = None
    if sighting_id:
        # Get VIN from the sighting record
        sighting = db.get_sighting_by_id(sighting_id)
        vin = sighting.get("vin") if sighting else None

    if not vin:
        # Fall back to looking up VIN from plate
        vehicle = db.get_tlc_vehicle_by_plate(plate)
        vin = vehicle.get("vin") if vehicle else None

    # 1. Regenerate web data (sightings + badges)
    try:
        print("🔄 Triggering web data generation...")
        result = gen_web_data(upload_to_r2=True)
        if result["status"] == "success":
            sightings = result["sightings"]
            print(f"✓ Web data updated: {sightings['sighted']}/{sightings['total']} vehicles")
        else:
            print(f"⚠️ Web data generation failed: {result}")
    except Exception as e:
        print(f"⚠️ Failed to generate web data: {e}")

    # 2. Check and trigger batch post
    try:
        print("🔍 Checking if batch post should be triggered...")
        check_and_trigger_batch_post.spawn()
        print("✓ Batch post check spawned")
    except Exception as e:
        print(f"⚠️ Failed to trigger batch post check: {e}")

    # 3. Send admin notification for non-admin contributors
    if contributor_id != 1:
        try:
            from notify import send_submission_notification

            contributor = db.get_contributor(contributor_id=contributor_id)
            display_name = contributor.get("preferred_name") or contributor_name

            # Get confirmation data (stats and badges)
            confirmation_data = get_confirmation_data(db, plate, contributor_id, vin)

            # Construct image URL
            image_url = None
            if image_filename:
                base_uri = os.getenv(
                    "SIGHTING_IMAGE_BASE_URI", "https://cdn.oceansofnyc.com/sightings/"
                )
                image_url = f"{base_uri}{image_filename}"

            # Send detailed notification
            send_submission_notification(
                contributor_name=display_name,
                plate=plate,
                borough=borough,
                vehicle_sighting_num=confirmation_data["vehicle_sighting_num"],
                total_sightings=confirmation_data["total_sightings"],
                contributor_sighting_num=confirmation_data["contributor_sighting_num"],
                image_url=image_url,
                new_badges=confirmation_data.get("new_badges", []),
            )
            print(f"✓ Admin notification sent for {display_name}")
        except Exception as e:
            print(f"⚠️ Failed to send admin notification: {e}")


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
)
def process_sighting_background(
    image_filename: str,
    plate: str,
    contributor_id: int,
    from_number: str,
    sighting_id: int | None = None,
):
    """
    Handle post-sighting background work after the TwiML response is sent.

    This function is spawned asynchronously to avoid blocking the Twilio webhook response.
    It handles:
    - Uploading the web-optimized image to R2
    - Regenerating vehicles.json
    - Checking if a batch post should be triggered
    - Sending admin notification for non-admin contributors

    Args:
        image_filename: The filename of the saved image
        plate: The validated license plate
        contributor_id: The contributor's database ID
        from_number: The contributor's phone number (for display name lookup)
        sighting_id: The sighting's database ID (optional, for fetching details)
    """
    import os

    from database import SightingsDatabase
    from utils.image_processor import ImageProcessor

    print(f"🔄 Processing background work for {plate}...")

    # 1. Upload web version to R2
    try:
        processor = ImageProcessor(volume_path=VOLUME_PATH)

        # Check if web file exists, if not create it from original
        web_path = processor.get_web_path(image_filename)
        original_path = processor.get_original_path(image_filename)

        if not os.path.exists(web_path):
            print(f"⚠ Web file not found, creating from original: {original_path}")
            if os.path.exists(original_path):
                web_bytes, _ = processor.create_web_version(original_path)
                processor.save_web_version_local(web_bytes, image_filename)
                print(f"✓ Created web version: {web_path}")
            else:
                print(f"⚠️ Original file not found either: {original_path}")

        r2_url = processor.upload_web_version(image_filename)
        if r2_url:
            print(f"✓ Uploaded to R2: {r2_url}")
        else:
            print("⚠️ Web version upload skipped (file not found)")
    except Exception as e:
        print(f"⚠️ Failed to upload to R2: {e}")

    # 2. Get borough from sighting record if sighting_id provided
    borough = None
    if sighting_id:
        db = SightingsDatabase()
        sighting = db.get_sighting_by_id(sighting_id)
        if sighting:
            borough = sighting.get("borough")

    # 3. Run post-submission hooks (web data, batch post, notification)
    run_post_submission_hooks(
        plate=plate,
        contributor_id=contributor_id,
        contributor_name=from_number,
        borough=borough,
        image_filename=image_filename,
        sighting_id=sighting_id,
    )

    # Commit volume changes
    volume.commit()
    print(f"✅ Background processing complete for {plate}")


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("twilio-credentials"),
        modal.Secret.from_name("cloudflare-r2"),
    ],
    volumes={VOLUME_PATH: volume},
)
def process_sms_message(
    from_number: str,
    body: str,
    num_media: int,
    media_urls: list[str],
    media_types: list[str],
    channel_type: str,
):
    """
    Process an incoming SMS/MMS message asynchronously.

    This function is spawned by the webhook to handle all processing
    in the background, allowing the webhook to return immediately.
    Responses are sent via Twilio API instead of webhook TwiML response.

    Args:
        from_number: Sender's phone number
        body: Text content of the message
        num_media: Number of media attachments
        media_urls: List of media URLs
        media_types: List of media content types
        channel_type: Channel type (sms, mms, etc.)
    """
    import re

    from chat.webhook import handle_incoming_sms
    from notify.sms import send_sms

    print(f"🔄 Processing SMS from {from_number} asynchronously...")

    try:
        # Process the message using existing logic
        twiml_response = handle_incoming_sms(
            from_number=from_number,
            body=body,
            num_media=num_media,
            media_urls=media_urls,
            media_types=media_types,
            volume_path=VOLUME_PATH,
            channel_type=channel_type,
        )

        # Extract message text from TwiML response
        # TwiML format: <Response><Message>text</Message></Response>
        match = re.search(r"<Message>(.*?)</Message>", twiml_response, re.DOTALL)
        if match:
            message_text = match.group(1)
            # Unescape XML entities
            message_text = (
                message_text.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", '"')
                .replace("&apos;", "'")
            )

            # Send response via Twilio API
            print(f"📤 Sending response via Twilio API to {from_number}")
            send_sms(from_number, message_text)
        else:
            print("⚠️ No message found in TwiML response")

        # Commit volume changes
        volume.commit()
        print(f"✅ Async SMS processing complete for {from_number}")

    except Exception as e:
        print(f"❌ Error processing SMS: {e}")
        import traceback

        traceback.print_exc()

        # Try to send error message to user
        with contextlib.suppress(Exception):
            send_sms(from_number, "Sorry, something went wrong. Please try again.")


@app.function(image=image, secrets=secrets)
def check_and_trigger_batch_post():
    """
    Check if batch posting conditions are met and trigger a post if needed.

    This function is called after each sighting is saved to determine if we should
    post immediately based on:
    - 4 or more sightings waiting, OR
    - Oldest sighting has been waiting 24+ hours

    Returns:
        dict with status and any action taken
    """
    from database import SightingsDatabase
    from post.batch_trigger import should_trigger_batch_post

    print("🔍 Checking batch posting conditions...")

    db = SightingsDatabase()
    unposted = db.get_unposted_sightings()

    if should_trigger_batch_post(unposted):
        print("🚀 Triggering batch post...")
        try:
            # Trigger the batch post (will block until complete)
            result = post_batch.remote(batch_size=4, dry_run=False)
            return {
                "status": "triggered",
                "message": "Batch post completed",
                "result": result,
            }
        except Exception as e:
            print(f"❌ Error triggering batch post: {e}")
            return {
                "status": "error",
                "message": f"Failed to trigger batch post: {e}",
            }
    else:
        return {
            "status": "not_triggered",
            "message": "Conditions not met for batch posting",
            "count": len(unposted),
        }


@app.function(image=image, secrets=secrets, volumes={VOLUME_PATH: volume})
def post_batch(batch_size: int = 4, dry_run: bool = False):
    """
    Post one or more sightings using the unified batch format.

    This is the only posting function needed - it handles 1-4 sightings
    using the same unified format with contributor statistics.

    Args:
        batch_size: Number of sightings to include (1-4, default: 4)
        dry_run: If True, only show what would be posted without actually posting
    """
    import os

    from database import SightingsDatabase
    from post.bluesky import BlueskyClient

    print(f"🚀 Starting multi-post (batch_size: {batch_size}, dry_run: {dry_run})")

    # Ensure directories exist
    os.makedirs(IMAGES_PATH, exist_ok=True)

    # Initialize database and client
    db = SightingsDatabase()

    # Get unposted sightings
    sightings = db.get_unposted_sightings()

    if not sightings:
        print("✓ No unposted sightings found")
        return {"posted": 0, "message": "No unposted sightings"}

    # Limit to batch_size
    if batch_size < 1 or batch_size > 4:
        batch_size = 4

    sightings_to_post = sightings[:batch_size]

    print(f"Found {len(sightings)} unposted sighting(s), posting {len(sightings_to_post)} in batch")

    # Get statistics
    unique_sighted = db.get_unique_sighted_count()
    total_fiskers = db.get_tlc_vehicle_count()

    # Extract info for logging
    plates = [s[1] for s in sightings_to_post]
    contributors = set(s[9] for s in sightings_to_post if s[9])

    print("\n📊 Batch Post Info:")
    print(f"   Plates: {', '.join(plates)}")
    print(f"   Contributors: {len(contributors)}")
    print(f"   Progress: {unique_sighted}/{total_fiskers}")

    if dry_run:
        print("\n🔍 DRY RUN - Not actually posting")
        return {
            "posted": 0,
            "message": f"Dry run: would post {len(sightings_to_post)} sightings",
            "plates": plates,
            "contributors": len(contributors),
        }

    try:
        # Get contributor statistics
        contributor_stats = db.get_all_contributor_sighting_counts()

        # Post to Bluesky
        client = BlueskyClient()
        response = client.create_batch_sighting_post(
            sightings=sightings_to_post,
            unique_sighted=unique_sighted,
            total_fiskers=total_fiskers,
            contributor_stats=contributor_stats,
        )

        # Mark all sightings as posted
        sighting_ids = [s[0] for s in sightings_to_post]
        post_uri = response.uri
        db.mark_batch_as_posted(sighting_ids, post_uri)

        print("\n✓ Batch posted successfully!")
        print(f"  Post URI: {post_uri}")
        print(f"  Marked {len(sighting_ids)} sighting(s) as posted")

        return {
            "posted": len(sighting_ids),
            "post_uri": post_uri,
            "plates": plates,
            "contributors": len(contributors),
            "message": f"Posted {len(sighting_ids)} sightings in batch",
        }

    except Exception as e:
        print(f"❌ Error posting batch: {e}")
        import traceback

        traceback.print_exc()
        return {"posted": 0, "error": str(e), "message": f"Failed to post batch: {e}"}


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
    schedule=modal.Cron("0 22 * * *"),  # Run daily at 10 PM UTC (6 PM ET) as backup
)
def post_sightings_queue():
    """
    Backup scheduled function that runs daily at 6 PM ET (10 PM UTC).

    This serves as a backup to the conditional posting system. It will post any
    sightings that meet the criteria:
    - 4 or more sightings waiting, OR
    - Oldest sighting has been waiting 24+ hours

    Primary posting now happens immediately after sightings are saved via
    check_and_trigger_batch_post(). This scheduled job ensures nothing gets
    stuck in the queue if the conditional posting fails.
    """
    from datetime import datetime

    from database import SightingsDatabase
    from post.batch_trigger import should_trigger_batch_post

    print(f"⏰ Backup scheduled post check triggered at {datetime.now()}")

    # Check how many unposted sightings we have
    db = SightingsDatabase()
    sightings = db.get_unposted_sightings()

    if not sightings:
        print("✓ No unposted sightings found")
        return {"posted": 0, "message": "No unposted sightings"}

    num_sightings = len(sightings)
    print(f"Found {num_sightings} unposted sighting(s)")

    # Check if we should post based on conditions
    if not should_trigger_batch_post(sightings):
        print("✓ Conditions not met for posting - sightings will wait")
        return {
            "posted": 0,
            "message": f"Conditions not met: {num_sightings} sightings waiting",
            "count": num_sightings,
        }

    # Conditions met - post the batch
    print(f"📮 Posting batch of {min(num_sightings, 4)} sightings")
    result = post_batch.remote(batch_size=4, dry_run=False)
    print(f"✓ Posted batch: {result}")

    # If there are more than 4 sightings, recursively process the remainder
    if num_sightings > 4:
        print(f"\n🔄 {num_sightings - 4} sightings remaining, processing next batch...")
        import time

        time.sleep(2)  # Brief pause between batches
        next_result = post_sightings_queue.remote()

        # Combine results
        total_posted = result.get("posted", 0) + next_result.get("posted", 0)
        return {
            "posted": total_posted,
            "batches": 2,
            "message": f"Posted {total_posted} sightings across multiple batches",
        }

    return result


@app.function(
    image=image,
    secrets=secrets,
)
def get_stats():
    """Get database statistics."""
    from database import SightingsDatabase

    db = SightingsDatabase()

    stats = {
        "total_sightings": len(db.get_all_sightings()),
        "unique_posted": db.get_unique_posted_count(),
        "unique_sighted": db.get_unique_sighted_count(),
        "total_vehicles": db.get_tlc_vehicle_count(),
        "unposted": len(db.get_unposted_sightings()),
    }

    print("\n📊 Database Statistics:")
    print(f"   Total sightings: {stats['total_sightings']}")
    print(f"   Unique plates sighted: {stats['unique_sighted']}")
    print(f"   Unique plates posted: {stats['unique_posted']}")
    print(f"   Total TLC vehicles: {stats['total_vehicles']}")
    print(f"   Unposted sightings: {stats['unposted']}")

    return stats


@app.function(image=image)
def get_hello():
    """Test basic connectivity without secrets."""
    import sys

    print("✓ Modal function executed successfully!")
    print(f"Python version: {sys.version}")
    print("✓ Source files mounted correctly")

    # Try importing our modules
    try:
        print("✓ database module imported successfully")
    except Exception as e:
        print(f"✗ Error importing database: {e}")

    try:
        print("✓ post.bluesky module imported successfully")
    except Exception as e:
        print(f"✗ Error importing post.bluesky: {e}")

    try:
        print("✓ geolocate module imported successfully")
    except Exception as e:
        print(f"✗ Error importing geolocate: {e}")

    try:
        print("✓ validate module imported successfully")
    except Exception as e:
        print(f"✗ Error importing validate: {e}")

    return {"status": "success"}


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("cloudflare-r2"),
        modal.Secret.from_name("resend-email"),
    ],
    volumes={VOLUME_PATH: volume},
)
@modal.asgi_app()
def web_submission_webhook():
    """
    Web submission endpoint for sighting submissions from the static website.

    Configure CORS to allow requests from oceansofnyc.com.

    POST /submit - Submit a new sighting
    - Form data: image (file), license_plate (str), borough (str), contributor_name (str)
    - Returns JSON with success/error status
    """
    from datetime import datetime

    from fastapi import FastAPI, Form, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    from database import SightingsDatabase
    from utils.image_hashing import calculate_both_hashes_from_bytes
    from utils.image_processor import ImageProcessor
    from utils.r2_storage import R2Storage
    from validate import validate_plate

    web_app = FastAPI()

    # Add CORS middleware to allow requests from the static site
    web_app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://oceansofnyc.com",
            "https://www.oceansofnyc.com",
            "http://localhost:8000",  # For local testing
        ],
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["*"],
    )

    @web_app.post("/submit")
    async def submit_sighting(
        image: UploadFile,
        license_plate: str = Form(...),
        borough: str = Form(...),
        contributor_name: str = Form(...),
        email: str = Form(None),
    ):
        """Handle web submission of a new sighting."""
        try:
            # Validate required fields
            if not contributor_name.strip():
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "validation_error",
                        "message": "Name is required",
                    },
                )

            # Normalize and validate license plate
            plate = license_plate.strip().upper()
            # Handle 6-digit shorthand (e.g., "123456" -> "T123456C")
            if plate.isdigit() and len(plate) == 6:
                plate = f"T{plate}C"

            is_valid, vehicle_info = validate_plate(plate)
            if not is_valid:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "invalid_plate",
                        "message": f"License plate {plate} not found in TLC database",
                    },
                )

            # Extract VIN from vehicle info
            vin = vehicle_info.get("vin") if vehicle_info else None

            # Validate borough
            valid_boroughs = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
            if borough not in valid_boroughs:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "validation_error",
                        "message": f"Invalid borough. Must be one of: {', '.join(valid_boroughs)}",
                    },
                )

            # Read image data
            image_bytes = await image.read()
            if len(image_bytes) == 0:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "validation_error",
                        "message": "Image file is empty",
                    },
                )

            # Calculate image hashes for duplicate detection
            sha256_hash, perceptual_hash = calculate_both_hashes_from_bytes(image_bytes)

            # Extract image timestamp from EXIF
            from geolocate.exif import extract_image_timestamp_from_bytes

            image_timestamp = extract_image_timestamp_from_bytes(image_bytes)
            if image_timestamp is None:
                # Fallback to current time if no EXIF timestamp
                image_timestamp = datetime.now()

            # Initialize database
            db = SightingsDatabase()

            # Process image: save original, create web version, upload to R2
            processor = ImageProcessor(volume_path=VOLUME_PATH)

            # Generate unified filename using new convention: {plate}_{timestamp}.jpg
            image_filename = processor.generate_filename(plate, image_timestamp)

            # Save original image to volume
            original_path = processor.save_original(image_bytes, image_filename)
            print(f"💾 Saved original: {original_path}")

            # Create web-optimized version
            web_bytes, _ = processor.create_web_version_from_bytes(image_bytes)

            # Save web version locally
            processor.save_web_version_local(web_bytes, image_filename)

            # Upload web version to R2 (using same filename, no web_ prefix)
            r2_key = f"sightings/{image_filename}"
            r2 = R2Storage()
            web_url = r2.upload_bytes(web_bytes, r2_key, content_type="image/jpeg")
            print(f"🌐 Web URL: {web_url}")

            # Get or create contributor
            # Priority: email (if provided) > name-based identifier
            if email and email.strip():
                # Use email as primary identifier - provides stable identity across submissions
                contributor_id = db.get_or_create_contributor(email=email.strip())
            else:
                # Fallback to name-based identifier for anonymous submissions
                web_identifier = f"web:{contributor_name.strip().lower().replace(' ', '_')}"
                contributor_id = db.get_or_create_contributor(bluesky_handle=web_identifier)

            # Update the contributor's preferred name if needed
            conn = db._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE contributors SET preferred_name = %s WHERE id = %s AND preferred_name IS NULL",
                (contributor_name.strip(), contributor_id),
            )
            conn.commit()
            conn.close()

            # Create sighting record
            result = db.add_sighting(
                license_plate=plate,
                timestamp=image_timestamp,
                latitude=None,
                longitude=None,
                contributor_id=contributor_id,
                image_filename=image_filename,
                image_hash_sha256=sha256_hash,
                image_hash_perceptual=perceptual_hash,
                borough=borough,
                image_timestamp=image_timestamp,
                vin=vin,
            )

            if result is None:
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": "duplicate_image",
                        "message": "This image has already been submitted (exact match)",
                    },
                )

            sighting_id = result["id"]

            # Log warning if similar image detected (but still accept it)
            if result.get("duplicate_type") == "similar":
                duplicate_info = result.get("duplicate_info", {})
                print(
                    f"⚠️ Similar image detected (distance: {duplicate_info.get('distance')}), but allowing web submission"
                )

            # Run post-submission hooks (web data, batch post, notification)
            run_post_submission_hooks(
                plate=plate,
                contributor_id=contributor_id,
                contributor_name=contributor_name.strip(),
                borough=borough,
                image_filename=image_filename,
                sighting_id=sighting_id,
            )

            # Get confirmation data (stats + badges) for rich feedback
            from utils.sighting_confirmation import get_confirmation_data

            conf = get_confirmation_data(db, plate, contributor_id, vin)

            # Commit volume changes
            volume.commit()

            return JSONResponse(
                content={
                    "success": True,
                    "message": f"Sighting submitted successfully! Vehicle {plate} recorded.",
                    "sighting_id": sighting_id,
                    "stats": {
                        "vehicle_sighting_num": conf["vehicle_sighting_num"],
                        "total_sightings": conf["total_sightings"],
                        "contributor_sighting_num": conf["contributor_sighting_num"],
                    },
                    "new_badges": conf["new_badges"],
                }
            )

        except Exception as e:
            print(f"Error processing web submission: {e}")
            import traceback

            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "server_error",
                    "message": "An error occurred processing your submission. Please try again.",
                },
            )

    @web_app.get("/")
    async def health_check():
        return {"status": "ok", "service": "oceans-of-nyc-web-submission"}

    return web_app


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
)
def upload_image(filename: str, image_data: bytes):
    """
    Upload an image to the Modal volume.

    Args:
        filename: Name for the image file
        image_data: Raw image bytes
    """
    import os

    os.makedirs(IMAGES_PATH, exist_ok=True)

    file_path = f"{IMAGES_PATH}/{filename}"
    with open(file_path, "wb") as f:
        f.write(image_data)

    volume.commit()

    size = len(image_data) / 1024
    print(f"✓ Uploaded {filename} ({size:.1f} KB)")

    return {"filename": filename, "size_kb": size, "path": file_path}


# ==================== Twilio SMS/MMS Webhook ====================


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("twilio-credentials"),
        modal.Secret.from_name("cloudflare-r2"),
    ],
    volumes={VOLUME_PATH: volume},
)
@modal.asgi_app()
def chat_sms_webhook():
    """
    Twilio SMS/MMS webhook endpoint.

    Configure this URL in your Twilio phone number settings:
    https://wallabout--oceans-of-nyc-chat-sms-webhook.modal.run

    This webhook immediately returns an empty TwiML response and spawns
    async processing to avoid Twilio's 15-second timeout. Responses are
    sent via Twilio API instead of webhook response.

    Twilio sends POST requests with form-encoded data including:
    - From: Sender phone number
    - Body: Message text
    - NumMedia: Number of media attachments
    - MediaUrl0, MediaUrl1, etc.: URLs to media files
    - MediaContentType0, etc.: MIME types of media
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import Response

    from chat.webhook import parse_twilio_request

    web_app = FastAPI()

    @web_app.post("/")
    async def handle_sms(request: Request):
        print("📨 Received webhook request")

        # Get the raw body from the request
        body = await request.body()

        data = parse_twilio_request(body)

        # Extract message details
        from_number = data.get("From", "unknown")
        message_body = data.get("Body", "")
        num_media = int(data.get("NumMedia", 0))

        # Determine channel type (SMS, MMS, RCS, etc.)
        channel_type = data.get("MessagingServiceChannelType", "sms").lower()

        # Collect media URLs and types
        media_urls = []
        media_types = []
        for i in range(num_media):
            url = data.get(f"MediaUrl{i}")
            mtype = data.get(f"MediaContentType{i}")
            if url:
                media_urls.append(url)
                media_types.append(mtype or "unknown")

        print(
            f"📱 Incoming from {from_number}: {message_body[:50] if message_body else '(no text)'}"
        )
        print(f"   Media: {num_media}, Channel: {channel_type}")

        # Spawn async processing - response will be sent via Twilio API
        process_sms_message.spawn(
            from_number=from_number,
            body=message_body,
            num_media=num_media,
            media_urls=media_urls,
            media_types=media_types,
            channel_type=channel_type,
        )

        print("✓ Spawned async processing, returning empty TwiML")

        # Return empty TwiML immediately to avoid timeout
        empty_twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(
            content=empty_twiml,
            media_type="application/xml",
        )

    @web_app.get("/")
    async def health_check():
        return {"status": "ok", "service": "fisker-ocean-sms-webhook"}

    return web_app


# ==================== TLC Data Updates ====================


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
    timeout=300,
    schedule=modal.Cron("0 7 * * *"),  # Run daily at 3 AM ET (7 AM UTC)
)
def update_tlc_vehicles():
    """
    Download latest TLC vehicle data from NYC Open Data and update the database.
    Stores versioned CSVs in Modal volume and filters to Fisker vehicles only.

    Runs automatically every day at 3 AM ET.
    Can also be triggered manually via: modal run modal_app.py --command=update-tlc
    """
    import os
    from datetime import datetime

    from validate.tlc import TLCDatabase

    print(f"🚀 Starting TLC data update at {datetime.now()}")
    print(f"{'='*60}")

    # Ensure TLC directory exists
    os.makedirs(TLC_PATH, exist_ok=True)

    try:
        # Initialize TLC database
        tlc_db = TLCDatabase()

        # Download, import, and filter
        result = tlc_db.update_from_nyc_open_data(output_dir=TLC_PATH)

        # Commit volume changes to persist CSVs
        volume.commit()

        print(f"\n{'='*60}")
        print("✓ TLC data update complete!")
        print(f"  CSV: {result['csv_path']}")
        print(f"  Active Fisker vehicles: {result['active_count']:,}")
        print(f"  Cumulative unique Fisker vehicles: {result['global_count']:,}")
        print(f"  Timestamp: {result['timestamp']}")
        print(f"{'='*60}")

        return result

    except Exception as e:
        print(f"❌ Error updating TLC data: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
    timeout=3600,
)
def backfill_tlc_vehicle_history():
    """
    Backfill historical TLC vehicle counts from stored CSV files.
    Processes all versioned CSV files in the Modal volume and records daily counts.

    Can be triggered manually via: modal run modal_app.py::backfill_tlc_vehicle_history
    """
    import os
    from datetime import datetime

    from validate.tlc import TLCDatabase

    print(f"🚀 Starting TLC vehicle history backfill at {datetime.now()}")
    print(f"{'='*60}")

    # Ensure TLC directory exists
    os.makedirs(TLC_PATH, exist_ok=True)

    try:
        # Initialize TLC database
        tlc_db = TLCDatabase()

        # Run backfill from stored CSVs
        result = tlc_db.backfill_history_from_csvs(csv_dir=TLC_PATH)

        print(f"\n{'='*60}")
        print("✓ TLC vehicle history backfill complete!")
        print(f"  Files processed: {result['files_processed']}")
        if result["date_range"]:
            print(f"  Date range: {result['date_range'][0]} to {result['date_range'][1]}")
        if result["errors"]:
            print(f"  Errors encountered: {len(result['errors'])}")
            for error in result["errors"]:
                print(f"    - {error}")
        print(f"{'='*60}")

        return result

    except Exception as e:
        print(f"❌ Error backfilling TLC vehicle history: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.function(image=image, secrets=secrets, volumes={VOLUME_PATH: volume}, timeout=3600)
def backfill_image_hashes(batch_size: int = 100, dry_run: bool = False):
    """
    Backfill image hashes for existing sightings in Modal volume.

    Args:
        batch_size: Number of sightings to process in each batch
        dry_run: If True, show what would be done without updating database
    """
    import os

    from database import SightingsDatabase
    from utils.image_hashing import ImageHashError, calculate_both_hashes
    from utils.image_processor import ImageProcessor

    print("🔄 Starting image hash backfill on Modal...")
    print(f"   Batch size: {batch_size}")
    if dry_run:
        print("   DRY RUN MODE - no changes will be made")
    print()

    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    # Initialize image processor to derive paths from filenames
    processor = ImageProcessor(volume_path=VOLUME_PATH)

    # Get all sightings without hashes
    cursor.execute(
        """
        SELECT id, image_filename
        FROM sightings
        WHERE image_hash_sha256 IS NULL OR image_hash_perceptual IS NULL
        ORDER BY id ASC
        """
    )

    sightings = cursor.fetchall()
    total = len(sightings)

    if total == 0:
        print("✓ All sightings already have hashes!")
        conn.close()
        return {"status": "complete", "processed": 0, "successful": 0, "skipped": 0}

    print(f"Found {total} sightings without hashes\n")

    processed = 0
    successful = 0
    skipped = 0
    failed = []

    for sighting_id, image_filename in sightings:
        processed += 1

        # Derive full path from filename
        image_path = processor.get_original_path(image_filename)

        # Check if file exists
        if not os.path.exists(image_path):
            print(f"⚠️  Sighting #{sighting_id}: Image file not found: {image_path}")
            skipped += 1
            failed.append((sighting_id, image_filename, "File not found"))
            continue

        try:
            # Calculate hashes
            sha256, phash = calculate_both_hashes(image_path)

            if dry_run:
                print(
                    f"[DRY RUN] Would update sighting #{sighting_id}: "
                    f"SHA256={sha256[:16]}..., pHash={phash}"
                )
                successful += 1
            else:
                # Update database
                cursor.execute(
                    """
                    UPDATE sightings
                    SET image_hash_sha256 = %s, image_hash_perceptual = %s
                    WHERE id = %s
                    """,
                    (sha256, phash, sighting_id),
                )

                successful += 1

                # Commit in batches
                if successful % batch_size == 0:
                    conn.commit()
                    print(
                        f"✓ Committed batch of {batch_size} updates (total: {successful}/{total})"
                    )

        except ImageHashError as e:
            print(f"❌ Sighting #{sighting_id}: Failed to calculate hashes: {e}")
            failed.append((sighting_id, image_filename, str(e)))
            continue

        except Exception as e:
            print(f"❌ Sighting #{sighting_id}: Unexpected error: {e}")
            failed.append((sighting_id, image_filename, str(e)))
            continue

    # Final commit
    if not dry_run and successful > 0:
        conn.commit()
        print("\n✓ Final commit completed")

    # Commit volume changes
    volume.commit()

    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total sightings processed: {processed}")
    print(f"Successfully updated:       {successful}")
    print(f"Skipped (file not found):  {skipped}")
    print(f"Failed:                    {len(failed)}")

    if failed and len(failed) <= 10:
        print("\nFailed sightings:")
        for sighting_id, image_filename, error in failed:
            print(f"  #{sighting_id}: {error}")
            print(f"    Filename: {image_filename}")
    elif failed:
        print(f"\n{len(failed)} sightings failed (showing first 10):")
        for sighting_id, _image_filename, error in failed[:10]:
            print(f"  #{sighting_id}: {error}")

    if dry_run:
        print("\n⚠️  DRY RUN - no changes were made to the database")
    else:
        print(f"\n✅ Backfill complete! Updated {successful}/{total} sightings")

    return {
        "status": "complete",
        "processed": processed,
        "successful": successful,
        "skipped": skipped,
        "failed": len(failed),
        "dry_run": dry_run,
    }


@app.function(image=image, secrets=secrets)
def generate_web_data():
    """
    Generate all web data (vehicles.json and badges.json) and upload to R2.

    This function queries the database for all TLC vehicles, sightings, and badges,
    then generates JSON files and uploads them to R2 for the static website.

    Can be triggered manually via: modal run modal_app.py --command=generate-web-data
    """
    from web.generate_data import generate_web_data as gen_web_data

    print("🔄 Generating web data...")
    result = gen_web_data(upload_to_r2=True)

    if result["status"] == "success":
        sightings = result["sightings"]
        badges = result["badges"]
        print("✓ Web data generated and uploaded successfully")
        print(f"  Sightings: {sightings['sighted']}/{sightings['total']} vehicles")
        print(
            f"  Badges: {badges['total_badges']} badges, {badges['total_contributors']} contributors"
        )
    else:
        print(f"❌ Failed to generate web data: {result}")

    return result


@app.function(image=image, secrets=secrets, volumes={VOLUME_PATH: volume}, timeout=3600)
def backfill_r2_images(batch_size: int = 10, dry_run: bool = False):
    """
    DEPRECATED: This migration function is no longer needed.

    The image_path column has been dropped. All new sightings now use
    image_filename directly. This function remains for reference only.
    """
    print("⚠️  backfill_r2_images() is DEPRECATED")
    print("   The image_path column has been dropped.")
    print("   All sightings now use image_filename directly.")
    print("   This migration function is no longer needed.")
    return {
        "status": "deprecated",
        "message": "Migration complete - image_path column no longer exists",
    }


@app.function(image=image, secrets=secrets, volumes={VOLUME_PATH: volume}, timeout=3600)
def migrate_image_storage(batch_size: int = 50, dry_run: bool = True):
    """
    DEPRECATED: This migration function is no longer needed.

    The image_path column has been dropped. All new sightings now use
    image_filename directly. This function remains for reference only.
    """
    print("⚠️  migrate_image_storage() is DEPRECATED")
    print("   The image_path column has been dropped.")
    print("   All sightings now use image_filename directly.")
    print("   This migration function is no longer needed.")
    return {
        "status": "deprecated",
        "message": "Migration complete - image_path column no longer exists",
    }


@app.function(image=image, secrets=secrets, volumes={VOLUME_PATH: volume}, timeout=600)
def reprocess_web_images(filenames: list[str], dry_run: bool = False):
    """
    Reprocess specific images to fix EXIF orientation issues.

    Reads originals from Modal volume, creates new web versions with correct
    orientation, saves to web folder, and uploads to R2.

    Args:
        filenames: List of image filenames to reprocess
        dry_run: If True, only report what would be done
    """
    from utils.image_processor import ImageProcessor

    processor = ImageProcessor(volume_path=VOLUME_PATH)
    results = []

    for filename in filenames:
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Processing: {filename}")

        original_path = processor.get_original_path(filename)
        import os

        if not os.path.exists(original_path):
            print(f"  ✗ Original not found: {original_path}")
            results.append(
                {"filename": filename, "status": "error", "reason": "original not found"}
            )
            continue

        if dry_run:
            print(f"  Would reprocess from: {original_path}")
            print(f"  Would save web to: {processor.get_web_path(filename)}")
            print(f"  Would upload to R2: sightings/{filename}")
            results.append({"filename": filename, "status": "would_process"})
            continue

        # Create new web version (now with EXIF orientation fix)
        web_bytes, web_filename = processor.create_web_version(original_path)
        print(f"  ✓ Created web version ({len(web_bytes)} bytes)")

        # Save to local web folder
        web_path = processor.save_web_version_local(web_bytes, web_filename)
        print(f"  ✓ Saved to: {web_path}")

        # Upload to R2
        from utils.r2_storage import R2Storage

        r2 = R2Storage()
        object_key = f"sightings/{web_filename}"
        web_url = r2.upload_bytes(web_bytes, object_key, content_type="image/jpeg")
        print(f"  ✓ Uploaded to R2: {web_url}")

        # Commit volume changes
        volume.commit()

        results.append({"filename": filename, "status": "success", "web_url": web_url})

    return {"processed": len(results), "results": results}


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
    secrets=[modal.Secret.from_name("neon-db")],
    timeout=3600,  # 1 hour timeout for processing all CSVs
)
def rebuild_tlc_table(dry_run: bool = False):
    """
    Rebuild the tlc_vehicles table with the new schema using compound unique key.

    Args:
        dry_run: If True, build temp table and show comparison without swapping

    This function:
    1. Creates a temporary table (tlc_vehicles_new) with the new schema
    2. Replays all historical CSV files into the temporary table
    3. Shows statistics for review
    4. If not dry_run: Swaps tables atomically (zero downtime)
    5. If not dry_run: Updates tlc_vehicle_history table with daily counts
    """
    from pathlib import Path

    from validate.tlc import TLCDatabase

    csv_dir = TLC_PATH

    print("=" * 60)
    print("TLC Vehicles Table Rebuild (Zero-Downtime)")
    print("=" * 60)
    print()
    print("Running in Modal environment")
    print(f"CSV directory: {csv_dir}")
    print()

    # Initialize database connection
    db = TLCDatabase()

    # Verify CSV files exist
    if not Path(csv_dir).exists():
        print(f"\n✗ CSV directory not found at {csv_dir}")
        return {"error": "CSV directory not found"}

    csv_files = list(Path(csv_dir).glob("tlc_vehicles_*.csv"))
    if not csv_files:
        print(f"\n✗ No CSV files found in {csv_dir}")
        return {"error": "No CSV files found"}

    print(f"Found {len(csv_files)} CSV files")

    # Step 1: Build temporary table
    print("\n" + "=" * 60)
    print("STEP 1: Building temporary table")
    print("=" * 60)
    print("\nStarting rebuild into tlc_vehicles_new...")

    try:
        results = db.rebuild_from_csvs(csv_dir, table_name="tlc_vehicles_new", update_history=False)

        print("\n✓ Temporary table built successfully!")
        print("\nResults:")
        print(f"  Files processed: {results['files_processed']}")
        print(f"  Total records (VIN+plate combos): {results['total_records']:,}")
        print(f"  Unique VINs: {results['unique_vins']:,}")
        if results["date_range"]:
            print(f"  Date range: {results['date_range'][0]} to {results['date_range'][1]}")
        if results["errors"]:
            print(f"\n⚠ Errors encountered: {len(results['errors'])}")
            for error in results["errors"]:
                print(f"    - {error}")

    except Exception as e:
        print(f"\n✗ Rebuild failed: {e}")
        raise

    # Step 2: Compare with current table
    print("\n" + "=" * 60)
    print("STEP 2: Comparison with current table")
    print("=" * 60)

    try:
        current_stats = db.get_table_stats("tlc_vehicles")
        new_stats = db.get_table_stats("tlc_vehicles_new")

        print("\nCurrent table (tlc_vehicles):")
        print(f"  Total records: {current_stats['total_records']:,}")
        print(f"  Unique VINs: {current_stats['unique_vins']:,}")

        print("\nNew table (tlc_vehicles_new):")
        print(f"  Total records: {new_stats['total_records']:,}")
        print(f"  Unique VINs: {new_stats['unique_vins']:,}")

        print("\nDifference:")
        print(f"  Records: {new_stats['total_records'] - current_stats['total_records']:+,}")
        print(f"  VINs: {new_stats['unique_vins'] - current_stats['unique_vins']:+,}")

        comparison = {
            "current": current_stats,
            "new": new_stats,
            "difference": {
                "records": new_stats["total_records"] - current_stats["total_records"],
                "vins": new_stats["unique_vins"] - current_stats["unique_vins"],
            },
        }

    except Exception as e:
        print(f"\n⚠ Could not compare tables: {e}")
        comparison = {"error": str(e)}  # type: ignore[dict-item]

    if dry_run:
        # Dry run mode - skip swap and history update
        print("\n" + "=" * 60)
        print("DRY RUN MODE - Skipping table swap")
        print("=" * 60)
        print("\nTemporary table tlc_vehicles_new has been created.")
        print("To complete the rebuild, run again without --dry-run flag.")
        print("To clean up: DROP TABLE tlc_vehicles_new;")

        history_results = {"skipped": "dry_run"}

    else:
        # Step 3: Perform swap
        print("\n" + "=" * 60)
        print("STEP 3: Swapping tables")
        print("=" * 60)
        print("\nProceeding with automatic table swap...")

        try:
            db.swap_tables("tlc_vehicles", "tlc_vehicles_new", "_old")
            print("\n✓ Tables swapped successfully!")
        except Exception as e:
            print(f"\n✗ Table swap failed: {e}")
            print("The temporary table tlc_vehicles_new is still available.")
            raise

        # Step 4: Update history table
        print("\n" + "=" * 60)
        print("STEP 4: Updating history table")
        print("=" * 60)
        print("\nReplaying CSV files to update tlc_vehicle_history...")

        try:
            # Re-run to update history (using production table now)
            history_results = db.rebuild_from_csvs(
                csv_dir, table_name="tlc_vehicles", update_history=True
            )
            print("\n✓ History table updated!")
        except Exception as e:
            print(f"\n⚠ History update failed: {e}")
            print("The main table swap was successful, but history may be incomplete.")
            history_results = {"error": str(e)}

        # Final summary
        print("\n" + "=" * 60)
        print("✓ Rebuild complete!")
        print()
        print("The old table has been backed up as tlc_vehicles_old.")
        print("You can drop it after confirming everything works correctly.")
        print("=" * 60)

    # Commit volume changes
    volume.commit()

    return {
        "success": True,
        "build_results": results,
        "comparison": comparison,
        "history_results": history_results,
    }


@app.local_entrypoint()
def main(
    command: str = "stats",
    limit: int = 5,
    dry_run: bool = False,
    file: str = None,
    files: str = None,
):
    """
    Local CLI for testing Modal functions.

    Usage:
        modal run modal_app.py --command=test
        modal run modal_app.py --command=stats
        modal run modal_app.py --command=post --limit=3 --dry-run=true
        modal run modal_app.py --command=upload --file=path/to/image.jpg
        modal run modal_app.py --command=sync-images
        modal run modal_app.py --command=update-tlc
        modal run modal_app.py --command=backfill-hashes --dry-run=true
        modal run modal_app.py --command=generate-web-data
        modal run modal_app.py --command=migrate-images --dry-run=true
        modal run modal_app.py --command=reprocess-web --files="file1.jpg,file2.jpg" --dry-run=true
        modal run modal_app.py --command=rebuild-tlc --dry-run=true
    """
    import os
    from pathlib import Path

    if command == "test":
        result = get_hello.remote()
        print(f"\nTest result: {result}")
    elif command == "stats":
        get_stats.remote()
    elif command == "post":
        # Use the unified batch posting (works for any number of sightings 1-4)
        post_batch.remote(batch_size=limit if limit <= 4 else 4, dry_run=dry_run)
    elif command == "upload":
        if not file:
            print("✗ Error: --file is required for upload command")
            return
        if not os.path.exists(file):
            print(f"✗ Error: File not found: {file}")
            return

        with open(file, "rb") as f:
            image_data = f.read()
        filename = Path(file).name
        upload_image.remote(filename, image_data)
    elif command == "sync-images":
        # Sync all images from local sightings directory
        local_images_dir = Path("sightings")
        if not local_images_dir.exists():
            print("✗ Error: Local sightings directory not found")
            return

        image_files = (
            list(local_images_dir.glob("*.jpg"))
            + list(local_images_dir.glob("*.jpeg"))
            + list(local_images_dir.glob("*.png"))
        )
        print(f"Found {len(image_files)} images to sync")

        for img_path in image_files:
            print(f"Uploading {img_path.name}...")
            with open(img_path, "rb") as f:
                image_data = f.read()
            upload_image.remote(img_path.name, image_data)

        print(f"\n✓ Synced {len(image_files)} images to Modal volume")
    elif command == "update-tlc":
        print("🔄 Updating TLC vehicle data...")
        update_tlc_vehicles.remote()
    elif command == "backfill-hashes":
        print("🔄 Backfilling image hashes...")
        result = backfill_image_hashes.remote(batch_size=100, dry_run=dry_run)
        print(f"\n✓ Backfill result: {result}")
    elif command == "backfill-r2":
        print("🔄 Backfilling images to R2...")
        result = backfill_r2_images.remote(batch_size=10, dry_run=dry_run)
        print(f"\n✓ Backfill result: {result}")
    elif command == "generate-web-data":
        print("🔄 Generating web data...")
        result = generate_web_data.remote()
        print(f"\n✓ Result: {result}")
    elif command == "migrate-images":
        print("🔄 Migrating image storage to new format...")
        result = migrate_image_storage.remote(batch_size=50, dry_run=dry_run)
        print(f"\n✓ Migration result: {result}")
    elif command == "reprocess-web":
        if not files:
            print("✗ Error: --files is required for reprocess-web command")
            print("  Example: --files='file1.jpg,file2.jpg'")
            return
        filenames = [f.strip() for f in files.split(",")]
        print(f"🔄 Reprocessing {len(filenames)} web images...")
        result = reprocess_web_images.remote(filenames=filenames, dry_run=dry_run)
        print(f"\n✓ Reprocess result: {result}")
    elif command == "rebuild-tlc":
        if dry_run:
            print("🔄 Rebuilding TLC table (DRY RUN MODE)...")
            print("This will build the temporary table but NOT swap it into production.")
        else:
            print("🔄 Rebuilding TLC table...")
            print("⚠️  This WILL swap the tables into production!")
        result = rebuild_tlc_table.remote(dry_run=dry_run)
        if result.get("success"):
            print("\n✓ Success!")
            if result.get("build_results"):
                print(f"  Files processed: {result['build_results']['files_processed']}")
                print(f"  Unique VINs: {result['build_results']['unique_vins']:,}")
            if result.get("comparison") and not result["comparison"].get("error"):
                comp = result["comparison"]
                print(f"\n  Record difference: {comp['difference']['records']:+,}")
                print(f"  VIN difference: {comp['difference']['vins']:+,}")
        else:
            print("\n✗ Failed!")
            print(f"  Error: {result.get('error', 'Unknown error')}")
    else:
        print(f"Unknown command: {command}")
        print(
            "Available commands: test, stats, post, upload, sync-images, update-tlc, backfill-hashes, backfill-r2, generate-web-data, migrate-images, reprocess-web, rebuild-tlc"
        )
