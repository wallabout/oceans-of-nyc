#!/usr/bin/env python3
"""Generate JSON data file for static website."""

import json
import os
import sys
from datetime import datetime, timezone

# Add parent directory to path to import database models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from database.models import SightingsDatabase

# Load environment variables (only for local execution)
if os.path.exists(os.path.join(os.path.dirname(__file__), "..", ".env")):
    load_dotenv()


def generate_web_sightings_data(upload_to_r2: bool = False) -> dict:
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

    # Get all distinct VINs from tlc_vehicles_minimal with their most recent sighting
    cursor.execute("""
        SELECT DISTINCT
            t.vin,
            s.image_filename,
            s.timestamp
        FROM tlc_vehicles_minimal t
        LEFT JOIN LATERAL (
            SELECT image_filename, timestamp
            FROM sightings
            WHERE COALESCE(vin, (
                SELECT vin
                FROM tlc_vehicles_minimal
                WHERE license_plate = sightings.license_plate
                ORDER BY most_recently_reported_on DESC
                LIMIT 1
            )) = t.vin
            ORDER BY timestamp DESC
            LIMIT 1
        ) s ON true
        ORDER BY
            t.vin
    """)

    # Store the main vehicle data
    vehicle_rows = cursor.fetchall()

    # Get all license plates for each VIN (sorted alphabetically)
    cursor.execute("""
        SELECT
            vin,
            license_plate
        FROM tlc_vehicles_minimal
        ORDER BY vin, license_plate
    """)

    # Build a dict of license plates by VIN
    plates_by_vin: dict[str, list[str]] = {}
    for row in cursor.fetchall():
        vin, plate = row
        if vin not in plates_by_vin:
            plates_by_vin[vin] = []
        plates_by_vin[vin].append(plate)

    # Get license plate history for each VIN
    cursor.execute("""
        SELECT
            vin,
            license_plate,
            first_reported_on,
            most_recently_reported_on
        FROM tlc_vehicles_minimal
        ORDER BY vin, license_plate
    """)

    # Build a dict of license plate history by VIN
    plate_history_by_vin: dict[str, list[dict[str, str]]] = {}
    for row in cursor.fetchall():
        vin, plate, first_reported, most_recent = row
        if vin not in plate_history_by_vin:
            plate_history_by_vin[vin] = []
        plate_history_by_vin[vin].append(
            {
                "license_plate": plate,
                "first_reported_on": first_reported,
                "most_recently_reported_on": most_recent,
            }
        )

    # Get all sightings with contributor information from the sightings_export view
    cursor.execute("""
        SELECT
            vin,
            license_plate,
            timestamp_et,
            borough,
            preferred_name,
            image_filename,
            vehicle_sighting_index
        FROM sightings_export
    """)

    # Build a dict of sightings by VIN
    sightings_by_vin: dict[str, list[dict[str, str | None | int]]] = {}
    for row in cursor.fetchall():
        (
            vin,
            plate,
            timestamp_et,
            borough,
            preferred_name,
            image_filename,
            vehicle_sighting_index,
        ) = row
        image_url = f"{image_base_uri}/{image_filename}" if image_filename else None
        if vin not in sightings_by_vin:
            sightings_by_vin[vin] = []

        sightings_by_vin[vin].append(
            {
                "license_plate": plate,
                "timestamp": timestamp_et,
                "borough": borough,
                "contributor": preferred_name,
                "image": image_url,
                "isFirstSighting": vehicle_sighting_index == 1,
            }
        )

    # Build vehicles array
    vehicles = []
    for row in vehicle_rows:
        vin, image_filename, timestamp = row
        image_url = f"{image_base_uri}/{image_filename}" if image_filename else None
        vehicle_data = {
            "vin": vin,
            "license_plates": plates_by_vin.get(vin, []),
            "image": image_url,
            "timestamp": timestamp,
            "license_plate_history": plate_history_by_vin.get(vin, []),
        }

        # Add sightings array if vehicle has any sightings
        if vin in sightings_by_vin:
            vehicle_data["sightings"] = sightings_by_vin[vin]

        vehicles.append(vehicle_data)

    conn.close()

    # Generate JSON data
    data = {
        "vehicles": vehicles,
        "total": len(vehicles),
        "sighted": sum(1 for v in vehicles if v["image"]),
    }

    def json_serializer(obj):
        """Custom JSON serializer for datetime and date objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        from datetime import date

        if isinstance(obj, date):
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


def generate_web_badges_data(upload_to_r2: bool = False) -> dict:
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
        """Custom JSON serializer for datetime and date objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        from datetime import date

        if isinstance(obj, date):
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


