"""Conversation history storage for LLM-based SMS handler."""

import json
import os

import psycopg2
import psycopg2.extras


class ChatHistory:
    """Stores and retrieves conversation messages for a phone number."""

    def __init__(self, phone_number: str, db_url: str | None = None):
        self.phone_number = phone_number
        self.db_url = db_url or os.getenv("DATABASE_URL")

    def add_message(self, role: str, content: str, tool_use: dict | None = None):
        """Insert a message into chat_messages."""
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (phone_number, role, content, tool_use)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        self.phone_number,
                        role,
                        content,
                        json.dumps(tool_use) if tool_use else None,
                    ),
                )
                conn.commit()

    def get_recent(self, limit: int = 20) -> list[dict]:
        """Get last N messages ordered by created_at ASC (oldest first)."""
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT role, content, tool_use, created_at
                    FROM chat_messages
                    WHERE phone_number = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (self.phone_number, limit),
                )
                rows = cur.fetchall()
                return list(reversed(rows))

    def clear(self):
        """Delete all messages for this phone number."""
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM chat_messages WHERE phone_number = %s",
                    (self.phone_number,),
                )
                conn.commit()
