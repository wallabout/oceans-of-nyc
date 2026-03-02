"""Backfill sighting_id on existing contributor_badges rows.

For each badge row where sighting_id IS NULL, runs the badge's sighting_sql
(if defined) to find the earning sighting and updates the record.

Safe to re-run — only updates rows where sighting_id is still NULL.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SightingsDatabase
from badges.definitions import BADGE_BY_NAME


def backfill(db_url: str) -> None:
    db = SightingsDatabase(db_url)
    conn = db._get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT contributor_id, badge_name
            FROM contributors_badges
            WHERE sighting_id IS NULL
            ORDER BY contributor_id, badge_name
            """
        )
        rows = cursor.fetchall()
        print(f"Found {len(rows)} badge row(s) with no sighting_id")

        updated = 0
        skipped = 0

        for contributor_id, badge_name in rows:
            badge = BADGE_BY_NAME.get(badge_name)

            if badge is None:
                print(f"  WARNING: unknown badge '{badge_name}' — skipping")
                skipped += 1
                continue

            if not badge.sighting_sql:
                skipped += 1
                continue

            sighting_sql = badge.sighting_sql.replace("$1", "%s")
            param_count = sighting_sql.count("%s")
            cursor.execute(sighting_sql, (contributor_id,) * param_count)
            result = cursor.fetchone()

            if result is None:
                print(
                    f"  WARNING: no earning sighting found for contributor {contributor_id}, badge '{badge_name}'"
                )
                skipped += 1
                continue

            sighting_id = result[0]
            cursor.execute(
                """
                UPDATE contributors_badges
                SET sighting_id = %s
                WHERE contributor_id = %s AND badge_name = %s
                """,
                (sighting_id, contributor_id, badge_name),
            )
            updated += 1

        conn.commit()
        print(f"Done. Updated: {updated}, skipped: {skipped}")

    except Exception as e:
        conn.rollback()
        print(f"Error during backfill: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable is required")
        sys.exit(1)
    backfill(db_url)
