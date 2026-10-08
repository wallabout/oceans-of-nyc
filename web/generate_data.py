#!/usr/bin/env python3
"""Generate JSON data file for static website."""

import json
import os
import sys
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# Add parent directory to path to import database models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

from database.models import SightingsDatabase  # noqa: E402

# Load environment variables (only for local execution)
if os.path.exists(os.path.join(os.path.dirname(__file__), "..", ".env")):
    load_dotenv()


def _json_serializer(obj):
    """Custom JSON serializer for datetime and date objects."""
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# The feed's first pages are published as small static files so /feed can paint
# without downloading (and parsing) the whole of oceans.json. Most visitors never
# scroll past a few dozen cards; anyone who goes past the last static page, or
# filters, gets the full dataset loaded on demand.
FEED_PAGE_SIZE = 50
FEED_STATIC_PAGES = 10


def _feed_vehicle_stub(vehicle: dict, sighting: dict) -> dict:
    """
    The slice of a vehicle the feed card reads: its plates (for the plate line
    and TLC debut date) and just the previous sighting (for "last seen X ago").
    """
    n = sighting.get("vehicle_sighting_index")
    previous = [
        {"vehicle_sighting_index": s["vehicle_sighting_index"], "timestamp": s["timestamp"]}
        for s in vehicle["sightings"]
        if n is not None and s.get("vehicle_sighting_index") == n - 1
    ]
    return {
        "vin": vehicle["vin"],
        "license_plates": vehicle["license_plates"],
        "sightings": previous,
    }


