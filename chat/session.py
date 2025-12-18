"""Session state management for SMS conversations."""

import os
from datetime import datetime

import psycopg2


class ChatSession:
    """Manages conversation state for a phone number."""

    # Session states
    IDLE = "idle"
    AWAITING_LOCATION = "awaiting_location"
    AWAITING_PLATE = "awaiting_plate"
    AWAITING_NAME = "awaiting_name"

    def __init__(self, phone_number: str, db_url: str | None = None):
        self.phone_number = phone_number
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._data = None

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
                    conn.commit()

        return self._data

    def update(
        self,
        state: str | None = None,
        pending_image_path: str | None = None,
        pending_plate: str | None = None,
        pending_latitude: float | None = None,
        pending_longitude: float | None = None,
        pending_timestamp: datetime | None = None,
    ):
        """Update session state.

        Note: To explicitly clear a field, pass None.
        To leave a field unchanged, don't pass it at all.
        """
        updates = []
        params = []

        if state is not None:
            updates.append("state = %s")
            params.append(state)
        if pending_image_path is not None:
            updates.append("pending_image_path = %s")
            params.append(pending_image_path)
        if pending_plate is not None:
            updates.append("pending_plate = %s")
            params.append(pending_plate)

        # Special handling: when transitioning to AWAITING_PLATE or IDLE, always update lat/lon
        # This ensures stale coordinates from previous sessions are cleared
        if state in (self.AWAITING_PLATE, self.IDLE):
            # Always update these fields when changing to these states
            # This handles both new images (AWAITING_PLATE) and resets (IDLE)
            updates.append("pending_latitude = %s")
            params.append(pending_latitude)
            updates.append("pending_longitude = %s")
            params.append(pending_longitude)
        elif pending_latitude is not None or pending_longitude is not None:
            # For other states, only update if values are non-None
            updates.append("pending_latitude = %s")
            params.append(pending_latitude)
            updates.append("pending_longitude = %s")
            params.append(pending_longitude)

        if pending_timestamp is not None:
            updates.append("pending_timestamp = %s")
            params.append(pending_timestamp)

        updates.append("updated_at = CURRENT_TIMESTAMP")

        if len(updates) <= 1:  # Only updated_at
            return

        params.append(self.phone_number)

        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                query = f"""
                    UPDATE chat_sessions
                    SET {', '.join(updates)}
                    WHERE phone_number = %s
                    RETURNING *
                """
                cur.execute(query, params)
                row = cur.fetchone()
                if row:
                    cols = [desc[0] for desc in cur.description]
                    self._data = dict(zip(cols, row, strict=False))
                conn.commit()

    def reset(self):
        """Reset session to idle state."""
        self.update(
            state=self.IDLE,
            pending_image_path=None,
            pending_plate=None,
            pending_latitude=None,
            pending_longitude=None,
            pending_timestamp=None,
        )
