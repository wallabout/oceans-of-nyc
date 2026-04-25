"""Tool definitions and execution for LLM-based SMS handler."""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime

import psycopg2
import psycopg2.extras

VALIDATE_PLATE_TOOL = {
    "name": "validate_plate",
    "description": (
        "Validate a NYC TLC license plate against the TLC database. "
        "The plate format is T######C (T followed by 6 digits followed by C). "
        "Normalize user input before calling: if they say '123456', pass 'T123456C'. "
        "Returns whether the plate is valid and the VIN if found."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plate": {
                "type": "string",
                "description": "The license plate in T######C format.",
            }
        },
        "required": ["plate"],
    },
}

SAVE_SIGHTING_TOOL = {
    "name": "save_sighting",
    "description": (
        "Save a confirmed sighting to the database. Call this ONLY when you have: "
        "(1) a photo (from conversation context), "
        "(2) a validated TLC plate (you must have called validate_plate first), and "
        "(3) either GPS coordinates from the photo or a borough from the user. "
        "Returns confirmation details including sighting stats and any badges earned."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plate": {
                "type": "string",
                "description": "The validated license plate in T######C format.",
            },
            "borough": {
                "type": "string",
                "enum": [
                    "Brooklyn",
                    "Manhattan",
                    "Queens",
                    "Bronx",
                    "Staten Island",
                    "Outside NYC",
                ],
                "description": "NYC borough. Only required if the photo had no GPS data.",
            },
        },
        "required": ["plate"],
    },
}

SET_CONTRIBUTOR_NAME_TOOL = {
    "name": "set_contributor_name",
    "description": (
        "Set or update the contributor's preferred display name. "
        "This name appears on the public leaderboard and Bluesky posts. "
        "Call this when the user wants to set or change their name."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The preferred display name (max 50 characters).",
            }
        },
        "required": ["name"],
    },
}

ALL_TOOLS = [VALIDATE_PLATE_TOOL, SAVE_SIGHTING_TOOL, SET_CONTRIBUTOR_NAME_TOOL]