def build_feed_pages(
    vehicles: list[dict],
    badge_definitions: list[dict],
    page_size: int = FEED_PAGE_SIZE,
    max_pages: int = FEED_STATIC_PAGES,
) -> list[dict]:
    """
    Split the newest sightings into static feed pages, newest first.

    Each item is a {sighting, vehicle} pair shaped like oceans.json, so the site
    renders it with the same card builder. Page 1 also carries what the filter
    bar needs (contributors, boroughs) and the badge definitions.

    Returns:
        Up to max_pages page dicts. "pages" counts only the static pages; the
        client switches to oceans.json once "has_more" runs out of static pages.
    """
    pairs = [(s, v) for v in vehicles for s in v["sightings"]]
    pairs.sort(key=lambda pair: pair[0]["timestamp"], reverse=True)

    total = len(pairs)
    page_count = min(max_pages, max(1, -(-total // page_size)))
    pages = []
    for page in range(1, page_count + 1):
        chunk = pairs[(page - 1) * page_size : page * page_size]
        data: dict = {
            "page": page,
            "pages": page_count,
            "page_size": page_size,
            "total_sightings": total,
            "has_more": page * page_size < total,
            "items": [{"sighting": s, "vehicle": _feed_vehicle_stub(v, s)} for s, v in chunk],
        }
        if page == 1:
            data["contributors"] = sorted(
                {s["contributor"] for s, _ in pairs if s.get("contributor")}
            )
            data["boroughs"] = sorted({s["borough"] for s, _ in pairs if s.get("borough")})
            data["badge_definitions"] = badge_definitions
        pages.append(data)
    return pages


def _publish_json(data: dict, name: str, upload_to_r2: bool) -> str:
    """Upload data to R2 at web/<name>, or write it next to this file. Returns where it went."""
    json_content = json.dumps(data, default=_json_serializer)
    if upload_to_r2:
        from utils.r2_storage import R2Storage

        return R2Storage().upload_bytes(
            json_content.encode("utf-8"),
            f"web/{name}",
            content_type="application/json",
            cache_control="public, max-age=60",
        )

    output_path = os.path.join(os.path.dirname(__file__), name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        f.write(json_content)
    return output_path


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
            contributor_id,
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
    contributors_seen: dict[int, dict] = {}
    for row in cursor.fetchall():
        (
            sighting_id,
            vin,
            plate,
            timestamp_et,
            borough,
            contributor_id,
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
            "timestamp": timestamp_et.replace(tzinfo=_ET),
            "borough": borough,
            "contributor_id": contributor_id,
            "contributor": preferred_name,
            "bluesky_handle": bluesky_handle,
            "image": image_url,
            "vehicle_sighting_index": vehicle_sighting_index,
            "global_sighting_index": global_sighting_index,
            "global_unique_sighting_index": global_unique_sighting_index,
            "ocean_points": float(ocean_points) if ocean_points is not None else None,
            "badges": [],
        }
        if contributor_id is not None and contributor_id not in contributors_seen:
            contributors_seen[contributor_id] = {
                "id": contributor_id,
                "preferred_name": preferred_name,
                "bluesky_handle": bluesky_handle,
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

    # Query 4: All badges per contributor (for trophy cases on contributor pages).
    # Prefer the linked sighting's timestamp; fall back to earned_on if a badge isn't
    # tied to a specific sighting.
    cursor.execute("""
        SELECT cb.contributor_id, cb.badge_name,
               COALESCE(s.created_at::timestamptz, cb.earned_on::timestamptz) AS earned_at
        FROM contributors_badges cb
        LEFT JOIN sightings s ON s.id = cb.sighting_id
        ORDER BY cb.contributor_id, earned_at
    """)

    for contributor_id, badge_name, earned_at in cursor.fetchall():
        if contributor_id in contributors_seen:
            contributors_seen[contributor_id]["badges"].append(
                {"name": badge_name, "earned_on": earned_at}
            )

    # Query 5: Denominator for "X of Y Oceans found": leaves out inactive
    # Oceans nobody sighted before they left the TLC database.
    cursor.execute("SELECT COUNT(*) FROM ocean_findability WHERE is_findable")
    findable_total = cursor.fetchone()[0]

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

    contributors = sorted(
        contributors_seen.values(),
        key=lambda c: (c["preferred_name"] or "").lower(),
    )

    data = {
        "vehicles": vehicles,
        "contributors": contributors,
        "badge_definitions": [
            {
                "name": badge.name,
                "display_name": badge.display_name,
                "description": badge.description,
                "emoji": badge.emoji,
            }
            for badge in BADGE_DEFINITIONS
        ],
        "total": findable_total,
        "sighted": sum(1 for v in vehicles if v["sightings"]),
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }

    json_content = json.dumps(data, indent=2, default=_json_serializer)

    # Small companions to oceans.json: the nav's stats line on every page, and
    # the first pages of /feed.
    total_sightings = sum(len(v["sightings"]) for v in vehicles)
    _publish_json(
        {
            "total_sightings": total_sightings,
            "sighted": data["sighted"],
            "total": data["total"],
            "generated_at": data["generated_at"],
        },
        "summary.json",
        upload_to_r2,
    )
    feed_pages = build_feed_pages(vehicles, data["badge_definitions"])
    for feed_page in feed_pages:
        _publish_json(feed_page, f"feed_pages/{feed_page['page']}.json", upload_to_r2)
    print(f"  Feed pages: {len(feed_pages)} x {FEED_PAGE_SIZE} sightings")

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
        print(f"  Total vehicles: {len(vehicles)} ({findable_total} findable)")
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
    print(f"Total vehicles: {len(vehicles)} ({findable_total} findable)")
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
            rolling_avg_7_days,
            rolling_first_sighting_rate
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
            rolling_first_sighting_rate,
        ) = row
        rows.append(
            {
                "date": sighting_date.isoformat()
                if hasattr(sighting_date, "isoformat")
                else sighting_date,
                "first_sighting_count": first_sighting_count,
                "sighting_count": sighting_count,
                "first_sighting_rate": float(first_sighting_rate)
                if first_sighting_rate is not None
                else None,
                "global_ocean_count": global_ocean_count,
                "active_ocean_count": active_ocean_count,
                "expected_first_sighting_rate": float(expected_first_sighting_rate)
                if expected_first_sighting_rate is not None
                else None,
                "rolling_avg_7_days": float(rolling_avg_7_days)
                if rolling_avg_7_days is not None
                else None,
                "rolling_first_sighting_rate": float(rolling_first_sighting_rate)
                if rolling_first_sighting_rate is not None
                else None,
            }
        )

    conn.close()

    data = {
        "daily_sightings": rows,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }

    json_content = json.dumps(data, indent=2, default=_json_serializer)

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


def generate_web_tags_data(upload_to_r2: bool = False) -> dict:
    """
    Generate tags.json: community photo tags keyed by sighting id.

    Kept separate from oceans.json deliberately. Tags change far more often than
    sightings (every visitor click is a potential nomination) but the payload is
    tiny, so it can be regenerated on its own without re-uploading the full
    vehicle dataset. The site fetches both and merges them client-side.

    Args:
        upload_to_r2: If True, upload to R2 at /web/tags.json instead of writing locally

    Returns:
        Dictionary with generation results
    """
    from tags import TAG_DEFINITIONS

    db = SightingsDatabase()
    rows = db.get_sighting_tag_counts()

    # { "<sighting_id>": { "<tag_name>": count } } — string keys because JSON
    # object keys are always strings, and the client indexes by String(id).
    sighting_tags: dict[str, dict[str, int]] = {}
    tag_totals: dict[str, int] = {tag.name: 0 for tag in TAG_DEFINITIONS}
    for row in rows:
        key = str(row["sighting_id"])
        sighting_tags.setdefault(key, {})[row["tag_name"]] = row["nomination_count"]
        tag_totals[row["tag_name"]] = tag_totals.get(row["tag_name"], 0) + 1

    data = {
        "tag_definitions": [
            {
                "name": tag.name,
                "display_name": tag.display_name,
                "description": tag.description,
                "emoji": tag.emoji,
                "public": tag.public,
            }
            for tag in TAG_DEFINITIONS
        ],
        # Number of distinct photos carrying each tag, for the filter view counts.
        "tag_totals": tag_totals,
        "sighting_tags": sighting_tags,
        "tagged_sightings": len(sighting_tags),
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }

    json_content = json.dumps(data, indent=2, default=_json_serializer)

    if upload_to_r2:
        from utils.r2_storage import R2Storage

        r2 = R2Storage()
        r2_key = "web/tags.json"
        url = r2.upload_bytes(
            json_content.encode("utf-8"),
            r2_key,
            content_type="application/json",
            cache_control="public, max-age=60",
        )

        print(f"✓ Uploaded to R2: {url}")
        print(f"  Tagged photos: {len(sighting_tags)}")

        return {
            "status": "success",
            "url": url,
            "r2_key": r2_key,
            "tagged_sightings": len(sighting_tags),
        }

    output_path = os.path.join(os.path.dirname(__file__), "tags.json")
    with open(output_path, "w") as f:
        f.write(json_content)

    print(f"Generated {output_path}")
    print(f"Tagged photos: {len(sighting_tags)}")

    return {
        "status": "success",
        "path": output_path,
        "tagged_sightings": len(sighting_tags),
    }


# Twilio usage categories broken out on the admin-stats cost chart, in stack
# order. These are disjoint and together cover the account total ("totalprice");
# anything left over (failed-message fees, stray voice minutes) is shown as "Other".
# Carrier fees are billed as their own categories, not inside sms-/mms-*.
TWILIO_COST_BREAKDOWN = [
    ("sms-outbound", "SMS out"),
    ("sms-inbound", "SMS in"),
    ("mms-inbound", "MMS in"),
    ("sms-messages-carrierfees", "SMS carrier fees"),
    ("mms-messages-carrierfees", "MMS carrier fees"),
    ("phonenumbers", "Phone numbers"),
    ("a2p-registration-fees", "A2P 10DLC fees"),
]
TWILIO_MESSAGE_CATEGORIES = ["sms-inbound", "sms-outbound", "mms-inbound", "mms-outbound"]


def build_twilio_cost_days(
    usage_rows: list[tuple], submissions_by_day: dict, through: date
) -> list[dict]:
    """
    Combine stored Twilio usage and daily submission counts into one row per UTC day.

    Args:
        usage_rows: (usage_date, category, count, price) tuples from twilio_daily_usage
        submissions_by_day: {date: submission count}
        through: last day to include (yesterday, so a partial day never shows)

    Returns:
        Rows sorted by date from the first day with usage, with total Twilio $,
        $ per breakdown category (plus "other"), message count and submissions.
    """
    usage_by_day: dict = {}
    for usage_date, category, count, price in usage_rows:
        usage_by_day.setdefault(usage_date, {})[category] = (
            float(count or 0),
            float(price or 0),
        )

    if not usage_by_day:
        return []

    days = []
    day = min(usage_by_day)
    while day <= through:
        categories = usage_by_day.get(day, {})
        breakdown = {cat: categories.get(cat, (0.0, 0.0))[1] for cat, _ in TWILIO_COST_BREAKDOWN}
        if "totalprice" in categories:
            total = categories["totalprice"][1]
        else:
            total = sum(breakdown.values())
        breakdown["other"] = total - sum(breakdown.values())
        days.append(
            {
                "date": day.isoformat(),
                "submissions": submissions_by_day.get(day, 0),
                "total_price": round(total, 4),
                "messages": int(
                    sum(categories.get(cat, (0.0, 0.0))[0] for cat in TWILIO_MESSAGE_CATEGORIES)
                ),
                "price_by_category": {cat: round(p, 4) for cat, p in breakdown.items()},
            }
        )
        day += timedelta(days=1)
    return days


def generate_web_twilio_cost_data(upload_to_r2: bool = False) -> dict:
    """
    Generate twilio_cost.json for the unlisted /admin-stats page.

    Daily Twilio spend (from twilio_daily_usage) alongside daily submissions
    (SMS and web alike), both by UTC day since that's how Twilio reports usage.

    Args:
        upload_to_r2: If True, upload to R2 at /web/twilio_cost.json instead of writing locally

    Returns:
        Dictionary with generation results
    """
    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT usage_date, category, count, price
        FROM twilio_daily_usage
        ORDER BY usage_date
    """)
    usage_rows = cursor.fetchall()

    cursor.execute("""
        SELECT (created_at::timestamp)::date AS submitted_on, count(*)
        FROM sightings
        GROUP BY 1
    """)
    submissions_by_day = dict(cursor.fetchall())
    conn.close()

    yesterday = datetime.now(tz=UTC).date() - timedelta(days=1)
    days = build_twilio_cost_days(usage_rows, submissions_by_day, through=yesterday)

    data = {
        "days": days,
        "categories": [{"key": key, "label": label} for key, label in TWILIO_COST_BREAKDOWN]
        + [{"key": "other", "label": "Other"}],
        "currency": "USD",
        "timezone": "UTC",
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }

    json_content = json.dumps(data, indent=2, default=_json_serializer)

    if upload_to_r2:
        from utils.r2_storage import R2Storage

        r2 = R2Storage()
        r2_key = "web/twilio_cost.json"
        url = r2.upload_bytes(
            json_content.encode("utf-8"),
            r2_key,
            content_type="application/json",
            cache_control="public, max-age=60",
        )

        print(f"✓ Uploaded to R2: {url}")
        print(f"  Days: {len(days)}")

        return {"status": "success", "url": url, "r2_key": r2_key, "days": len(days)}

    output_path = os.path.join(os.path.dirname(__file__), "twilio_cost.json")
    with open(output_path, "w") as f:
        f.write(json_content)

    print(f"Generated {output_path}")
    print(f"Days: {len(days)}")

    return {"status": "success", "path": output_path, "days": len(days)}


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
    tags_result = generate_web_tags_data(upload_to_r2=upload_to_r2)
    return {
        "oceans": oceans_result,
        "daily_sightings": daily_result,
        "tags": tags_result,
    }


if __name__ == "__main__":
    # When run directly, write to local files
    generate_web_oceans_data(upload_to_r2=False)
    generate_web_daily_sightings_data(upload_to_r2=False)
    generate_web_tags_data(upload_to_r2=False)
