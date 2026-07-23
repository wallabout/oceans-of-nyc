"""Badge evaluation logic for Badges feature."""

from badges.definitions import BADGE_DEFINITIONS, BadgeDefinition


def evaluate_single_badge(
    conn, contributor_id: int, badge: BadgeDefinition
) -> tuple[bool, int | None]:
    """
    Evaluate if a contributor qualifies for a specific badge.

    Args:
        conn: Database connection
        contributor_id: The contributor's ID
        badge: The badge definition to evaluate

    Returns:
        Tuple of (qualified, sighting_id) where sighting_id is the ID of the
        earning sighting if badge.sighting_sql is defined, otherwise None.
    """
    cursor = conn.cursor()

    # Replace $1 placeholder with psycopg2's %s
    sql = badge.sql_check.replace("$1", "%s")

    cursor.execute(sql, (contributor_id,))
    result = cursor.fetchone()

    if not result or not result[0]:
        return False, None

    # Contributor qualifies — find the earning sighting if sighting_sql is defined
    sighting_id = None
    if badge.sighting_sql:
        sighting_sql = badge.sighting_sql.replace("$1", "%s")
        param_count = sighting_sql.count("%s")
        cursor.execute(sighting_sql, (contributor_id,) * param_count)
        sighting_result = cursor.fetchone()
        if sighting_result:
            sighting_id = sighting_result[0]

    return True, sighting_id


def evaluate_badges_for_contributor(
    db,
    contributor_id: int,
    context: dict = None,
) -> list[tuple[str, int | None]]:
    """
    Evaluate all badges the contributor doesn't have and return newly earned ones.

    Args:
        db: SightingsDatabase instance
        contributor_id: The contributor's ID
        context: Optional context dict with keys like 'license_plate', 'borough'
                (reserved for future use with context-dependent badges)

    Returns:
        List of (badge_name, sighting_id) tuples for newly earned badges
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

            qualified, sighting_id = evaluate_single_badge(conn, contributor_id, badge)
            if qualified:
                newly_earned.append((badge.name, sighting_id))

        return newly_earned

    finally:
        conn.close()


def evaluate_all_badges_for_contributor(db, contributor_id: int) -> list[tuple[str, int | None]]:
    """
    Evaluate all badges for a contributor, ignoring existing badges.
    Used for retroactive backfill.

    Args:
        db: SightingsDatabase instance
        contributor_id: The contributor's ID

    Returns:
        List of (badge_name, sighting_id) tuples for all badges the contributor qualifies for
    """
    conn = db._get_connection()

    try:
        qualified = []

        for badge in BADGE_DEFINITIONS:
            earned, sighting_id = evaluate_single_badge(conn, contributor_id, badge)
            if earned:
                qualified.append((badge.name, sighting_id))

        return qualified

    finally:
        conn.close()
