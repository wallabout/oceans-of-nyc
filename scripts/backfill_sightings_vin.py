from dotenv import load_dotenv

from database import SightingsDatabase

"""Backfill vin values for existing sightings based on tlc_vehicles_minimal."""

# Load environment variables
load_dotenv()


def backfill_sightings_vin(dry_run: bool = True):
    """
    Backfill vin values for sightings that have a license_plate in tlc_vehicles_minimal
    but no vin set on the sighting itself.

    Uses the most recently reported VIN for each plate.

    Args:
        dry_run: If True, only print what would be updated without making changes
    """
    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    # Count how many sightings are missing a VIN but have a resolvable plate
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM sightings s
        WHERE s.vin IS NULL
          AND EXISTS (
              SELECT 1
              FROM tlc_vehicles_minimal t
              WHERE t.license_plate = s.license_plate
          )
        """
    )
    (resolvable_count,) = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM sightings WHERE vin IS NULL")
    (total_null_count,) = cursor.fetchone()

    print(f"Sightings with no VIN: {total_null_count}")
    print(f"  Resolvable via tlc_vehicles_minimal: {resolvable_count}")
    print(f"  No matching plate in TLC data: {total_null_count - resolvable_count}")

    if resolvable_count == 0:
        print("Nothing to backfill!")
        conn.close()
        return

    if dry_run:
        # Show a sample of what would be updated
        cursor.execute(
            """
            SELECT s.id, s.license_plate, t.vin, t.most_recently_reported_on
            FROM sightings s
            JOIN LATERAL (
                SELECT vin, most_recently_reported_on
                FROM tlc_vehicles_minimal
                WHERE license_plate = s.license_plate
                ORDER BY most_recently_reported_on DESC
                LIMIT 1
            ) t ON true
            WHERE s.vin IS NULL
            ORDER BY s.id
            LIMIT 10
            """
        )
        samples = cursor.fetchall()
        print(f"\n[DRY RUN] Sample of first {len(samples)} updates:")
        for sighting_id, plate, vin, reported_on in samples:
            print(f"  Sighting #{sighting_id} ({plate}) -> VIN {vin} (last seen {reported_on})")
        if resolvable_count > 10:
            print(f"  ... and {resolvable_count - 10} more")
        print(f"\n[DRY RUN] Would update {resolvable_count} sightings. No changes made.")
        print("Add --apply flag to actually update the database.")
    else:
        cursor.execute(
            """
            UPDATE sightings
            SET vin = t.vin
            FROM (
                SELECT DISTINCT ON (license_plate) license_plate, vin
                FROM tlc_vehicles_minimal
                ORDER BY license_plate, most_recently_reported_on DESC
            ) t
            WHERE sightings.license_plate = t.license_plate
              AND sightings.vin IS NULL
            """
        )
        updated_count = cursor.rowcount
        conn.commit()
        print(f"\n✅ Backfill complete! Updated {updated_count} sightings.")

    conn.close()


if __name__ == "__main__":
    import sys

    apply = "--apply" in sys.argv

    if apply:
        print("Running backfill with APPLY mode (will update database)")
        backfill_sightings_vin(dry_run=False)
    else:
        print("Running backfill in DRY RUN mode (no changes will be made)")
        backfill_sightings_vin(dry_run=True)
