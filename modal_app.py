"""
Modal app for automated Bluesky posting of Fisker Ocean sightings.

This serverless app runs scheduled batch posts to Bluesky.
Images are stored in a Modal volume for persistent access.
"""

import contextlib
from typing import TypedDict

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
        "boto3>=1.42.23",
        "python-multipart>=0.0.6",
        "resend>=2.0.0",
        "anthropic>=0.52.0",
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
# modal secret create cloudflare-pages-deploy CLOUDFLARE_PAGES_DEPLOY_HOOK_URL=<hook-url>
secrets = [
    modal.Secret.from_name("bluesky-credentials"),
    modal.Secret.from_name("neon-db"),
    modal.Secret.from_name("twilio-credentials"),
    modal.Secret.from_name("cloudflare-r2"),
    modal.Secret.from_name("resend-email"),
    modal.Secret.from_name("cloudflare-pages-deploy"),
]

# Create a persistent volume for images and TLC data
volume = modal.Volume.from_name("oceans-of-nyc", create_if_missing=True)
VOLUME_PATH = "/data"
IMAGES_PATH = f"{VOLUME_PATH}/images"
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
        oceans = result["oceans"]
        if oceans["status"] == "success":
            print(f"✓ Web data updated: {oceans['sighted']}/{oceans['total']} vehicles")
        else:
            print(f"⚠️ Web data generation failed: {result}")
    except Exception as e:
        print(f"⚠️ Failed to generate web data: {e}")

    # 1b. Trigger Cloudflare Pages rebuild so static vehicle pages pick up new data
    deploy_hook_url = os.getenv("CLOUDFLARE_PAGES_DEPLOY_HOOK_URL")
    if deploy_hook_url:
        try:
            import requests as _requests
            resp = _requests.post(deploy_hook_url, timeout=10)
            if resp.ok:
                print("✓ Cloudflare Pages rebuild triggered")
            else:
                print(f"⚠️ Deploy hook returned {resp.status_code}")
        except Exception as e:
            print(f"⚠️ Failed to trigger Pages rebuild: {e}")

    # 2. Check and trigger batch post
    try:
        print("🔍 Checking if batch post should be triggered...")
        process_sightings_queue.spawn()
        print("✓ Sightings queue check spawned")
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

    # 1. Upload web version to R2 (with retries)
    import time

    processor = ImageProcessor(volume_path=VOLUME_PATH)
    r2_uploaded = False
    max_r2_attempts = 3

    for attempt in range(1, max_r2_attempts + 1):
        try:
            web_path = processor.get_web_path(image_filename)
            original_path = processor.get_original_path(image_filename)

            if not os.path.exists(web_path):
                print(f"⚠ Web file not found, creating from original: {original_path}")
                if os.path.exists(original_path):
                    web_bytes, _ = processor.create_web_version(original_path)
                    processor.save_web_version_local(web_bytes, image_filename)
                    volume.commit()
                    print(f"✓ Created web version: {web_path}")
                else:
                    print(f"⚠️ Original file not found either: {original_path}")
                    break

            r2_url = processor.upload_web_version(image_filename)
            if r2_url:
                print(f"✓ Uploaded to R2: {r2_url}")
                r2_uploaded = True
                break
            else:
                print(f"⚠️ Web version upload returned None (attempt {attempt}/{max_r2_attempts})")
        except Exception as e:
            print(f"⚠️ R2 upload attempt {attempt}/{max_r2_attempts} failed: {e}")

        if attempt < max_r2_attempts:
            time.sleep(2 ** attempt)

    if not r2_uploaded:
        print(f"❌ R2 upload failed after {max_r2_attempts} attempts for {image_filename}")

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
        modal.Secret.from_name("anthropic-credentials"),
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
    import os
    import re

    from notify.sms import send_sms

    print(f"🔄 Processing SMS from {from_number} asynchronously...")

    # Reload volume to see files committed by other containers (e.g., pending_ images
    # saved in a previous invocation that handled the same user's image upload).
    volume.reload()

    # Check if this number should use the LLM-based handler
    llm_phones = os.getenv("LLM_CHAT_PHONES", "").split(",")
    llm_phones = [p.strip() for p in llm_phones if p.strip()]

    if from_number in llm_phones:
        print(f"🤖 Using LLM handler for {from_number}")
        try:
            from chat.llm_handler import handle_incoming_sms_llm

            response_text = handle_incoming_sms_llm(
                from_number=from_number,
                body=body,
                num_media=num_media,
                media_urls=media_urls,
                media_types=media_types,
                volume_path=VOLUME_PATH,
                channel_type=channel_type,
            )
            if response_text:
                print(f"📤 Sending LLM response to {from_number}")
                send_sms(from_number, response_text)
            volume.commit()
            print(f"✅ LLM SMS processing complete for {from_number}")
            return
        except Exception as e:
            print(f"❌ LLM handler error: {e}")
            import traceback

            traceback.print_exc()
            with contextlib.suppress(Exception):
                send_sms(from_number, "Sorry, something went wrong. Please try again.")
            return

    try:
        from chat.webhook import handle_incoming_sms

        # Process the message using existing state machine logic
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


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
    schedule=modal.Cron("0 22 * * *"),  # Run daily at 10 PM UTC (6 PM ET) as backup
)
def process_sightings_queue(dry_run: bool = False):
    """
    Check for unposted sightings and post batches until conditions are no longer met.

    Posts if:
    - 4 or more sightings are waiting, OR
    - Oldest sighting has been waiting 24+ hours

    Triggered after each sighting is confirmed (via .spawn()) and as a daily backup.

    Args:
        dry_run: If True, only show what would be posted without actually posting
    """
    import os
    from datetime import datetime

    from database import SightingsDatabase
    from post.batch_trigger import should_trigger_batch_post
    from post.bluesky import BlueskyClient

    print(f"🔍 Checking sightings queue at {datetime.now()} (dry_run={dry_run})")
    os.makedirs(IMAGES_PATH, exist_ok=True)
    volume.reload()  # Ensure we see the latest committed files from other containers

    db = SightingsDatabase()
    total_posted = 0

    # Serialize posting across all containers with a Postgres advisory lock.
    # process_sightings_queue is spawned after every confirmed sighting and also
    # runs as a daily cron, so multiple invocations can overlap. Without this lock
    # two workers can both read the same unposted sightings and each post them to
    # Bluesky, producing duplicate posts. A non-blocking try-lock means a second
    # worker simply exits; the holder loops below and drains everything, and the
    # daily backup covers anything left. (dry_run posts nothing, so it skips the
    # lock and never blocks a real post.)
    lock_conn = None
    if not dry_run:
        lock_conn = db.acquire_posting_lock()
        if lock_conn is None:
            print("🔒 Another worker holds the posting lock; exiting to avoid duplicate posts")
            return {"posted": 0, "message": "Another worker is processing the queue"}

    try:
        while True:
            unposted = db.get_unposted_sightings()

            if not unposted:
                print("✓ No unposted sightings found")
                break

            if not should_trigger_batch_post(unposted):
                print(f"✗ Conditions not met: {len(unposted)} sighting(s) waiting")
                break

            sightings_to_post = unposted[:4]
            plates = [s[1] for s in sightings_to_post]
            contributors = set(s[9] for s in sightings_to_post if s[9])
            unique_sighted = db.get_unique_sighted_count()
            total_fiskers = db.get_tlc_vehicle_count()

            print(f"\n📊 Batch ({len(sightings_to_post)} sighting(s)):")
            print(f"   Plates: {', '.join(plates)}")
            print(f"   Contributors: {len(contributors)}")
            print(f"   Progress: {unique_sighted}/{total_fiskers}")

            # Wait for images to become available on the volume.
            # A race condition can occur when the 4th sighting's webhook has written
            # to the DB but hasn't committed its image to the volume yet.
            import time

            from utils.image_processor import ImageProcessor

            processor = ImageProcessor(volume_path=VOLUME_PATH)
            missing_filenames = [
                s[5] for s in sightings_to_post
                if s[5] and not os.path.exists(processor.get_original_path(s[5]))
            ]
            if missing_filenames:
                print(f"⏳ Waiting for {len(missing_filenames)} image(s): {missing_filenames}")
                for attempt in range(6):  # up to ~30 seconds
                    time.sleep(5)
                    volume.reload()
                    missing_filenames = [
                        f for f in missing_filenames
                        if not os.path.exists(processor.get_original_path(f))
                    ]
                    if not missing_filenames:
                        print("✓ All images now available")
                        break
                    print(f"   Still waiting ({attempt + 1}/6): {missing_filenames}")
                if missing_filenames:
                    print(f"⚠️ Proceeding without {len(missing_filenames)} image(s): {missing_filenames}")

            if dry_run:
                print("🔍 DRY RUN - not posting")
                return {
                    "posted": 0,
                    "message": f"Dry run: would post {len(sightings_to_post)} sightings",
                    "plates": plates,
                    "contributors": len(contributors),
                }

            try:
                sighting_ids = [s[0] for s in sightings_to_post]
                new_badges = db.get_badges_for_sightings(sighting_ids)
                client = BlueskyClient()
                response = client.create_batch_sighting_post(
                    sightings=sightings_to_post,
                    unique_sighted=unique_sighted,
                    total_fiskers=total_fiskers,
                    new_badges=new_badges,
                )

                sighting_ids = [s[0] for s in sightings_to_post]
                db.mark_batch_as_posted(sighting_ids, response.uri)
                total_posted += len(sighting_ids)

                print(f"✓ Posted {len(sighting_ids)} sighting(s), URI: {response.uri}")

            except Exception as e:
                print(f"❌ Error posting batch: {e}")
                import traceback

                traceback.print_exc()
                return {"posted": total_posted, "error": str(e)}
    finally:
        db.release_posting_lock(lock_conn)

    return {"posted": total_posted, "message": f"Posted {total_posted} sighting(s)"}


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
    from utils.image_processor import ImageProcessor
    from utils.r2_storage import R2Storage
    from validate.tlc import validate_plate

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
            valid_boroughs = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island", "Outside NYC"]
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
            # Always compute unique_name from the display name
            web_identifier = contributor_name.strip().lower().replace(' ', '_')

            # Priority: email (if provided) > name-based identifier
            if email and email.strip():
                # Use email as primary identifier - provides stable identity across submissions
                contributor_id = db.get_or_create_contributor(email=email.strip(), unique_name=web_identifier)
            else:
                # Fallback to name-based identifier for anonymous submissions
                contributor_id = db.get_or_create_contributor(unique_name=web_identifier)

            # Update the contributor's preferred name and unique_name if not yet set
            conn = db._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE contributors SET preferred_name = %s WHERE id = %s AND preferred_name IS NULL",
                (contributor_name.strip(), contributor_id),
            )
            cursor.execute(
                "UPDATE contributors SET unique_name = %s WHERE id = %s AND unique_name IS NULL",
                (web_identifier, contributor_id),
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
                borough=borough,
                image_timestamp=image_timestamp,
                vin=vin,
            )

            if result is None:
                return JSONResponse(
                    status_code=500,
                    content={
                        "success": False,
                        "error": "database_error",
                        "message": "Failed to save sighting",
                    },
                )

            sighting_id = result["id"]

            # Evaluate badges BEFORE running hooks, so web data generation
            # and Bluesky posts include the newly earned badges
            from utils.sighting_confirmation import get_confirmation_data

            conf = get_confirmation_data(db, plate, contributor_id, vin, sighting_id)

            # Run post-submission hooks (web data, batch post, notification)
            run_post_submission_hooks(
                plate=plate,
                contributor_id=contributor_id,
                contributor_name=contributor_name.strip(),
                borough=borough,
                image_filename=image_filename,
                sighting_id=sighting_id,
            )

            # Commit volume changes
            volume.commit()

            if conf["ocean_points"] is not None:
                message = (
                    f"Ocean #{conf['global_unique_sighting_index']} discovered! "
                    f"Vehicle {plate} recorded. Earned {conf['ocean_points']:.1f} ◎p!"
                )
            else:
                message = f"Sighting submitted successfully! Vehicle {plate} recorded."

            return JSONResponse(
                content={
                    "success": True,
                    "message": message,
                    "sighting_id": sighting_id,
                    "stats": {
                        "vehicle_sighting_num": conf["vehicle_sighting_num"],
                        "total_sightings": conf["total_sightings"],
                        "contributor_sighting_num": conf["contributor_sighting_num"],
                    },
                    "new_badges": conf["new_badges"],
                    "ocean_points": conf["ocean_points"],
                    "global_unique_sighting_index": conf["global_unique_sighting_index"],
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


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
    secrets=[
        modal.Secret.from_name("cloudflare-r2"),
    ],
    timeout=300,
)
def process_uploaded_image(image_filename: str):
    """
    Process an image that has already been uploaded to the Modal volume.

    Creates the web-optimized version and uploads it to R2.
    Used by `just reprocess-image` after uploading the original via `modal volume put`.
    """
    import os

    from utils.image_processor import ImageProcessor

    processor = ImageProcessor(volume_path=VOLUME_PATH)
    original_path = processor.get_original_path(image_filename)

    if not os.path.exists(original_path):
        print(f"❌ Original not found: {original_path}")
        return {"success": False, "error": "Original not found in volume"}

    print(f"✓ Found original: {original_path} ({os.path.getsize(original_path)} bytes)")

    # Create web version
    web_bytes, _ = processor.create_web_version(original_path)
    processor.save_web_version_local(web_bytes, image_filename)
    print(f"✓ Created web version ({len(web_bytes)} bytes)")

    # Upload to R2
    r2_url = processor.upload_web_version(image_filename)
    if r2_url:
        print(f"✓ Uploaded to R2: {r2_url}")
    else:
        print("❌ R2 upload failed")

    volume.commit()
    print(f"✅ Processing complete for {image_filename}")
    return {"success": True, "filename": image_filename, "r2_url": r2_url}


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
    timeout=3600,
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

    oceans = result["oceans"]
    daily = result["daily_sightings"]
    if oceans["status"] == "success" and daily["status"] == "success":
        print("✓ Web data generated and uploaded successfully")
        print(f"  Sightings: {oceans['sighted']}/{oceans['total']} vehicles")
        print(f"  Daily sightings: {daily['days']} days")
    else:
        print(f"❌ Failed to generate web data: {result}")

    return result


class CleanupStats(TypedDict):
    """Statistics for R2 cleanup operation."""

    total_sightings: int
    already_in_r2: int
    missing_from_r2: int
    uploaded_successfully: int
    upload_failed: int
    web_file_missing: int
    errors: list[str]


class BadgeBackfillStats(TypedDict):
    """Statistics for badge backfill operation."""

    total_contributors: int
    contributors_with_new_badges: int
    total_badges_awarded: int
    errors: list[str]


class PlateOCREvalResult(TypedDict):
    """Results from a plate OCR accuracy evaluation run."""

    sample_size: int
    evaluated: int
    correct: int
    wrong: int
    no_result: int
    skipped: int
    accuracy: float
    recall: float


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("anthropic-credentials"),
    ],
    timeout=3600,
)
def eval_plate_ocr(sample_size: int = 50, seed: int | None = None) -> PlateOCREvalResult:
    """
    Evaluate plate OCR accuracy against labeled sightings.

    Randomly samples sightings_export rows that have both image_filename and
    license_plate set, reads each original image from the Modal volume, runs
    extract_plate_from_image, and compares the result to the known plate.

    Args:
        sample_size: Number of sightings to evaluate (default: 50)
        seed: Random seed for reproducibility (default: random)

    Returns:
        PlateOCREvalResult with accuracy and recall metrics
    """
    import os
    import random

    import psycopg2

    from utils.plate_ocr import extract_plate_from_image

    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT image_filename, license_plate
        FROM sightings_export
        WHERE image_filename IS NOT NULL
          AND license_plate  IS NOT NULL
    """)
    rows = cursor.fetchall()
    conn.close()

    rng = random.Random(seed)
    rng.shuffle(rows)
    sample = rows[:sample_size]
    actual_n = len(sample)

    print(f"Evaluating {actual_n} sightings (seed={seed}, pool={len(rows)})")

    correct = 0
    wrong = 0
    no_result = 0
    skipped = 0

    for i, (image_filename, known_plate) in enumerate(sample, 1):
        original_path = f"{VOLUME_PATH}/sightings/original/{image_filename}"
        try:
            with open(original_path, "rb") as f:
                image_bytes = f.read()
        except OSError as e:
            print(f"[{i}/{actual_n}] SKIP   {image_filename} ({e})")
            skipped += 1
            continue

        extracted = extract_plate_from_image(image_bytes)

        if extracted is None:
            no_result += 1
            status = "MISS  "
        elif extracted == known_plate:
            correct += 1
            status = "OK    "
        else:
            wrong += 1
            status = "WRONG "

        print(f"[{i}/{actual_n}] {status} known={known_plate}  extracted={extracted}  ({image_filename})")

    evaluated = correct + wrong + no_result
    accuracy = round(correct / evaluated * 100, 1) if evaluated else 0.0
    recall = round(correct / (correct + no_result) * 100, 1) if (correct + no_result) else 0.0

    return PlateOCREvalResult(
        sample_size=sample_size,
        evaluated=evaluated,
        correct=correct,
        wrong=wrong,
        no_result=no_result,
        skipped=skipped,
        accuracy=accuracy,
        recall=recall,
    )


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("cloudflare-r2"),
    ],
    timeout=3600,  # 1 hour timeout for large cleanup jobs
    schedule=modal.Period(hours=1),
)
def cleanup_missing_r2_uploads(dry_run: bool = False, limit: int | None = None, since_hours: int = 24, recover_from_twilio: bool = True, recover_pending: bool = True) -> CleanupStats:
    """
    Find and upload missing images to R2.

    Scans all sightings in the database and uploads any web versions that are
    missing from R2. If web version doesn't exist locally, attempts to create
    it from the original image.

    Args:
        dry_run: If True, only report what would be uploaded without uploading
        limit: Maximum number of images to process (None = all)
        since_hours: Only consider sightings created in the last N hours (default: 24)
        recover_from_twilio: If True, spawn recover_images_from_twilio for any images
                             missing from both R2 and the Modal volume
        recover_pending: If True, when the final-named original is missing, look for a
                         pending_YYYYMMDD_HHMMSS_*.jpg file with matching timestamp and
                         rename it to the final filename before processing

    Returns:
        Dictionary with cleanup statistics
    """
    import os
    from datetime import datetime, timedelta, timezone

    from database.models import SightingsDatabase
    from utils.r2_storage import R2Storage, R2UploadError

    print("=" * 80)
    print("R2 CLEANUP SCRIPT")
    print("=" * 80)
    if dry_run:
        print("🔍 DRY RUN MODE - No uploads will be performed")
    print(f"⏱ Considering sightings from the last {since_hours} hours")
    print()

    # Initialize database and R2
    db = SightingsDatabase()
    r2 = R2Storage()

    # Track statistics
    stats: CleanupStats = {
        "total_sightings": 0,
        "already_in_r2": 0,
        "missing_from_r2": 0,
        "uploaded_successfully": 0,
        "upload_failed": 0,
        "web_file_missing": 0,
        "errors": [],
    }

    # Get sightings created within the last since_hours
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, image_filename, license_plate
        FROM sightings
        WHERE image_filename IS NOT NULL
          AND created_at >= %s
        ORDER BY id
        """,
        (since.isoformat(),),
    )
    sightings = cursor.fetchall()
    conn.close()

    stats["total_sightings"] = len(sightings)
    print(f"📊 Found {stats['total_sightings']} sightings with images in the last {since_hours}h")
    print()

    processed = 0
    missing_both: list[str] = []  # filenames missing from both volume and R2
    for sighting_id, image_filename, license_plate in sightings:
        # Check if we've hit the limit
        if limit and processed >= limit:
            print(f"⏸ Reached processing limit of {limit} images")
            break

        # Check if file already exists in R2
        object_key = f"sightings/{image_filename}"
        if r2.file_exists(object_key):
            stats["already_in_r2"] += 1
            continue

        stats["missing_from_r2"] += 1
        processed += 1

        print(
            f"[{processed}] Processing: {image_filename} (ID: {sighting_id}, Plate: {license_plate})"
        )

        # Check if web version exists in Modal storage
        web_path = f"{VOLUME_PATH}/sightings/web/{image_filename}"
        if not os.path.exists(web_path):
            print(f"  ⚠ Web file not found: {web_path}")
            stats["web_file_missing"] += 1

            # Try to find original and create web version
            original_path = f"{VOLUME_PATH}/sightings/original/{image_filename}"
            if os.path.exists(original_path):
                print(f"  🔄 Creating web version from original: {original_path}")
                if not dry_run:
                    try:
                        from utils.image_processor import ImageProcessor

                        processor = ImageProcessor(volume_path=VOLUME_PATH)
                        web_bytes, _ = processor.create_web_version(original_path)
                        processor.save_web_version_local(web_bytes, image_filename)
                        print(f"  ✓ Created web version: {web_path}")
                    except Exception as e:
                        error_msg = f"Failed to create web version for {image_filename}: {e}"
                        print(f"  ✗ {error_msg}")
                        stats["errors"].append(error_msg)
                        stats["upload_failed"] += 1
                        continue
            else:
                # Try to find a pending_ file with a matching timestamp
                pending_found = False
                if recover_pending:
                    import glob
                    import re as _re

                    # Final filename format: PLATE_YYYYMMDD_HHMMSS_MMMM.jpg
                    # Pending filename format: pending_YYYYMMDD_HHMMSS_PPPP.jpg
                    ts_match = _re.search(r"_(\d{8}_\d{6})_", image_filename)
                    if ts_match:
                        ts_part = ts_match.group(1)
                        pattern = f"{VOLUME_PATH}/sightings/original/pending_{ts_part}_*.jpg"
                        candidates = glob.glob(pattern)
                        if candidates:
                            pending_path = candidates[0]
                            print(f"  🔍 Found pending file: {os.path.basename(pending_path)}")
                            if dry_run:
                                print(f"  [DRY RUN] Would rename: {os.path.basename(pending_path)} → {image_filename}")
                                pending_found = True
                            else:
                                import shutil
                                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                                shutil.move(pending_path, original_path)
                                print(f"  ✓ Renamed pending → {image_filename}")
                                # Rename pending web version if it exists, otherwise create from original
                                pending_web = f"{VOLUME_PATH}/sightings/web/{os.path.basename(pending_path)}"
                                final_web = f"{VOLUME_PATH}/sightings/web/{image_filename}"
                                if os.path.exists(pending_web):
                                    shutil.move(pending_web, final_web)
                                    print(f"  ✓ Renamed pending web version → {image_filename}")
                                    pending_found = True
                                else:
                                    try:
                                        from utils.image_processor import ImageProcessor
                                        _proc = ImageProcessor(volume_path=VOLUME_PATH)
                                        web_bytes, _ = _proc.create_web_version(original_path)
                                        _proc.save_web_version_local(web_bytes, image_filename)
                                        print(f"  ✓ Created web version from recovered original")
                                        pending_found = True
                                    except Exception as e:
                                        error_msg = f"Failed to create web version after pending recovery for {image_filename}: {e}"
                                        print(f"  ✗ {error_msg}")
                                        stats["errors"].append(error_msg)
                                        stats["upload_failed"] += 1
                        else:
                            print(f"  ✗ No pending file matching timestamp {ts_part}")

                if not pending_found:
                    print(f"  ✗ Original file also missing: {original_path}")
                    stats["errors"].append(f"Both web and original missing for {image_filename}")
                    stats["upload_failed"] += 1
                    missing_both.append(image_filename)
                    continue

        # Upload to R2
        object_key = f"sightings/{image_filename}"
        if dry_run:
            print(f"  [DRY RUN] Would upload: {web_path} → {object_key}")
            stats["uploaded_successfully"] += 1
        else:
            try:
                # Read web file
                with open(web_path, "rb") as f:
                    web_bytes = f.read()

                # Upload to R2 with retry logic
                print(f"  ⬆ Uploading to R2: {object_key}")
                r2_url = r2.upload_bytes(
                    web_bytes, object_key, content_type="image/jpeg", verify=True
                )
                print(f"  ✓ Uploaded successfully: {r2_url}")
                stats["uploaded_successfully"] += 1

            except R2UploadError as e:
                error_msg = f"R2 upload failed for {image_filename}: {e}"
                print(f"  ✗ {error_msg}")
                stats["errors"].append(error_msg)
                stats["upload_failed"] += 1
            except Exception as e:
                error_msg = f"Unexpected error for {image_filename}: {e}"
                print(f"  ✗ {error_msg}")
                stats["errors"].append(error_msg)
                stats["upload_failed"] += 1

        print()

    # Commit volume changes if we created any web versions
    if not dry_run:
        volume.commit()
        print("💾 Volume changes committed")

    # Spawn Twilio recovery for images missing from both volume and R2
    if recover_from_twilio and missing_both:
        print(f"\n🔄 Spawning Twilio recovery for {len(missing_both)} image(s)...")
        recover_images_from_twilio.spawn(filenames=missing_both, dry_run=dry_run)

    # Print summary
    print()
    print("=" * 80)
    print("CLEANUP SUMMARY")
    print("=" * 80)
    print(f"Total sightings with images: {stats['total_sightings']}")
    print(f"Already in R2: {stats['already_in_r2']}")
    print(f"Missing from R2: {stats['missing_from_r2']}")
    print()
    print(f"✓ Successfully uploaded: {stats['uploaded_successfully']}")
    print(f"✗ Failed uploads: {stats['upload_failed']}")
    print(f"⚠ Web files missing (created from original): {stats['web_file_missing']}")
    print()

    if stats["errors"]:
        print("ERRORS:")
        for error in stats["errors"][:10]:  # Show first 10 errors
            print(f"  - {error}")
        if len(stats["errors"]) > 10:
            print(f"  ... and {len(stats['errors']) - 10} more errors")
    print("=" * 80)

    return stats


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("twilio-credentials"),
        modal.Secret.from_name("cloudflare-r2"),
    ],
    timeout=3600,
)
def recover_images_from_twilio(filenames: list[str] | None = None, dry_run: bool = False) -> dict:
    """
    Recover sightings whose images are missing from both R2 and Modal volume.

    All targets must be SMS/MMS submissions. This function queries the Twilio API to find
    the original MMS message for each sighting, re-downloads the image, saves it
    to the Modal volume as both original and web versions, and uploads the web
    version to R2.

    Args:
        filenames: Image filenames to recover. Contributor phone number and created_at
                   are looked up from the database for each filename. If None or empty,
                   nothing is recovered.
        dry_run: If True, report what would be done without writing any files.

    Matching strategy: the filename encodes a processing timestamp (datetime.now()
    at the time the image was saved, since Twilio strips EXIF from stored media).
    For each sighting we parse that timestamp from the filename and find the Twilio
    message whose date_sent is closest to it (messages arrive seconds before the
    image is saved). When multiple sightings share the same phone number we track
    used message SIDs so each message is assigned to at most one sighting.

    Can be triggered manually via: modal run modal_app.py --command=recover-images --files=<csv>
    """
    import os
    from datetime import datetime, timedelta, timezone

    import psycopg2
    import requests
    from twilio.rest import Client as TwilioClient

    from utils.image_processor import ImageProcessor
    from utils.r2_storage import R2Storage, R2UploadError

    if not filenames:
        print("No filenames provided — nothing to recover.")
        return {"total": 0, "recovered": 0, "already_in_r2": 0, "not_found_in_twilio": 0, "failed": 0, "errors": []}

    # Look up sighting data (sighting_id, phone_number) from the database.
    # unique_name on contributors stores the phone number for SMS submitters.
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT s.id, s.image_filename, s.license_plate, c.unique_name, s.created_at::text
        FROM sightings s
        JOIN contributors c ON s.contributor_id = c.id
        WHERE s.image_filename = ANY(%s)
        ORDER BY s.id
        """,
        (filenames,),
    )
    rows = cursor.fetchall()
    conn.close()

    found_filenames = {row[1] for row in rows}
    for fn in filenames:
        if fn not in found_filenames:
            print(f"WARNING: {fn} not found in database — skipping")

    # Fields: (sighting_id, image_filename, license_plate, phone_number, created_at_iso)
    missing_sightings = list(rows)

    def parse_filename_timestamp(filename: str) -> datetime:
        """
        Parse the processing timestamp embedded in a sighting filename.

        Filename format: {plate}_{yyyymmdd_hhmmss}_{subsec}.jpg
        e.g. "T663358C_20260406_144455_9612.jpg" → datetime(2026, 4, 6, 14, 44, 55)

        The timestamp is UTC (Modal functions run in UTC) with second precision.
        """
        parts = filename.replace(".jpg", "").split("_")
        # parts: [plate_prefix, plate_suffix?, date, time, subsec]
        # Robustly find the date (8-digit) and time (6-digit) parts
        date_part = next(p for p in parts if len(p) == 8 and p.isdigit())
        time_part = next(p for p in parts if len(p) == 6 and p.isdigit())
        return datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S").replace(
            tzinfo=timezone.utc
        )

    account_sid = os.environ["TWILIO_ACCOUNT_SID"]
    auth_token = os.environ["TWILIO_AUTH_TOKEN"]
    twilio_client = TwilioClient(account_sid, auth_token)

    r2 = R2Storage()
    processor = ImageProcessor(volume_path=VOLUME_PATH)

    stats = {
        "total": len(missing_sightings),
        "recovered": 0,
        "already_in_r2": 0,
        "not_found_in_twilio": 0,
        "failed": 0,
        "errors": [],
    }

    print("=" * 80)
    print("TWILIO IMAGE RECOVERY")
    print("=" * 80)
    if dry_run:
        print("DRY RUN — no files will be written or uploaded")
    print()

    # Track which Twilio message SIDs have already been claimed so the same
    # MMS is not assigned to two sightings when a contributor sent multiple
    # photos in a short window.
    claimed_message_sids: set[str] = set()

    for sighting_id, target_filename, plate, phone_number, created_at_str in missing_sightings:
        print(f"[{sighting_id}] {target_filename}  ({phone_number})")

        # Skip if already in R2 (a previous partial recovery may have succeeded)
        r2_key = f"sightings/{target_filename}"
        if r2.file_exists(r2_key):
            print(f"  Already in R2 — skipping")
            stats["already_in_r2"] += 1
            continue

        # The timestamp embedded in the filename is when the image was saved during
        # processing (datetime.now()), since Twilio strips EXIF from stored media.
        # Twilio date_sent arrives a few seconds before this processing timestamp.
        filename_ts = parse_filename_timestamp(target_filename)
        window_start = filename_ts - timedelta(minutes=3)
        window_end = filename_ts + timedelta(seconds=30)

        print(f"  Filename timestamp: {filename_ts.strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"  Twilio search window: {window_start.strftime('%H:%M:%S')} – {window_end.strftime('%H:%M:%S')} UTC")

        try:
            twilio_messages = twilio_client.messages.list(
                from_=phone_number,
                date_sent_after=window_start,
                date_sent_before=window_end,
            )
        except Exception as e:
            error = f"Twilio API error for sighting {sighting_id}: {e}"
            print(f"  ERROR: {error}")
            stats["errors"].append(error)
            stats["failed"] += 1
            continue

        # Filter to messages not already claimed and that have media
        candidate_messages = [
            msg for msg in twilio_messages
            if msg.sid not in claimed_message_sids and int(msg.num_media or 0) > 0
        ]
        print(f"  Twilio messages in window: {len(twilio_messages)} total, {len(candidate_messages)} unclaimed with media")

        if not candidate_messages:
            print(f"  No unclaimed media messages found in window")
            stats["not_found_in_twilio"] += 1
            continue

        # Pick the message whose date_sent is closest to the filename timestamp.
        # date_sent is when Twilio received the MMS, which is a few seconds before
        # our processing timestamp.
        def seconds_from_filename_ts(msg) -> float:
            msg_dt = msg.date_sent
            if msg_dt.tzinfo is None:
                msg_dt = msg_dt.replace(tzinfo=timezone.utc)
            else:
                msg_dt = msg_dt.astimezone(timezone.utc)
            return abs((msg_dt - filename_ts).total_seconds())

        best_msg = min(candidate_messages, key=seconds_from_filename_ts)
        best_dt = best_msg.date_sent
        if best_dt.tzinfo is None:
            best_dt = best_dt.replace(tzinfo=timezone.utc)
        delta_s = (filename_ts - best_dt.astimezone(timezone.utc)).total_seconds()
        print(f"  Best match: {best_msg.sid}  date_sent={best_dt.strftime('%H:%M:%S')} UTC  (Δ {delta_s:+.0f}s vs filename_ts)")

        # Warn if the match is suspiciously far away
        if abs(delta_s) > 120:
            print(f"  WARNING: best match is {abs(delta_s):.0f}s away — may be wrong image")

        # Download the media from the matched message
        try:
            media_list = twilio_client.messages(best_msg.sid).media.list()
        except Exception as e:
            error = f"Could not fetch media for message {best_msg.sid}: {e}"
            print(f"  ERROR: {error}")
            stats["errors"].append(error)
            stats["failed"] += 1
            continue

        if not media_list:
            print(f"  No media objects on message {best_msg.sid} — skipping")
            stats["not_found_in_twilio"] += 1
            continue

        media = media_list[0]
        media_url = f"https://api.twilio.com{media.uri.replace('.json', '')}"
        try:
            resp = requests.get(media_url, auth=(account_sid, auth_token), timeout=30)
            resp.raise_for_status()
            matched_image = resp.content
        except Exception as e:
            error = f"Could not download media {media.sid}: {e}"
            print(f"  ERROR: {error}")
            stats["errors"].append(error)
            stats["failed"] += 1
            continue

        claimed_message_sids.add(best_msg.sid)
        print(f"  Downloaded {len(matched_image):,} bytes from media {media.sid}")

        if dry_run:
            print(f"  [DRY RUN] Would save original + web version and upload to R2: {r2_key}")
            stats["recovered"] += 1
            print()
            continue

        try:
            # Save original to volume
            processor.save_original(matched_image, target_filename)
            print(f"  Saved original: {VOLUME_PATH}/sightings/original/{target_filename}")

            # Create and save web-optimized version
            web_bytes, _ = processor.create_web_version_from_bytes(matched_image)
            processor.save_web_version_local(web_bytes, target_filename)
            print(f"  Saved web version: {VOLUME_PATH}/sightings/web/{target_filename}")

            # Upload web version to R2
            r2_url = r2.upload_bytes(web_bytes, r2_key, content_type="image/jpeg", verify=True)
            print(f"  Uploaded to R2: {r2_url}")

            stats["recovered"] += 1
        except R2UploadError as e:
            error = f"R2 upload failed for sighting {sighting_id} ({target_filename}): {e}"
            print(f"  ERROR: {error}")
            stats["errors"].append(error)
            stats["failed"] += 1
        except Exception as e:
            error = f"Unexpected error for sighting {sighting_id} ({target_filename}): {e}"
            print(f"  ERROR: {error}")
            stats["errors"].append(error)
            stats["failed"] += 1

        print()

    if not dry_run and stats["recovered"] > 0:
        volume.commit()
        print("Volume committed")

    print()
    print("=" * 80)
    print("RECOVERY SUMMARY")
    print("=" * 80)
    print(f"Total targets:           {stats['total']}")
    print(f"Already in R2:           {stats['already_in_r2']}")
    print(f"Recovered:               {stats['recovered']}")
    print(f"Not found in Twilio:     {stats['not_found_in_twilio']}")
    print(f"Failed:                  {stats['failed']}")
    if stats["errors"]:
        print("Errors:")
        for err in stats["errors"]:
            print(f"  - {err}")
    print("=" * 80)

    return stats


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("neon-db")],
)
def backfill_badge_sighting_ids():
    """
    Backfill sighting_id on existing contributor_badges rows.

    For each badge row where sighting_id IS NULL, runs the badge's sighting_sql
    (if defined) to find the earning sighting and updates the record.

    Safe to re-run — only updates rows where sighting_id is still NULL.

    Can be triggered manually via: modal run modal_app.py --command=backfill-badge-sightings
    """
    from badges.definitions import BADGE_BY_NAME
    from database import SightingsDatabase

    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT contributor_id, badge_name
            FROM contributors_badges
            WHERE sighting_id IS NULL
            ORDER BY contributor_id, badge_name
            """
        )
        rows = cursor.fetchall()
        print(f"Found {len(rows)} badge row(s) with no sighting_id")

        updated = 0
        skipped = 0

        for contributor_id, badge_name in rows:
            badge = BADGE_BY_NAME.get(badge_name)

            if badge is None:
                print(f"  WARNING: unknown badge '{badge_name}' — skipping")
                skipped += 1
                continue

            if not badge.sighting_sql:
                skipped += 1
                continue

            sighting_sql = badge.sighting_sql.replace("$1", "%s")
            param_count = sighting_sql.count("%s")
            cursor.execute(sighting_sql, (contributor_id,) * param_count)
            result = cursor.fetchone()

            if result is None:
                print(
                    f"  WARNING: no earning sighting found for contributor {contributor_id}, badge '{badge_name}'"
                )
                skipped += 1
                continue

            sighting_id = result[0]
            cursor.execute(
                """
                UPDATE contributors_badges
                SET sighting_id = %s
                WHERE contributor_id = %s AND badge_name = %s
                """,
                (sighting_id, contributor_id, badge_name),
            )
            updated += 1

        conn.commit()
        print(f"Done. Updated: {updated}, skipped: {skipped}")
        return {"updated": updated, "skipped": skipped}

    except Exception as e:
        conn.rollback()
        print(f"Error during backfill: {e}")
        raise
    finally:
        conn.close()


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("neon-db")],
    timeout=3600,
)
def backfill_missing_badges(dry_run: bool = False) -> BadgeBackfillStats:
    """
    Find and award any badges that contributors have earned but not yet received.

    Evaluates all badge criteria for every contributor and awards any that are
    missing. Safe to re-run — existing badges are skipped via ON CONFLICT DO NOTHING.

    Args:
        dry_run: If True, only report what would be awarded without saving

    Returns:
        Dictionary with backfill statistics
    """
    from badges.definitions import BADGE_BY_NAME
    from badges.evaluator import evaluate_all_badges_for_contributor
    from database import SightingsDatabase

    print("=" * 80)
    print("BADGE BACKFILL")
    print("=" * 80)
    if dry_run:
        print("DRY RUN MODE - No badges will be saved")
    print()

    db = SightingsDatabase()
    contributors = db.get_all_contributors()

    stats: BadgeBackfillStats = {
        "total_contributors": len(contributors),
        "contributors_with_new_badges": 0,
        "total_badges_awarded": 0,
        "errors": [],
    }

    print(f"Evaluating badges for {len(contributors)} contributor(s)...")
    print()

    for contributor in contributors:
        contributor_id = contributor["id"]
        display_name = (
            contributor.get("preferred_name")
            or contributor.get("bluesky_handle")
            or f"Contributor #{contributor_id}"
        )

        try:
            existing_badges = set(db.get_contributor_badge_names(contributor_id))
            qualified = evaluate_all_badges_for_contributor(db, contributor_id)
            new_badges = [(name, sid) for name, sid in qualified if name not in existing_badges]

            if not new_badges:
                continue

            stats["contributors_with_new_badges"] += 1

            if dry_run:
                print(f"  {display_name}: would earn {len(new_badges)} badge(s)")
                for badge_name, _ in new_badges:
                    badge_def = BADGE_BY_NAME.get(badge_name)
                    if badge_def:
                        print(f"    - {badge_def.emoji} {badge_def.display_name}")
                stats["total_badges_awarded"] += len(new_badges)
            else:
                saved = db.save_badges(contributor_id, new_badges)
                stats["total_badges_awarded"] += saved
                print(f"  {display_name}: awarded {saved} badge(s)")
                for badge_name, _ in new_badges:
                    badge_def = BADGE_BY_NAME.get(badge_name)
                    if badge_def:
                        print(f"    - {badge_def.emoji} {badge_def.display_name}")

        except Exception as e:
            error_msg = f"Error processing contributor {contributor_id}: {e}"
            print(f"  ERROR: {error_msg}")
            stats["errors"].append(error_msg)

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total contributors: {stats['total_contributors']}")
    if dry_run:
        print(f"Would award badges to: {stats['contributors_with_new_badges']} contributor(s)")
        print(f"Total badges to award: {stats['total_badges_awarded']}")
    else:
        print(f"Contributors with new badges: {stats['contributors_with_new_badges']}")
        print(f"Total badges awarded: {stats['total_badges_awarded']}")
    if stats["errors"]:
        print(f"Errors: {len(stats['errors'])}")
        for error in stats["errors"]:
            print(f"  - {error}")
    print("=" * 80)

    return stats


