"""Sync daily Twilio usage totals from the Usage Records API into Postgres.

Twilio reports usage per UTC day per billing category (``sms-inbound``,
``mms-outbound``, ``phonenumbers``, ...). We store every category with any
activity in ``twilio_daily_usage`` so cost can be compared with daily
submissions (see ``web.generate_data.generate_web_twilio_cost_data``).

Recent days are re-fetched on every run because Twilio keeps revising them
(late carrier fees, monthly number rental landing on one day), so each sync
replaces the whole window it fetched.
"""

import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

# How many trailing days the daily job re-fetches. Covers a full billing month
# so monthly charges that Twilio back-dates are picked up.
DEFAULT_LOOKBACK_DAYS = 35

# Twilio pages are capped at 1000 records; fetch the backfill in chunks so no
# single request has to page through years of categories.
BACKFILL_CHUNK_DAYS = 31


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _client():
    from twilio.rest import Client

    return Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])


def account_created_on(client) -> date:
    """The day the Twilio account was created — the earliest day usage can exist."""
    account = client.api.v2010.accounts(client.account_sid).fetch()
    return account.date_created.date()


def fetch_daily_usage(client, start: date, end: date) -> list[dict]:
    """
    Fetch per-day, per-category usage records for start..end (inclusive, UTC).

    Categories with no activity (zero count, usage and price) are dropped.
    """
    records = client.api.v2010.account.usage.records.daily.list(
        start_date=start, end_date=end, page_size=1000
    )

    rows = []
    for record in records:
        count = _to_decimal(record.count)
        usage = _to_decimal(record.usage)
        price = _to_decimal(record.price)
        if not any((count, usage, price)):
            continue
        rows.append(
            {
                "usage_date": record.start_date,
                "category": record.category,
                "description": record.description,
                "count": count,
                "count_unit": record.count_unit,
                "usage": usage,
                "usage_unit": record.usage_unit,
                "price": price,
                "price_unit": record.price_unit,
            }
        )
    return rows


def store_daily_usage(conn, rows: list[dict], start: date, end: date) -> None:
    """Replace everything stored for start..end with rows, in one transaction."""
    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM twilio_daily_usage WHERE usage_date BETWEEN %s AND %s",
            (start, end),
        )
        for row in rows:
            cursor.execute(
                """
                INSERT INTO twilio_daily_usage (
                    usage_date, category, description, count, count_unit,
                    usage, usage_unit, price, price_unit
                )
                VALUES (
                    %(usage_date)s, %(category)s, %(description)s, %(count)s, %(count_unit)s,
                    %(usage)s, %(usage_unit)s, %(price)s, %(price_unit)s
                )
                """,
                row,
            )
    conn.commit()


def sync_twilio_usage(
    backfill: bool = False,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    client=None,
    conn=None,
) -> dict:
    """
    Pull daily usage from Twilio and store it.

    Args:
        backfill: If True, fetch everything since the account was created.
            Otherwise fetch the last lookback_days days.
        lookback_days: Trailing window for the regular daily sync.
        client: Twilio client (built from env vars if omitted).
        conn: psycopg2 connection (opened from DATABASE_URL if omitted).

    Returns:
        Summary dict with the date range, days fetched and rows stored.
    """
    import psycopg2

    client = client or _client()
    owns_conn = conn is None
    conn = conn or psycopg2.connect(os.environ["DATABASE_URL"])

    end = datetime.now(tz=UTC).date()
    start = account_created_on(client) if backfill else end - timedelta(days=lookback_days - 1)

    total_rows = 0
    try:
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(chunk_start + timedelta(days=BACKFILL_CHUNK_DAYS - 1), end)
            rows = fetch_daily_usage(client, chunk_start, chunk_end)
            store_daily_usage(conn, rows, chunk_start, chunk_end)
            print(f"  {chunk_start}..{chunk_end}: {len(rows)} usage rows")
            total_rows += len(rows)
            chunk_start = chunk_end + timedelta(days=1)
    finally:
        if owns_conn:
            conn.close()

    return {
        "status": "success",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": (end - start).days + 1,
        "rows": total_rows,
    }
