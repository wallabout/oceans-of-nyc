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

    def import_tlc_data(
        self,
        csv_path: str,
        snapshot_date: str,
        filter_fisker: bool = True,
        table_name: str = "tlc_vehicles",
    ) -> int:
        """
        Import TLC vehicle data from CSV file.

        Args:
            csv_path: Path to the TLC CSV file
            snapshot_date: Date of the snapshot in YYYY-MM-DD format
            filter_fisker: If True, only import Fisker vehicles (VIN starts with VCF1)
            table_name: Name of the table to import into (default: tlc_vehicles)

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
                    # Insert/update into main tlc_vehicles table
                    cursor.execute(
                        sql.SQL("""
                        INSERT INTO {} (
                            active, vehicle_license_number, name, license_type,
                            expiration_date, permit_license_number, dmv_license_plate_number,
                            vehicle_vin_number, wheelchair_accessible, certification_date,
                            hack_up_date, vehicle_year, base_number, base_name,
                            base_type, veh, base_telephone_number, website,
                            base_address, reason, order_date, last_date_updated,
                            last_time_updated, first_load_date, most_recent_date
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (vehicle_vin_number, dmv_license_plate_number) DO UPDATE SET
                            active = EXCLUDED.active,
                            vehicle_license_number = EXCLUDED.vehicle_license_number,
                            name = EXCLUDED.name,
                            license_type = EXCLUDED.license_type,
                            expiration_date = EXCLUDED.expiration_date,
                            permit_license_number = EXCLUDED.permit_license_number,
                            wheelchair_accessible = EXCLUDED.wheelchair_accessible,
                            certification_date = EXCLUDED.certification_date,
                            hack_up_date = EXCLUDED.hack_up_date,
                            vehicle_year = EXCLUDED.vehicle_year,
                            base_number = EXCLUDED.base_number,
                            base_name = EXCLUDED.base_name,
                            base_type = EXCLUDED.base_type,
                            veh = EXCLUDED.veh,
                            base_telephone_number = EXCLUDED.base_telephone_number,
                            website = EXCLUDED.website,
                            base_address = EXCLUDED.base_address,
                            reason = EXCLUDED.reason,
                            order_date = EXCLUDED.order_date,
                            last_date_updated = EXCLUDED.last_date_updated,
                            last_time_updated = EXCLUDED.last_time_updated,
                            most_recent_date = EXCLUDED.most_recent_date
                    """).format(sql.Identifier(table_name)),
                        (
                            row.get("Active", ""),
                            row.get("Vehicle License Number", ""),
                            row.get("Name", ""),
                            row.get("License Type", ""),
                            row.get("Expiration Date", ""),
                            row.get("Permit License Number", ""),
                            license_plate,
                            vin,
                            row.get("Wheelchair Accessible", ""),
                            row.get("Certification Date", ""),
                            row.get("Hack Up Date", ""),
                            row.get("Vehicle Year", ""),
                            row.get("Base Number", ""),
                            row.get("Base Name", ""),
                            row.get("Base Type", ""),
                            row.get("VEH", ""),
                            row.get("Base Telephone Number", ""),
                            row.get("Website", ""),
                            row.get("Base Address", ""),
                            row.get("Reason", ""),
                            row.get("Order Date", ""),
                            row.get("Last Date Updated", ""),
                            row.get("Last Time Updated", ""),
                            snapshot_date,  # first_load_date
                            snapshot_date,  # most_recent_date
                        ),
                    )

                    # Also insert/update into tlc_vehicles_minimal (only when importing to default table)
                    if table_name == "tlc_vehicles":
                        cursor.execute(
                            """
                            INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (vin, license_plate) DO UPDATE SET
                                most_recently_reported_on = GREATEST(
                                    tlc_vehicles_minimal.most_recently_reported_on,
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

    def filter_fisker_vehicles(self) -> int:
        """
        Remove all non-Fisker vehicles from the TLC database.
        Fisker VINs start with 'VCF1'.

        Returns:
            Number of Fisker vehicles remaining
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM tlc_vehicles WHERE vehicle_vin_number NOT LIKE 'VCF1%'")
        conn.commit()

        cursor.execute("SELECT COUNT(*) FROM tlc_vehicles")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def get_vehicle_by_plate(self, license_plate: str) -> dict | None:
        """Get TLC vehicle information by license plate from tlc_vehicles_minimal.

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

    def get_vehicle_by_plate_full(self, license_plate: str) -> dict | None:
        """Get full TLC vehicle information by license plate from tlc_vehicles.

        For backwards compatibility - use get_vehicle_by_plate() for most cases.

        Returns:
            Dictionary with vehicle data including 'vehicle_vin_number', or None if not found
        """
        conn = self._get_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cursor.execute(
            """
            SELECT * FROM tlc_vehicles WHERE dmv_license_plate_number = %s
        """,
            (license_plate,),
        )

        vehicle = cursor.fetchone()
        conn.close()

        return vehicle

    def get_vehicle_count(self) -> int:
        """Get total count of TLC vehicles in database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM tlc_vehicles")
        count = cursor.fetchone()[0]
        conn.close()

        return count

    def search_plates_wildcard(self, pattern: str) -> list:
        """
        Search for license plates using wildcard pattern.
        Use * for any single character.

        Args:
            pattern: Search pattern like 'T73**580C' where * matches any character

        Returns:
            List of matching vehicle records
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        # Convert * to SQL wildcard _
        sql_pattern = pattern.replace("*", "_")

        cursor.execute(
            """
            SELECT dmv_license_plate_number, vehicle_vin_number, vehicle_year,
                   name, base_name, base_type
            FROM tlc_vehicles
            WHERE dmv_license_plate_number LIKE %s
            ORDER BY dmv_license_plate_number
        """,
            (sql_pattern,),
        )

        results = cursor.fetchall()
        conn.close()

        return results

    def get_all_plates(self) -> list[str]:
        """Get all license plates in the TLC database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT dmv_license_plate_number FROM tlc_vehicles ORDER BY dmv_license_plate_number"
        )
        plates = [row[0] for row in cursor.fetchall()]
        conn.close()

        return plates

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

    def rebuild_table_with_new_schema(
        self, table_name: str = "tlc_vehicles", drop_if_exists: bool = True
    ) -> None:
        """
        Create the tlc_vehicles table with the new schema.

        Args:
            table_name: Name of the table to create (default: tlc_vehicles)
            drop_if_exists: If True, drop the table if it exists (default: True)

        New schema uses:
        - Compound unique key: (vehicle_vin_number, dmv_license_plate_number)
        - first_load_date: Date record was first seen
        - most_recent_date: Most recent date record was seen in TLC data
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        if drop_if_exists:
            print(f"Dropping existing {table_name} table if exists...")
            cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table_name)))

        print(f"Creating {table_name} table with updated schema...")
        cursor.execute(
            sql.SQL("""
            CREATE TABLE {} (
                active TEXT,
                vehicle_license_number TEXT,
                name TEXT,
                license_type TEXT,
                expiration_date TEXT,
                permit_license_number TEXT,
                dmv_license_plate_number TEXT NOT NULL,
                vehicle_vin_number TEXT NOT NULL,
                wheelchair_accessible TEXT,
                certification_date TEXT,
                hack_up_date TEXT,
                vehicle_year TEXT,
                base_number TEXT,
                base_name TEXT,
                base_type TEXT,
                veh TEXT,
                base_telephone_number TEXT,
                website TEXT,
                base_address TEXT,
                reason TEXT,
                order_date TEXT,
                last_date_updated TEXT,
                last_time_updated TEXT,
                first_load_date DATE NOT NULL,
                most_recent_date DATE NOT NULL,
                PRIMARY KEY (vehicle_vin_number, dmv_license_plate_number)
            )
        """).format(sql.Identifier(table_name))
        )

        # Add indexes for common queries
        cursor.execute(
            sql.SQL("CREATE INDEX {} ON {} (vehicle_vin_number)").format(
                sql.Identifier(f"idx_{table_name}_vin"), sql.Identifier(table_name)
            )
        )
        cursor.execute(
            sql.SQL("CREATE INDEX {} ON {} (dmv_license_plate_number)").format(
                sql.Identifier(f"idx_{table_name}_plate"), sql.Identifier(table_name)
            )
        )

        conn.commit()
        conn.close()
        print(f"✓ Table {table_name} created with new schema")

    def swap_tables(
        self,
        old_table: str = "tlc_vehicles",
        new_table: str = "tlc_vehicles_new",
        backup_suffix: str = "_old",
    ) -> None:
        """
        Atomically swap tables by renaming.

        Args:
            old_table: Current production table name
            new_table: New table to swap in
            backup_suffix: Suffix to add to old table (default: _old)

        Process:
        1. Rename old_table to old_table_backup
        2. Rename new_table to old_table
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        backup_table = f"{old_table}{backup_suffix}"

        print(f"Swapping tables: {old_table} -> {backup_table}, {new_table} -> {old_table}")

        # Drop old backup if exists
        cursor.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(backup_table)))

        # Rename operations (atomic within a transaction)
        cursor.execute(
            sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                sql.Identifier(old_table), sql.Identifier(backup_table)
            )
        )
        cursor.execute(
            sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                sql.Identifier(new_table), sql.Identifier(old_table)
            )
        )

        conn.commit()
        conn.close()
        print(f"✓ Tables swapped successfully. Old table backed up as {backup_table}")

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
            sql.SQL("SELECT COUNT(DISTINCT vehicle_vin_number) FROM {}").format(
                sql.Identifier(table_name)
            )
        )
        unique_vins = cursor.fetchone()[0]

        conn.close()

        return {"total_records": total_records, "unique_vins": unique_vins}

    def rebuild_from_csvs(
        self,
        csv_dir: str = "/data/tlc",
        table_name: str = "tlc_vehicles",
        update_history: bool = True,
    ) -> dict:
        """
        Rebuild a tlc_vehicles table by replaying all historical CSV files.
        Optionally updates the tlc_vehicle_history table with daily counts.

        Args:
            csv_dir: Directory containing versioned CSV files (tlc_vehicles_YYYYMMDD_HHMMSS.csv)
            table_name: Name of the table to rebuild (default: tlc_vehicles)
            update_history: If True, update tlc_vehicle_history table (default: True)

        Returns:
            dict with statistics: {
                'files_processed': int,
                'total_records': int,
                'unique_vins': int,
                'date_range': tuple,
                'errors': list
            }
        """
        csv_path = Path(csv_dir)
        if not csv_path.exists():
            raise ValueError(f"CSV directory not found: {csv_dir}")

        # Find all versioned CSV files (not the _latest symlink)
        csv_files = sorted(
            [f for f in csv_path.glob("tlc_vehicles_*.csv") if not f.name.endswith("_latest.csv")]
        )

        if not csv_files:
            print(f"No CSV files found in {csv_dir}")
            return {
                "files_processed": 0,
                "total_records": 0,
                "unique_vins": 0,
                "date_range": None,
                "errors": [],
            }

        # Rebuild table schema
        self.rebuild_table_with_new_schema(table_name=table_name)

        processed = 0
        errors = []
        dates = []

        # Track cumulative unique VINs for history table
        cumulative_vins = set()

        print(f"\nFound {len(csv_files)} CSV files to process")
        print("Replaying all historical data...")

        for csv_file in csv_files:
            try:
                # Extract date from filename: tlc_vehicles_YYYYMMDD_HHMMSS.csv
                filename = csv_file.stem  # removes .csv
                timestamp_str = filename.replace("tlc_vehicles_", "")
                date_str = timestamp_str.split("_")[0]  # Get YYYYMMDD part

                # Convert to YYYY-MM-DD format
                file_date = datetime.strptime(date_str, "%Y%m%d").date().isoformat()

                print(f"\nProcessing {csv_file.name} (date: {file_date})...")

                # Import the CSV
                imported = self.import_tlc_data(
                    str(csv_file), file_date, filter_fisker=True, table_name=table_name
                )
                print(f"  ✓ Imported {imported:,} Fisker records")

                # Track active VINs in this file for history
                active_vins = set()
                with open(csv_file, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        vin = row.get("Vehicle VIN Number", "")
                        if vin.startswith("VCF1"):
                            active_vins.add(vin)
                            cumulative_vins.add(vin)

                # Record daily counts to history table (only if updating production table)
                if update_history:
                    global_count = len(cumulative_vins)
                    active_count = len(active_vins)
                    self.record_daily_count(file_date, global_count, active_count)

                dates.append(file_date)
                processed += 1

            except Exception as e:
                error_msg = f"Error processing {csv_file.name}: {str(e)}"
                print(f"  ✗ {error_msg}")
                errors.append(error_msg)

        # Get final statistics
        stats = self.get_table_stats(table_name)
        total_records = stats["total_records"]
        unique_vins = stats["unique_vins"]

        date_range = (min(dates), max(dates)) if dates else None

        print(f"\n{'='*60}")
        print(f"Rebuild complete for {table_name}!")
        print(f"  Files processed: {processed}")
        print(f"  Total records (VIN+plate combinations): {total_records:,}")
        print(f"  Unique VINs: {unique_vins:,}")
        if date_range:
            print(f"  Date range: {date_range[0]} to {date_range[1]}")
        if errors:
            print(f"  Errors: {len(errors)}")
        print(f"{'='*60}")

        return {
            "files_processed": processed,
            "total_records": total_records,
            "unique_vins": unique_vins,
            "date_range": date_range,
            "errors": errors,
        }

    def backfill_history_from_csvs(self, csv_dir: str = "/data/tlc") -> dict:
        """
        Backfill historical counts by processing all stored CSV files.
        Simulates cumulative table growth: tracks all unique VINs seen over time,
        just like tlc_vehicles table does with upserts.

        Args:
            csv_dir: Directory containing versioned CSV files (tlc_vehicles_YYYYMMDD_HHMMSS.csv)

        Returns:
            dict with statistics: {
                'files_processed': int,
                'date_range': tuple,
                'errors': list
            }
        """
        csv_path = Path(csv_dir)
        if not csv_path.exists():
            raise ValueError(f"CSV directory not found: {csv_dir}")

        # Find all versioned CSV files (not the _latest symlink)
        csv_files = sorted(
            [f for f in csv_path.glob("tlc_vehicles_*.csv") if not f.name.endswith("_latest.csv")]
        )

        if not csv_files:
            print(f"No CSV files found in {csv_dir}")
            return {"files_processed": 0, "date_range": None, "errors": []}

        processed = 0
        errors = []
        dates = []

        # Track cumulative unique VINs seen (simulates table behavior)
        cumulative_vins = set()

        print(f"Found {len(csv_files)} CSV files to process")
        print("Simulating cumulative table growth (tracking unique VINs over time)...")

        for csv_file in csv_files:
            try:
                # Extract date from filename: tlc_vehicles_YYYYMMDD_HHMMSS.csv
                filename = csv_file.stem  # removes .csv
                timestamp_str = filename.replace("tlc_vehicles_", "")
                date_str = timestamp_str.split("_")[0]  # Get YYYYMMDD part

                # Convert to YYYY-MM-DD format
                file_date = datetime.strptime(date_str, "%Y%m%d").date().isoformat()

                # Track both active (in this CSV) and cumulative (ever seen) counts
                active_vins = set()
                new_vins = 0
                with open(csv_file, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        vin = row.get("Vehicle VIN Number", "")
                        if vin.startswith("VCF1"):
                            active_vins.add(vin)  # Present in this day's export
                            if vin not in cumulative_vins:
                                new_vins += 1
                            cumulative_vins.add(vin)  # Ever seen

                # Record both counts
                global_count = len(cumulative_vins)
                active_count = len(active_vins)
                self.record_daily_count(file_date, global_count, active_count)
                dates.append(file_date)
                processed += 1

                if new_vins > 0:
                    print(
                        f"  {file_date}: +{new_vins} new VINs "
                        f"(active: {active_count:,}, cumulative: {global_count:,})"
                    )

            except Exception as e:
                error_msg = f"Error processing {csv_file.name}: {str(e)}"
                print(f"  ✗ {error_msg}")
                errors.append(error_msg)

        date_range = (min(dates), max(dates)) if dates else None

        return {
            "files_processed": processed,
            "date_range": date_range,
            "errors": errors,
        }

    def upsert_to_minimal(self, vin: str, license_plate: str, snapshot_date: str) -> None:
        """
        Insert or update a record in tlc_vehicles_minimal.

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
            INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (vin, license_plate) DO UPDATE SET
                most_recently_reported_on = GREATEST(
                    tlc_vehicles_minimal.most_recently_reported_on,
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
        Import TLC vehicle data from CSV file directly into tlc_vehicles_minimal only.
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
                        INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (vin, license_plate) DO UPDATE SET
                            most_recently_reported_on = GREATEST(
                                tlc_vehicles_minimal.most_recently_reported_on,
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

    def populate_minimal_from_full(self) -> dict:
        """
        Populate tlc_vehicles_minimal from existing tlc_vehicles data.
        This extracts only the essential columns needed for plate validation.

        Returns:
            dict with statistics: {
                'records_created': int,
                'unique_vins': int,
                'unique_plates': int
            }
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        print("Populating tlc_vehicles_minimal from tlc_vehicles...")

        # Insert all VIN+plate combinations with their date ranges
        cursor.execute("""
            INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
            SELECT
                vehicle_vin_number as vin,
                dmv_license_plate_number as license_plate,
                first_load_date as first_reported_on,
                most_recent_date as most_recently_reported_on
            FROM tlc_vehicles
            ON CONFLICT (vin, license_plate) DO UPDATE SET
                first_reported_on = LEAST(
                    tlc_vehicles_minimal.first_reported_on,
                    EXCLUDED.first_reported_on
                ),
                most_recently_reported_on = GREATEST(
                    tlc_vehicles_minimal.most_recently_reported_on,
                    EXCLUDED.most_recently_reported_on
                )
        """)

        records_created = cursor.rowcount
        conn.commit()

        # Get statistics
        cursor.execute("SELECT COUNT(DISTINCT vin) FROM tlc_vehicles_minimal")
        unique_vins = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT license_plate) FROM tlc_vehicles_minimal")
        unique_plates = cursor.fetchone()[0]

        conn.close()

        print("✓ Populated tlc_vehicles_minimal:")
        print(f"  Records: {records_created:,}")
        print(f"  Unique VINs: {unique_vins:,}")
        print(f"  Unique plates: {unique_plates:,}")

        return {
            "records_created": records_created,
            "unique_vins": unique_vins,
            "unique_plates": unique_plates,
        }

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
        imported_count = self.import_tlc_data(csv_path, snapshot_date, filter_fisker=True)
        print(f"✓ Imported/updated {imported_count:,} records")

        # Get cumulative count of unique VINs from database
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT vehicle_vin_number) FROM tlc_vehicles")
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