@dataclass
class ConversationContext:
    """Per-request state passed to tool execution functions.

    Persisted to DB between messages so multi-turn flows retain state.
    """

    from_number: str
    volume_path: str = "/data"
    pending_image_path: str | None = None
    pending_latitude: float | None = None
    pending_longitude: float | None = None
    pending_timestamp: datetime | None = None
    pending_image_timestamp: datetime | None = None
    validated_vin: str | None = None
    # Track validated plates so save_sighting can access the VIN
    validated_plates: dict = field(default_factory=dict)

    # -- Persistence --------------------------------------------------------

    _SERIALIZED_FIELDS = (
        "pending_image_path",
        "pending_latitude",
        "pending_longitude",
        "pending_timestamp",
        "pending_image_timestamp",
        "validated_vin",
        "validated_plates",
    )

    def save(self) -> None:
        """Persist context to the chat_context table."""
        data = {}
        for key in self._SERIALIZED_FIELDS:
            val = getattr(self, key)
            if isinstance(val, datetime):
                val = val.isoformat()
            if val is not None:
                data[key] = val

        db_url = os.getenv("DATABASE_URL")
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_context (phone_number, context_json, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (phone_number)
                    DO UPDATE SET context_json = EXCLUDED.context_json,
                                  updated_at = NOW()
                    """,
                    (self.from_number, json.dumps(data)),
                )
                conn.commit()

    @classmethod
    def load(cls, from_number: str, volume_path: str = "/data") -> "ConversationContext":
        """Load persisted context, or return a fresh one."""
        ctx = cls(from_number=from_number, volume_path=volume_path)
        db_url = os.getenv("DATABASE_URL")
        try:
            with psycopg2.connect(db_url) as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT context_json FROM chat_context WHERE phone_number = %s",
                        (from_number,),
                    )
                    row = cur.fetchone()
        except Exception:
            return ctx

        if not row or not row["context_json"]:
            return ctx

        data = row["context_json"]
        if isinstance(data, str):
            data = json.loads(data)

        for key in cls._SERIALIZED_FIELDS:
            if key not in data:
                continue
            val = data[key]
            if key in ("pending_timestamp", "pending_image_timestamp") and isinstance(val, str):
                val = datetime.fromisoformat(val)
            setattr(ctx, key, val)

        return ctx

    def clear_after_save(self) -> None:
        """Reset all pending state after a successful save."""
        self.pending_image_path = None
        self.pending_latitude = None
        self.pending_longitude = None
        self.pending_timestamp = None
        self.pending_image_timestamp = None
        self.validated_vin = None
        self.validated_plates = {}


def execute_tool(name: str, tool_input: dict, ctx: ConversationContext) -> str:
    """Dispatch a tool call and return the JSON-serialized result."""
    handlers = {
        "validate_plate": _execute_validate_plate,
        "save_sighting": _execute_save_sighting,
        "set_contributor_name": _execute_set_contributor_name,
    }

    handler = handlers.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})

    try:
        result = handler(tool_input, ctx)
        return json.dumps(result)
    except Exception as e:
        print(f"Tool execution error ({name}): {e}")
        return json.dumps({"error": str(e)})


def _execute_validate_plate(tool_input: dict, ctx: ConversationContext) -> dict:
    """Validate a plate against the TLC database."""
    from validate.tlc import validate_plate

    plate = tool_input["plate"].strip().upper()
    is_valid, vehicle = validate_plate(plate)

    if is_valid and vehicle:
        vin = vehicle.get("vin")
        # Store for later use by save_sighting
        ctx.validated_plates[plate] = vin
        return {
            "valid": True,
            "plate": plate,
            "vin": vin,
        }

    # Try to find similar plates for suggestions
    suggestions = _find_similar_plates(plate)
    result = {"valid": False, "plate": plate}
    if suggestions:
        result["suggestions"] = suggestions
    return result


def _find_similar_plates(plate: str) -> list[str]:
    """Find similar plates in the TLC database for suggestions."""
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return []

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Look for plates with similar digit sequences
                digits = "".join(c for c in plate if c.isdigit())
                if len(digits) < 4:
                    return []

                # Search for plates sharing a 4+ digit substring
                cur.execute(
                    """
                    SELECT DISTINCT license_plate
                    FROM tlc_vehicles
                    WHERE license_plate LIKE %s
                    LIMIT 5
                    """,
                    (f"%{digits[:4]}%",),
                )
                return [row[0] for row in cur.fetchall() if row[0] != plate]
    except Exception:
        return []


def _execute_save_sighting(tool_input: dict, ctx: ConversationContext) -> dict:
    """Save a sighting to the database."""
    from chat.webhook import spawn_background_processing
    from database.models import SightingsDatabase
    from utils.image_processor import ImageProcessor
    from utils.sighting_confirmation import get_confirmation_data

    plate = tool_input["plate"].strip().upper()
    borough = tool_input.get("borough")

    if not ctx.pending_image_path:
        return {"error": "No photo available. The user needs to send a photo first."}

    db = SightingsDatabase()
    processor = ImageProcessor(volume_path=ctx.volume_path)

    # Get or create contributor
    contributor_id = db.get_or_create_contributor(phone_number=ctx.from_number)

    # Get image timestamp, fall back to now
    image_timestamp = ctx.pending_image_timestamp or datetime.now()

    # Generate final filename and rename
    final_filename = processor.generate_filename(plate, image_timestamp)
    processor.rename_to_final(ctx.pending_image_path, final_filename)

    # Look up VIN from validated plates cache
    vin = ctx.validated_plates.get(plate)

    # Save sighting
    result = db.add_sighting(
        license_plate=plate,
        timestamp=ctx.pending_timestamp or datetime.now(),
        latitude=ctx.pending_latitude,
        longitude=ctx.pending_longitude,
        contributor_id=contributor_id,
        image_filename=final_filename,
        borough=borough if not ctx.pending_latitude else None,
        image_timestamp=image_timestamp,
        vin=vin,
    )

    if result is None:
        return {"error": "Failed to save sighting."}

    sighting_id = result["id"]
    print(f"Sighting saved: plate={plate}, id={sighting_id}")

    # Clear pending image so the same photo can't be submitted twice
    ctx.clear_after_save()

    # Evaluate badges and get confirmation stats
    conf = get_confirmation_data(db, plate, contributor_id, vin)

    # Spawn background processing (R2 upload, web data gen, batch check)
    spawn_background_processing(
        image_filename=final_filename,
        plate=plate,
        contributor_id=contributor_id,
        from_number=ctx.from_number,
        sighting_id=sighting_id,
    )

    # Check if contributor has a display name
    contributor = db.get_contributor(contributor_id=contributor_id)
    has_display_name = bool(contributor and contributor.get("preferred_name"))

    return {
        "success": True,
        "plate": plate,
        "vehicle_sighting_num": conf["vehicle_sighting_num"],
        "total_sightings": conf["total_sightings"],
        "contributor_sighting_num": conf["contributor_sighting_num"],
        "new_badges": conf["new_badges"],
        "has_display_name": has_display_name,
    }


def _execute_set_contributor_name(tool_input: dict, ctx: ConversationContext) -> dict:
    """Set the contributor's preferred display name."""
    from database.models import SightingsDatabase

    name = tool_input["name"].strip()[:50]
    db = SightingsDatabase()

    contributor_id = db.get_or_create_contributor(phone_number=ctx.from_number)
    db.update_contributor_name(contributor_id, name)

    return {"success": True, "name": name}
