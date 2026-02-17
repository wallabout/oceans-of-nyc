#!/usr/bin/env python3
"""Create and populate tlc_vehicles_minimal table from existing tlc_vehicles data."""

from pathlib import Path

from dotenv import load_dotenv

from validate.tlc import TLCDatabase

# Load environment variables
load_dotenv()


def run_migration(db):
    """Execute the SQL migration to create tlc_vehicles_minimal table."""
    migration_file = (
        Path(__file__).parent.parent / "database" / "migrations" / "create_tlc_vehicles_minimal.sql"
    )

    print(f"Reading migration from {migration_file}")
    with open(migration_file) as f:
        migration_sql = f.read()

    print("Executing migration...")
    conn = db._get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(migration_sql)
        conn.commit()
        print("✓ Migration completed successfully")
    except Exception as e:
        print(f"⚠ Migration error (table may already exist): {e}")
        conn.rollback()
    finally:
        conn.close()


def process_historical_csvs(db, csv_dir="/data/tlc"):
    """Process all historical TLC CSV files to populate tlc_vehicles_minimal only."""
    from datetime import datetime
    from pathlib import Path

    csv_path = Path(csv_dir)
    if not csv_path.exists():
        # Try local path
        csv_dir = "./data/tlc"
        csv_path = Path(csv_dir)
        if not csv_path.exists():
            raise ValueError(f"CSV directory not found at {csv_dir}")

    # Find all versioned CSV files (not the _latest symlink)
    csv_files = sorted(
        [f for f in csv_path.glob("tlc_vehicles_*.csv") if not f.name.endswith("_latest.csv")]
    )

    if not csv_files:
        print(f"No CSV files found in {csv_dir}")
        return {"files_processed": 0}

    print(f"\nFound {len(csv_files)} CSV files to process")
    print("Processing historical data in chronological order...")
    print("Populating tlc_vehicles_minimal table only (not touching tlc_vehicles)")

    processed = 0
    total_records = 0

    for csv_file in csv_files:
        try:
            # Extract date from filename: tlc_vehicles_YYYYMMDD_HHMMSS.csv
            filename = csv_file.stem
            timestamp_str = filename.replace("tlc_vehicles_", "")
            date_str = timestamp_str.split("_")[0]  # Get YYYYMMDD part

            # Convert to YYYY-MM-DD format
            file_date = datetime.strptime(date_str, "%Y%m%d").date().isoformat()

            print(f"\nProcessing {csv_file.name} (date: {file_date})...")

            # Import to minimal table only
            imported = db.import_to_minimal_only(str(csv_file), file_date, filter_fisker=True)
            print(f"  ✓ Imported {imported:,} Fisker records to tlc_vehicles_minimal")

            total_records += imported
            processed += 1

        except Exception as e:
            print(f"  ✗ Error processing {csv_file.name}: {e}")

    # Get final statistics
    conn = db._get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(DISTINCT vin) FROM tlc_vehicles_minimal")
    unique_vins = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT license_plate) FROM tlc_vehicles_minimal")
    unique_plates = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tlc_vehicles_minimal")
    total_minimal_records = cursor.fetchone()[0]

    conn.close()

    print("\n" + "=" * 60)
    print("Historical processing complete!")
    print(f"  Files processed: {processed}")
    print(f"  Total records imported: {total_records:,}")
    print(f"  tlc_vehicles_minimal records: {total_minimal_records:,}")
    print(f"  Unique VINs: {unique_vins:,}")
    print(f"  Unique plates: {unique_plates:,}")
    print("=" * 60)

    return {
        "files_processed": processed,
        "unique_vins": unique_vins,
        "unique_plates": unique_plates,
    }


def main():
    """Main execution."""
    print("TLC Vehicles Minimal - Migration and Population")
    print("=" * 60)

    # Initialize database connection
    db = TLCDatabase()

    # Run migration
    print("\n1. Creating tlc_vehicles_minimal table...")
    try:
        run_migration(db)
    except Exception as e:
        print(f"✗ Migration error: {e}")
        raise

    # Process historical CSV files
    print("\n2. Processing historical TLC CSV files...")
    csv_dir = "/data/tlc" if Path("/data/tlc").exists() else "./data/tlc"
    print(f"   Using CSV directory: {csv_dir}")
    try:
        process_historical_csvs(db, csv_dir)
    except Exception as e:
        print(f"✗ Processing error: {e}")
        raise

    print("\n" + "=" * 60)
    print("✓ All done!")
    print("\nThe tlc_vehicles_minimal table has been populated from CSV files.")
    print("The tlc_vehicles table was not modified.")
    print("Future TLC imports will automatically update both tables.")


if __name__ == "__main__":
    main()
