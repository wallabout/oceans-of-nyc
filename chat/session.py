"""Session state management for SMS conversations."""

import os
from datetime import datetime

import psycopg2

# Sentinel value to indicate "set to NULL" vs "don't update"
_UNSET = object()


class ChatSession:
    """Manages conversation state for a phone number."""

    # Session states
    IDLE = "idle"
    AWAITING_BOROUGH = "awaiting_borough"
    AWAITING_PLATE = "awaiting_plate"
    AWAITING_NAME = "awaiting_name"
    # A sighting was just saved but the photo is kept around so the contributor
    # can text additional plates for the same picture (several Oceans in one frame).
    SAVED = "saved"

    # How long after a save the last photo may be reused for another plate.
    REUSE_WINDOW_SECONDS = 15 * 60

    def __init__(self, phone_number: str, db_url: str | None = None):
        self.phone_number = phone_number
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._data = None
        self._is_new_session = False

    def get(self) -> dict:
        """Get or create session for this phone number."""
        if self._data:
            return self._data

        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                # Try to get existing session
                cur.execute(
                    "SELECT * FROM chat_sessions WHERE phone_number = %s", (self.phone_number,)
                )
                row = cur.fetchone()

                if row:
                    cols = [desc[0] for desc in cur.description]
                    self._data = dict(zip(cols, row, strict=False))
                    self._is_new_session = False
                else:
                    # Create new session
                    cur.execute(
                        """
                        INSERT INTO chat_sessions (phone_number, state)
                        VALUES (%s, %s)
                        RETURNING *
                        """,
                        (self.phone_number, self.IDLE),
                    )
                    row = cur.fetchone()
                    cols = [desc[0] for desc in cur.description]
                    self._data = dict(zip(cols, row, strict=False))
                    self._is_new_session = True
                    conn.commit()

        return self._data

    def is_new_session(self) -> bool:
        """Check if this is a newly created session."""
        return self._is_new_session

    def update(
        self,
        state: str | None = _UNSET,
        pending_image_path: str | None = _UNSET,
        pending_plate: str | None = _UNSET,
        pending_latitude: float | None = _UNSET,
        pending_longitude: float | None = _UNSET,
        pending_timestamp: datetime | None = _UNSET,
        pending_borough: str | None = _UNSET,
        pending_image_timestamp: datetime | None = _UNSET,
    ):
        """Update session state.

        Note: To explicitly clear a field, pass None.
        To leave a field unchanged, don't pass it at all.
        """
        updates = []
        params = []

        if state is not _UNSET:
            updates.append("state = %s")
            params.append(state)
        if pending_image_path is not _UNSET:
            updates.append("pending_image_path = %s")
            params.append(pending_image_path)
        if pending_plate is not _UNSET:
            updates.append("pending_plate = %s")
            params.append(pending_plate)
        if pending_borough is not _UNSET:
            updates.append("pending_borough = %s")
            params.append(pending_borough)

        # Special handling: when transitioning to AWAITING_PLATE or IDLE, always update lat/lon
        # This ensures stale coordinates from previous sessions are cleared
        if state in (self.AWAITING_PLATE, self.IDLE):
            # Always update these fields when changing to these states
            # This handles both new images (AWAITING_PLATE) and resets (IDLE)
            updates.append("pending_latitude = %s")
            params.append(pending_latitude if pending_latitude is not _UNSET else None)
            updates.append("pending_longitude = %s")
            params.append(pending_longitude if pending_longitude is not _UNSET else None)
        elif pending_latitude is not _UNSET or pending_longitude is not _UNSET:
            # For other states, only update if explicitly passed
            updates.append("pending_latitude = %s")
            params.append(pending_latitude if pending_latitude is not _UNSET else None)
            updates.append("pending_longitude = %s")
            params.append(pending_longitude if pending_longitude is not _UNSET else None)

        if pending_timestamp is not _UNSET:
            updates.append("pending_timestamp = %s")
            params.append(pending_timestamp)

        if pending_image_timestamp is not _UNSET:
            updates.append("pending_image_timestamp = %s")
            params.append(pending_image_timestamp)

        updates.append("updated_at = CURRENT_TIMESTAMP")

        if len(updates) <= 1:  # Only updated_at
            return

        params.append(self.phone_number)

        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                query = f"""
                    UPDATE chat_sessions
                    SET {", ".join(updates)}
                    WHERE phone_number = %s
                    RETURNING *
                """
                cur.execute(query, params)
                row = cur.fetchone()
                if row:
                    cols = [desc[0] for desc in cur.description]
                    self._data = dict(zip(cols, row, strict=False))
                conn.commit()

    def mark_saved(self):
        """Record that the pending sighting was saved, keeping the photo reusable.

        Unlike reset(), the pending image path, coordinates, borough and timestamps
        are retained so a follow-up plate within REUSE_WINDOW_SECONDS can be saved
        against the same photo. Only the plate is cleared.
        """
        self.update(state=self.SAVED, pending_plate=None)

    def can_reuse_image(self, now: datetime | None = None) -> bool:
        """True if the session holds a recently saved photo that may back another plate."""
        data = self.get()
        if data.get("state") != self.SAVED or not data.get("pending_image_path"):
            return False
        updated_at = data.get("updated_at")
        if updated_at is None:
            return False
        if now is None:
            now = datetime.now(updated_at.tzinfo) if updated_at.tzinfo else datetime.now()
        return (now - updated_at).total_seconds() <= self.REUSE_WINDOW_SECONDS

    def reset(self):
        """Reset session to idle state."""
        self.update(
            state=self.IDLE,
            pending_image_path=None,
            pending_plate=None,
            pending_latitude=None,
            pending_longitude=None,
            pending_timestamp=None,
            pending_borough=None,
            pending_image_timestamp=None,
        )