@app.local_entrypoint()
def main(
    command: str = "stats",
    limit: int = 5,
    dry_run: bool = False,
    file: str = None,
    files: str = None,
    seed: int = None,
    recover_pending: bool = False,
    since_hours: int = 24,
):
    """
    Local CLI for testing Modal functions.

    Usage:
        modal run modal_app.py --command=test
        modal run modal_app.py --command=stats
        modal run modal_app.py --command=post --dry-run=true
        modal run modal_app.py --command=upload --file=path/to/image.jpg
        modal run modal_app.py --command=sync-images
        modal run modal_app.py --command=update-tlc
        modal run modal_app.py --command=generate-web-data
        modal run modal_app.py --command=cleanup-r2 --dry-run=true
        modal run modal_app.py --command=cleanup-r2 --limit=10
        modal run modal_app.py --command=cleanup-r2 --files=1  # also spawn Twilio recovery for any both-missing
        modal run modal_app.py --command=cleanup-r2 --recover-pending=true --since-hours=720  # rename pending_ files to final names (last 30 days)
        modal run modal_app.py --command=backfill-badge-sightings
        modal run modal_app.py --command=backfill-badges --dry-run=true
        modal run modal_app.py --command=backfill-badges
        modal run modal_app.py --command=recover-images --files="T146420C_20260421_015725_8135.jpg,..."
        modal run modal_app.py --command=recover-images --dry-run=true --files="..."
        modal run modal_app.py --command=eval-plate-ocr --limit=50
        modal run modal_app.py --command=eval-plate-ocr --limit=100 --seed=42
    """
    import os
    from pathlib import Path

    if command == "post":
        process_sightings_queue.remote(dry_run=dry_run)
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
    elif command == "generate-web-data":
        print("🔄 Generating web data...")
        result = generate_web_data.remote()
        print(f"\n✓ Result: {result}")
    elif command == "cleanup-r2":
        print("🔄 Cleaning up missing R2 uploads...")
        result = cleanup_missing_r2_uploads.remote(
            dry_run=dry_run,
            limit=limit if limit != 5 else None,
            since_hours=since_hours,
            recover_from_twilio=bool(files),
            recover_pending=recover_pending,
        )
        print(f"\n✓ Cleanup result: {result}")
    elif command == "backfill-badge-sightings":
        print("🔄 Backfilling sighting_id on contributor_badges...")
        result = backfill_badge_sighting_ids.remote()
        print(f"\n✓ Result: {result}")
    elif command == "backfill-badges":
        print("🔄 Backfilling missing badges..." + (" (dry run)" if dry_run else ""))
        result = backfill_missing_badges.remote(dry_run=dry_run)
        print(f"\n✓ Result: {result}")
    elif command == "recover-images":
        target_filenames = [f.strip() for f in files.split(",") if f.strip()] if files else []
        if not target_filenames:
            print("✗ --files is required (comma-separated image filenames)")
            return
        print(f"🔄 Recovering {len(target_filenames)} image(s) from Twilio..." + (" (dry run)" if dry_run else ""))
        result = recover_images_from_twilio.remote(filenames=target_filenames, dry_run=dry_run)
        print(f"\n✓ Result: {result}")
    elif command == "eval-plate-ocr":
        sample = limit if limit != 5 else 50
        print(f"🔄 Evaluating plate OCR on {sample} sightings" + (f" (seed={seed})" if seed else "") + "...")
        result = eval_plate_ocr.remote(sample_size=sample, seed=seed)
        print(f"\n{'─' * 40}")
        print(f"Evaluated : {result['evaluated']}")
        print(f"Correct   : {result['correct']}")
        print(f"Wrong     : {result['wrong']}")
        print(f"No result : {result['no_result']}")
        if result["skipped"]:
            print(f"Skipped   : {result['skipped']} (missing from volume)")
        print(f"Accuracy  : {result['accuracy']}%  (correct / evaluated)")
        print(f"Recall    : {result['recall']}%  (correct / correct+no-result)")
    else:
        print(f"Unknown command: {command}")
        print(
            "Available commands: post, upload, sync-images, update-tlc, generate-web-data, "
            "cleanup-r2, backfill-badge-sightings, backfill-badges, recover-images, eval-plate-ocr"
        )
