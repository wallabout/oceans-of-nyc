"""
Modal app for automated Bluesky posting of Fisker Ocean sightings.

This serverless app runs scheduled batch posts to Bluesky.
Images are stored in a Modal volume for persistent access.
"""

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
    )
    .add_local_python_source("database")
    .add_local_python_source("validate")
    .add_local_python_source("geolocate")
    .add_local_python_source("post")
    .add_local_python_source("chat")
)

# Define secrets
# To set these up, run:
# modal secret create bluesky-credentials BLUESKY_HANDLE=<handle> BLUESKY_PASSWORD=<password>
# modal secret create neon-db DATABASE_URL=<connection-string>
secrets = [
    modal.Secret.from_name("bluesky-credentials"),
    modal.Secret.from_name("neon-db"),
]

# Create a persistent volume for images and maps
volume = modal.Volume.from_name("oceans-of-nyc", create_if_missing=True)
VOLUME_PATH = "/data"
IMAGES_PATH = f"{VOLUME_PATH}/images"
MAPS_PATH = f"{VOLUME_PATH}/maps"
TLC_PATH = f"{VOLUME_PATH}/tlc"


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
    timeout=600,  # 10 minutes max
)
def post_single_sighting(limit: int = 5, dry_run: bool = False):
    """
    Post unposted sightings to Bluesky with images.

    Args:
        limit: Maximum number of posts to make (default: 5)
        dry_run: If True, only show what would be posted without actually posting
    """
    import os
    import time
    from datetime import datetime
    from pathlib import Path

    from database import SightingsDatabase
    from geolocate import generate_map, reverse_geocode
    from post.bluesky import BlueskyClient

    print(f"🚀 Starting batch post (limit: {limit}, dry_run: {dry_run})")

    # Ensure directories exist
    os.makedirs(IMAGES_PATH, exist_ok=True)
    os.makedirs(MAPS_PATH, exist_ok=True)

    # Initialize database and client
    db = SightingsDatabase()
    client = BlueskyClient()

    # Get unposted sightings
    sightings = db.get_unposted_sightings()

    if not sightings:
        print("✓ No unposted sightings found")
        return {"posted": 0, "message": "No unposted sightings"}

    print(f"Found {len(sightings)} unposted sighting(s)")

    # Limit the number of posts
    sightings_to_post = sightings[:limit] if limit else sightings
    posted_count = 0

    for idx, sighting in enumerate(sightings_to_post, 1):
        (
            sighting_id,
            license_plate,
            timestamp,
            latitude,
            longitude,
            image_path,
            created_at,
            posted,
            post_uri,
            contributed_by,
        ) = sighting

        print(f"\n{'='*60}")
        print(f"Processing sighting {idx}/{len(sightings_to_post)} (ID: {sighting_id})")
        print(f"{'='*60}")

        try:
            # Get sighting counts
            posted_count_for_plate = db.get_posted_sighting_count(license_plate)
            unique_posted_count = db.get_unique_posted_count()
            total_vehicles = db.get_tlc_vehicle_count()

            # Get neighborhood name
            neighborhood = "Unknown location"
            if latitude and longitude:
                try:
                    neighborhood = reverse_geocode(latitude, longitude)
                    time.sleep(1.1)  # Respect Nominatim rate limit
                except Exception as e:
                    print(f"⚠ Warning: Could not reverse geocode: {e}")

            # Format timestamp
            dt = datetime.fromisoformat(timestamp)
            formatted_date = dt.strftime("%B %d, %Y at %I:%M %p")

            # Build post text
            ordinal = lambda n: f"{n}{'th' if 11<=n<=13 else {1:'st',2:'nd',3:'rd'}.get(n%10,'th')}"

            post_text = f"""🌊 Fisker Ocean sighting!

🚗 Plate: {license_plate}
📈 {unique_posted_count + 1} out of {total_vehicles} Oceans collected
🔢 This is the {ordinal(posted_count_for_plate + 1)} sighting of this vehicle
📅 {formatted_date}
📍 Spotted in {neighborhood}"""

            if contributed_by:
                post_text += f"\n\n🙏 Contributed by {contributed_by}"

            print(f"\nPost preview:\n{post_text}\n")

            # Prepare images for posting
            images_to_post = []
            image_alts = []

            # Check if sighting image exists in volume
            if image_path:
                # Convert local path to volume path
                image_filename = Path(image_path).name
                volume_image_path = f"{IMAGES_PATH}/{image_filename}"

                if os.path.exists(volume_image_path):
                    images_to_post.append(volume_image_path)
                    image_alts.append(
                        f"Fisker Ocean with plate {license_plate} spotted in {neighborhood}"
                    )
                    print(f"✓ Found image: {image_filename}")
                else:
                    print(f"⚠ Image not found in volume: {image_filename}")

            # Generate map if we have coordinates
            if latitude and longitude:
                map_filename = f"map_{sighting_id}.png"
                map_path = f"{MAPS_PATH}/{map_filename}"

                if not os.path.exists(map_path):
                    try:
                        print("🗺 Generating map...")
                        generate_map(latitude, longitude, map_path)
                        volume.commit()  # Persist the map to volume
                        print(f"✓ Map generated: {map_filename}")
                    except Exception as e:
                        print(f"⚠ Could not generate map: {e}")

                if os.path.exists(map_path):
                    images_to_post.append(map_path)
                    image_alts.append(
                        f"Map showing location of Fisker Ocean sighting in {neighborhood}"
                    )

            if dry_run:
                print("🔍 DRY RUN - Would post to Bluesky")
                print(f"   Images: {len(images_to_post)}")
                posted_count += 1
            else:
                # Post with images if available
                if images_to_post:
                    print(f"📸 Posting with {len(images_to_post)} image(s)")
                    response = client.create_post(
                        post_text, images=images_to_post, image_alts=image_alts
                    )
                else:
                    print("📝 Posting text only (no images available)")
                    response = client.create_post(post_text)

                post_uri_result = response.uri

                # Mark as posted
                db.mark_as_posted(sighting_id, post_uri_result)

                print(f"✓ Posted to Bluesky: {post_uri_result}")
                posted_count += 1

                # Rate limiting - wait between posts
                if idx < len(sightings_to_post):
                    print("⏱ Waiting 10 seconds before next post...")
                    time.sleep(10)

        except Exception as e:
            print(f"✗ Error posting sighting {sighting_id}: {e}")
            import traceback

            traceback.print_exc()
            continue

    print(f"\n{'='*60}")
    print(f"✓ Batch complete: {posted_count} sighting(s) posted")
    print(f"{'='*60}")

    return {
        "posted": posted_count,
        "total_unposted": len(sightings),
        "message": f"Posted {posted_count} sightings",
    }


