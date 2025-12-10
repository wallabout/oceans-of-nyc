"""Core database operations for sightings."""

import psycopg2
import psycopg2.extras
import os
from datetime import datetime


class SightingsDatabase:
    """Database operations for Fisker Ocean sightings."""

    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv('DATABASE_URL')
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

    def get_or_create_contributor(self, phone_number: str = None, bluesky_handle: str = None) -> int:
        """
        Get or create a contributor by phone number or Bluesky handle.

        Args:
            phone_number: Phone number (e.g., +14123342330)
            bluesky_handle: Bluesky handle (e.g., @user.bsky.social)

        Returns:
            Contributor ID
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Try to find existing contributor
            if phone_number:
                cursor.execute("SELECT id FROM contributors WHERE phone_number = %s", (phone_number,))
            elif bluesky_handle:
                cursor.execute("SELECT id FROM contributors WHERE bluesky_handle = %s", (bluesky_handle,))
            else:
                raise ValueError("Either phone_number or bluesky_handle must be provided")

            result = cursor.fetchone()

            if result:
                return result[0]

            # Create new contributor
            cursor.execute("""
                INSERT INTO contributors (phone_number, bluesky_handle)
                VALUES (%s, %s)
                RETURNING id
            """, (phone_number, bluesky_handle))

            contributor_id = cursor.fetchone()[0]
            conn.commit()
            return contributor_id

        finally:
            conn.close()

    def get_contributor(self, phone_number: str = None, bluesky_handle: str = None, contributor_id: int = None):
        """Get contributor by phone number, handle, or ID."""
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        try:
            if contributor_id:
                cursor.execute("SELECT * FROM contributors WHERE id = %s", (contributor_id,))
            elif phone_number:
                cursor.execute("SELECT * FROM contributors WHERE phone_number = %s", (phone_number,))
            elif bluesky_handle:
                cursor.execute("SELECT * FROM contributors WHERE bluesky_handle = %s", (bluesky_handle,))
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
            cursor.execute("""
                UPDATE contributors SET preferred_name = %s WHERE id = %s
            """, (preferred_name, contributor_id))

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

        if contributor['preferred_name']:
            return contributor['preferred_name']

        if contributor['bluesky_handle']:
            return contributor['bluesky_handle']

        # Phone number only - return None (will be shown as anonymous)
        return None

    # ==================== Sighting Operations ====================

    def add_sighting(
        self,
        license_plate: str | None,
        timestamp: str,
        latitude: float | None,
        longitude: float | None,
        image_path: str,
        contributor_id: int
    ):
        """
        Add a new sighting to the database.

        Args:
            license_plate: License plate number (or None if unreadable)
            timestamp: ISO timestamp of sighting
            latitude: GPS latitude (or None)
            longitude: GPS longitude (or None)
            image_path: Path to image file
            contributor_id: ID of contributor (required)

        Returns:
            int: The ID of the inserted sighting, or None if the image already exists.

        Raises:
            psycopg2.Error: For database errors other than duplicate image_path.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        created_at = datetime.now().isoformat()

        try:
            cursor.execute("""
                INSERT INTO sightings (license_plate, timestamp, latitude, longitude, image_path, created_at, contributor_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (license_plate, timestamp, latitude, longitude, image_path, created_at, contributor_id))

            sighting_id = cursor.fetchone()[0]
            conn.commit()
            return sighting_id

        except psycopg2.errors.UniqueViolation as e:
            conn.rollback()
            # Image already exists - this is expected behavior
            return None
        finally:
            conn.close()

    def get_sighting_by_id(self, sighting_id: int):
        """Get a sighting by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM sightings WHERE id = %s", (sighting_id,))
        sighting = cursor.fetchone()
        conn.close()

        return sighting

    def get_sighting_count(self, license_plate: str) -> int:
        """Get the number of times a license plate has been spotted."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM sightings WHERE license_plate = %s
        """, (license_plate,))

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_posted_sighting_count(self, license_plate: str) -> int:
        """Get the number of times a license plate has been posted (excludes current unposted sighting)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) FROM sightings WHERE license_plate = %s AND post_uri IS NOT NULL
        """, (license_plate,))

        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_all_sightings(self, license_plate: str = None):
        """Get all sightings, optionally filtered by license plate."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if license_plate:
            cursor.execute("""
                SELECT * FROM sightings WHERE license_plate = %s ORDER BY timestamp DESC
            """, (license_plate,))
        else:
            cursor.execute("SELECT * FROM sightings ORDER BY timestamp DESC")

        sightings = cursor.fetchall()
        conn.close()

        return sightings

    def get_unposted_sightings(self):
        """
        Get all sightings that haven't been posted yet (excludes unreadable plates).

        Returns tuples with contributor info:
        (id, license_plate, timestamp, latitude, longitude, image_path, created_at, post_uri,
         contributor_id, preferred_name, bluesky_handle, phone_number)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id, s.license_plate, s.timestamp, s.latitude, s.longitude, s.image_path,
                   s.created_at, s.post_uri, s.contributor_id,
                   c.preferred_name, c.bluesky_handle, c.phone_number
            FROM sightings s
            LEFT JOIN contributors c ON s.contributor_id = c.id
            WHERE s.post_uri IS NULL
            AND s.license_plate IS NOT NULL
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

        cursor.execute("""
            UPDATE sightings SET post_uri = %s
            WHERE id = %s
        """, (post_uri, sighting_id))

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

        cursor.execute("""
            UPDATE sightings SET post_uri = %s
            WHERE id = ANY(%s)
        """, (post_uri, sighting_ids))

        conn.commit()
        conn.close()

    # ==================== Statistics ====================

    def get_unique_sighted_count(self) -> int:
        """Get the count of unique license plates that have been sighted (excludes unreadable plates)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(DISTINCT license_plate) FROM sightings WHERE license_plate IS NOT NULL")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_unique_posted_count(self) -> int:
        """Get the count of unique license plates that have been posted (excludes unreadable plates)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(DISTINCT license_plate) FROM sightings WHERE post_uri IS NOT NULL AND license_plate IS NOT NULL")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    # ==================== TLC Operations (delegated) ====================
    # These methods delegate to validate.tlc for backwards compatibility

    def get_tlc_vehicle_count(self) -> int:
        """Get total count of TLC vehicles in database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM tlc_vehicles")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_tlc_vehicle_by_plate(self, license_plate: str):
        """Get TLC vehicle information by license plate."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM tlc_vehicles WHERE dmv_license_plate_number = %s
        """, (license_plate,))

        vehicle = cursor.fetchone()
        conn.close()

        return vehicle

    def search_plates_wildcard(self, pattern: str) -> list:
        """
        Search for license plates using wildcard pattern.
        Use * for any number of characters.

        Args:
            pattern: Search pattern like 'T73**580C' where * matches any character

        Returns:
            List of matching vehicle records
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Convert * to SQL wildcard _
        sql_pattern = pattern.replace('*', '_')

        cursor.execute("""
            SELECT dmv_license_plate_number, vehicle_vin_number, vehicle_year,
                   name, base_name, base_type
            FROM tlc_vehicles
            WHERE dmv_license_plate_number LIKE %s
            ORDER BY dmv_license_plate_number
        """, (sql_pattern,))

        results = cursor.fetchall()
        conn.close()

        return results

    def import_tlc_data(self, csv_path: str) -> int:
        """
        Import TLC vehicle data from CSV file.
        Delegates to validate.tlc.TLCDatabase for implementation.
        """
        from validate.tlc import TLCDatabase
        tlc_db = TLCDatabase(self.db_url)
        return tlc_db.import_tlc_data(csv_path)

    def filter_fisker_vehicles(self) -> int:
        """
        Remove all non-Fisker vehicles from the TLC database.
        Delegates to validate.tlc.TLCDatabase for implementation.
        """
        from validate.tlc import TLCDatabase
        tlc_db = TLCDatabase(self.db_url)
        return tlc_db.filter_fisker_vehicles()
