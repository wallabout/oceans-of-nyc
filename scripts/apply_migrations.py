"""Apply pending SQL migrations in ``database/migrations`` to a Postgres database.

Applied files are recorded in a ``schema_migrations`` tracking table so each
migration runs exactly once, in filename order. This is used by the Deploy
workflow (``.github/workflows/deploy.yml``) to bring the production Neon
database up to date before new code goes live.

One-time setup on an existing database
--------------------------------------
The migrations in this repo predate this runner and are already applied in
production, and several are not idempotent (e.g. ``ALTER TABLE ... ADD COLUMN``).
Blindly re-running them would fail. So run once against production to record the
current files as already applied, WITHOUT executing them::

    DATABASE_URL=<prod-url> uv run python scripts/apply_migrations.py --baseline

After that, every deploy runs the plain form, which applies only new files::

    DATABASE_URL=<prod-url> uv run python scripts/apply_migrations.py

Authoring new migrations
------------------------
Files are applied in sorted filename order. Give new migrations a sortable
prefix so ordering is explicit and dependencies apply first, e.g.::

    database/migrations/20260721_1200_add_foo_column.sql
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"


def ensure_tracking_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    conn.commit()


def applied_filenames(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def record_applied(conn, filename: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING",
            (filename,),
        )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Record all current migrations as applied WITHOUT executing them "
        "(use once on an existing database).",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Postgres connection string (defaults to the DATABASE_URL env var).",
    )
    args = parser.parse_args()

    if not args.database_url:
        print(
            "ERROR: no database URL. Pass --database-url or set DATABASE_URL.",
            file=sys.stderr,
        )
        return 1

    if not MIGRATIONS_DIR.is_dir():
        print(f"ERROR: migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("No migration files found; nothing to do.")
        return 0

    conn = psycopg2.connect(args.database_url)
    conn.autocommit = False
    try:
        ensure_tracking_table(conn)
        already_applied = applied_filenames(conn)
        pending = [f for f in files if f.name not in already_applied]

        if not pending:
            print("Database is up to date; no pending migrations.")
            return 0

        if args.baseline:
            for migration in pending:
                record_applied(conn, migration.name)
                print(f"baselined (marked applied, not run): {migration.name}")
            print(f"Baseline complete: {len(pending)} migration(s) recorded as applied.")
            return 0

        for migration in pending:
            print(f"applying: {migration.name}")
            sql = migration.read_text()
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
            except Exception as exc:  # noqa: BLE001 - surface the failing migration and stop
                conn.rollback()
                print(f"ERROR applying {migration.name}: {exc}", file=sys.stderr)
                return 1
            record_applied(conn, migration.name)

        print(f"Applied {len(pending)} migration(s).")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
