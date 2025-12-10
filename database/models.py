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

    # ==================== Sighting Operations ====================

    def add_sighting(
        self,
        license_plate: str | None,
        timestamp: str,
        latitude: float | None,
        longitude: float | None,
        image_path: str,
        contributed_by: str | None = None
    ):
        """Add a new sighting to the database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        created_at = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO sightings (license_plate, timestamp, latitude, longitude, image_path, created_at, contributed_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (license_plate, timestamp, latitude, longitude, image_path, created_at, contributed_by))

        conn.commit()
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
            SELECT COUNT(*) FROM sightings WHERE license_plate = %s AND posted = 1
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
        """Get all sightings that haven't been posted yet (excludes unreadable plates)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM sightings
            WHERE (posted = 0 OR posted IS NULL)
            AND license_plate IS NOT NULL
            ORDER BY timestamp ASC
        """)

        sightings = cursor.fetchall()
        conn.close()

        return sightings

    def mark_as_posted(self, sighting_id: int, post_uri: str):
        """
        Mark a sighting as posted and record the post URI.

        Args:
            sighting_id: The sighting ID
            post_uri: The Bluesky post URI
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE sightings SET posted = 1, post_uri = %s
            WHERE id = %s
        """, (post_uri, sighting_id))

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

        cursor.execute("SELECT COUNT(DISTINCT license_plate) FROM sightings WHERE posted = 1 AND license_plate IS NOT NULL")
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
