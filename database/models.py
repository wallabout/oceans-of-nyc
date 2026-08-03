"""Core database operations for sightings."""

import os
from datetime import datetime

import psycopg2
import psycopg2.extras


class SightingsDatabase:
    """Database operations for Fisker Ocean sightings."""

    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided and not found in environment")
        self.init_database()

    def init_database(self):
        """Initialize the database with the sightings and TLC vehicle tables."""
        # Tables already created in Neon, this is now a no-op
        pass

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self.db_url)

    # Arbitrary, fixed key identifying the global "Bluesky batch posting" lock.
    # Any worker that wants to post the sightings queue must hold this lock, which
    # guarantees only one worker is ever in the read -> post -> mark section at a
    # time (see acquire_posting_lock).
    POSTING_LOCK_KEY = 918273645

    def acquire_posting_lock(self):
        """
        Try to acquire the global advisory lock that serializes Bluesky posting.

        Uses a Postgres *session-level* advisory lock (pg_try_advisory_lock), which
        is shared across every process/container connected to the same database.
        This prevents the race where two concurrently-spawned queue processors both
        read the same unposted sightings and each post them to Bluesky, producing
        duplicate posts.

        Returns:
            An open connection holding the lock if it was acquired, or None if
            another worker already holds it. When a connection is returned the
            caller MUST later call release_posting_lock(conn). Because the lock is
            session-scoped, Postgres releases it automatically if the connection
            drops (e.g. the worker crashes), so the queue can never get stuck.
        """
        conn = self._get_connection()
        # Autocommit so we don't hold an idle-in-transaction connection open for
        # the (potentially several-second) duration of the Bluesky post while the
        # advisory lock is held. The session-level lock persists regardless.
        conn.autocommit = True
        cursor = conn.cursor()
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (self.POSTING_LOCK_KEY,))
        acquired = cursor.fetchone()[0]
        if not acquired:
            conn.close()
            return None
        return conn

    def release_posting_lock(self, conn):
        """
        Release the advisory lock acquired via acquire_posting_lock and close the
        connection. Safe to call with None.
        """
        if conn is None:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT pg_advisory_unlock(%s)", (self.POSTING_LOCK_KEY,))
        finally:
            conn.close()

    # ==================== Contributor Operations ====================

    def get_or_create_contributor(
        self,
        phone_number: str = None,
        bluesky_handle: str = None,
        email: str = None,
        unique_name: str = None,
    ) -> int:
        """
        Get or create a contributor by phone number, email, Bluesky handle, or unique name.

        Lookup priority:
        1. phone_number (exact match - SMS contributors)
        2. email (case-insensitive - web contributors with email)
        3. bluesky_handle (exact match - Bluesky contributors)
        4. unique_name (exact match - web contributors without email)

        Args:
            phone_number: Phone number (e.g., +14123342330)
            bluesky_handle: Bluesky handle (e.g., @user.bsky.social)
            email: Email address for web contributors (optional)
            unique_name: Lowercase underscore-delimited name for web contributors without email

        Returns:
            Contributor ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Try to find existing contributor in priority order
            if phone_number:
                cursor.execute(
                    "SELECT id FROM contributors WHERE phone_number = %s", (phone_number,)
                )
            elif email:
                # Case-insensitive email lookup
                cursor.execute(
                    "SELECT id FROM contributors WHERE LOWER(email) = LOWER(%s)",
                    (email.strip(),),
                )
            elif bluesky_handle:
                cursor.execute(
                    "SELECT id FROM contributors WHERE bluesky_handle = %s", (bluesky_handle,)
                )
            elif unique_name:
                cursor.execute("SELECT id FROM contributors WHERE unique_name = %s", (unique_name,))
            else:
                raise ValueError(
                    "Either phone_number, email, bluesky_handle, or unique_name must be provided"
                )

            result = cursor.fetchone()

            if result:
                return result[0]

            # Create new contributor
            cursor.execute(
                """
                INSERT INTO contributors (phone_number, bluesky_handle, email, unique_name)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """,
                (
                    phone_number,
                    bluesky_handle,
                    email.strip().lower() if email else None,
                    unique_name,
                ),
            )

            contributor_id = cursor.fetchone()[0]
            conn.commit()
            return contributor_id

        finally:
            conn.close()

    def get_contributor(
        self, phone_number: str = None, bluesky_handle: str = None, contributor_id: int = None
    ):
        """Get contributor by phone number, handle, or ID."""
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            if contributor_id:
                cursor.execute("SELECT * FROM contributors WHERE id = %s", (contributor_id,))
            elif phone_number:
                cursor.execute(
                    "SELECT * FROM contributors WHERE phone_number = %s", (phone_number,)
                )
            elif bluesky_handle:
                cursor.execute(
                    "SELECT * FROM contributors WHERE bluesky_handle = %s", (bluesky_handle,)
                )
            else:
                raise ValueError("Must provide contributor_id, phone_number, or bluesky_handle")

            return cursor.fetchone()

        finally:
            conn.close()

    def update_contributor_name(self, contributor_id: int, preferred_name: str):
        """Update a contributor's preferred name."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE contributors SET preferred_name = %s WHERE id = %s
            """,
                (preferred_name, contributor_id),
            )

            conn.commit()

        finally:
            conn.close()

    def get_contributor_display_name(self, contributor_id: int) -> str | None:
        """
        Get the display name for a contributor.
        Priority: preferred_name > bluesky_handle > None

        Returns:
            Display name or None if contributor should be anonymous
        """
        contributor = self.get_contributor(contributor_id=contributor_id)

        if not contributor:
            return None

        if contributor["preferred_name"]:
            return contributor["preferred_name"]

        if contributor["bluesky_handle"]:
            return contributor["bluesky_handle"]

        # Phone number only - return None (will be shown as anonymous)
        return None

    # ==================== Sighting Operations ====================

    def add_sighting(
        self,
        license_plate: str,
        timestamp: datetime | str,
        latitude: float | None,
        longitude: float | None,
        contributor_id: int,
        image_filename: str,
        borough: str | None = None,
        image_timestamp: datetime | None = None,
        vin: str | None = None,
    ):
        """
        Add a new sighting to the database.

        Args:
            license_plate: License plate number (required)
            timestamp: Timestamp of sighting (datetime preferred, ISO string accepted for backwards compat)
            latitude: GPS latitude (or None)
            longitude: GPS longitude (or None)
            contributor_id: ID of contributor (required)
            image_filename: Unified filename ({plate}_{yyyymmdd_hhmmss_ssss}.jpg)
            borough: NYC borough name (Manhattan, Brooklyn, Queens, Bronx, Staten Island) or None
            image_timestamp: Timestamp when image was taken (from EXIF)
            vin: Vehicle Identification Number from TLC database (optional)

        Returns:
            dict with keys:
                - 'id': The ID of the inserted sighting
            Returns None on unexpected database error.

        Raises:
            psycopg2.Error: For database errors.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        created_at = datetime.now().isoformat()

        # Auto-populate borough from coordinates if available
        if borough is None and latitude is not None and longitude is not None:
            from geolocate.boroughs import get_borough_from_coords

            borough = get_borough_from_coords(latitude, longitude)

        try:
            cursor.execute(
                """
                INSERT INTO sightings (license_plate, timestamp, latitude, longitude, created_at, contributor_id, borough, image_timestamp, image_filename, vin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    license_plate,
                    timestamp,
                    latitude,
                    longitude,
                    created_at,
                    contributor_id,
                    borough,
                    image_timestamp,
                    image_filename,
                    vin,
                ),
            )

            sighting_id = cursor.fetchone()[0]
            conn.commit()

            return {"id": sighting_id}

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            print("Warning: UniqueViolation in add_sighting")
            return None
        finally:
            conn.close()

    def get_sighting_by_id(self, sighting_id: int):
        """Get a sighting by ID.

        Returns:
            Dict with sighting data, or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute("SELECT * FROM sightings WHERE id = %s", (sighting_id,))
        sighting = cursor.fetchone()
        conn.close()

        return sighting

    def get_sighting_count(self, license_plate: str) -> int:
        """Get the number of times a license plate has been spotted."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM sightings WHERE license_plate = %s
        """,
            (license_plate,),
        )

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_sighting_count_by_vin(self, vin: str) -> int:
        """Get the number of times a VIN has been spotted (across all license plates)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM sightings WHERE vin = %s
        """,
            (vin,),
        )

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_sighting_export_data(self, sighting_id: int) -> dict | None:
        """Get computed fields for a sighting from the sightings_export view.

        Returns ocean_points, global_unique_sighting_index, and
        contributor_vehicle_sighting_index, or None if not found.
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute(
            "SELECT ocean_points, global_unique_sighting_index, contributor_vehicle_sighting_index "
            "FROM sightings_export WHERE sighting_id = %s",
            (sighting_id,),
        )
        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def get_posted_sighting_count(self, license_plate: str) -> int:
        """Get the number of times a license plate has been posted (excludes current unposted sighting)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM sightings WHERE license_plate = %s AND post_uri IS NOT NULL
        """,
            (license_plate,),
        )

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_total_sighting_count(self) -> int:
        """Get the total number of all sightings."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM sightings")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_contributor_sighting_count(self, contributor_id: int) -> int:
        """Get the number of sightings submitted by a specific contributor."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*) FROM sightings WHERE contributor_id = %s
        """,
            (contributor_id,),
        )

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_all_contributor_sighting_counts(self) -> dict[int, int]:
        """Get sighting counts for all contributors.

        Returns:
            Dictionary mapping contributor_id to their total sighting count
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT contributor_id, COUNT(*) as count
            FROM sightings
            WHERE contributor_id IS NOT NULL
            GROUP BY contributor_id
        """
        )

        counts = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        return counts

    def get_all_sightings(self, license_plate: str = None):
        """Get all sightings, optionally filtered by license plate."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if license_plate:
            cursor.execute(
                """
                SELECT * FROM sightings WHERE license_plate = %s ORDER BY created_at DESC
            """,
                (license_plate,),
            )
        else:
            cursor.execute("SELECT * FROM sightings ORDER BY created_at DESC")

        sightings = cursor.fetchall()
        conn.close()

        return sightings

    def get_unposted_sightings(self):
        """
        Get all sightings that haven't been posted yet.

        Returns tuples with contributor info:
        (id, license_plate, created_at, latitude, longitude, image_filename, borough, created_at,
         post_uri, contributor_id, preferred_name, bluesky_handle, phone_number,
         global_sighting_index, global_unique_sighting_index,
         contributor_sighting_index, contributor_unique_sighting_index)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id, s.license_plate, s.created_at, s.latitude, s.longitude, s.image_filename,
                   s.borough, s.created_at, s.post_uri, s.contributor_id,
                   c.preferred_name, c.bluesky_handle, c.phone_number,
                   se.global_sighting_index, se.global_unique_sighting_index,
                   se.contributor_sighting_index, se.contributor_unique_sighting_index
            FROM sightings s
            LEFT JOIN contributors c ON s.contributor_id = c.id
            LEFT JOIN sightings_export se ON se.sighting_id = s.id
            WHERE s.post_uri IS NULL
              AND (s.posting_claimed_at IS NULL OR s.posting_claimed_at < NOW() - INTERVAL '2 minutes')
            ORDER BY s.created_at ASC
        """)

        sightings = cursor.fetchall()
        conn.close()

        return sightings

    def claim_sightings_for_posting(self, sighting_ids: list[int]) -> list[int]:
        """
        Atomically claim a set of sightings before posting them to Bluesky.

        A single UPDATE ... RETURNING is atomic even under connection pooling
        (unlike the session-level posting advisory lock), so this is what
        actually prevents two concurrent workers from posting the same batch:
        only the worker that wins the claim on a given sighting should post it.

        Args:
            sighting_ids: Candidate sighting IDs (e.g. the next batch to post)

        Returns:
            The subset of sighting_ids actually claimed by this call. If this
            is shorter than sighting_ids, another worker already claimed (or
            posted) some of them and the caller should not post this batch.
        """
        if not sighting_ids:
            return []

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE sightings SET posting_claimed_at = NOW()
            WHERE id = ANY(%s)
              AND post_uri IS NULL
              AND (posting_claimed_at IS NULL OR posting_claimed_at < NOW() - INTERVAL '2 minutes')
            RETURNING id
        """,
            (sighting_ids,),
        )
        claimed = [row[0] for row in cursor.fetchall()]

        conn.commit()
        conn.close()

        return claimed

    def release_sighting_claims(self, sighting_ids: list[int]):
        """
        Release claims on sightings that were claimed but never posted (e.g. the
        Bluesky post failed). Only clears still-unposted rows so a completed
        post's claim marker can't be reopened.
        """
        if not sighting_ids:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE sightings SET posting_claimed_at = NULL
            WHERE id = ANY(%s) AND post_uri IS NULL
        """,
            (sighting_ids,),
        )

        conn.commit()
        conn.close()

    def mark_as_posted(self, sighting_id: int, post_uri: str):
        """
        Mark a sighting as posted by setting the post URI.

        Args:
            sighting_id: The sighting ID
            post_uri: The Bluesky post URI
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE sightings SET post_uri = %s
            WHERE id = %s
        """,
            (post_uri, sighting_id),
        )

        conn.commit()
        conn.close()

    def mark_batch_as_posted(self, sighting_ids: list[int], post_uri: str):
        """
        Mark multiple sightings as posted by setting the same post URI.

        Args:
            sighting_ids: List of sighting IDs
            post_uri: The Bluesky post URI
        """
        if not sighting_ids:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        # Only claim rows that are still unposted. Combined with the posting
        # advisory lock this is belt-and-suspenders against ever overwriting a
        # post_uri that another worker already set.
        cursor.execute(
            """
            UPDATE sightings SET post_uri = %s
            WHERE id = ANY(%s) AND post_uri IS NULL
        """,
            (post_uri, sighting_ids),
        )

        conn.commit()
        conn.close()

    # ==================== Photo Tag Operations ====================

    def add_sighting_tag(
        self,
        sighting_id: int,
        tag_name: str,
        submitter_fingerprint: str,
        ip_hash: str = None,
        user_agent: str = None,
    ) -> bool:
        """
        Record an anonymous tag nomination on a sighting's photo.

        Duplicates from the same visitor are dropped by the unique index on
        (sighting_id, tag_name, submitter_fingerprint), so calling this twice
        with the same arguments is harmless.

        Args:
            sighting_id: The sighting whose photo is being tagged
            tag_name: Tag identifier (validated against tags.TAG_NAMES by the caller)
            submitter_fingerprint: Browser fingerprint (or hashed-IP fallback)
            ip_hash: Salted hash of the request IP, for later abuse analysis
            user_agent: Truncated User-Agent string

        Returns:
            True if a new nomination was stored, False if it was a duplicate or
            the sighting doesn't exist.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO sighting_tags
                    (sighting_id, tag_name, submitter_fingerprint, ip_hash, user_agent)
                SELECT %s, %s, %s, %s, %s
                WHERE EXISTS (SELECT 1 FROM sightings WHERE id = %s)
                ON CONFLICT (sighting_id, tag_name, submitter_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    sighting_id,
                    tag_name,
                    submitter_fingerprint,
                    ip_hash,
                    user_agent,
                    sighting_id,
                ),
            )
            inserted = cursor.fetchone() is not None
            conn.commit()
            return inserted
        finally:
            conn.close()

    def count_recent_tags_by_fingerprint(self, submitter_fingerprint: str, minutes: int) -> int:
        """
        Count nominations a fingerprint has recorded within the last N minutes.

        Used to rate-limit scripted tag spam before it reaches the table.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM sighting_tags
                WHERE submitter_fingerprint = %s
                  AND created_at > now() - (%s * INTERVAL '1 minute')
                """,
                (submitter_fingerprint, minutes),
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def get_sighting_tag_counts(self) -> list[dict]:
        """
        Get de-duplicated tag counts for every tagged sighting.

        Returns:
            List of dicts with sighting_id, tag_name, nomination_count,
            first_tagged_at and last_tagged_at, ordered by sighting then tag.
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("""
                SELECT sighting_id, tag_name, nomination_count, first_tagged_at, last_tagged_at
                FROM sighting_tags_export
                ORDER BY sighting_id, tag_name
            """)
            return list(cursor.fetchall())
        finally:
            conn.close()

    def get_latest_tag_timestamp(self) -> datetime | None:
        """Get the timestamp of the most recent tag nomination, or None if untagged."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT MAX(created_at) FROM sighting_tags")
            return cursor.fetchone()[0]
        finally:
            conn.close()

    # ==================== Statistics ====================

    def get_unique_sighted_count(self) -> int:
        """Get the count of unique license plates that have been sighted."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(DISTINCT license_plate) FROM sightings")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_unique_posted_count(self) -> int:
        """Get the count of unique license plates that have been posted."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(DISTINCT license_plate) FROM sightings WHERE post_uri IS NOT NULL"
        )
        count = cursor.fetchone()[0]
        conn.close()

        return count

    # ==================== TLC Operations (delegated) ====================
    # These methods delegate to validate.tlc for backwards compatibility

    def get_tlc_vehicle_count(self) -> int:
        """Get count of distinct Fisker VINs in database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(DISTINCT vin) FROM tlc_vehicles")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_tlc_vehicle_by_plate(self, license_plate: str):
        """Get TLC vehicle information by license plate from tlc_vehicles.

        Returns the most recent record for this plate.

        Returns:
            Dictionary with keys: 'license_plate', 'vin', 'first_reported_on',
            'most_recently_reported_on', or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute(
            """
            SELECT license_plate, vin, first_reported_on, most_recently_reported_on
            FROM tlc_vehicles
            WHERE license_plate = %s
            ORDER BY most_recently_reported_on DESC
            LIMIT 1
        """,
            (license_plate,),
        )

        vehicle = cursor.fetchone()
        conn.close()

        return vehicle

    def import_tlc_data(self, csv_path: str, snapshot_date: str, filter_fisker: bool = True) -> int:
        """
        Import TLC vehicle data from CSV file.
        Delegates to validate.tlc.TLCDatabase for implementation.

        Args:
            csv_path: Path to the TLC CSV file
            snapshot_date: Date of the snapshot in YYYY-MM-DD format
            filter_fisker: If True, only import Fisker vehicles (VIN starts with VCF1)
        """
        from validate.tlc import TLCDatabase

        tlc_db = TLCDatabase(self.db_url)
        return tlc_db.import_to_minimal_only(csv_path, snapshot_date, filter_fisker)

    def filter_fisker_vehicles(self) -> int:
        """
        Remove all non-Fisker vehicles from the TLC database.
        Delegates to validate.tlc.TLCDatabase for implementation.
        """
        from validate.tlc import TLCDatabase

        tlc_db = TLCDatabase(self.db_url)
        return tlc_db.filter_fisker_vehicles()

    # ==================== Badge Operations ====================

    def get_contributor_badges(self, contributor_id: int) -> list[dict]:
        """
        Get all badges earned by a contributor.

        Args:
            contributor_id: The contributor's ID

        Returns:
            List of dicts with badge_name, earned_on, and sighting_id
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT badge_name, earned_on, sighting_id
                FROM contributors_badges
                WHERE contributor_id = %s
                ORDER BY earned_on DESC
                """,
                (contributor_id,),
            )
            return list(cursor.fetchall())
        finally:
            conn.close()

    def get_contributor_badge_names(self, contributor_id: int) -> list[str]:
        """
        Get just the badge names for a contributor.

        Args:
            contributor_id: The contributor's ID

        Returns:
            List of badge names
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT badge_name
                FROM contributors_badges
                WHERE contributor_id = %s
                """,
                (contributor_id,),
            )
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    def save_badge(
        self, contributor_id: int, badge_name: str, sighting_id: int | None = None
    ) -> bool:
        """
        Save a newly earned badge.

        Args:
            contributor_id: The contributor's ID
            badge_name: The badge name to save
            sighting_id: The ID of the sighting that earned the badge (optional)

        Returns:
            True if the badge was newly saved, False if already existed
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO contributors_badges (contributor_id, badge_name, sighting_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (contributor_id, badge_name) DO NOTHING
                RETURNING badge_name
                """,
                (contributor_id, badge_name, sighting_id),
            )
            result = cursor.fetchone()
            conn.commit()
            return result is not None
        finally:
            conn.close()

    def save_badges(self, contributor_id: int, badge_data: list[tuple[str, int | None]]) -> int:
        """
        Save multiple badges for a contributor.

        Args:
            contributor_id: The contributor's ID
            badge_data: List of (badge_name, sighting_id) tuples

        Returns:
            Number of badges that were newly saved
        """
        if not badge_data:
            return 0

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            saved_count = 0
            for badge_name, sighting_id in badge_data:
                cursor.execute(
                    """
                    INSERT INTO contributors_badges (contributor_id, badge_name, sighting_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (contributor_id, badge_name) DO NOTHING
                    RETURNING badge_name
                    """,
                    (contributor_id, badge_name, sighting_id),
                )
                if cursor.fetchone():
                    saved_count += 1

            conn.commit()
            return saved_count
        finally:
            conn.close()

    def get_badges_for_sightings(self, sighting_ids: list[int]) -> dict[int, list[str]]:
        """
        Get badges earned from specific sightings.

        Args:
            sighting_ids: List of sighting IDs to look up

        Returns:
            Dict mapping sighting_id to list of badge names earned from that sighting
        """
        if not sighting_ids:
            return {}

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT sighting_id, badge_name
                FROM contributors_badges
                WHERE sighting_id = ANY(%s)
                """,
                (sighting_ids,),
            )
            result: dict[int, list[str]] = {}
            for sighting_id, badge_name in cursor.fetchall():
                result.setdefault(sighting_id, []).append(badge_name)
            return result
        finally:
            conn.close()

    def get_all_contributors(self) -> list[dict]:
        """
        Get all contributors.

        Returns:
            List of contributor dicts
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute("SELECT * FROM contributors ORDER BY id")
            return list(cursor.fetchall())
        finally:
            conn.close()
