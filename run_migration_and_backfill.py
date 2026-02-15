#!/usr/bin/env python3
"""Execute migration and backfill historical TLC vehicle counts."""

from pathlib import Path

from dotenv import load_dotenv

from validate.tlc import TLCDatabase

# Load environment variables
load_dotenv()


def run_migration(db):
    """Execute the SQL migration to refactor tlc_vehicle_history table."""
    migration_file = (
        Path(__file__).parent / "database" / "migrations" / "refactor_tlc_vehicle_history.sql"
    )

    print(f"Reading migration from {migration_file}")
    with open(migration_file) as f:
        migration_sql = f.read()

    print("Executing migration...")
    conn = db._get_connection()
    cursor = conn.cursor()

    cursor.execute(migration_sql)
    conn.commit()
    conn.close()

    print("✓ Migration completed successfully")


def run_backfill(db):
    """Backfill historical data from stored CSV files."""
    # Check if running in Modal environment or local
    csv_dir = "/data/tlc" if Path("/data/tlc").exists() else "./data/tlc"

    if not Path(csv_dir).exists():
        print(f"⚠ CSV directory not found at {csv_dir}")
        print("  Please provide the correct path to your stored TLC CSV files")
        return

    print(f"\nBackfilling from CSV files in {csv_dir}...")
    results = db.backfill_history_from_csvs(csv_dir)

    print("\n✓ Backfill completed!")
    print(f"  Files processed: {results['files_processed']}")
    if results["date_range"]:
        print(f"  Date range: {results['date_range'][0]} to {results['date_range'][1]}")
    if results["errors"]:
        print(f"  Errors: {len(results['errors'])}")
        for error in results["errors"]:
            print(f"    - {error}")


def main():
    """Main execution."""
    print("TLC Vehicle History - Migration and Backfill")
    print("=" * 50)

    # Initialize database connection
    db = TLCDatabase()

    # Run migration
    print("\n1. Running migration...")
    try:
        run_migration(db)
    except Exception as e:
        print(f"⚠ Migration error (may already exist): {e}")

    # Run backfill
    print("\n2. Backfilling historical data...")
    try:
        run_backfill(db)
    except Exception as e:
        print(f"✗ Backfill error: {e}")
        raise

    print("\n" + "=" * 50)
    print("✓ All done!")


if __name__ == "__main__":
    main()
