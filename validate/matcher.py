"""License plate matching and validation."""

from typing import Optional
from .tlc import TLCDatabase


def validate_plate(plate: str, db_url: str = None) -> tuple[bool, Optional[tuple]]:
    """
    Validate a license plate against the TLC database.

    Args:
        plate: License plate to validate
        db_url: Database URL (uses DATABASE_URL env var if not provided)

    Returns:
        Tuple of (is_valid, vehicle_record or None)
    """
    tlc_db = TLCDatabase(db_url)
    vehicle = tlc_db.get_vehicle_by_plate(plate)

    if vehicle:
        return True, vehicle
    return False, None


def get_potential_matches(partial_plate: str, db_url: str = None, max_results: int = 10) -> list[str]:
    """
    Get potential plate matches for a partial or unclear plate.

    This function is useful when a user can't read all characters on a plate.
    It uses wildcard matching to find possible matches.

    Args:
        partial_plate: Partial plate with * for unknown characters (e.g., 'T73**580C')
        db_url: Database URL (uses DATABASE_URL env var if not provided)
        max_results: Maximum number of results to return

    Returns:
        List of matching license plate strings
    """
    tlc_db = TLCDatabase(db_url)
    results = tlc_db.search_plates_wildcard(partial_plate)

    # Extract just the plate numbers
    plates = [row[0] for row in results[:max_results]]
    return plates


def find_similar_plates(plate: str, db_url: str = None, max_results: int = 5) -> list[str]:
    """
    Find plates similar to the given plate (for typo correction).

    This performs a simple character-by-character comparison and returns
    plates that differ by only 1-2 characters.

    Args:
        plate: The plate to find similar matches for
        db_url: Database URL (uses DATABASE_URL env var if not provided)
        max_results: Maximum number of results to return

    Returns:
        List of similar license plate strings, sorted by similarity
    """
    tlc_db = TLCDatabase(db_url)
    all_plates = tlc_db.get_all_plates()

    # Calculate similarity scores
    scored_plates = []
    for candidate in all_plates:
        if len(candidate) != len(plate):
            continue

        # Count differing characters
        diff_count = sum(1 for a, b in zip(plate.upper(), candidate.upper()) if a != b)

        # Only include plates with 1-2 character differences
        if 0 < diff_count <= 2:
            scored_plates.append((diff_count, candidate))

    # Sort by difference count and return top matches
    scored_plates.sort(key=lambda x: x[0])
    return [p[1] for p in scored_plates[:max_results]]
