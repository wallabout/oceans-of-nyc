"""
Cleanup script to upload missing images from Modal storage to Cloudflare R2.

This script:
1. Scans all sightings in the database
2. Checks if web version exists in R2
3. If missing, uploads from Modal storage to R2
4. Updates the database with the R2 URL

Usage:
    modal run scripts/r2_cleanup.py
    modal run scripts/r2_cleanup.py --dry-run  # Preview without uploading
    modal run scripts/r2_cleanup.py --limit 10  # Process only first 10 missing
"""

import os
from typing import TypedDict

import modal


class CleanupStats(TypedDict):
    """Statistics for R2 cleanup operation."""

    total_sightings: int
    already_in_r2: int
    missing_from_r2: int
    uploaded_successfully: int
    upload_failed: int
    web_file_missing: int
    errors: list[str]


app = modal.App("r2-cleanup")

# Define the volume that contains the images
volume = modal.Volume.from_name("oceans-of-nyc", create_if_missing=False)

# Image with dependencies and local modules
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "boto3>=1.42.23",
        "psycopg2-binary>=2.9.10",
        "Pillow>=11.0.0",
    )
    .add_local_dir("database", remote_path="/root/database")
    .add_local_dir("utils", remote_path="/root/utils")
    .add_local_dir("geolocate", remote_path="/root/geolocate")
)


@app.function(
    image=image,
    volumes={"/data": volume},
    secrets=[
        modal.Secret.from_name("neon-db"),
        modal.Secret.from_name("cloudflare-r2"),
    ],
    timeout=3600,  # 1 hour timeout for large cleanup jobs
)
def cleanup_missing_r2_uploads(dry_run: bool = False, limit: int | None = None) -> CleanupStats:
    """
    Find and upload missing images to R2.

    Args:
        dry_run: If True, only report what would be uploaded without uploading
        limit: Maximum number of images to process (None = all)

    Returns:
        Dictionary with cleanup statistics
    """
    from database.models import SightingsDatabase
    from utils.r2_storage import R2Storage, R2UploadError

    print("=" * 80)
    print("R2 CLEANUP SCRIPT")
    print("=" * 80)
    if dry_run:
        print("🔍 DRY RUN MODE - No uploads will be performed")
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

    # Get all sightings from database
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, image_filename, license_plate
        FROM sightings
        WHERE image_filename IS NOT NULL
        ORDER BY id
        """
    )
    sightings = cursor.fetchall()
    conn.close()

    stats["total_sightings"] = len(sightings)
    print(f"📊 Found {stats['total_sightings']} total sightings with images")
    print()

    processed = 0
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
        web_path = f"/data/sightings/web/{image_filename}"
        if not os.path.exists(web_path):
            print(f"  ⚠ Web file not found: {web_path}")
            stats["web_file_missing"] += 1

            # Try to find original and create web version
            original_path = f"/data/sightings/original/{image_filename}"
            if os.path.exists(original_path):
                print(f"  🔄 Creating web version from original: {original_path}")
                if not dry_run:
                    try:
                        from utils.image_processor import ImageProcessor

                        processor = ImageProcessor(volume_path="/data")
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
                print(f"  ✗ Original file also missing: {original_path}")
                stats["errors"].append(f"Both web and original missing for {image_filename}")
                stats["upload_failed"] += 1
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


@app.local_entrypoint()
def main(dry_run: bool = False, limit: int | None = None):
    """
    Run the cleanup script.

    Args:
        dry_run: If True, only report what would be uploaded
        limit: Maximum number of images to process
    """
    result = cleanup_missing_r2_uploads.remote(dry_run=dry_run, limit=limit)
    return result
