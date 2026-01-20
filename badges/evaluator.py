"""Badge evaluation logic for Bumper Stickers feature."""

from badges.definitions import BADGE_DEFINITIONS, BadgeDefinition


def evaluate_single_badge(conn, contributor_id: int, badge: BadgeDefinition) -> bool:
    """
    Evaluate if a contributor qualifies for a specific badge.

    Args:
        conn: Database connection
        contributor_id: The contributor's ID
        badge: The badge definition to evaluate

    Returns:
        True if the contributor qualifies for the badge
    """
    cursor = conn.cursor()

    # Replace $1 placeholder with psycopg2's %s
    sql = badge.sql_check.replace("$1", "%s")

    cursor.execute(sql, (contributor_id,))
    result = cursor.fetchone()

    # SQL should return a single boolean value
    return bool(result[0]) if result else False


def evaluate_badges_for_contributor(
    db,
    contributor_id: int,
    context: dict = None,
) -> list[str]:
    """
    Evaluate all badges the contributor doesn't have and return newly earned ones.

    Args:
        db: SightingsDatabase instance
        contributor_id: The contributor's ID
        context: Optional context dict with keys like 'license_plate', 'borough'
                (reserved for future use with context-dependent badges)

    Returns:
        List of badge names that were newly earned
    """
    conn = db._get_connection()

    try:
        # Get badges the contributor already has
        existing_badges = set(db.get_contributor_badge_names(contributor_id))

        # Evaluate each badge the contributor doesn't have
        newly_earned = []

        for badge in BADGE_DEFINITIONS:
            if badge.name in existing_badges:
                continue

            if evaluate_single_badge(conn, contributor_id, badge):
                newly_earned.append(badge.name)

        return newly_earned

    finally:
        conn.close()


def evaluate_all_badges_for_contributor(db, contributor_id: int) -> list[str]:
    """
    Evaluate all badges for a contributor, ignoring existing badges.
    Used for retroactive backfill.

    Args:
        db: SightingsDatabase instance
        contributor_id: The contributor's ID

    Returns:
        List of all badge names the contributor qualifies for
    """
    conn = db._get_connection()

    try:
        qualified = []

        for badge in BADGE_DEFINITIONS:
            if evaluate_single_badge(conn, contributor_id, badge):
                qualified.append(badge.name)

        return qualified

    finally:
        conn.close()
