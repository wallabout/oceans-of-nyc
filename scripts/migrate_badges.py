#!/usr/bin/env python3
"""Migrate badges: remove old week_streak badges and backfill new badges."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from badges.definitions import BADGE_BY_NAME
from badges.evaluator import evaluate_all_badges_for_contributor
from database import SightingsDatabase

# Load environment variables
load_dotenv()


def delete_old_badges(db):
    """Delete old week_streak_4 and week_streak_12 badges."""
    print("\n" + "=" * 60)
    print("Step 1: Removing old badge records")
    print("=" * 60 + "\n")

    conn = db._get_connection()
    cursor = conn.cursor()

    try:
        # Check how many records will be deleted
        cursor.execute(
            """
            SELECT badge_name, COUNT(*) as count
            FROM contributors_badges
            WHERE badge_name IN ('week_streak_4', 'week_streak_12')
            GROUP BY badge_name
        """
        )

        old_badges = cursor.fetchall()

        if not old_badges:
            print("✓ No old badge records found (already cleaned up)")
            return

        print("Found old badge records:")
        for badge_name, count in old_badges:
            print(f"  - {badge_name}: {count} record(s)")

        # Delete the old badges
        cursor.execute(
            """
            DELETE FROM contributors_badges
            WHERE badge_name IN ('week_streak_4', 'week_streak_12')
        """
        )

        deleted_count = cursor.rowcount
        conn.commit()

        print(f"\n✓ Deleted {deleted_count} old badge record(s)")

    finally:
        conn.close()


def backfill_new_badges(db):
    """Evaluate and award new badges to all contributors."""
    print("\n" + "=" * 60)
    print("Step 2: Evaluating and awarding new badges")
    print("=" * 60 + "\n")

    contributors = db.get_all_contributors()

    if not contributors:
        print("No contributors found in database.")
        return

    print(f"Evaluating badges for {len(contributors)} contributor(s)...\n")

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

        # Filter to only new badges
        new_badges = [b for b in qualified_badges if b not in existing_badges]

        if new_badges:
            contributors_with_new_badges += 1

            # Save the new badges
            saved_count = db.save_badges(contributor_id, new_badges)
            total_badges_awarded += saved_count

            print(f"  {display_name}: Awarded {saved_count} new badge(s)")
            for badge_name in new_badges:
                badge_def = BADGE_BY_NAME.get(badge_name)
                if badge_def:
                    print(f"    - {badge_def.emoji} {badge_def.display_name}")

    print(
        f"\n✓ Awarded {total_badges_awarded} badge(s) to {contributors_with_new_badges} contributor(s)"
    )


def main():
    """Main execution."""
    print("\nBadge Migration Script")
    print("=" * 60)
    print("This will:")
    print("  1. Remove week_streak_4 and week_streak_12 badges")
    print("  2. Award new badges: ocean_month, ocean_quarter, self_dupe")
    print("=" * 60)

    # Initialize database
    db = SightingsDatabase()

    # Step 1: Delete old badges
    delete_old_badges(db)

    # Step 2: Backfill new badges
    backfill_new_badges(db)

    print("\n" + "=" * 60)
    print("✓ Badge migration completed!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
