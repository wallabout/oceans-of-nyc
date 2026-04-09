#!/usr/bin/env python3
"""
Script to correct a sighting that was entered with the wrong license plate.

Usage:
    python scripts/correct_sighting_license_plate.py <sighting_number> <correct_license_plate>

This script:
1. Looks up the sighting by its sighting number (global_sighting_index from sightings_export)
2. Displays the current sighting record (to confirm it's the right one)
3. Validates the correct license plate exists in the TLC database
4. Asks for confirmation
5. Updates the sighting to reference the correct vehicle (plate + VIN)
6. Deletes any badges associated with this sighting
7. Re-evaluates badges for the contributor
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from badges.evaluator import evaluate_badges_for_contributor
from database import SightingsDatabase

# Load environment variables
load_dotenv()


def lookup_sighting_id_by_number(db: SightingsDatabase, sighting_number: int) -> int | None:
    """Look up the sighting ID for a given global_sighting_index."""
    conn = db._get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT sighting_id FROM sightings_export WHERE global_sighting_index = %s",
            (sighting_number,),
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def correct_sighting_license_plate(sighting_number: int, correct_license_plate: str):
    """Correct the license plate (and VIN) on a sighting record."""

    db = SightingsDatabase()

    print("Looking up sighting and vehicle information...\n")

    # Resolve sighting number -> sighting ID
    sighting_id = lookup_sighting_id_by_number(db, sighting_number)
    if not sighting_id:
        print(f"❌ Error: Sighting number #{sighting_number} not found in sightings_export")
        return 1

    # Look up the sighting
    sighting = db.get_sighting_by_id(sighting_id)
    if not sighting:
        print(f"❌ Error: Sighting ID {sighting_id} not found")
        return 1

    # Look up the contributor
    contributor_id = sighting["contributor_id"]
    contributor = db.get_contributor(contributor_id=contributor_id)
    display_name = db.get_contributor_display_name(contributor_id)

    # Validate the correct plate exists in TLC
    tlc_vehicle = db.get_tlc_vehicle_by_plate(correct_license_plate)
    if not tlc_vehicle:
        print(f"❌ Error: License plate '{correct_license_plate}' not found in TLC database")
        return 1

    # Display current sighting info
    print("=" * 70)
    print("SIGHTING LICENSE PLATE CORRECTION")
    print("=" * 70)
    print()
    print(f"📋 SIGHTING #{sighting_number} (ID: {sighting_id})")
    print(f"   Contributor:     {display_name or '(anonymous)'} (ID: {contributor_id})")
    print(f"   Timestamp:       {sighting['timestamp']}")
    print(f"   Image:           {sighting.get('image_filename') or 'None'}")
    print(f"   Borough:         {sighting.get('borough') or 'None'}")
    print()
    print(f"   Current plate:   {sighting['license_plate']}")
    print(f"   Current VIN:     {sighting.get('vin') or 'None'}")
    print()
    print(f"   Correct plate:   {correct_license_plate}")
    print(f"   Correct VIN:     {tlc_vehicle['vin']}")
    print()
    print("=" * 70)
    print()

    if sighting["license_plate"] == correct_license_plate:
        print(f"ℹ️  Sighting #{sighting_number} already has plate '{correct_license_plate}'. Nothing to do.")
        return 0

    # Ask for confirmation
    response = input("Do you want to proceed with this correction? (yes/no): ").strip().lower()

    if response not in ["yes", "y"]:
        print("\n❌ Correction cancelled.")
        return 0

    conn = db._get_connection()
    cursor = conn.cursor()

    try:
        # Update the sighting
        print(f"\n🔄 Updating sighting {sighting_id}...")
        cursor.execute(
            """
            UPDATE sightings
            SET license_plate = %s, vin = %s
            WHERE id = %s
            """,
            (correct_license_plate, tlc_vehicle["vin"], sighting_id),
        )
        conn.commit()
        print(f"✅ Sighting updated to plate '{correct_license_plate}' (VIN: {tlc_vehicle['vin']})")

        # Delete badges associated with this sighting
        print(f"\n🔄 Removing badges associated with sighting {sighting_id}...")
        cursor.execute(
            "DELETE FROM contributors_badges WHERE sighting_id = %s",
            (sighting_id,),
        )
        badges_deleted = cursor.rowcount
        conn.commit()
        print(f"✅ Deleted {badges_deleted} badge(s) tied to this sighting")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during update: {e}")
        return 1
    finally:
        conn.close()

    # Re-evaluate badges for the contributor
    print(f"\n🔄 Re-evaluating badges for contributor {contributor_id}...")
    new_badges = evaluate_badges_for_contributor(db, contributor_id)
    if new_badges:
        saved_count = db.save_badges(contributor_id, new_badges)
        badge_names = [name for name, _ in new_badges]
        print(f"✅ Earned {saved_count} new badge(s): {', '.join(badge_names)}")
    else:
        print("✅ No new badges earned")

    print("\n✅ Correction complete!")
    return 0


def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Usage: python scripts/correct_sighting_license_plate.py <sighting_number> <correct_license_plate>")
        print()
        print("Arguments:")
        print("  sighting_number       - The sighting number shown in the web UI (global_sighting_index)")
        print("  correct_license_plate - The correct license plate for this sighting")
        print()
        print("Example:")
        print("  python scripts/correct_sighting_license_plate.py 42 T123456C")
        return 1

    try:
        sighting_number = int(sys.argv[1])
    except ValueError:
        print("❌ Error: sighting_number must be an integer")
        return 1

    correct_license_plate = sys.argv[2].strip().upper()

    return correct_sighting_license_plate(sighting_number, correct_license_plate)


if __name__ == "__main__":
    sys.exit(main())
