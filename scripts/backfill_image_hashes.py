#!/usr/bin/env python3
"""
Backfill image hashes for existing sightings.

This script calculates SHA-256 and perceptual hashes for all existing
sightings that don't have hashes yet, and updates the database.

Usage:
    python scripts/backfill_image_hashes.py [--batch-size=100] [--dry-run]
"""

import os
import sys
from pathlib import Path

import click

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SightingsDatabase
from utils.image_hashing import ImageHashError, calculate_both_hashes


@click.command()
@click.option(
    "--batch-size",
    default=100,
    help="Number of sightings to process in each batch",
    show_default=True,
)
@click.option("--dry-run", is_flag=True, help="Show what would be done without updating database")
def backfill_hashes(batch_size: int, dry_run: bool):
    """Backfill image hashes for existing sightings."""
    click.echo("🔄 Starting image hash backfill...")
    click.echo(f"   Batch size: {batch_size}")
    if dry_run:
        click.echo("   DRY RUN MODE - no changes will be made")
    click.echo()

    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    # Get all sightings without hashes
    cursor.execute(
        """
        SELECT id, image_path
        FROM sightings
        WHERE image_hash_sha256 IS NULL OR image_hash_perceptual IS NULL
        ORDER BY id ASC
        """
    )

    sightings = cursor.fetchall()
    total = len(sightings)

    if total == 0:
        click.echo("✓ All sightings already have hashes!")
        conn.close()
        return

    click.echo(f"Found {total} sightings without hashes\n")

    processed = 0
    successful = 0
    skipped = 0
    failed = []

    with click.progressbar(sightings, label="Processing sightings", show_pos=True) as bar:
        for sighting_id, image_path in bar:
            processed += 1

            # Check if file exists
            if not os.path.exists(image_path):
                click.echo(f"\n⚠️  Sighting #{sighting_id}: Image file not found: {image_path}")
                skipped += 1
                failed.append((sighting_id, image_path, "File not found"))
                continue

            try:
                # Calculate hashes
                sha256, phash = calculate_both_hashes(image_path)

                if dry_run:
                    click.echo(
                        f"\n[DRY RUN] Would update sighting #{sighting_id}: "
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
                        click.echo(f"\n✓ Committed batch of {batch_size} updates")

            except ImageHashError as e:
                click.echo(f"\n❌ Sighting #{sighting_id}: Failed to calculate hashes: {e}")
                failed.append((sighting_id, image_path, str(e)))
                continue

            except Exception as e:
                click.echo(f"\n❌ Sighting #{sighting_id}: Unexpected error: {e}")
                failed.append((sighting_id, image_path, str(e)))
                continue

    # Final commit
    if not dry_run and successful > 0:
        conn.commit()
        click.echo("\n✓ Final commit completed")

    conn.close()

    # Summary
    click.echo("\n" + "=" * 60)
    click.echo("SUMMARY")
    click.echo("=" * 60)
    click.echo(f"Total sightings processed: {processed}")
    click.echo(f"Successfully updated:       {successful}")
    click.echo(f"Skipped (file not found):  {skipped}")
    click.echo(f"Failed:                    {len(failed)}")

    if failed:
        click.echo("\nFailed sightings:")
        for sighting_id, image_path, error in failed[:10]:  # Show first 10
            click.echo(f"  #{sighting_id}: {error}")
            click.echo(f"    Path: {image_path}")
        if len(failed) > 10:
            click.echo(f"  ... and {len(failed) - 10} more")

    if dry_run:
        click.echo("\n⚠️  DRY RUN - no changes were made to the database")
    else:
        click.echo(f"\n✅ Backfill complete! Updated {successful}/{total} sightings")


if __name__ == "__main__":
    backfill_hashes()
