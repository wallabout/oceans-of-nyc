import click
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
from database import SightingsDatabase
from exif_utils import extract_image_metadata, ExifDataError
from bluesky_client import BlueskyClient
from map_generator import MapGenerator

# Load environment variables from .env file
load_dotenv()


@click.group()
def cli():
    """Fisker Ocean spotter Bluesky Bot"""
    pass


@cli.command()
@click.argument('image_path', type=click.Path(exists=True))
@click.argument('license_plate')
def process(image_path: str, license_plate: str):
    """
    Process a Fisker Ocean sighting image and store it in the database.

    If license_plate contains wildcards (*), searches for matches and prompts for selection.
    Example: T73**580C
    """
    try:
        click.echo(f"Processing image: {image_path}")
        click.echo(f"License plate: {license_plate}")

        db = SightingsDatabase()

        # Check if license plate contains wildcards
        if '*' in license_plate:
            click.echo(f"\nSearching for plates matching pattern: {license_plate}")
            results = db.search_plates_wildcard(license_plate.upper())

            if not results:
                click.echo(f"Error: No plates found matching pattern: {license_plate}", err=True)
                raise click.Abort()

            click.echo(f"\nFound {len(results)} matching plate(s):\n")

            # Display options
            for idx, result in enumerate(results, 1):
                plate, vin, year, owner, base_name, base_type = result
                click.echo(f"{idx}. {plate} - {year} (VIN: {vin})")
                click.echo(f"   Owner: {owner}")
                click.echo(f"   Base: {base_name}")
                click.echo()

            # Prompt for selection
            if len(results) == 1:
                if click.confirm(f"Use plate {results[0][0]}?", default=True):
                    license_plate = results[0][0]
                else:
                    click.echo("Operation cancelled.")
                    raise click.Abort()
            else:
                selection = click.prompt(
                    f"Select plate number (1-{len(results)}) or 'q' to quit",
                    type=str
                )

                if selection.lower() == 'q':
                    click.echo("Operation cancelled.")
                    raise click.Abort()

                try:
                    idx = int(selection) - 1
                    if 0 <= idx < len(results):
                        license_plate = results[idx][0]
                        click.echo(f"\nSelected: {license_plate}")
                    else:
                        click.echo("Error: Invalid selection", err=True)
                        raise click.Abort()
                except ValueError:
                    click.echo("Error: Invalid input", err=True)
                    raise click.Abort()

        metadata = extract_image_metadata(image_path)
        click.echo(f"\n✓ Extracted EXIF data:")
        click.echo(f"  - Timestamp: {metadata['timestamp']}")
        click.echo(f"  - Location: {metadata['latitude']}, {metadata['longitude']}")

        previous_count = db.get_sighting_count(license_plate)

        db.add_sighting(
            license_plate=license_plate,
            timestamp=metadata['timestamp'],
            latitude=metadata['latitude'],
            longitude=metadata['longitude'],
            image_path=str(Path(image_path).absolute())
        )

        new_count = previous_count + 1
        click.echo(f"✓ Sighting saved to database")
        click.echo(f"  - This is sighting #{new_count} for {license_plate}")

    except ExifDataError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option('--plate', help='Filter by license plate')
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
        click.echo(f"  Recorded: {sighting[6]}\n")


