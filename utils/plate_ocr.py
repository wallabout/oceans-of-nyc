"""Read license plates from sighting photos and match them to known Oceans.

Reading a plate from a street photo is unreliable, but the answer is never
open-ended: it has to be one of the Fisker Oceans in the TLC registry. So the
vision model only needs to get close, and match_plate() turns a partial or
slightly wrong reading into a short list of real plates to suggest.
"""

import base64
import io
import json
import re
from dataclasses import dataclass, field

import anthropic
from PIL import Image, ImageOps

from chat.extractors import extract_plate_from_text

DEFAULT_MODEL = "claude-haiku-4-5"

# Claude downsizes anything with a long edge over ~1568px, so sending more
# only costs upload time. Plates are small in the frame, so don't go lower.
MAX_IMAGE_EDGE = 1568

# Characters the model couldn't make out are returned as this.
UNREADABLE = "?"

# A reading with fewer legible characters than this matches too many plates
# to be worth suggesting.
MIN_LEGIBLE_CHARS = 4

PLATE_PROMPT = f"""This photo should show a Fisker Ocean operating as a NYC TLC vehicle.
Read its license plate. Almost every TLC plate is "T", six digits, then "C" (e.g. T731580C),
though a few are different.

Transcribe the plate characters exactly as printed, with no spaces or dashes.
Use "{UNREADABLE}" for each character you can't make out, so a partly hidden plate might be T73{UNREADABLE}580C.
If several cars are visible, read the Fisker Ocean's plate.
If no plate is visible at all, return an empty string."""

PLATE_SCHEMA = {
    "type": "object",
    "properties": {"plate": {"type": "string"}},
    "required": ["plate"],
    "additionalProperties": False,
}


@dataclass
class PlateMatch:
    """A known plate that a reading could plausibly be."""

    plate: str
    distance: int


@dataclass
class PlateReading:
    """What the model read from a photo, plus the known plates it might be."""

    raw: str | None
    suggestions: list[PlateMatch] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def best(self) -> str | None:
        return self.suggestions[0].plate if self.suggestions else None


def prepare_image(image_bytes: bytes, max_edge: int = MAX_IMAGE_EDGE) -> bytes:
    """Orient, shrink and re-encode a photo as JPEG for the vision model."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def normalize_reading(raw: str | None) -> str | None:
    """
    Clean up a model reading into a comparable plate string.

    Keeps "?" placeholders, strips everything else that isn't a letter or digit,
    and expands shorthand like "731580" to the standard T731580C form.
    """
    if not raw:
        return None

    cleaned = re.sub(rf"[^A-Z0-9{re.escape(UNREADABLE)}]", "", raw.upper())
    if not cleaned:
        return None

    if UNREADABLE not in cleaned:
        return extract_plate_from_text(cleaned) or cleaned

    # Same shorthand expansion, but with placeholders in the digits
    digits = r"[0-9?]{6}"
    if re.fullmatch(digits, cleaned):
        return f"T{cleaned}C"
    if re.fullmatch(rf"T{digits}", cleaned):
        return f"{cleaned}C"
    if re.fullmatch(rf"{digits}C", cleaned):
        return f"T{cleaned}"
    return cleaned


def plate_distance(reading: str, plate: str) -> int:
    """
    Edit distance between a reading and a known plate.

    A "?" in the reading matches any single character for free, since it marks
    a character the model saw but couldn't read.
    """
    previous = list(range(len(plate) + 1))
    for i, read_char in enumerate(reading, 1):
        current = [i]
        for j, plate_char in enumerate(plate, 1):
            substitution = 0 if read_char in (plate_char, UNREADABLE) else 1
            current.append(
                min(
                    previous[j] + 1,  # extra character in the reading
                    current[j - 1] + 1,  # character missing from the reading
                    previous[j - 1] + substitution,
                )
            )
        previous = current
    return previous[-1]


def match_plate(
    reading: str | None,
    known_plates: list[str],
    max_distance: int = 2,
    limit: int = 3,
) -> list[PlateMatch]:
    """
    Find the known plates closest to a model reading.

    Args:
        reading: Raw or normalized model reading (may contain "?")
        known_plates: Every plate in the TLC registry
        max_distance: Largest edit distance worth suggesting
        limit: Maximum number of suggestions

    Returns:
        Up to `limit` matches, closest first. Empty if the reading is too
        illegible to narrow things down.
    """
    reading = normalize_reading(reading)
    if not reading:
        return []

    legible = sum(1 for char in reading if char != UNREADABLE)
    if legible < MIN_LEGIBLE_CHARS:
        return []

    matches = []
    for plate in known_plates:
        distance = plate_distance(reading, plate)
        if distance <= max_distance:
            matches.append(PlateMatch(plate=plate, distance=distance))

    matches.sort(key=lambda match: (match.distance, match.plate))
    return matches[:limit]


def read_plate(
    image_bytes: bytes,
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
) -> tuple[str | None, int, int]:
    """
    Ask the vision model to transcribe the plate in a photo.

    Returns:
        Tuple of (raw reading or None, input tokens, output tokens)
    """
    client = client or anthropic.Anthropic()
    image_data = base64.standard_b64encode(prepare_image(image_bytes)).decode("utf-8")

    response = client.messages.create(
        model=model,
        max_tokens=256,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": PLATE_PROMPT},
                ],
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": PLATE_SCHEMA}},
    )

    usage = (response.usage.input_tokens, response.usage.output_tokens)

    if response.stop_reason != "end_turn":
        print(f"Plate read stopped early: {response.stop_reason}")
        return None, *usage

    text = next((block.text for block in response.content if block.type == "text"), "")
    plate = json.loads(text).get("plate", "").strip()
    return plate or None, *usage


def extract_plate_from_image(
    image_bytes: bytes,
    known_plates: list[str],
    client: anthropic.Anthropic | None = None,
    model: str = DEFAULT_MODEL,
) -> PlateReading:
    """
    Read the plate in a photo and suggest the known plates it most likely is.

    Args:
        image_bytes: Original photo bytes (any format Pillow can open)
        known_plates: Every plate in the TLC registry
        client: Anthropic client (created from the environment if omitted)
        model: Vision model to use

    Returns:
        PlateReading with the raw reading and closest known plates
    """
    raw, input_tokens, output_tokens = read_plate(image_bytes, client=client, model=model)
    return PlateReading(
        raw=raw,
        suggestions=match_plate(raw, known_plates),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
