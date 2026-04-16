import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv

from database import SightingsDatabase

# Load environment variables from .env file
load_dotenv()


@click.group()
def cli():
    """Fisker Ocean spotter Bluesky Bot"""
    pass


@cli.command()
@click.argument("image_path", type=click.Path(exists=True))
@click.argument("license_plate")
def process(image_path: str, license_plate: str):
    """
    Process a Fisker Ocean sighting image and store it in the database.
    """
    from geolocate.exif import ExifDataError, extract_image_metadata

    try:
        click.echo(f"Processing image: {image_path}")
        click.echo(f"License plate: {license_plate}")

        db = SightingsDatabase()

        vehicle = db.get_tlc_vehicle_by_plate(license_plate.upper())
        vin = vehicle.get("vin") if vehicle else None

        metadata = extract_image_metadata(image_path)
        click.echo("\n✓ Extracted EXIF data:")
        click.echo(f"  - Timestamp: {metadata['timestamp']}")
        click.echo(f"  - Location: {metadata['latitude']}, {metadata['longitude']}")

        previous_count = db.get_sighting_count(license_plate)

        # Generate unified filename and copy to expected location
        from utils.image_processor import ImageProcessor

        processor = ImageProcessor()
        image_timestamp = datetime.fromisoformat(metadata["timestamp"].replace("Z", "+00:00"))
        image_filename = processor.generate_filename(license_plate, image_timestamp)

        # Copy source image to the expected location
        import shutil

        dest_path = processor.get_original_path(image_filename)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(str(Path(image_path).absolute()), dest_path)

        # Use default contributor ID (1) for CLI-added sightings
        result = db.add_sighting(
            license_plate=license_plate,
            timestamp=metadata["timestamp"],
            latitude=metadata["latitude"],
            longitude=metadata["longitude"],
            contributor_id=1,
            image_filename=image_filename,
            vin=vin,
        )

        if result is None:
            click.echo("⚠️  Failed to save sighting to the database")
            raise click.Abort()

        sighting_id = result["id"]

        new_count = previous_count + 1
        click.echo(f"✓ Sighting saved to database (ID: {sighting_id})")
        click.echo(f"  - This is sighting #{new_count} for {license_plate}")

    except ExifDataError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option("--plate", help="Filter by license plate")
def list_sightings(plate: str = None):
    """List all sightings in the database."""
    db = SightingsDatabase()
    sightings = db.get_all_sightings(plate)

    if not sightings:
        if plate:
            click.echo(f"No sightings found for license plate: {plate}")
        else:
            click.echo("No sightings in database")
        return

    click.echo(f"Found {len(sightings)} sighting(s):\n")
    for sighting in sightings:
        click.echo(f"ID: {sighting[0]}")
        click.echo(f"  License Plate: {sighting[1]}")
        click.echo(f"  Timestamp: {sighting[2]}")
        click.echo(f"  Location: {sighting[3]}, {sighting[4]}")
        click.echo(f"  Image: {sighting[5]}")
        click.echo(f"  Borough: {sighting[6]}")
        click.echo(f"  Recorded: {sighting[7]}\n")


