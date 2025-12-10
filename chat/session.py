"""Session state management for SMS conversations."""

import os
from datetime import datetime
from typing import Optional
import psycopg2


class ChatSession:
    """Manages conversation state for a phone number."""

    # Session states
    IDLE = "idle"
    AWAITING_LOCATION = "awaiting_location"
    AWAITING_PLATE = "awaiting_plate"
    AWAITING_CONFIRMATION = "awaiting_confirmation"

    def __init__(self, phone_number: str, db_url: Optional[str] = None):
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
                    "SELECT * FROM chat_sessions WHERE phone_number = %s",
                    (self.phone_number,)
                )
                row = cur.fetchone()

                if row:
                    cols = [desc[0] for desc in cur.description]
                    self._data = dict(zip(cols, row))
                else:
                    # Create new session
                    cur.execute(
                        """
                        INSERT INTO chat_sessions (phone_number, state)
                        VALUES (%s, %s)
                        RETURNING *
                        """,
                        (self.phone_number, self.IDLE)
                    )
                    row = cur.fetchone()
                    cols = [desc[0] for desc in cur.description]
                    self._data = dict(zip(cols, row))
                    conn.commit()

        return self._data

    def update(
        self,
        state: Optional[str] = None,
        pending_image_path: Optional[str] = None,
        pending_plate: Optional[str] = None,
        pending_latitude: Optional[float] = None,
        pending_longitude: Optional[float] = None,
        pending_timestamp: Optional[datetime] = None,
    ):
        """Update session state."""
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
        if pending_latitude is not None:
            updates.append("pending_latitude = %s")
            params.append(pending_latitude)
        if pending_longitude is not None:
            updates.append("pending_longitude = %s")
            params.append(pending_longitude)
        if pending_timestamp is not None:
            updates.append("pending_timestamp = %s")
            params.append(pending_timestamp)

        updates.append("updated_at = CURRENT_TIMESTAMP")

        if not updates:
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
                    self._data = dict(zip(cols, row))
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
