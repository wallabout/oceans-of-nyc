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

    # ==================== Contributor Operations ====================

    def get_or_create_contributor(
        self, phone_number: str = None, bluesky_handle: str = None, email: str = None
    ) -> int:
        """
        Get or create a contributor by phone number, email, or Bluesky handle.

        Lookup priority:
        1. phone_number (exact match - SMS contributors)
        2. email (case-insensitive - web contributors with email)
        3. bluesky_handle (exact match - web contributors without email, Bluesky)

        Args:
            phone_number: Phone number (e.g., +14123342330)
            bluesky_handle: Bluesky handle (e.g., @user.bsky.social)
            email: Email address for web contributors (optional)

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
            else:
                raise ValueError("Either phone_number, email, or bluesky_handle must be provided")

            result = cursor.fetchone()

            if result:
                return result[0]

            # Create new contributor
            cursor.execute(
                """
                INSERT INTO contributors (phone_number, bluesky_handle, email)
                VALUES (%s, %s, %s)
                RETURNING id
            """,
                (phone_number, bluesky_handle, email.strip().lower() if email else None),
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
        image_hash_sha256: str | None = None,
        image_hash_perceptual: str | None = None,
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
            image_hash_sha256: SHA-256 hash of image (optional, calculated if not provided)
            image_hash_perceptual: Perceptual hash of image (optional, calculated if not provided)
            borough: NYC borough name (Manhattan, Brooklyn, Queens, Bronx, Staten Island) or None
            image_timestamp: Timestamp when image was taken (from EXIF)
            vin: Vehicle Identification Number from TLC database (optional)

        Returns:
            dict with keys:
                - 'id': The ID of the inserted sighting
                - 'duplicate_type': None if new, 'exact' or 'similar' if duplicate detected
                - 'duplicate_info': Dict with duplicate sighting info if applicable
            Returns None if exact duplicate is detected (same SHA-256 hash)

        Raises:
            psycopg2.Error: For database errors.
        """
        from utils.image_hashing import (
            ImageHashError,
            calculate_both_hashes,
            check_exact_duplicate,
            find_similar_images,
        )

        conn = self._get_connection()
        cursor = conn.cursor()

        # Calculate hashes if not provided (requires accessing the image file)
        if image_hash_sha256 is None or image_hash_perceptual is None:
            from utils.image_processor import ImageProcessor

            # Derive image path from filename for hash calculation
            processor = ImageProcessor()
            image_path = processor.get_original_path(image_filename)
            try:
                sha256, phash = calculate_both_hashes(image_path)
                image_hash_sha256 = image_hash_sha256 or sha256
                image_hash_perceptual = image_hash_perceptual or phash
            except ImageHashError as e:
                # Log error but continue without hashes
                print(f"Warning: Failed to calculate hashes for {image_path}: {e}")
                image_hash_sha256 = None
                image_hash_perceptual = None

        # Check for exact duplicate by SHA-256 hash
        exact_duplicate = None
        if image_hash_sha256:
            exact_duplicate = check_exact_duplicate(conn, image_hash_sha256)
            if exact_duplicate:
                conn.close()
                return None  # Reject exact duplicates

        # Check for near-duplicates by perceptual hash
        similar_images = []
        if image_hash_perceptual:
            similar_images = find_similar_images(conn, image_hash_perceptual, threshold=5)

        created_at = datetime.now().isoformat()

        # Auto-populate borough from coordinates if available
        if borough is None and latitude is not None and longitude is not None:
            from geolocate.boroughs import get_borough_from_coords

            borough = get_borough_from_coords(latitude, longitude)

        try:
            cursor.execute(
                """
                INSERT INTO sightings (license_plate, timestamp, latitude, longitude, created_at, contributor_id, image_hash_sha256, image_hash_perceptual, borough, image_timestamp, image_filename, vin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    license_plate,
                    timestamp,
                    latitude,
                    longitude,
                    created_at,
                    contributor_id,
                    image_hash_sha256,
                    image_hash_perceptual,
                    borough,
                    image_timestamp,
                    image_filename,
                    vin,
                ),
            )

            sighting_id = cursor.fetchone()[0]
            conn.commit()

            # Return success with duplicate warnings if applicable
            result = {"id": sighting_id, "duplicate_type": None, "duplicate_info": None}

            if similar_images:
                result["duplicate_type"] = "similar"
                result["duplicate_info"] = similar_images[0]  # Most similar

            return result

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            # Unique constraint violation - unexpected, log and return None
            print("Warning: UniqueViolation in add_sighting - possible duplicate")
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
                SELECT * FROM sightings WHERE license_plate = %s ORDER BY timestamp DESC
            """,
                (license_plate,),
            )
        else:
            cursor.execute("SELECT * FROM sightings ORDER BY timestamp DESC")

        sightings = cursor.fetchall()
        conn.close()

        return sightings

    def get_unposted_sightings(self):
        """
        Get all sightings that haven't been posted yet.

        Returns tuples with contributor info:
        (id, license_plate, timestamp, latitude, longitude, image_filename, borough, created_at,
         post_uri, contributor_id, preferred_name, bluesky_handle, phone_number)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id, s.license_plate, s.timestamp, s.latitude, s.longitude, s.image_filename,
                   s.borough, s.created_at, s.post_uri, s.contributor_id,
                   c.preferred_name, c.bluesky_handle, c.phone_number
            FROM sightings s
            LEFT JOIN contributors c ON s.contributor_id = c.id
            WHERE s.post_uri IS NULL
            ORDER BY s.timestamp ASC
        """)

        sightings = cursor.fetchall()
        conn.close()

        return sightings

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

        cursor.execute(
            """
            UPDATE sightings SET post_uri = %s
            WHERE id = ANY(%s)
        """,
            (post_uri, sighting_ids),
        )

        conn.commit()
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

        cursor.execute("SELECT COUNT(DISTINCT vin) FROM tlc_vehicles_minimal")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_tlc_vehicle_by_plate(self, license_plate: str):
        """Get TLC vehicle information by license plate from tlc_vehicles_minimal.

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
            FROM tlc_vehicles_minimal
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
        return tlc_db.import_tlc_data(csv_path, snapshot_date, filter_fisker)

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
            List of dicts with badge_name and earned_on
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            cursor.execute(
                """
                SELECT badge_name, earned_on
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

    def save_badge(self, contributor_id: int, badge_name: str) -> bool:
        """
        Save a newly earned badge.

        Args:
            contributor_id: The contributor's ID
            badge_name: The badge name to save

        Returns:
            True if the badge was newly saved, False if already existed
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO contributors_badges (contributor_id, badge_name)
                VALUES (%s, %s)
                ON CONFLICT (contributor_id, badge_name) DO NOTHING
                RETURNING badge_name
                """,
                (contributor_id, badge_name),
            )
            result = cursor.fetchone()
            conn.commit()
            return result is not None
        finally:
            conn.close()

    def save_badges(self, contributor_id: int, badge_names: list[str]) -> int:
        """
        Save multiple badges for a contributor.

        Args:
            contributor_id: The contributor's ID
            badge_names: List of badge names to save

        Returns:
            Number of badges that were newly saved
        """
        if not badge_names:
            return 0

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Use executemany with ON CONFLICT to handle duplicates gracefully
            saved_count = 0
            for badge_name in badge_names:
                cursor.execute(
                    """
                    INSERT INTO contributors_badges (contributor_id, badge_name)
                    VALUES (%s, %s)
                    ON CONFLICT (contributor_id, badge_name) DO NOTHING
                    RETURNING badge_name
                    """,
                    (contributor_id, badge_name),
                )
                if cursor.fetchone():
                    saved_count += 1

            conn.commit()
            return saved_count
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