@cli.command()
@click.argument("csv_path", type=click.Path(exists=True))
def import_tlc(csv_path: str):
    """Import NYC TLC vehicle data from CSV file."""
    try:
        from datetime import datetime
        from pathlib import Path

        click.echo(f"Importing TLC data from: {csv_path}")
        db = SightingsDatabase()

        # Extract date from filename if it matches pattern: tlc_vehicles_YYYYMMDD_HHMMSS.csv
        # Otherwise use today's date
        csv_file = Path(csv_path)
        filename = csv_file.stem  # removes .csv
        try:
            if filename.startswith("tlc_vehicles_"):
                timestamp_str = filename.replace("tlc_vehicles_", "")
                date_str = timestamp_str.split("_")[0]  # Get YYYYMMDD part
                snapshot_date = datetime.strptime(date_str, "%Y%m%d").date().isoformat()
            else:
                snapshot_date = datetime.now().date().isoformat()
        except (ValueError, IndexError):
            snapshot_date = datetime.now().date().isoformat()

        count = db.import_tlc_data(csv_path, snapshot_date)

        click.echo(f"✓ Successfully imported {count:,} TLC vehicle records")
        click.echo(f"  - Snapshot date: {snapshot_date}")
        click.echo(f"  - Total vehicles in database: {db.get_tlc_vehicle_count():,}")

    except Exception as e:
        click.echo(f"Error importing TLC data: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.argument("license_plate")
def lookup_tlc(license_plate: str):
    """Look up NYC TLC vehicle information by license plate."""
    try:
        db = SightingsDatabase()
        vehicle = db.get_tlc_vehicle_by_plate(license_plate)

        if not vehicle:
            click.echo(f"No TLC vehicle found for license plate: {license_plate}")
            return

        click.echo(f"\nTLC Vehicle Information for {license_plate}:\n")
        click.echo(f"  License Plate: {vehicle['license_plate']}")
        click.echo(f"  VIN: {vehicle['vin']}")
        click.echo(f"  First Reported: {vehicle['first_reported_on']}")
        click.echo(f"  Most Recently Reported: {vehicle['most_recently_reported_on']}")
        click.echo(f"  Base Name: {vehicle[14]}")
        click.echo(f"  Base Type: {vehicle[15]}")
        click.echo(f"  Base Address: {vehicle[19]}")

    except Exception as e:
        click.echo(f"Error looking up TLC data: {e}", err=True)
        raise click.Abort()


@cli.command()
def filter_fiskers():
    """Remove all non-Fisker vehicles from TLC database (keeps only VINs starting with VCF1)."""
    try:
        db = SightingsDatabase()

        original_count = db.get_tlc_vehicle_count()
        click.echo(f"Current TLC vehicles in database: {original_count:,}")

        if not click.confirm(
            "Remove all non-Fisker vehicles? This will keep only vehicles with VINs starting with 'VCF1'"
        ):
            click.echo("Operation cancelled.")
            return

        fisker_count = db.filter_fisker_vehicles()
        removed = original_count - fisker_count

        click.echo("✓ Filtered database to Fisker vehicles only")
        click.echo(f"  - Fisker vehicles: {fisker_count:,}")
        click.echo(f"  - Removed: {removed:,}")

    except Exception as e:
        click.echo(f"Error filtering vehicles: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.argument("sighting_id", type=int)
def post(sighting_id: int):
    """Post a sighting to Bluesky by its database ID using the unified format."""
    from post.bluesky import BlueskyClient

    try:
        db = SightingsDatabase()

        # Get the sighting with contributor info using get_unposted_sightings format
        sightings = db.get_unposted_sightings()

        # Find the specific sighting by ID
        sighting = None
        for s in sightings:
            if s[0] == sighting_id:
                sighting = s
                break

        if not sighting:
            click.echo(f"Error: No unposted sighting found with ID {sighting_id}", err=True)
            raise click.Abort()

        # Get statistics
        unique_sighted = db.get_unique_sighted_count()
        total_fiskers = db.get_tlc_vehicle_count()
        contributor_stats = db.get_all_contributor_sighting_counts()

        # Extract sighting info for preview
        license_plate = sighting[1]
        contributor_id = sighting[9]
        preferred_name = sighting[10]
        bluesky_handle = sighting[11]

        # Determine contributor display name
        contributor_name = "Unknown"
        if contributor_id and contributor_id != 1:
            if preferred_name:
                contributor_name = preferred_name
            elif bluesky_handle:
                contributor_name = bluesky_handle
            total_count = contributor_stats.get(contributor_id, 0)
        else:
            total_count = 0

        click.echo("\n" + "=" * 60)
        click.echo("POST PREVIEW (Unified Format)")
        click.echo("=" * 60)
        click.echo("🌊 +1 sighting in the last 24 hours")
        click.echo(f"🚗 {license_plate}")
        progress_bar = f"{(unique_sighted / total_fiskers * 100):.1f}%"
        click.echo(f"📈 {progress_bar} ({unique_sighted} out of {total_fiskers})")
        if contributor_id and contributor_id != 1:
            click.echo(f"\n* {contributor_name} +1 → {total_count}")
        click.echo("=" * 60 + "\n")

        if not click.confirm("Do you want to post this to Bluesky?"):
            click.echo("Post cancelled.")
            return

        click.echo("\nPosting to Bluesky...")

        bluesky = BlueskyClient()
        new_badges = db.get_badges_for_sightings([sighting_id])
        response = bluesky.create_batch_sighting_post(
            sightings=[sighting],
            unique_sighted=unique_sighted,
            total_fiskers=total_fiskers,
            new_badges=new_badges,
        )

        # Mark as posted
        db.mark_as_posted(sighting_id, response.uri)

        click.echo("✓ Successfully posted to Bluesky!")
        click.echo(f"  - Post URI: {response.uri}")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo(
            "\nMake sure to set BLUESKY_HANDLE and BLUESKY_PASSWORD environment variables.",
            err=True,
        )
        raise click.Abort()
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option("--images-dir", default="images", help="Directory containing images to process")
@click.option(
    "--preview", is_flag=True, help="Preview images that would be processed without processing them"
)
def batch_process(images_dir: str, preview: bool):
    """
    Batch process unprocessed images in the images directory.

    For each unprocessed image:
    - Opens the image for viewing
    - Prompts for license plate
    - Validates plate against TLC database
    - Processes and saves to database
    - Does NOT post to Bluesky (use batch-post for that)
    """
    from geolocate.exif import extract_image_metadata

    try:
        db = SightingsDatabase()
        images_path = Path(images_dir)

        if not images_path.exists():
            click.echo(f"Error: Images directory not found: {images_dir}", err=True)
            raise click.Abort()

        # Get all image files
        image_extensions = {".jpg", ".jpeg", ".png", ".gif"}
        all_images = [f for f in images_path.glob("*") if f.suffix.lower() in image_extensions]

        if not all_images:
            click.echo(f"No images found in {images_dir}")
            return

        # Get already processed images from database
        import sqlite3

        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT image_filename FROM sightings")
        processed_filenames = {row[0] for row in cursor.fetchall() if row[0]}
        conn.close()

        # Find unprocessed images
        unprocessed = [img for img in all_images if img.name not in processed_filenames]

        if not unprocessed:
            click.echo(f"✓ All images in {images_dir} have been processed!")
            return

        # If preview mode, just list the files and exit
        if preview:
            click.echo(f"\n{'='*60}")
            click.echo(f"PREVIEW: {len(unprocessed)} unprocessed image(s) would be processed")
            click.echo(f"{'='*60}\n")
            for idx, img in enumerate(unprocessed, 1):
                click.echo(f"{idx}. {img.name}")
            click.echo(f"\n{'='*60}")
            click.echo("Run without --preview to process these images")
            click.echo(f"{'='*60}\n")
            return

        click.echo(
            f"\nFound {len(unprocessed)} unprocessed image(s) out of {len(all_images)} total\n"
        )

        for idx, image_path in enumerate(unprocessed, 1):
            click.echo(f"\n{'='*60}")
            click.echo(f"Processing image {idx}/{len(unprocessed)}: {image_path.name}")
            click.echo(f"{'='*60}\n")

            # Open image for user to view
            try:
                if sys.platform == "darwin":  # macOS
                    subprocess.run(["open", str(image_path)], check=True)
                elif sys.platform == "win32":  # Windows
                    subprocess.run(["start", str(image_path)], shell=True, check=True)
                else:  # Linux
                    subprocess.run(["xdg-open", str(image_path)], check=True)
            except Exception as e:
                click.echo(f"Warning: Could not open image: {e}")

            # Prompt for license plate with validation loop
            while True:
                license_plate = click.prompt("Enter license plate (or 's' to skip, 'q' to quit)")

                if license_plate.lower() == "q":
                    click.echo("Batch processing cancelled.")
                    return

                if license_plate.lower() == "s":
                    click.echo("Skipping this image.\n")
                    break

                license_plate = license_plate.upper()

                # Verify plate exists in TLC database
                vehicle = db.get_tlc_vehicle_by_plate(license_plate)
                vin = None
                if not vehicle:
                    click.echo(f"Warning: Plate {license_plate} not found in TLC database")
                    if not click.confirm("Continue anyway?", default=False):
                        continue
                else:
                    # Extract VIN from vehicle record
                    vin = vehicle.get("vin") if vehicle else None

                # Valid plate - break out of validation loop
                break

            # Skip if user chose to skip this image
            if isinstance(license_plate, str) and license_plate.lower() == "s":
                continue

            # Extract EXIF and process
            try:
                metadata = extract_image_metadata(str(image_path))

                # Show what data we extracted
                click.echo("\n✓ Extracted metadata:")
                click.echo(f"  - Timestamp: {metadata['timestamp']}")

                if metadata["latitude"] and metadata["longitude"]:
                    click.echo(f"  - Location: {metadata['latitude']}, {metadata['longitude']}")
                else:
                    click.echo(
                        "  - Location: No GPS data available (using current time as timestamp)"
                    )

                # Prompt for optional contributor name
                contributed_by = click.prompt(
                    "\nContributor name (optional, press Enter to skip)",
                    default="",
                    show_default=False,
                )

                # Get or create contributor
                if contributed_by.strip():
                    contributed_by = contributed_by.strip()
                    # Check if it's a Bluesky handle
                    if contributed_by.startswith("@"):
                        contributor_id = db.get_or_create_contributor(bluesky_handle=contributed_by)
                    else:
                        # For non-handle names, just use the default contributor
                        # and note the name in console (not stored separately in this flow)
                        click.echo(f"  Note: Name '{contributed_by}' recorded for this sighting")
                        contributor_id = 1
                else:
                    # Use default contributor (ID 1)
                    contributor_id = 1

                # Generate unified filename and copy to expected location
                from utils.image_processor import ImageProcessor

                processor = ImageProcessor()
                image_timestamp = datetime.fromisoformat(
                    metadata["timestamp"].replace("Z", "+00:00")
                )
                image_filename = processor.generate_filename(license_plate, image_timestamp)

                # Copy source image to the expected location
                dest_path = processor.get_original_path(image_filename)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(str(image_path.absolute()), dest_path)

                # Save to database
                result = db.add_sighting(
                    license_plate=license_plate,
                    timestamp=metadata["timestamp"],
                    latitude=metadata["latitude"],
                    longitude=metadata["longitude"],
                    contributor_id=contributor_id,
                    image_filename=image_filename,
                    vin=vin,
                )

                if result is None:
                    click.echo("⚠️  Failed to save sighting to the database")
                    continue

                sighting_id = result["id"]

                click.echo(f"✓ Sighting saved to database (ID: {sighting_id})")

                # Show sighting count
                sighting_count = db.get_sighting_count(license_plate)
                click.echo(f"  - This is sighting #{sighting_count} for {license_plate}")

                click.echo("✓ Sighting ready to post (use batch-post command)\n")

            except Exception as e:
                click.echo(f"Unexpected error: {e}", err=True)
                if not click.confirm("Continue with next image?", default=True):
                    return

        click.echo(f"\n{'='*60}")
        click.echo("Batch processing complete!")
        click.echo(f"{'='*60}\n")

    except Exception as e:
        click.echo(f"Error in batch processing: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option(
    "--limit", type=int, default=None, help="Maximum number of sightings to post (default: all)"
)
@click.option(
    "--preview", is_flag=True, help="Preview sightings that would be posted without posting them"
)
def batch_post(limit: int = None, preview: bool = False):
    """
    Post all unposted sightings from the database to Bluesky.

    For each unposted sighting:
    - Shows post preview with neighborhood name
    - Posts to Bluesky with confirmation (default: Yes)
    - Records post_uri in database
    """
    from post.bluesky import BlueskyClient

    try:
        db = SightingsDatabase()
        unposted = db.get_unposted_sightings()

        if not unposted:
            click.echo("✓ No unposted sightings found!")
            return

        # Apply limit if specified
        total_unposted = len(unposted)
        if limit and limit < total_unposted:
            unposted = unposted[:limit]
            limit_msg = f", showing first {limit}" if preview else f", processing first {limit}"
            click.echo(f"\nFound {total_unposted} unposted sighting(s){limit_msg}\n")
        else:
            action = "to preview" if preview else ""
            click.echo(f"\nFound {len(unposted)} unposted sighting(s) {action}\n")

        # If preview mode, show list and exit
        if preview:
            click.echo(f"{'='*60}")
            click.echo("PREVIEW: Sightings that would be posted")
            click.echo(f"{'='*60}\n")
            for idx, sighting in enumerate(unposted, 1):
                # Schema: id, license_plate, created_at, latitude, longitude, image_filename, borough, created_at, post_uri, contributor_id, preferred_name, bluesky_handle, phone_number
                sighting_id = sighting[0]
                license_plate = sighting[1]
                created_at = sighting[2]
                image_filename = sighting[5]
                # sighting[9] is contributor_id (not used here)
                preferred_name = sighting[10]
                bluesky_handle = sighting[11]

                # Format created_at
                from datetime import datetime

                dt = datetime.fromisoformat(created_at)
                formatted_time = dt.strftime("%B %d, %Y at %I:%M %p")

                click.echo(f"{idx}. ID {sighting_id}: {license_plate}")
                click.echo(f"   Date: {formatted_time}")
                click.echo(f"   Image: {image_filename}")
                # Display contributor name
                if preferred_name:
                    click.echo(f"   Contributor: {preferred_name}")
                elif bluesky_handle:
                    click.echo(f"   Contributor: {bluesky_handle}")
                click.echo()

            click.echo(f"{'='*60}")
            click.echo("Run without --preview to post these sightings")
            click.echo(f"{'='*60}\n")
            return

        for idx, sighting in enumerate(unposted, 1):
            # Unpack sighting data
            # Schema: id, license_plate, created_at, latitude, longitude, image_filename, borough, created_at, post_uri, contributor_id, preferred_name, bluesky_handle, phone_number
            sighting_id = sighting[0]
            license_plate = sighting[1]
            # created_at = sighting[2]  # Not used in new format
            # latitude = sighting[3]  # Not used in new format
            # longitude = sighting[4]  # Not used in new format
            image_filename = sighting[5]
            # sighting[6] is borough
            # sighting[7] is created_at
            # sighting[8] is post_uri
            # sighting[9] is contributor_id (not used here)
            preferred_name = sighting[10]
            bluesky_handle = sighting[11]

            click.echo(f"\n{'='*60}")
            click.echo(f"Sighting {idx}/{len(unposted)} (ID: {sighting_id})")
            click.echo(f"{'='*60}\n")

            # Get statistics for post
            unique_sighted = db.get_unique_sighted_count()
            total_fiskers = db.get_tlc_vehicle_count()
            contributor_stats = db.get_all_contributor_sighting_counts()

            contributor_id = sighting[9]
            contributor_name = "Unknown"
            total_count = 0

            if contributor_id and contributor_id != 1:
                if preferred_name:
                    contributor_name = preferred_name
                elif bluesky_handle:
                    contributor_name = bluesky_handle
                total_count = contributor_stats.get(contributor_id, 0)

            # Format post preview in new unified format
            click.echo("POST PREVIEW (Unified Format)")
            click.echo("=" * 60)
            click.echo("🌊 +1 sighting in the last 24 hours")
            click.echo(f"🚗 {license_plate}")
            progress_bar = f"{(unique_sighted / total_fiskers * 100):.1f}%"
            click.echo(f"📈 {progress_bar} ({unique_sighted} out of {total_fiskers})")
            if contributor_id and contributor_id != 1:
                click.echo(f"\n* {contributor_name} +1 → {total_count}")
            click.echo("\nImages:")
            click.echo(f"  1. {image_filename}")
            click.echo("=" * 60 + "\n")

            # Ask to post with default Yes
            if click.confirm("Post this to Bluesky?", default=True):
                click.echo("\nPosting to Bluesky...")

                try:
                    # Initialize client
                    bluesky = BlueskyClient()

                    # Get contributor statistics
                    contributor_stats = db.get_all_contributor_sighting_counts()

                    # Post using unified batch format (with single sighting)
                    new_badges = db.get_badges_for_sightings([sighting_id])
                    response = bluesky.create_batch_sighting_post(
                        sightings=[sighting],
                        unique_sighted=unique_sighted,
                        total_fiskers=total_fiskers,
                        new_badges=new_badges,
                    )

                    # Mark as posted
                    db.mark_as_posted(sighting_id, response.uri)

                    click.echo("✓ Successfully posted to Bluesky!")
                    click.echo(f"  - Post URI: {response.uri}\n")

                except Exception as e:
                    click.echo(f"Error posting to Bluesky: {e}", err=True)
                    if not click.confirm("Continue with next sighting?", default=True):
                        return
            else:
                click.echo("Post skipped\n")

        click.echo(f"\n{'='*60}")
        click.echo("Batch posting complete!")
        click.echo(f"{'='*60}\n")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo(
            "\nMake sure to set BLUESKY_HANDLE and BLUESKY_PASSWORD environment variables.",
            err=True,
        )
        raise click.Abort()
    except Exception as e:
        click.echo(f"Error in batch posting: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option(
    "--batch-size",
    type=int,
    default=4,
    help="Number of sightings per batch post (max 4, default: 4)",
)
@click.option("--preview", is_flag=True, help="Preview the batch post without posting")
def multi_post(batch_size: int = 4, preview: bool = False):
    """
    Post multiple unposted sightings in a single Bluesky post.

    Creates a batch post with:
    - Count of new sightings
    - Count of unique contributors
    - Progress bar
    - List of license plates
    - Up to 4 images
    """
    try:
        if batch_size < 1 or batch_size > 4:
            click.echo("Error: Batch size must be between 1 and 4 (Bluesky image limit)", err=True)
            raise click.Abort()

        db = SightingsDatabase()
        unposted = db.get_unposted_sightings()

        if not unposted:
            click.echo("✓ No unposted sightings found!")
            return

        # Limit to batch_size
        sightings_to_post = unposted[:batch_size]

        # Get statistics
        unique_sighted = db.get_unique_sighted_count()
        total_fiskers = db.get_tlc_vehicle_count()

        # Extract data for preview
        # Sighting tuple: (id, license_plate, created_at, lat, lon, image_filename, borough, created_at,
        #                  post_uri, contributor_id, preferred_name, bluesky_handle, phone_number)
        plates = [s[1] for s in sightings_to_post]

        # Get unique contributor display names
        contributor_display_names = set()
        contributor_ids = set()
        for s in sightings_to_post:
            contributor_id = s[9]  # contributor_id
            if contributor_id:
                contributor_ids.add(contributor_id)
                preferred_name = s[10]  # preferred_name
                bluesky_handle = s[11]  # bluesky_handle
                if preferred_name:
                    contributor_display_names.add(preferred_name)
                elif bluesky_handle:
                    contributor_display_names.add(bluesky_handle)

        # Show preview
        click.echo(f"\n{'='*60}")
        click.echo(f"Batch Post Preview ({len(sightings_to_post)} sightings)")
        click.echo(f"{'='*60}\n")

        sighting_word = "sighting" if len(sightings_to_post) == 1 else "sightings"
        contributor_word = "contributor" if len(contributor_ids) == 1 else "contributors"

        click.echo(f"🌊 {len(sightings_to_post)} new {sighting_word}")
        if contributor_ids:
            click.echo(f"   from {len(contributor_ids)} {contributor_word}")

        # Show progress bar
        from post.bluesky import BlueskyClient

        progress_bar = BlueskyClient._create_progress_bar(unique_sighted, total_fiskers)
        click.echo(f"📈 {progress_bar}\n")

        # Show plates
        click.echo(f"🚗 Plates: {', '.join(plates)}\n")

        # Show contributors
        if contributor_display_names:
            click.echo(f"🙏 Thanks to: {', '.join(sorted(contributor_display_names))}\n")
        elif contributor_ids:
            # Contributors exist but haven't set names
            click.echo(f"🙏 Thanks to: {len(contributor_ids)} anonymous contributor(s)\n")

        # Show images
        click.echo("📸 Images:")
        for idx, sighting in enumerate(sightings_to_post, 1):
            image_filename = sighting[5]
            plate = sighting[1]
            click.echo(f"   {idx}. {image_filename} ({plate})")

        click.echo(f"\n{'='*60}\n")

        if preview:
            click.echo("Run without --preview to post this batch")
            return

        # Confirm posting
        if not click.confirm("Post this batch to Bluesky?", default=True):
            click.echo("Cancelled.")
            return

        # Post to Bluesky
        click.echo("\nPosting to Bluesky...")
        bluesky = BlueskyClient()

        # Get contributor statistics
        contributor_stats = db.get_all_contributor_sighting_counts()

        new_badges = db.get_badges_for_sightings([s[0] for s in sightings_to_post])
        response = bluesky.create_batch_sighting_post(
            sightings=sightings_to_post,
            unique_sighted=unique_sighted,
            total_fiskers=total_fiskers,
            new_badges=new_badges,
        )

        # Mark all sightings as posted
        sighting_ids = [s[0] for s in sightings_to_post]
        post_uri = response.uri
        db.mark_batch_as_posted(sighting_ids, post_uri)

        click.echo("✓ Batch posted successfully!")
        click.echo(f"  Post URI: {post_uri}")
        click.echo(f"  Marked {len(sighting_ids)} sighting(s) as posted")

    except Exception as e:
        click.echo(f"Error in multi-posting: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option(
    "--preview", is_flag=True, help="Preview badges that would be awarded without saving them"
)
def backfill_badges(preview: bool = False):
    """
    Evaluate and award badges retroactively to all existing contributors.

    This command evaluates all badge criteria for each contributor and awards
    any badges they qualify for based on their existing sightings.
    """
    from badges.definitions import BADGE_BY_NAME
    from badges.evaluator import evaluate_all_badges_for_contributor

    try:
        db = SightingsDatabase()
        contributors = db.get_all_contributors()

        if not contributors:
            click.echo("No contributors found in database.")
            return

        click.echo(f"\nEvaluating badges for {len(contributors)} contributor(s)...\n")

        total_badges_awarded = 0
        contributors_with_new_badges = 0

        for contributor in contributors:
            contributor_id = contributor["id"]
            display_name = (
                contributor.get("preferred_name")
                or contributor.get("bluesky_handle")
                or f"Contributor #{contributor_id}"
            )

            # Get existing badges for this contributor
            existing_badges = set(db.get_contributor_badge_names(contributor_id))

            # Evaluate which badges they qualify for
            qualified_badges = evaluate_all_badges_for_contributor(db, contributor_id)

            # Filter to only new badges (qualified_badges is list of (name, sighting_id) tuples)
            new_badges = [(name, sid) for name, sid in qualified_badges if name not in existing_badges]

            if new_badges:
                contributors_with_new_badges += 1

                if preview:
                    click.echo(f"  {display_name}: Would earn {len(new_badges)} new badge(s)")
                    for badge_name, _ in new_badges:
                        badge_def = BADGE_BY_NAME.get(badge_name)
                        if badge_def:
                            click.echo(f"    - {badge_def.emoji} {badge_def.display_name}")
                else:
                    # Save the new badges
                    saved_count = db.save_badges(contributor_id, new_badges)
                    total_badges_awarded += saved_count

                    click.echo(f"  {display_name}: Awarded {saved_count} new badge(s)")
                    for badge_name, _ in new_badges:
                        badge_def = BADGE_BY_NAME.get(badge_name)
                        if badge_def:
                            click.echo(f"    - {badge_def.emoji} {badge_def.display_name}")
            else:
                # Only show this in verbose mode or if they have badges
                if existing_badges:
                    click.echo(
                        f"  {display_name}: Already has {len(existing_badges)} badge(s), no new badges"
                    )

        click.echo(f"\n{'='*60}")
        if preview:
            click.echo("PREVIEW MODE - No badges were saved")
            click.echo(f"Would award badges to {contributors_with_new_badges} contributor(s)")
        else:
            click.echo(
                f"Awarded {total_badges_awarded} badge(s) to {contributors_with_new_badges} contributor(s)"
            )
        click.echo(f"{'='*60}\n")

    except Exception as e:
        click.echo(f"Error during badge backfill: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    cli()