@cli.command()
@click.argument('csv_path', type=click.Path(exists=True))
def import_tlc(csv_path: str):
    """Import NYC TLC vehicle data from CSV file."""
    try:
        click.echo(f"Importing TLC data from: {csv_path}")
        db = SightingsDatabase()

        count = db.import_tlc_data(csv_path)

        click.echo(f"✓ Successfully imported {count:,} TLC vehicle records")
        click.echo(f"  - Total vehicles in database: {db.get_tlc_vehicle_count():,}")

    except Exception as e:
        click.echo(f"Error importing TLC data: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.argument('license_plate')
def lookup_tlc(license_plate: str):
    """Look up NYC TLC vehicle information by license plate."""
    try:
        db = SightingsDatabase()
        vehicle = db.get_tlc_vehicle_by_plate(license_plate)

        if not vehicle:
            click.echo(f"No TLC vehicle found for license plate: {license_plate}")
            return

        click.echo(f"\nTLC Vehicle Information for {license_plate}:\n")
        click.echo(f"  Active: {vehicle[1]}")
        click.echo(f"  Vehicle License Number: {vehicle[2]}")
        click.echo(f"  Owner Name: {vehicle[3]}")
        click.echo(f"  License Type: {vehicle[4]}")
        click.echo(f"  VIN: {vehicle[8]}")
        click.echo(f"  Vehicle Year: {vehicle[12]}")
        click.echo(f"  Wheelchair Accessible: {vehicle[9]}")
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

        if not click.confirm("Remove all non-Fisker vehicles? This will keep only vehicles with VINs starting with 'VCF1'"):
            click.echo("Operation cancelled.")
            return

        fisker_count = db.filter_fisker_vehicles()
        removed = original_count - fisker_count

        click.echo(f"✓ Filtered database to Fisker vehicles only")
        click.echo(f"  - Fisker vehicles: {fisker_count:,}")
        click.echo(f"  - Removed: {removed:,}")

    except Exception as e:
        click.echo(f"Error filtering vehicles: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.argument('pattern')
def search_plate(pattern: str):
    """
    Search for license plates using wildcard pattern.

    Use * to match any single character.
    Example: T73**580C will match T731580C, T732580C, etc.
    """
    try:
        db = SightingsDatabase()
        results = db.search_plates_wildcard(pattern.upper())

        if not results:
            click.echo(f"No plates found matching pattern: {pattern}")
            return

        click.echo(f"\nFound {len(results)} matching plate(s):\n")
        click.echo("="*80)

        for result in results:
            plate, vin, year, owner, base_name, base_type = result
            click.echo(f"Plate: {plate}")
            click.echo(f"  VIN: {vin}")
            click.echo(f"  Year: {year}")
            click.echo(f"  Owner: {owner}")
            click.echo(f"  Base: {base_name} ({base_type})")
            click.echo("="*80)

    except Exception as e:
        click.echo(f"Error searching plates: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.argument('sighting_id', type=int)
def post(sighting_id: int):
    """Post a sighting to Bluesky by its database ID."""
    try:
        db = SightingsDatabase()

        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM sightings WHERE id = ?", (sighting_id,))
        sighting = cursor.fetchone()
        conn.close()

        if not sighting:
            click.echo(f"Error: No sighting found with ID {sighting_id}", err=True)
            raise click.Abort()

        # Unpack sighting data
        # Schema: id, license_plate, timestamp, latitude, longitude, image_path, created_at, posted, post_uri, contributed_by
        sighting_id = sighting[0]
        license_plate = sighting[1]
        timestamp = sighting[2]
        latitude = sighting[3]
        longitude = sighting[4]
        image_path = sighting[5]
        # sighting[6] is created_at
        # sighting[7] is posted
        # sighting[8] is post_uri
        contributed_by = sighting[9] if len(sighting) > 9 else None

        db = SightingsDatabase()

        # Use posted count for accurate numbering
        posted_count = db.get_posted_sighting_count(license_plate)
        sighting_count = posted_count + 1

        # For unique count: get posted unique count, and add 1 if this plate hasn't been posted before
        unique_posted = db.get_unique_posted_count()
        if posted_count == 0:
            unique_sighted = unique_posted + 1
        else:
            unique_sighted = unique_posted

        total_fiskers = db.get_tlc_vehicle_count()

        bluesky = BlueskyClient()

        # Generate map only if GPS coordinates are available
        map_path = None
        if latitude is not None and longitude is not None:
            click.echo("\nGenerating map image...")
            map_gen = MapGenerator()
            map_path = map_gen.generate_sighting_map(
                latitude=latitude,
                longitude=longitude,
                license_plate=license_plate
            )
            click.echo(f"✓ Map saved to: {map_path}")

        post_text = bluesky.format_sighting_text(
            license_plate=license_plate,
            sighting_count=sighting_count,
            timestamp=timestamp,
            latitude=latitude,
            longitude=longitude,
            unique_sighted=unique_sighted,
            total_fiskers=total_fiskers,
            contributed_by=contributed_by
        )

        click.echo("\n" + "="*60)
        click.echo("POST PREVIEW")
        click.echo("="*60)
        click.echo(post_text)
        click.echo(f"\nImages:")
        click.echo(f"  1. {image_path}")
        if map_path:
            click.echo(f"  2. {map_path}")
        click.echo("="*60 + "\n")

        if not click.confirm("Do you want to post this to Bluesky?"):
            click.echo("Post cancelled.")
            return

        click.echo("\nPosting to Bluesky...")

        # Build images list - include map only if it exists
        images = [image_path]
        if map_path:
            images.append(map_path)

        response = bluesky.create_sighting_post(
            license_plate=license_plate,
            sighting_count=sighting_count,
            timestamp=timestamp,
            latitude=latitude,
            longitude=longitude,
            images=images,
            unique_sighted=unique_sighted,
            total_fiskers=total_fiskers,
            contributed_by=contributed_by
        )

        # Mark as posted
        db.mark_as_posted(sighting_id, response.uri)

        click.echo(f"✓ Successfully posted to Bluesky!")
        click.echo(f"  - Post URI: {response.uri}")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("\nMake sure to set BLUESKY_HANDLE and BLUESKY_PASSWORD environment variables.", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        raise click.Abort()


@cli.command()
@click.option('--images-dir', default='images', help='Directory containing images to process')
@click.option('--preview', is_flag=True, help='Preview images that would be processed without processing them')
def batch_process(images_dir: str, preview: bool):
    """
    Batch process unprocessed images in the images directory.

    For each unprocessed image:
    - Opens the image for viewing
    - Prompts for license plate
    - Validates plate against TLC database
    - Processes and saves to database
    - Generates map
    - Does NOT post to Bluesky (use batch-post for that)
    """
    try:
        db = SightingsDatabase()
        images_path = Path(images_dir)

        if not images_path.exists():
            click.echo(f"Error: Images directory not found: {images_dir}", err=True)
            raise click.Abort()

        # Get all image files
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif'}
        all_images = [
            f for f in images_path.glob('*')
            if f.suffix.lower() in image_extensions
        ]

        if not all_images:
            click.echo(f"No images found in {images_dir}")
            return

        # Get already processed images from database
        import sqlite3
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT image_path FROM sightings")
        processed_paths = {Path(row[0]).name for row in cursor.fetchall()}
        conn.close()

        # Find unprocessed images
        unprocessed = [img for img in all_images if img.name not in processed_paths]

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

        click.echo(f"\nFound {len(unprocessed)} unprocessed image(s) out of {len(all_images)} total\n")

        for idx, image_path in enumerate(unprocessed, 1):
            click.echo(f"\n{'='*60}")
            click.echo(f"Processing image {idx}/{len(unprocessed)}: {image_path.name}")
            click.echo(f"{'='*60}\n")

            # Open image for user to view
            try:
                if sys.platform == 'darwin':  # macOS
                    subprocess.run(['open', str(image_path)], check=True)
                elif sys.platform == 'win32':  # Windows
                    subprocess.run(['start', str(image_path)], shell=True, check=True)
                else:  # Linux
                    subprocess.run(['xdg-open', str(image_path)], check=True)
            except Exception as e:
                click.echo(f"Warning: Could not open image: {e}")

            # Prompt for license plate with validation loop
            while True:
                license_plate = click.prompt("Enter license plate (or 's' to skip, 'u' for unreadable, 'q' to quit)")

                if license_plate.lower() == 'q':
                    click.echo("Batch processing cancelled.")
                    return

                if license_plate.lower() == 's':
                    click.echo("Skipping this image.\n")
                    break

                if license_plate.lower() == 'u':
                    click.echo("Marking plate as unreadable.\n")
                    license_plate = None
                    break

                license_plate = license_plate.upper()

                # Check if contains wildcards
                if '*' in license_plate:
                    click.echo(f"\nSearching for plates matching pattern: {license_plate}")
                    results = db.search_plates_wildcard(license_plate)

                    if not results:
                        click.echo(f"No plates found matching pattern: {license_plate}")
                        continue

                    click.echo(f"\nFound {len(results)} matching plate(s):\n")

                    for result_idx, result in enumerate(results, 1):
                        plate, vin, year, owner, base_name, base_type = result
                        click.echo(f"{result_idx}. {plate} - {year} (VIN: {vin})")
                        click.echo(f"   Owner: {owner}")
                        click.echo(f"   Base: {base_name}")
                        click.echo()

                    if len(results) == 1:
                        if click.confirm(f"Use plate {results[0][0]}?", default=True):
                            license_plate = results[0][0]
                        else:
                            continue
                    else:
                        selection = click.prompt(
                            f"Select plate number (1-{len(results)}) or press Enter to re-enter",
                            type=str,
                            default=''
                        )

                        if not selection:
                            continue

                        try:
                            sel_idx = int(selection) - 1
                            if 0 <= sel_idx < len(results):
                                license_plate = results[sel_idx][0]
                            else:
                                click.echo("Invalid selection")
                                continue
                        except ValueError:
                            click.echo("Invalid input")
                            continue

                # Verify plate exists in TLC database
                vehicle = db.get_tlc_vehicle_by_plate(license_plate)
                if not vehicle:
                    click.echo(f"Warning: Plate {license_plate} not found in TLC database")
                    if not click.confirm("Continue anyway?", default=False):
                        continue

                # Valid plate - break out of validation loop
                break

            # Skip if user chose to skip this image
            if isinstance(license_plate, str) and license_plate.lower() == 's':
                continue

            # Extract EXIF and process
            try:
                metadata = extract_image_metadata(str(image_path))

                # Show what data we extracted
                click.echo(f"\n✓ Extracted metadata:")
                click.echo(f"  - Timestamp: {metadata['timestamp']}")

                if metadata['latitude'] and metadata['longitude']:
                    click.echo(f"  - Location: {metadata['latitude']}, {metadata['longitude']}")
                else:
                    click.echo(f"  - Location: No GPS data available (using current time as timestamp)")

                # Prompt for optional contributor name
                contributed_by = click.prompt(
                    "\nContributor name (optional, press Enter to skip)",
                    default='',
                    show_default=False
                )
                if not contributed_by.strip():
                    contributed_by = None
                else:
                    contributed_by = contributed_by.strip()

                # Save to database
                db.add_sighting(
                    license_plate=license_plate,
                    timestamp=metadata['timestamp'],
                    latitude=metadata['latitude'],
                    longitude=metadata['longitude'],
                    image_path=str(image_path.absolute()),
                    contributed_by=contributed_by
                )

                click.echo(f"✓ Sighting saved to database")

                # Show sighting count only for readable plates
                if license_plate:
                    sighting_count = db.get_sighting_count(license_plate)
                    click.echo(f"  - This is sighting #{sighting_count} for {license_plate}")
                else:
                    click.echo(f"  - Plate marked as unreadable (will not be posted)")

                # Generate map only if GPS data is available
                if metadata['latitude'] and metadata['longitude']:
                    click.echo("\nGenerating map image...")
                    map_gen = MapGenerator()
                    map_path = map_gen.generate_sighting_map(
                        latitude=metadata['latitude'],
                        longitude=metadata['longitude'],
                        license_plate=license_plate
                    )
                    click.echo(f"✓ Map saved to: {map_path}")

                # Only show "ready to post" message for readable plates
                if license_plate:
                    click.echo(f"✓ Sighting ready to post (use batch-post command)\n")
                else:
                    click.echo(f"✓ Sighting saved (unreadable plates are not posted)\n")

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
@click.option('--limit', type=int, default=None, help='Maximum number of sightings to post (default: all)')
@click.option('--preview', is_flag=True, help='Preview sightings that would be posted without posting them')
def batch_post(limit: int = None, preview: bool = False):
    """
    Post all unposted sightings from the database to Bluesky.

    For each unposted sighting:
    - Shows post preview with neighborhood name
    - Posts to Bluesky with confirmation (default: Yes)
    - Records post_uri in database
    """
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
                # Schema: id, license_plate, timestamp, latitude, longitude, image_path, created_at, posted, post_uri, contributed_by
                sighting_id = sighting[0]
                license_plate = sighting[1]
                timestamp = sighting[2]
                image_path = sighting[5]
                contributed_by = sighting[9] if len(sighting) > 9 else None

                # Format timestamp
                from datetime import datetime
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%B %d, %Y at %I:%M %p")

                click.echo(f"{idx}. ID {sighting_id}: {license_plate}")
                click.echo(f"   Date: {formatted_time}")
                click.echo(f"   Image: {Path(image_path).name}")
                if contributed_by:
                    click.echo(f"   Contributor: {contributed_by}")
                click.echo()

            click.echo(f"{'='*60}")
            click.echo("Run without --preview to post these sightings")
            click.echo(f"{'='*60}\n")
            return

        for idx, sighting in enumerate(unposted, 1):
            # Unpack sighting data
            # Schema: id, license_plate, timestamp, latitude, longitude, image_path, created_at, posted, post_uri, contributed_by
            sighting_id = sighting[0]
            license_plate = sighting[1]
            timestamp = sighting[2]
            latitude = sighting[3]
            longitude = sighting[4]
            image_path = sighting[5]
            # sighting[6] is created_at
            # sighting[7] is posted
            # sighting[8] is post_uri
            contributed_by = sighting[9] if len(sighting) > 9 else None

            click.echo(f"\n{'='*60}")
            click.echo(f"Sighting {idx}/{len(unposted)} (ID: {sighting_id})")
            click.echo(f"{'='*60}\n")

            # Get counts for post
            # Use posted count + 1 since this will be the next post for this plate
            posted_count = db.get_posted_sighting_count(license_plate)
            sighting_count = posted_count + 1

            # For unique count: get posted unique count, and add 1 if this plate hasn't been posted before
            unique_posted = db.get_unique_posted_count()
            if posted_count == 0:
                # This plate hasn't been posted before, so it's a new unique plate
                unique_sighted = unique_posted + 1
            else:
                # This plate has been posted before, so unique count stays the same
                unique_sighted = unique_posted

            total_fiskers = db.get_tlc_vehicle_count()

            # Generate map only if GPS coordinates are available
            map_path = None
            if latitude is not None and longitude is not None:
                map_gen = MapGenerator()
                map_path = map_gen.generate_sighting_map(
                    latitude=latitude,
                    longitude=longitude,
                    license_plate=license_plate
                )

            # Format post preview
            bluesky = BlueskyClient()
            post_text = bluesky.format_sighting_text(
                license_plate=license_plate,
                sighting_count=sighting_count,
                timestamp=timestamp,
                latitude=latitude,
                longitude=longitude,
                unique_sighted=unique_sighted,
                total_fiskers=total_fiskers,
                contributed_by=contributed_by
            )

            click.echo("POST PREVIEW")
            click.echo("="*60)
            click.echo(post_text)
            click.echo(f"\nImages:")
            click.echo(f"  1. {image_path}")
            if map_path:
                click.echo(f"  2. {map_path}")
            click.echo("="*60 + "\n")

            # Ask to post with default Yes
            if click.confirm("Post this to Bluesky?", default=True):
                click.echo("\nPosting to Bluesky...")

                try:
                    # Build images list - include map only if it exists
                    images = [image_path]
                    if map_path:
                        images.append(map_path)

                    response = bluesky.create_sighting_post(
                        license_plate=license_plate,
                        sighting_count=sighting_count,
                        timestamp=timestamp,
                        latitude=latitude,
                        longitude=longitude,
                        images=images,
                        unique_sighted=unique_sighted,
                        total_fiskers=total_fiskers,
                        contributed_by=contributed_by
                    )

                    # Mark as posted
                    db.mark_as_posted(sighting_id, response.uri)

                    click.echo(f"✓ Successfully posted to Bluesky!")
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
        click.echo("\nMake sure to set BLUESKY_HANDLE and BLUESKY_PASSWORD environment variables.", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Error in batch posting: {e}", err=True)
        raise click.Abort()


if __name__ == "__main__":
    cli()
