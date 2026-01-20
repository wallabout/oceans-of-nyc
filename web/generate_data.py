#!/usr/bin/env python3
"""Generate JSON data file for static website."""

import json
import os
import sys
from datetime import datetime

# Add parent directory to path to import database models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from database.models import SightingsDatabase

# Load environment variables (only for local execution)
if os.path.exists(os.path.join(os.path.dirname(__file__), "..", ".env")):
    load_dotenv()


def generate_vehicle_data(upload_to_r2: bool = False) -> dict:
    """
    Generate JSON file with all TLC vehicles and their sighting data.

    Args:
        upload_to_r2: If True, upload to R2 at /web/vehicles.json instead of writing locally

    Returns:
        Dictionary with generation results
    """
    # Get image base URI from env var (with fallback)
    image_base_uri = os.getenv(
        "SIGHTING_IMAGE_BASE_URI", "https://cdn.oceansofnyc.com/sightings/"
    ).rstrip("/")

    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    # Get all TLC vehicles with their most recent sighting
    cursor.execute("""
        SELECT
            t.dmv_license_plate_number,
            t.vehicle_vin_number,
            s.image_filename,
            s.borough,
            s.timestamp
        FROM tlc_vehicles t
        LEFT JOIN LATERAL (
            SELECT image_filename, borough, timestamp
            FROM sightings
            WHERE license_plate = t.dmv_license_plate_number
            ORDER BY timestamp DESC
            LIMIT 1
        ) s ON true
        ORDER BY
            t.dmv_license_plate_number
    """)

    # Store the main vehicle data
    vehicle_rows = cursor.fetchall()

    # Get all sightings for vehicles that have them
    cursor.execute("""
        SELECT
            s.license_plate,
            s.timestamp,
            s.borough,
            c.preferred_name,
            s.image_filename
        FROM sightings s
        JOIN contributors c ON s.contributor_id = c.id
        WHERE s.license_plate IN (
            SELECT dmv_license_plate_number FROM tlc_vehicles
        )
        ORDER BY s.license_plate, s.timestamp DESC
    """)

    # Build a dict of sightings by license plate
    sightings_by_plate: dict[str, list[dict[str, str | None]]] = {}
    for row in cursor.fetchall():
        plate, timestamp, borough, preferred_name, image_filename = row
        image_url = f"{image_base_uri}/{image_filename}" if image_filename else None
        if plate not in sightings_by_plate:
            sightings_by_plate[plate] = []
        sightings_by_plate[plate].append(
            {
                "timestamp": timestamp,
                "borough": borough,
                "contributor": preferred_name,
                "image": image_url,
            }
        )

    # Build vehicles array
    vehicles = []
    for row in vehicle_rows:
        plate, vin, image_filename, borough, timestamp = row
        image_url = f"{image_base_uri}/{image_filename}" if image_filename else None
        vehicle_data = {
            "plate": plate,
            "vin": vin,
            "image": image_url,
            "borough": borough,
            "timestamp": timestamp,
        }

        # Add sightings array if vehicle has any sightings
        if plate in sightings_by_plate:
            vehicle_data["sightings"] = sightings_by_plate[plate]

        vehicles.append(vehicle_data)

    conn.close()

    # Generate JSON data
    data = {
        "vehicles": vehicles,
        "total": len(vehicles),
        "sighted": sum(1 for v in vehicles if v["image"]),
    }

    def json_serializer(obj):
        """Custom JSON serializer for datetime objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    json_content = json.dumps(data, indent=2, default=json_serializer)

    if upload_to_r2:
        # Upload to R2 with short cache time (60 seconds)
        from utils.r2_storage import R2Storage

        r2 = R2Storage()
        r2_key = "web/vehicles.json"
        url = r2.upload_bytes(
            json_content.encode("utf-8"),
            r2_key,
            content_type="application/json",
            cache_control="public, max-age=60",  # 1 minute cache
        )

        print(f"✓ Uploaded to R2: {url}")
        print(f"  Total vehicles: {len(vehicles)}")
        print(f"  Vehicles with sightings: {sum(1 for v in vehicles if v['image'])}")

        return {
            "status": "success",
            "url": url,
            "r2_key": r2_key,
            "total": len(vehicles),
            "sighted": sum(1 for v in vehicles if v["image"]),
        }

    # Write to local file
    output_path = os.path.join(os.path.dirname(__file__), "vehicles.json")
    with open(output_path, "w") as f:
        f.write(json_content)

    print(f"Generated {output_path}")
    print(f"Total vehicles: {len(vehicles)}")
    print(f"Vehicles with sightings: {sum(1 for v in vehicles if v['image'])}")

    return {
        "status": "success",
        "path": output_path,
        "total": len(vehicles),
        "sighted": sum(1 for v in vehicles if v["image"]),
    }


def generate_badges_data(upload_to_r2: bool = False) -> dict:
    """
    Generate JSON file with contributor badges data for the badges page.

    Args:
        upload_to_r2: If True, upload to R2 at /web/badges.json instead of writing locally

    Returns:
        Dictionary with generation results
    """
    from badges.definitions import BADGE_DEFINITIONS

    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    # Get all contributors with sighting counts (only those with sightings)
    cursor.execute("""
        SELECT
            c.id,
            c.preferred_name,
            COUNT(s.id) as sighting_count
        FROM contributors c
        JOIN sightings s ON s.contributor_id = c.id
        GROUP BY c.id, c.preferred_name
        ORDER BY COUNT(s.id) DESC
    """)
    contributors = [
        {"id": row[0], "name": row[1], "sighting_count": row[2]} for row in cursor.fetchall()
    ]

    # Get all badges earned by all contributors
    cursor.execute("""
        SELECT contributor_id, badge_name, earned_on
        FROM contributors_badges
        ORDER BY contributor_id, earned_on
    """)

    # Build a lookup: contributor_id -> set of badge_names
    badges_by_contributor: dict[int, set[str]] = {}
    for row in cursor.fetchall():
        contributor_id, badge_name, _ = row
        if contributor_id not in badges_by_contributor:
            badges_by_contributor[contributor_id] = set()
        badges_by_contributor[contributor_id].add(badge_name)

    conn.close()

    # Build badge definitions list (ordered as in definitions.py)
    badges = [
        {
            "name": badge.name,
            "display_name": badge.display_name,
            "description": badge.description,
            "emoji": badge.emoji,
        }
        for badge in BADGE_DEFINITIONS
    ]

    # Build contributor list with their badge names
    contributor_data = []
    for c in contributors:
        earned_badges = badges_by_contributor.get(c["id"], set())
        contributor_data.append(
            {
                "name": c["name"] or "Anonymous",
                "sighting_count": c["sighting_count"],
                "badges": list(earned_badges),
            }
        )

    # Generate JSON data
    data = {
        "badges": badges,
        "contributors": contributor_data,
        "total_badges": len(badges),
        "total_contributors": len(contributors),
    }

    def json_serializer(obj):
        """Custom JSON serializer for datetime objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    json_content = json.dumps(data, indent=2, default=json_serializer)

    if upload_to_r2:
        # Upload to R2 with short cache time (60 seconds)
        from utils.r2_storage import R2Storage

        r2 = R2Storage()
        r2_key = "web/badges.json"
        url = r2.upload_bytes(
            json_content.encode("utf-8"),
            r2_key,
            content_type="application/json",
            cache_control="public, max-age=60",  # 1 minute cache
        )

        print(f"✓ Uploaded to R2: {url}")
        print(f"  Total badges: {len(badges)}")
        print(f"  Total contributors: {len(contributors)}")

        return {
            "status": "success",
            "url": url,
            "r2_key": r2_key,
            "total_badges": len(badges),
            "total_contributors": len(contributors),
        }

    # Write to local file
    output_path = os.path.join(os.path.dirname(__file__), "badges.json")
    with open(output_path, "w") as f:
        f.write(json_content)

    print(f"Generated {output_path}")
    print(f"Total badges: {len(badges)}")
    print(f"Total contributors: {len(contributors)}")

    return {
        "status": "success",
        "path": output_path,
        "total_badges": len(badges),
        "total_contributors": len(contributors),
    }


if __name__ == "__main__":
    # When run directly, write to local files
    generate_vehicle_data(upload_to_r2=False)
    generate_badges_data(upload_to_r2=False)
