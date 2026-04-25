"""TLC (Taxi & Limousine Commission) database operations."""

import csv
import os
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
import requests
from psycopg2 import sql


class TLCDatabase:
    """Database operations for NYC TLC vehicle registry."""

    # NYC Open Data API endpoint for TLC vehicle list
    TLC_CSV_URL = "https://data.cityofnewyork.us/api/views/8wbx-tsch/rows.csv?accessType=DOWNLOAD"

    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        if not self.db_url:
            raise ValueError("DATABASE_URL not provided and not found in environment")

    def _get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self.db_url)

    def download_tlc_csv(self, output_dir: str = "/data/tlc") -> str:
        """
        Download the latest TLC vehicle CSV from NYC Open Data.
        Stores versioned copies and maintains a _latest symlink.

        Args:
            output_dir: Directory to store CSV files (default: /data/tlc for Modal volume)

        Returns:
            Path to the downloaded CSV file

        Raises:
            requests.RequestException: If download fails
        """
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        versioned_file = output_path / f"tlc_vehicles_{timestamp}.csv"
        latest_file = output_path / "tlc_vehicles_latest.csv"

        # Download CSV
        print(f"Downloading TLC vehicle data from {self.TLC_CSV_URL}...")
        response = requests.get(self.TLC_CSV_URL, stream=True)
        response.raise_for_status()

        # Save versioned file
        total_bytes = 0
        with open(versioned_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                total_bytes += len(chunk)

        print(f"✓ Downloaded {total_bytes:,} bytes to {versioned_file}")

        # Update _latest symlink (or copy on systems without symlink support)
        try:
            if latest_file.is_symlink() or latest_file.exists():
                latest_file.unlink()
            latest_file.symlink_to(versioned_file.name)
            print(f"✓ Updated symlink: {latest_file} -> {versioned_file.name}")
        except (OSError, NotImplementedError):
            # Fallback to copying if symlinks not supported
            import shutil

            shutil.copy2(versioned_file, latest_file)
            print(f"✓ Copied to {latest_file}")

        return str(versioned_file)

    def filter_fisker_vehicles(self) -> int:
        """
        Remove all non-Fisker vehicles from the TLC database.
        Fisker VINs start with 'VCF1'.

        Returns:
            Number of Fisker vehicles remaining
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM tlc_vehicles WHERE vin NOT LIKE 'VCF1%'")
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM tlc_vehicles")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_vehicle_by_plate(self, license_plate: str) -> dict | None:
        """Get TLC vehicle information by license plate from tlc_vehicles.

        Returns the most recent record for this plate based on most_recently_reported_on.

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

    def record_daily_count(
        self, date: str, global_ocean_count: int, active_ocean_count: int
    ) -> None:
        """
        Record the count of Fisker Ocean vehicles for a specific date.

        Args:
            date: Date in YYYY-MM-DD format
            global_ocean_count: Cumulative count of unique Fisker Ocean VINs ever seen
            active_ocean_count: Count of Fisker Ocean vehicles actively in TLC on this date

        Note:
            Uses ON CONFLICT to update if record already exists for that date
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO tlc_vehicle_history (date, global_ocean_count, active_ocean_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (date) DO UPDATE SET
                global_ocean_count = EXCLUDED.global_ocean_count,
                active_ocean_count = EXCLUDED.active_ocean_count,
                created_at = NOW()
        """,
            (date, global_ocean_count, active_ocean_count),
        )

        conn.commit()
        conn.close()
        print(
            f"✓ Recorded {date}: {active_ocean_count:,} active, {global_ocean_count:,} cumulative"
        )

    def get_table_stats(self, table_name: str = "tlc_vehicles") -> dict:
        """
        Get statistics for a specific table.

        Args:
            table_name: Name of the table to get stats for

        Returns:
            dict with 'total_records' and 'unique_vins'
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name)))
        total_records = cursor.fetchone()[0]

        cursor.execute(
            sql.SQL("SELECT COUNT(DISTINCT vin) FROM {}").format(sql.Identifier(table_name))
        )
        unique_vins = cursor.fetchone()[0]

        conn.close()

        return {"total_records": total_records, "unique_vins": unique_vins}

    def upsert_to_minimal(self, vin: str, license_plate: str, snapshot_date: str) -> None:
        """
        Insert or update a record in tlc_vehicles.

        Args:
            vin: Vehicle Identification Number
            license_plate: License plate number
            snapshot_date: Date this combination was seen (YYYY-MM-DD format)

        Note:
            On conflict, updates most_recently_reported_on if snapshot_date is more recent
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO tlc_vehicles (vin, license_plate, first_reported_on, most_recently_reported_on)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (vin, license_plate) DO UPDATE SET
                most_recently_reported_on = GREATEST(
                    tlc_vehicles.most_recently_reported_on,
                    EXCLUDED.most_recently_reported_on
                )
        """,
            (vin, license_plate, snapshot_date, snapshot_date),
        )

        conn.commit()
        conn.close()

    def import_to_minimal_only(
        self, csv_path: str, snapshot_date: str, filter_fisker: bool = True
    ) -> int:
        """
        Import TLC vehicle data from CSV file directly into tlc_vehicles only.
        Does NOT touch the tlc_vehicles table.

        Args:
            csv_path: Path to the TLC CSV file
            snapshot_date: Date of the snapshot in YYYY-MM-DD format
            filter_fisker: If True, only import Fisker vehicles (VIN starts with VCF1)

        Returns:
            Number of records imported
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        count = 0
        skipped = 0

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)

            for row in reader:
                # Filter Fisker vehicles during import if requested
                vin = row.get("Vehicle VIN Number", "")
                if filter_fisker and not vin.startswith("VCF1"):
                    skipped += 1
                    continue

                license_plate = row.get("DMV License Plate Number", "")

                try:
                    cursor.execute(
                        """
                        INSERT INTO tlc_vehicles (vin, license_plate, first_reported_on, most_recently_reported_on)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (vin, license_plate) DO UPDATE SET
                            most_recently_reported_on = GREATEST(
                                tlc_vehicles.most_recently_reported_on,
                                EXCLUDED.most_recently_reported_on
                            )
                    """,
                        (vin, license_plate, snapshot_date, snapshot_date),
                    )
                    count += 1
                except psycopg2.IntegrityError:
                    pass

        conn.commit()
        conn.close()

        if filter_fisker:
            print(f"  Skipped {skipped:,} non-Fisker vehicles")

        return count

    def update_from_nyc_open_data(self, output_dir: str = "/data/tlc") -> dict:
        """
        Download latest TLC data from NYC Open Data and update the database.
        Only imports Fisker vehicles (VIN starts with VCF1) for efficiency.
        Records daily count to tlc_vehicle_history table.

        Args:
            output_dir: Directory to store CSV files

        Returns:
            dict with statistics: {
                'csv_path': str,
                'active_count': int,      # Oceans in today's TLC export
                'global_count': int,      # Cumulative unique Oceans ever seen
                'timestamp': str,
                'date': str
            }
        """
        # Download latest CSV
        csv_path = self.download_tlc_csv(output_dir)

        # Extract snapshot date from filename: tlc_vehicles_YYYYMMDD_HHMMSS.csv
        csv_file = Path(csv_path)
        filename = csv_file.stem  # removes .csv
        timestamp_str = filename.replace("tlc_vehicles_", "")
        date_str = timestamp_str.split("_")[0]  # Get YYYYMMDD part
        snapshot_date = datetime.strptime(date_str, "%Y%m%d").date().isoformat()

        # Count active Fisker vehicles in today's CSV (before importing)
        print("\nCounting active Fisker Ocean vehicles in TLC export...")
        active_count = 0
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                vin = row.get("Vehicle VIN Number", "")
                if vin.startswith("VCF1"):
                    active_count += 1
        print(f"✓ Found {active_count:,} active Fisker Ocean vehicles in TLC export")

        # Import only Fisker vehicles (filter during import for efficiency)
        print("\nImporting Fisker Ocean vehicles to database...")
        imported_count = self.import_to_minimal_only(csv_path, snapshot_date, filter_fisker=True)
        print(f"✓ Imported/updated {imported_count:,} records")

        # Get cumulative count of unique VINs from database
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT vin) FROM tlc_vehicles")
        global_count = cursor.fetchone()[0]
        conn.close()
        print(f"✓ Cumulative unique Fisker Ocean vehicles in database: {global_count:,}")

        # Record both counts to history table
        self.record_daily_count(snapshot_date, global_count, active_count)

        return {
            "csv_path": csv_path,
            "active_count": active_count,
            "global_count": global_count,
            "timestamp": datetime.now().isoformat(),
            "date": snapshot_date,
        }


def validate_plate(plate: str, db_url: str = None) -> tuple[bool, dict | None]:
    """
    Validate a license plate against the TLC database.

    Args:
        plate: License plate to validate
        db_url: Database URL (uses DATABASE_URL env var if not provided)

    Returns:
        Tuple of (is_valid, vehicle_dict or None)
        vehicle_dict contains keys: 'license_plate', 'vin', 'first_reported_on',
        'most_recently_reported_on'
    """
    tlc_db = TLCDatabase(db_url)
    vehicle = tlc_db.get_vehicle_by_plate(plate)

    if vehicle:
        return True, dict(vehicle)
    return False, None
