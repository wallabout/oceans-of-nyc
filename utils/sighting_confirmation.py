"""Shared utilities for sighting confirmation across SMS and web submissions."""

_HOUR = 3600
_DAY = 24 * _HOUR


def _plural(n: int, unit: str) -> str:
    return f"{n} {unit}" if n == 1 else f"{n} {unit}s"


def format_duration(seconds: float, hours: bool = True) -> str:
    """
    Describe an elapsed time in the largest unit that still reads naturally.

    "5 hours", "12 days", "4 months", "2 years". Mirrors formatDuration() in
    web/src/lib/feedCard.ts so SMS replies and the feed say the same thing.

    Args:
        seconds: Elapsed time in seconds
        hours: Allow hour-level answers. Pass False for date-only sources (like
            TLC report dates), where "3 hours" would be false precision.
    """
    seconds = max(seconds, 0)
    if hours and seconds < _HOUR:
        return "less than an hour"
    if hours and seconds < 2 * _DAY:
        return _plural(int(seconds // _HOUR), "hour")
    days = int(seconds // _DAY)
    if days < 1:
        return "less than a day"
    if days < 60:
        return _plural(days, "day")
    if days < 730:
        return _plural(round(days / 30.44), "month")
    return _plural(round(days / 365.25), "year")


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

        # Get list of newly earned (badge_name, sighting_id) tuples
        new_badge_data = evaluate_badges_for_contributor(db, contributor_id)

        if not new_badge_data:
            return []

        # Save the new badges
        db.save_badges(contributor_id, new_badge_data)

        # Return full badge info for display
        new_badges = []
        for name, _sighting_id in new_badge_data:
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


def get_confirmation_data(
    db, plate: str, contributor_id: int, vin: str = None, sighting_id: int = None
) -> dict:
    """
    Gather all confirmation data for a sighting submission.

    This function collects the stats and evaluates badges needed to provide
    rich feedback to contributors via SMS or web.

    Args:
        db: SightingsDatabase instance
        plate: The validated license plate
        contributor_id: The contributor's ID
        vin: The VIN (if available, used for count instead of plate)
        sighting_id: The sighting's DB ID (used to fetch ocean_points from the export view)

    Returns:
        Dict with:
        - vehicle_sighting_num: How many times this vehicle has been sighted (by VIN if available)
        - total_sightings: Total sightings across all vehicles
        - contributor_sighting_num: How many sightings this contributor has made
        - new_badges: List of newly earned badge dicts (may be empty)
        - ocean_points: ◎p earned for this sighting (None if not a first sighting)
        - global_unique_sighting_index: Ocean # for first sightings (None otherwise)
        - contributor_vehicle_sighting_num: How many times THIS contributor has sighted
          THIS specific ocean/vehicle (by VIN), including the current sighting. None when
          no VIN is available (can't reliably identify the same vehicle).
        - vehicle_first_sighted_ago: How long ago this vehicle was first sighted, e.g.
          "3 months". None for a first sighting or when no VIN is available.
        - vehicle_introduced_ago: How long ago this vehicle first appeared in TLC data,
          e.g. "8 months". None when unknown.
    """
    # Get stats - prefer VIN-based count over plate-based count
    if vin:
        vehicle_sighting_num = db.get_sighting_count_by_vin(vin)
    else:
        vehicle_sighting_num = db.get_sighting_count(plate)

    total_sightings = db.get_total_sighting_count()
    contributor_sighting_num = db.get_contributor_sighting_count(contributor_id)

    # Evaluate and save any new badges
    new_badges = evaluate_and_save_badges(db, contributor_id)

    if new_badges:
        print(f"New badges earned: {[b['name'] for b in new_badges]}")

    # Fetch Ocean Points from the export view if we have a sighting ID
    ocean_points = None
    global_unique_sighting_index = None
    contributor_vehicle_sighting_num = None
    if sighting_id:
        try:
            export_data = db.get_sighting_export_data(sighting_id)
            if export_data:
                op = export_data.get("ocean_points")
                # ocean_points is 0 for repeat sightings; only expose it for first sightings
                if op and float(op) > 0:
                    ocean_points = float(op)
                    global_unique_sighting_index = export_data.get("global_unique_sighting_index")
                # Only meaningful when we can identify the vehicle by VIN; with a NULL
                # VIN the export view groups all VIN-less sightings together.
                if vin:
                    cvsi = export_data.get("contributor_vehicle_sighting_index")
                    if cvsi is not None:
                        contributor_vehicle_sighting_num = int(cvsi)
        except Exception as e:
            print(f"Warning: Could not fetch export data for sighting {sighting_id}: {e}")

    vehicle_first_sighted_ago = None
    vehicle_introduced_ago = None
    if vin:
        try:
            history = db.get_vehicle_history(vin, exclude_sighting_id=sighting_id)
            if history["first_sighted_seconds_ago"] is not None:
                vehicle_first_sighted_ago = format_duration(history["first_sighted_seconds_ago"])
            if history["introduced_days_ago"] is not None:
                vehicle_introduced_ago = format_duration(
                    history["introduced_days_ago"] * _DAY, hours=False
                )
        except Exception as e:
            print(f"Warning: Could not fetch vehicle history for {vin}: {e}")

    return {
        "vehicle_sighting_num": vehicle_sighting_num,
        "total_sightings": total_sightings,
        "contributor_sighting_num": contributor_sighting_num,
        "new_badges": new_badges,
        "ocean_points": ocean_points,
        "global_unique_sighting_index": global_unique_sighting_index,
        "contributor_vehicle_sighting_num": contributor_vehicle_sighting_num,
        "vehicle_first_sighted_ago": vehicle_first_sighted_ago,
        "vehicle_introduced_ago": vehicle_introduced_ago,
    }
