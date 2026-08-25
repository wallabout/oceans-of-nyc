"""Extract structured data from user messages."""

import re

# Plausible plate lengths, used when falling back to free-form candidates.
MIN_PLATE_LENGTH = 4
MAX_PLATE_LENGTH = 8


def extract_plate_from_text(text: str) -> str | None:
    """
    Extract a plate in the standard TLC format from user text.

    Matches the NYC TLC plate formats almost every plate follows:
    - T######C (full format, e.g., T123456C)
    - ###### (6 digits only, will be normalized to T######C)
    - T###### (missing C suffix)
    - ######C (missing T prefix)

    A handful of valid plates don't follow this pattern, so a None here means
    "not in the standard format", not "not a real plate". Use
    extract_plate_candidates() to collect those too and let the TLC database
    decide.

    Args:
        text: User's message text

    Returns:
        Normalized plate (T######C format) or None if no standard-format plate found
    """
    if not text:
        return None

    text = text.strip().upper()

    # Pattern 1: Full format T######C
    match = re.search(r"\bT(\d{6})C\b", text)
    if match:
        return f"T{match.group(1)}C"

    # Pattern 2: Just 6 digits
    match = re.search(r"\b(\d{6})\b", text)
    if match:
        return f"T{match.group(1)}C"

    # Pattern 3: T###### (missing C suffix)
    match = re.search(r"\bT(\d{6})\b", text)
    if match:
        return f"T{match.group(1)}C"

    # Pattern 4: ######C (missing T prefix)
    match = re.search(r"\b(\d{6})C\b", text)
    if match:
        return f"T{match.group(1)}C"

    return None


def extract_plate_candidates(text: str) -> list[str]:
    """
    Collect every plate spelling worth checking against the TLC database.

    Validity is the database's call, not this function's. We only decide which
    strings are plausible enough to look up, ordered best guess first:

    1. The standard T######C reading, including shorthand like "123456"
    2. The whole message, if the user just sent a plate we have no pattern for
       (vanity plates and other non-conforming but valid TLC plates)
    3. Plate-shaped tokens inside a longer message, e.g. "plate is NO1BOSS"

    Args:
        text: User's message text

    Returns:
        Ordered, de-duplicated list of candidate plates (may be empty)
    """
    if not text:
        return []

    text = text.strip().upper()
    candidates = []

    standard = extract_plate_from_text(text)
    if standard:
        candidates.append(standard)

    # The message on its own, punctuation and spaces removed
    compact = re.sub(r"[^A-Z0-9]", "", text)
    if MIN_PLATE_LENGTH <= len(compact) <= MAX_PLATE_LENGTH:
        candidates.append(compact)

    # Tokens embedded in a longer message. Requiring a digit keeps ordinary
    # words out; a wordy message with an all-letters plate stays ambiguous.
    for token in re.findall(r"[A-Z0-9][A-Z0-9-]*", text):
        token = token.replace("-", "")
        if MIN_PLATE_LENGTH <= len(token) <= MAX_PLATE_LENGTH and any(
            char.isdigit() for char in token
        ):
            candidates.append(token)

    deduped = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)

    return deduped


def extract_borough_from_text(text: str) -> str | None:
    """
    Extract a borough from user text.

    Uses the existing borough parser to detect borough names or abbreviations
    anywhere in the text.

    Args:
        text: User's message text

    Returns:
        Canonical borough name or None if not found
    """
    if not text:
        return None

    from geolocate.boroughs import parse_borough_input

    # Try to parse the whole text first
    borough = parse_borough_input(text)
    if borough:
        return borough

    # Try to find borough keywords in the text
    text_upper = text.upper()

    # Look for common patterns like "in Brooklyn" or "Brooklyn"
    borough_keywords = {
        "BROOKLYN": "Brooklyn",
        "MANHATTAN": "Manhattan",
        "QUEENS": "Queens",
        "BRONX": "Bronx",
        "STATEN ISLAND": "Staten Island",
        "BK": "Brooklyn",  # Common abbreviation
    }

    for keyword, canonical in borough_keywords.items():
        if keyword in text_upper:
            return canonical

    # Look for single letter indicators (only if isolated, not part of a plate)
    # Match single letters that are word boundaries
    for letter, canonical in [
        ("B", "Brooklyn"),
        ("M", "Manhattan"),
        ("Q", "Queens"),
        ("X", "Bronx"),
        ("S", "Staten Island"),
    ]:
        # Use word boundary to avoid matching letters in plates
        if re.search(rf"\b{letter}\b", text_upper):
            return canonical

    return None
