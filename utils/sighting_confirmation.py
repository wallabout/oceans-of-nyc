"""Shared utilities for sighting confirmation across SMS and web submissions."""


def evaluate_and_save_badges(db, contributor_id: int) -> list[dict]:
    """
    Evaluate badges for a contributor and save any newly earned ones.

    Args:
        db: SightingsDatabase instance
        contributor_id: The contributor's ID

    Returns:
        List of badge dicts with name, display_name, description, emoji for newly earned badges
    """
    try:
        from badges.definitions import BADGE_BY_NAME
        from badges.evaluator import evaluate_badges_for_contributor

        # Get list of newly earned badge names
        new_badge_names = evaluate_badges_for_contributor(db, contributor_id)

        if not new_badge_names:
            return []

        # Save the new badges
        db.save_badges(contributor_id, new_badge_names)

        # Return full badge info for display
        new_badges = []
        for name in new_badge_names:
            badge_def = BADGE_BY_NAME.get(name)
            if badge_def:
                new_badges.append(
                    {
                        "name": badge_def.name,
                        "display_name": badge_def.display_name,
                        "description": badge_def.description,
                        "emoji": badge_def.emoji,
                    }
                )
        return new_badges
    except Exception as e:
        print(f"Warning: Badge evaluation failed: {e}")
        return []


def get_confirmation_data(db, plate: str, contributor_id: int) -> dict:
    """
    Gather all confirmation data for a sighting submission.

    This function collects the stats and evaluates badges needed to provide
    rich feedback to contributors via SMS or web.

    Args:
        db: SightingsDatabase instance
        plate: The validated license plate
        contributor_id: The contributor's ID

    Returns:
        Dict with:
        - vehicle_sighting_num: How many times this vehicle has been sighted
        - total_sightings: Total sightings across all vehicles
        - contributor_sighting_num: How many sightings this contributor has made
        - new_badges: List of newly earned badge dicts (may be empty)
    """
    # Get stats
    vehicle_sighting_num = db.get_sighting_count(plate)
    total_sightings = db.get_total_sighting_count()
    contributor_sighting_num = db.get_contributor_sighting_count(contributor_id)

    # Evaluate and save any new badges
    new_badges = evaluate_and_save_badges(db, contributor_id)

    if new_badges:
        print(f"New badges earned: {[b['name'] for b in new_badges]}")

    return {
        "vehicle_sighting_num": vehicle_sighting_num,
        "total_sightings": total_sightings,
        "contributor_sighting_num": contributor_sighting_num,
        "new_badges": new_badges,
    }
