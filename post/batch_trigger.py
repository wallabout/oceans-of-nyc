"""Batch posting trigger logic for conditional posting after sightings."""

from datetime import datetime


def should_trigger_batch_post(unposted_sightings: list) -> bool:
    """
    Determine if a batch post should be triggered based on queue state.

    Conditions for triggering:
    1. 4 or more sightings are waiting to be posted, OR
    2. The oldest sighting has been waiting for 24+ hours

    Args:
        unposted_sightings: List of unposted sighting tuples from db.get_unposted_sightings()
                           Format: (id, license_plate, created_at, latitude, longitude, image_filename,
                                   created_at, post_uri, contributor_id, preferred_name,
                                   bluesky_handle, phone_number)

    Returns:
        bool: True if batch post should be triggered, False otherwise
    """
    if not unposted_sightings:
        return False

    # Condition 1: Check if we have 4+ sightings waiting
    if len(unposted_sightings) >= 4:
        print(f"✓ Batch trigger: {len(unposted_sightings)} sightings waiting (threshold: 4)")
        return True

    # Condition 2: Check if oldest sighting has been waiting 24+ hours
    # created_at is at index 7 in the tuple (after borough)
    oldest_sighting = unposted_sightings[0]  # Already sorted by timestamp ASC
    created_at_str = oldest_sighting[7]

    try:
        # Parse the created_at timestamp
        if isinstance(created_at_str, str):
            created_at = datetime.fromisoformat(created_at_str)
        elif isinstance(created_at_str, datetime):
            created_at = created_at_str
        else:
            print(f"⚠️ Unexpected created_at type: {type(created_at_str)}")
            return False

        time_waiting = datetime.now() - created_at
        hours_waiting = time_waiting.total_seconds() / 3600

        if hours_waiting >= 24:
            print(
                f"✓ Batch trigger: Oldest sighting waiting {hours_waiting:.1f} hours (threshold: 24)"
            )
            return True

        print(
            f"✗ Batch not triggered: {len(unposted_sightings)} sightings, "
            f"oldest waiting {hours_waiting:.1f} hours"
        )
        return False

    except Exception as e:
        print(f"⚠️ Error checking oldest sighting timestamp: {e}")
        return False


def get_batch_post_stats(unposted_sightings: list) -> dict:
    """
    Get statistics about the current batch posting queue.

    Args:
        unposted_sightings: List of unposted sighting tuples from db.get_unposted_sightings()

    Returns:
        dict with keys:
            - count: Number of unposted sightings
            - oldest_hours: Hours the oldest sighting has been waiting (or None)
            - should_post: Whether batch post should be triggered
    """
    if not unposted_sightings:
        return {"count": 0, "oldest_hours": None, "should_post": False}

    oldest_sighting = unposted_sightings[0]
    created_at_str = oldest_sighting[7]

    oldest_hours = None
    try:
        if isinstance(created_at_str, str):
            created_at = datetime.fromisoformat(created_at_str)
        elif isinstance(created_at_str, datetime):
            created_at = created_at_str
        else:
            created_at = None

        if created_at:
            time_waiting = datetime.now() - created_at
            oldest_hours = time_waiting.total_seconds() / 3600
    except Exception as e:
        print(f"⚠️ Error calculating oldest hours: {e}")

    return {
        "count": len(unposted_sightings),
        "oldest_hours": oldest_hours,
        "should_post": should_trigger_batch_post(unposted_sightings),
    }
