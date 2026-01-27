#!/usr/bin/env python3
"""
Script to consolidate duplicate contributor identities.

Usage:
    python scripts/consolidate_contributors.py <eliminate_id> <retain_id>

This script:
1. Displays current sighting counts for both contributors
2. Asks for confirmation
3. Updates all sightings from eliminate_id to retain_id
4. Deletes badges for the eliminated contributor
5. Re-evaluates badges for the retained contributor
6. Offers to delete the eliminated contributor
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


def get_contributor_info(db: SightingsDatabase, contributor_id: int) -> dict | None:
    """Get contributor information and sighting count."""
    contributor = db.get_contributor(contributor_id=contributor_id)
    if not contributor:
        return None

    sighting_count = db.get_contributor_sighting_count(contributor_id)
    display_name = db.get_contributor_display_name(contributor_id)

    return {
        "id": contributor_id,
        "phone_number": contributor.get("phone_number"),
        "bluesky_handle": contributor.get("bluesky_handle"),
        "preferred_name": contributor.get("preferred_name"),
        "display_name": display_name,
        "sighting_count": sighting_count,
    }


def consolidate_contributors(eliminate_id: int, retain_id: int):
    """Consolidate two contributor identities by merging sightings."""

    # Initialize database
    db = SightingsDatabase()

    # Get info for both contributors
    print("Looking up contributor information...\n")

    eliminate_info = get_contributor_info(db, eliminate_id)
    if not eliminate_info:
        print(f"❌ Error: Contributor ID {eliminate_id} not found")
        return 1

    retain_info = get_contributor_info(db, retain_id)
    if not retain_info:
        print(f"❌ Error: Contributor ID {retain_id} not found")
        return 1

    # Display information
    print("=" * 70)
    print("CONTRIBUTOR CONSOLIDATION")
    print("=" * 70)
    print()
    print(f"📤 CONTRIBUTOR TO ELIMINATE (ID: {eliminate_id})")
    print(f"   Phone Number:    {eliminate_info['phone_number'] or 'None'}")
    print(f"   Bluesky Handle:  {eliminate_info['bluesky_handle'] or 'None'}")
    print(f"   Preferred Name:  {eliminate_info['preferred_name'] or 'None'}")
    print(f"   Display Name:    {eliminate_info['display_name'] or '(anonymous)'}")
    print(f"   Sighting Count:  {eliminate_info['sighting_count']}")
    print()
    print(f"📥 CONTRIBUTOR TO RETAIN (ID: {retain_id})")
    print(f"   Phone Number:    {retain_info['phone_number'] or 'None'}")
    print(f"   Bluesky Handle:  {retain_info['bluesky_handle'] or 'None'}")
    print(f"   Preferred Name:  {retain_info['preferred_name'] or 'None'}")
    print(f"   Display Name:    {retain_info['display_name'] or '(anonymous)'}")
    print(f"   Sighting Count:  {retain_info['sighting_count']}")
    print()
    print("=" * 70)
    print()

    total_after = eliminate_info["sighting_count"] + retain_info["sighting_count"]
    print(f"After consolidation, contributor {retain_id} will have {total_after} sightings.")
    print(f"Contributor {eliminate_id} will remain in the database but have 0 sightings.")
    print()

    # Ask for confirmation
    response = input("Do you want to proceed with this consolidation? (yes/no): ").strip().lower()

    if response not in ["yes", "y"]:
        print("\n❌ Consolidation cancelled.")
        return 0

    # Perform the update
    print(f"\n🔄 Updating sightings from contributor {eliminate_id} to {retain_id}...")

    conn = db._get_connection()
    cursor = conn.cursor()

    try:
        # Update all sightings
        cursor.execute(
            """
            UPDATE sightings
            SET contributor_id = %s
            WHERE contributor_id = %s
            """,
            (retain_id, eliminate_id),
        )

        rows_updated = cursor.rowcount
        conn.commit()

        print(f"✅ Successfully updated {rows_updated} sightings")

        # Delete badges for eliminated contributor
        print(f"\n🔄 Cleaning up badges for eliminated contributor {eliminate_id}...")
        cursor.execute(
            "DELETE FROM contributors_badges WHERE contributor_id = %s",
            (eliminate_id,),
        )
        badges_deleted = cursor.rowcount
        conn.commit()
        print(f"✅ Deleted {badges_deleted} badge(s) from eliminated contributor")

        # Re-evaluate badges for retained contributor
        print(f"\n🔄 Re-evaluating badges for retained contributor {retain_id}...")
        new_badges = evaluate_badges_for_contributor(db, retain_id)
        if new_badges:
            # Save newly earned badges
            saved_count = db.save_badges(retain_id, new_badges)
            print(f"✅ Earned {saved_count} new badge(s): {', '.join(new_badges)}")
        else:
            print("✅ No new badges earned")

        # Verify the update
        new_retain_count = db.get_contributor_sighting_count(retain_id)
        new_eliminate_count = db.get_contributor_sighting_count(eliminate_id)

        print("\n✅ Consolidation complete!")
        print(f"   Contributor {retain_id} now has {new_retain_count} sightings")
        print(f"   Contributor {eliminate_id} now has {new_eliminate_count} sightings")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Error during consolidation: {e}")
        return 1
    finally:
        conn.close()

    # Offer to delete the eliminated contributor
    print(f"\n⚠️  Contributor {eliminate_id} still exists in the database with 0 sightings.")
    delete_response = input("Do you want to delete this contributor? (yes/no): ").strip().lower()

    if delete_response in ["yes", "y"]:
        conn = db._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "DELETE FROM contributors WHERE id = %s",
                (eliminate_id,),
            )
            conn.commit()
            print(f"✅ Contributor {eliminate_id} deleted")
        except Exception as e:
            conn.rollback()
            print(f"❌ Error deleting contributor: {e}")
            return 1
        finally:
            conn.close()
    else:
        print(f"ℹ️  Contributor {eliminate_id} was not deleted")

    return 0


def main():
    """Main entry point."""
    if len(sys.argv) != 3:
        print("Usage: python scripts/consolidate_contributors.py <eliminate_id> <retain_id>")
        print()
        print("Arguments:")
        print("  eliminate_id  - The contributor ID to eliminate (will lose all sightings)")
        print("  retain_id     - The contributor ID to retain (will gain all sightings)")
        print()
        print("Example:")
        print("  python scripts/consolidate_contributors.py 42 17")
        return 1

    try:
        eliminate_id = int(sys.argv[1])
        retain_id = int(sys.argv[2])
    except ValueError:
        print("❌ Error: Both arguments must be integers")
        return 1

    if eliminate_id == retain_id:
        print("❌ Error: eliminate_id and retain_id must be different")
        return 1

    return consolidate_contributors(eliminate_id, retain_id)


if __name__ == "__main__":
    sys.exit(main())