@app.function(image=image, secrets=secrets, volumes={VOLUME_PATH: volume})
def post_multiple_sightings(batch_size: int = 4, dry_run: bool = False):
    """
    Post multiple sightings in a single batch post.

    Args:
        batch_size: Number of sightings to include (max 4)
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
        # Post to Bluesky
        client = BlueskyClient()
        response = client.create_batch_sighting_post(
            sightings=sightings_to_post, unique_sighted=unique_sighted, total_fiskers=total_fiskers
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
    schedule=modal.Cron("0 22 * * *"),  # Run daily at 6 PM ET (10 PM UTC)
)
def post_sightings_queue():
    """
    Scheduled function that runs daily at 6 PM ET.
    Recursively processes all unposted sightings:
    - If 1 sighting: uses single-sighting format with full details
    - If 2-4 sightings: uses batch format
    - If 5+ sightings: posts first 4 in batch, then recursively processes remainder
    - If no sightings: exits gracefully
    """
    import os
    from datetime import datetime
    from pathlib import Path

    from database import SightingsDatabase
    from geolocate import generate_map
    from post.bluesky import BlueskyClient

    print(f"⏰ Scheduled sightings queue post triggered at {datetime.now()}")

    # Check how many unposted sightings we have
    db = SightingsDatabase()
    sightings = db.get_unposted_sightings()

    if not sightings:
        print("✓ No unposted sightings found")
        return {"posted": 0, "message": "No unposted sightings"}

    num_sightings = len(sightings)
    print(f"Found {num_sightings} unposted sighting(s)")

    if num_sightings == 1:
        # Use single-sighting format for one sighting
        print("Using single-sighting format")
        sighting = sightings[0]
        (
            sighting_id,
            license_plate,
            timestamp,
            latitude,
            longitude,
            image_path,
            created_at,
            post_uri,
            contributor_id,
            preferred_name,
            bluesky_handle,
            phone_number,
        ) = sighting

        try:
            # Ensure directories exist
            os.makedirs(IMAGES_PATH, exist_ok=True)
            os.makedirs(MAPS_PATH, exist_ok=True)

            # Get statistics
            sighting_count = db.get_sighting_count(license_plate)
            unique_sighted = db.get_unique_sighted_count()
            total_fiskers = db.get_tlc_vehicle_count()

            # Determine contributor display name
            contributed_by = None
            if contributor_id and contributor_id != 1:
                if bluesky_handle:
                    contributed_by = (
                        bluesky_handle if bluesky_handle.startswith("@") else f"@{bluesky_handle}"
                    )
                elif preferred_name:
                    contributed_by = preferred_name

            # Prepare images
            images = []
            image_filename = Path(image_path).name if image_path else None
            volume_image_path = f"{IMAGES_PATH}/{image_filename}" if image_filename else None

            if volume_image_path and os.path.exists(volume_image_path):
                images.append(volume_image_path)
                print(f"✓ Found image: {image_filename}")
            else:
                print(f"⚠ Image not found: {image_filename}")

            # Generate map if we have coordinates
            if latitude and longitude:
                map_filename = f"map_{sighting_id}.png"
                map_path = f"{MAPS_PATH}/{map_filename}"

                if not os.path.exists(map_path):
                    try:
                        print("🗺 Generating map...")
                        generate_map(latitude, longitude, map_path)
                        volume.commit()
                        print(f"✓ Map generated: {map_filename}")
                    except Exception as e:
                        print(f"⚠ Could not generate map: {e}")

                if os.path.exists(map_path):
                    images.append(map_path)

            # Post to Bluesky using single-sighting format
            client = BlueskyClient()
            response = client.create_sighting_post(
                license_plate=license_plate,
                sighting_count=sighting_count,
                timestamp=timestamp,
                latitude=latitude,
                longitude=longitude,
                images=images,
                unique_sighted=unique_sighted,
                total_fiskers=total_fiskers,
                contributed_by=contributed_by,
            )

            # Mark as posted
            db.mark_as_posted(sighting_id, response.uri)

            result = {
                "posted": 1,
                "post_uri": response.uri,
                "plate": license_plate,
                "message": "Posted 1 sighting (single format)",
            }
            print(f"✓ Scheduled post complete: {result}")
            return result

        except Exception as e:
            print(f"✗ Error posting sighting: {e}")
            import traceback

            traceback.print_exc()
            return {"posted": 0, "error": str(e), "message": f"Failed to post: {e}"}

    else:
        # Use batch format for multiple sightings (2+)
        print(f"Using batch format for {min(num_sightings, 4)} sightings")
        result = post_multiple_sightings.remote(batch_size=4, dry_run=False)
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
    ],
    volumes={VOLUME_PATH: volume},
)
@modal.asgi_app()
def chat_sms_webhook():
    """
    Twilio SMS/MMS webhook endpoint.

    Configure this URL in your Twilio phone number settings:
    https://wallabout--oceans-of-nyc-chat-sms-webhook.modal.run

    Twilio sends POST requests with form-encoded data including:
    - From: Sender phone number
    - Body: Message text
    - NumMedia: Number of media attachments
    - MediaUrl0, MediaUrl1, etc.: URLs to media files
    - MediaContentType0, etc.: MIME types of media
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import Response

    from chat.webhook import handle_incoming_sms, parse_twilio_request

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
        # Twilio provides this in the webhook data
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

        # Handle the message
        twiml_response = handle_incoming_sms(
            from_number=from_number,
            body=message_body,
            num_media=num_media,
            media_urls=media_urls,
            media_types=media_types,
            volume_path=VOLUME_PATH,
            channel_type=channel_type,
        )

        # Commit volume changes if any images were saved
        volume.commit()

        # Return TwiML response
        return Response(
            content=twiml_response,
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
        print(f"  Fisker vehicles: {result['fisker_count']:,}")
        print(f"  Timestamp: {result['timestamp']}")
        print(f"{'='*60}")

        return result

    except Exception as e:
        print(f"❌ Error updating TLC data: {e}")
        import traceback

        traceback.print_exc()
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.local_entrypoint()
def main(
    command: str = "stats",
    limit: int = 5,
    dry_run: bool = False,
    file: str = None,
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
    """
    import os
    from pathlib import Path

    if command == "test":
        result = get_hello.remote()
        print(f"\nTest result: {result}")
    elif command == "stats":
        get_stats.remote()
    elif command == "post":
        post_single_sighting.remote(limit=limit, dry_run=dry_run)
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
    else:
        print(f"Unknown command: {command}")
        print("Available commands: test, stats, post, upload, sync-images, update-tlc")