def generate_web_oceans_data(upload_to_r2: bool = False) -> dict:
    """
    Generate oceans.json with a nested vehicle -> sightings -> badges structure.

    Args:
        upload_to_r2: If True, upload to R2 at /web/oceans.json instead of writing locally

    Returns:
        Dictionary with generation results
    """
    image_base_uri = os.getenv(
        "SIGHTING_IMAGE_BASE_URI", "https://cdn.oceansofnyc.com/sightings/"
    ).rstrip("/")

    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    # Query 1: All license plate history by VIN (preserves alphabetical VIN order)
    cursor.execute("""
        SELECT
            vin,
            license_plate,
            first_reported_on,
            most_recently_reported_on
        FROM tlc_vehicles_minimal
        ORDER BY vin, license_plate
    """)

    plates_by_vin: dict[str, list[dict]] = {}
    vins_ordered: list[str] = []
    for vin, plate, first_reported, most_recent in cursor.fetchall():
        if vin not in plates_by_vin:
            plates_by_vin[vin] = []
            vins_ordered.append(vin)
        plates_by_vin[vin].append(
            {
                "license_plate": plate,
                "first_reported_on": first_reported,
                "most_recently_reported_on": most_recent,
            }
        )

    # Query 2: All sightings from sightings_export, indexed by sighting_id for badge attachment
    cursor.execute("""
        SELECT
            sighting_id,
            vin,
            license_plate,
            timestamp_et,
            borough,
            preferred_name,
            bluesky_handle,
            image_filename,
            vehicle_sighting_index
        FROM sightings_export
        ORDER BY vin, timestamp_et
    """)

    sightings_by_vin: dict[str, list[dict]] = {}
    sighting_index: dict[int, dict] = {}
    for row in cursor.fetchall():
        (
            sighting_id,
            vin,
            plate,
            timestamp_et,
            borough,
            preferred_name,
            bluesky_handle,
            image_filename,
            vehicle_sighting_index,
        ) = row
        image_url = f"{image_base_uri}/{image_filename}" if image_filename else None
        sighting: dict = {
            "id": sighting_id,
            "license_plate": plate,
            "timestamp": timestamp_et,
            "borough": borough,
            "contributor": preferred_name,
            "bluesky_handle": bluesky_handle,
            "image": image_url,
            "vehicle_sighting_index": vehicle_sighting_index,
            "badges": [],
        }
        if vin not in sightings_by_vin:
            sightings_by_vin[vin] = []
        sightings_by_vin[vin].append(sighting)
        sighting_index[sighting_id] = sighting

    # Query 3: All badges that are linked to a sighting, attached in-place to their sighting
    cursor.execute("""
        SELECT sighting_id, badge_name, earned_on
        FROM contributors_badges
        WHERE sighting_id IS NOT NULL
        ORDER BY sighting_id, badge_name
    """)

    for sighting_id, badge_name, earned_on in cursor.fetchall():
        if sighting_id in sighting_index:
            sighting_index[sighting_id]["badges"].append(
                {"name": badge_name, "earned_on": earned_on}
            )

    conn.close()

    # Assemble vehicles array
    vehicles = [
        {
            "vin": vin,
            "license_plates": plates_by_vin[vin],
            "sightings": sightings_by_vin.get(vin, []),
        }
        for vin in vins_ordered
    ]

    from badges.definitions import BADGE_DEFINITIONS

    data = {
        "vehicles": vehicles,
        "badge_definitions": [
            {
                "name": badge.name,
                "display_name": badge.display_name,
                "description": badge.description,
                "emoji": badge.emoji,
            }
            for badge in BADGE_DEFINITIONS
        ],
        "total": len(vehicles),
        "sighted": sum(1 for v in vehicles if v["sightings"]),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    def json_serializer(obj):
        """Custom JSON serializer for datetime and date objects."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        from datetime import date

        if isinstance(obj, date):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    json_content = json.dumps(data, indent=2, default=json_serializer)

    if upload_to_r2:
        from utils.r2_storage import R2Storage

        r2 = R2Storage()
        r2_key = "web/oceans.json"
        url = r2.upload_bytes(
            json_content.encode("utf-8"),
            r2_key,
            content_type="application/json",
            cache_control="public, max-age=60",
        )

        print(f"✓ Uploaded to R2: {url}")
        print(f"  Total vehicles: {len(vehicles)}")
        print(f"  Vehicles with sightings: {data['sighted']}")

        return {
            "status": "success",
            "url": url,
            "r2_key": r2_key,
            "total": data["total"],
            "sighted": data["sighted"],
        }

    output_path = os.path.join(os.path.dirname(__file__), "oceans.json")
    with open(output_path, "w") as f:
        f.write(json_content)

    print(f"Generated {output_path}")
    print(f"Total vehicles: {len(vehicles)}")
    print(f"Vehicles with sightings: {data['sighted']}")

    return {
        "status": "success",
        "path": output_path,
        "total": data["total"],
        "sighted": data["sighted"],
    }


def generate_web_data(upload_to_r2: bool = False) -> dict:
    """
    Generate all web data files (sightings, badges, and oceans).

    Args:
        upload_to_r2: If True, upload to R2 instead of writing locally

    Returns:
        Dictionary with combined generation results
    """
    sightings_result = generate_web_sightings_data(upload_to_r2=upload_to_r2)
    badges_result = generate_web_badges_data(upload_to_r2=upload_to_r2)
    oceans_result = generate_web_oceans_data(upload_to_r2=upload_to_r2)

    return {
        "status": "success",
        "sightings": sightings_result,
        "badges": badges_result,
        "oceans": oceans_result,
    }


if __name__ == "__main__":
    # When run directly, write to local files
    generate_web_oceans_data(upload_to_r2=False)
