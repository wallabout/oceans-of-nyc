"""Computer vision extraction of TLC license plates from sighting images."""

import base64
import json
import re

import anthropic

MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = (
    "You are a license plate reader for NYC TLC (Taxi & Limousine Commission) vehicles. "
    "NYC TLC plates follow the format T######C — the letter T, exactly six digits, then the letter C "
    "(example: T123456C). "
    "When given an image, identify all text that is or could be a TLC license plate, "
    "including partial matches such as just the 6 digits, or a plate missing the T prefix or C suffix. "
    "Respond ONLY with a JSON object: {\"candidates\": [\"...\", \"...\"]} "
    "listing candidates from most to least likely. "
    "If no plates are visible, respond: {\"candidates\": []}"
)


def _normalize_candidate(text: str) -> str | None:
    """Normalize a raw string to T######C format, or return None if not plate-like."""
    text = re.sub(r"\s+", "", text.strip().upper())

    if re.fullmatch(r"T\d{6}C", text):
        return text

    if re.fullmatch(r"\d{6}", text):
        return f"T{text}C"

    m = re.fullmatch(r"T(\d{6})", text)
    if m:
        return f"T{m.group(1)}C"

    m = re.fullmatch(r"(\d{6})C", text)
    if m:
        return f"T{m.group(1)}C"

    return None


def extract_plate_from_image(image_bytes: bytes, db_url: str = None) -> str | None:
    """
    Use Claude Vision to extract a valid TLC license plate from a sighting image.

    Sends the image to Claude and asks it to identify all potential license plate
    strings. Each candidate is normalized to T######C format and validated against
    the tlc_vehicles table. Returns the first valid plate found, or None.

    Multiple plates may be visible in the image; all candidates are checked in
    confidence order before giving up.

    Args:
        image_bytes: Raw image bytes (JPEG or PNG)
        db_url: Database URL for TLC validation (uses DATABASE_URL env var if not provided)

    Returns:
        Validated license plate in T######C format, or None if no valid plate found
    """
    from validate.tlc import validate_plate

    if image_bytes[:2] == b"\xff\xd8":
        media_type = "image/jpeg"
    elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        media_type = "image/png"
    else:
        media_type = "image/jpeg"

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    client = anthropic.Anthropic()

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Identify all TLC license plates or partial plate numbers in this image.",
                        },
                    ],
                }
            ],
        )
    except anthropic.APIError:
        return None

    response_text = message.content[0].text.strip() if message.content else ""

    try:
        clean = re.sub(r"```[a-z]*\n?", "", response_text).strip().rstrip("`")
        data = json.loads(clean)
        candidates = data.get("candidates", [])
    except (json.JSONDecodeError, AttributeError):
        # Fallback: scan for anything plate-like in the raw text
        candidates = re.findall(r"T?\d{6}C?", response_text.upper())

    for raw in candidates:
        plate = _normalize_candidate(str(raw))
        if plate is None:
            continue
        try:
            is_valid, _ = validate_plate(plate, db_url=db_url)
            if is_valid:
                return plate
        except Exception:
            continue

    return None
