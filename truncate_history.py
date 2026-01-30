#!/usr/bin/env python3
"""Truncate tlc_vehicle_history table."""

from dotenv import load_dotenv

from validate.tlc import TLCDatabase

load_dotenv()

db = TLCDatabase()
conn = db._get_connection()
cursor = conn.cursor()

print("Truncating tlc_vehicle_history table...")
cursor.execute("TRUNCATE TABLE tlc_vehicle_history")
conn.commit()
conn.close()

print("✓ Table truncated successfully")
