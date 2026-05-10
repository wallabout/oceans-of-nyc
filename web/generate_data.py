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
        FROM tlc_vehicles
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
            vehicle_sighting_index,
            global_sighting_index,
            global_unique_sighting_index,
            ocean_points
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
            global_sighting_index,
            global_unique_sighting_index,
            ocean_points,
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
            "global_sighting_index": global_sighting_index,
            "global_unique_sighting_index": global_unique_sighting_index,
            "ocean_points": float(ocean_points) if ocean_points is not None else None,
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


def generate_web_daily_sightings_data(upload_to_r2: bool = False) -> dict:
    """
    Generate daily_sightings.json from the daily_sightings_export view.

    Args:
        upload_to_r2: If True, upload to R2 at /web/daily_sightings.json instead of writing locally

    Returns:
        Dictionary with generation results
    """
    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            sighting_date,
            first_sighting_count,
            sighting_count,
            first_sighting_rate,
            global_ocean_count,
            active_ocean_count,
            expected_first_sighting_rate,
            rolling_avg_7_days
        FROM daily_sightings_export
        ORDER BY sighting_date
    """)

    rows = []
    for row in cursor.fetchall():
        (
            sighting_date,
            first_sighting_count,
            sighting_count,
            first_sighting_rate,
            global_ocean_count,
            active_ocean_count,
            expected_first_sighting_rate,
            rolling_avg_7_days,
        ) = row
        rows.append({
            "date": sighting_date.isoformat() if hasattr(sighting_date, "isoformat") else sighting_date,
            "first_sighting_count": first_sighting_count,
            "sighting_count": sighting_count,
            "first_sighting_rate": float(first_sighting_rate) if first_sighting_rate is not None else None,
            "global_ocean_count": global_ocean_count,
            "active_ocean_count": active_ocean_count,
            "expected_first_sighting_rate": float(expected_first_sighting_rate) if expected_first_sighting_rate is not None else None,
            "rolling_avg_7_days": float(rolling_avg_7_days) if rolling_avg_7_days is not None else None,
        })

    conn.close()

    data = {
        "daily_sightings": rows,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    def json_serializer(obj):
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
        r2_key = "web/daily_sightings.json"
        url = r2.upload_bytes(
            json_content.encode("utf-8"),
            r2_key,
            content_type="application/json",
            cache_control="public, max-age=60",
        )

        print(f"✓ Uploaded to R2: {url}")
        print(f"  Days: {len(rows)}")

        return {"status": "success", "url": url, "r2_key": r2_key, "days": len(rows)}

    output_path = os.path.join(os.path.dirname(__file__), "daily_sightings.json")
    with open(output_path, "w") as f:
        f.write(json_content)

    print(f"Generated {output_path}")
    print(f"Days: {len(rows)}")

    return {"status": "success", "path": output_path, "days": len(rows)}


def generate_web_data(upload_to_r2: bool = False) -> dict:
    """
    Generate all web data files.

    Args:
        upload_to_r2: If True, upload to R2 instead of writing locally

    Returns:
        Dictionary with generation results
    """
    oceans_result = generate_web_oceans_data(upload_to_r2=upload_to_r2)
    daily_result = generate_web_daily_sightings_data(upload_to_r2=upload_to_r2)
    return {"oceans": oceans_result, "daily_sightings": daily_result}


if __name__ == "__main__":
    # When run directly, write to local files
    generate_web_oceans_data(upload_to_r2=False)
    generate_web_daily_sightings_data(upload_to_r2=False)
