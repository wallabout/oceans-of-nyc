"""
Modal app for automated Bluesky posting of Fisker Ocean sightings.

This serverless app runs scheduled batch posts to Bluesky.
Images are stored in a Modal volume for persistent access.
"""

import modal

# Create Modal app
app = modal.App("fisker-ocean-bot")

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
    )
    .add_local_python_source("database")
    .add_local_python_source("bluesky_client")
    .add_local_python_source("geocoding")
    .add_local_python_source("exif_utils")
    .add_local_python_source("map_generator")
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
volume = modal.Volume.from_name("fisker-ocean-data", create_if_missing=True)
VOLUME_PATH = "/data"
IMAGES_PATH = f"{VOLUME_PATH}/images"
MAPS_PATH = f"{VOLUME_PATH}/maps"


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
    timeout=600,  # 10 minutes max
)
def batch_post(limit: int = 5, dry_run: bool = False):
    """
    Post unposted sightings to Bluesky with images.

    Args:
        limit: Maximum number of posts to make (default: 5)
        dry_run: If True, only show what would be posted without actually posting
    """
    import os
    from datetime import datetime
    from pathlib import Path
    import time

    from database import SightingsDatabase
    from bluesky_client import BlueskyClient
    from geocoding import reverse_geocode
    from map_generator import generate_map

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
                        print(f"🗺 Generating map...")
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
                        post_text,
                        images=images_to_post,
                        image_alts=image_alts
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


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Period(hours=6),  # Run every 6 hours
)
def scheduled_batch_post():
    """
    Scheduled function that runs batch posting every 6 hours.
    Posts up to 3 sightings per run.
    """
    from datetime import datetime

    print(f"⏰ Scheduled batch post triggered at {datetime.now()}")
    result = batch_post.remote(limit=3, dry_run=False)
    print(f"✓ Scheduled post complete: {result}")
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
def test_connection():
    """Test basic connectivity without secrets."""
    import sys

    print("✓ Modal function executed successfully!")
    print(f"Python version: {sys.version}")
    print("✓ Source files mounted correctly")

    # Try importing our modules
    try:
        from database import SightingsDatabase
        print("✓ database.py imported successfully")
    except Exception as e:
        print(f"✗ Error importing database: {e}")

    try:
        from bluesky_client import BlueskyClient
        print("✓ bluesky_client.py imported successfully")
    except Exception as e:
        print(f"✗ Error importing bluesky_client: {e}")

    return {"status": "success"}


@app.function(
    image=image,
    volumes={VOLUME_PATH: volume},
)
def list_images():
    """List all images stored in the Modal volume."""
    import os

    print("\n📁 Volume Contents:")
    print(f"{'='*60}")

    # Ensure directories exist
    os.makedirs(IMAGES_PATH, exist_ok=True)
    os.makedirs(MAPS_PATH, exist_ok=True)

    # List sighting images
    print(f"\n📸 Sighting Images ({IMAGES_PATH}):")
    images = sorted(os.listdir(IMAGES_PATH)) if os.path.exists(IMAGES_PATH) else []
    if images:
        for img in images:
            path = f"{IMAGES_PATH}/{img}"
            size = os.path.getsize(path)
            print(f"   {img} ({size / 1024:.1f} KB)")
    else:
        print("   (empty)")

    # List map images
    print(f"\n🗺 Map Images ({MAPS_PATH}):")
    maps = sorted(os.listdir(MAPS_PATH)) if os.path.exists(MAPS_PATH) else []
    if maps:
        for m in maps:
            path = f"{MAPS_PATH}/{m}"
            size = os.path.getsize(path)
            print(f"   {m} ({size / 1024:.1f} KB)")
    else:
        print("   (empty)")

    print(f"\n{'='*60}")
    print(f"Total: {len(images)} images, {len(maps)} maps")

    return {
        "images": images,
        "maps": maps,
        "image_count": len(images),
        "map_count": len(maps),
    }


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
)
def delete_image(filename: str):
    """Delete an image from the Modal volume."""
    import os

    file_path = f"{IMAGES_PATH}/{filename}"
    if os.path.exists(file_path):
        os.remove(file_path)
        volume.commit()
        print(f"✓ Deleted {filename}")
        return {"deleted": True, "filename": filename}
    else:
        print(f"✗ File not found: {filename}")
        return {"deleted": False, "filename": filename}


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
        modal run modal_app.py --command=list-images
        modal run modal_app.py --command=upload --file=path/to/image.jpg
        modal run modal_app.py --command=sync-images
    """
    import os
    from pathlib import Path

    if command == "test":
        result = test_connection.remote()
        print(f"\nTest result: {result}")
    elif command == "stats":
        get_stats.remote()
    elif command == "post":
        batch_post.remote(limit=limit, dry_run=dry_run)
    elif command == "list-images":
        list_images.remote()
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
            print(f"✗ Error: Local sightings directory not found")
            return

        image_files = list(local_images_dir.glob("*.jpg")) + list(local_images_dir.glob("*.jpeg")) + list(local_images_dir.glob("*.png"))
        print(f"Found {len(image_files)} images to sync")

        for img_path in image_files:
            print(f"Uploading {img_path.name}...")
            with open(img_path, "rb") as f:
                image_data = f.read()
            upload_image.remote(img_path.name, image_data)

        print(f"\n✓ Synced {len(image_files)} images to Modal volume")
    elif command == "delete-image":
        if not file:
            print("✗ Error: --file is required for delete-image command")
            return
        delete_image.remote(file)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: test, stats, post, list-images, upload, sync-images, delete-image")
