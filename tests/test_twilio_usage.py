"""Tests for Twilio usage sync and the twilio_cost.json day builder."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from utils.twilio_usage import fetch_daily_usage, store_daily_usage, sync_twilio_usage
from web.generate_data import build_twilio_cost_days


def _record(day, category, count="0", usage="0", price=0.0, description=None):
    return SimpleNamespace(
        start_date=day,
        category=category,
        description=description or category,
        count=count,
        count_unit="messages",
        usage=usage,
        usage_unit="segments",
        price=price,
        price_unit="usd",
    )


@pytest.mark.unit
class TestFetchDailyUsage:
    def test_drops_inactive_categories_and_parses_numbers(self):
        client = MagicMock()
        client.api.v2010.account.usage.records.daily.list.return_value = [
            _record(date(2026, 9, 1), "sms-inbound", count="12", usage="12", price=0.0996),
            _record(date(2026, 9, 1), "calls", count="0", usage="0", price=0.0),
        ]

        rows = fetch_daily_usage(client, date(2026, 9, 1), date(2026, 9, 1))

        assert [r["category"] for r in rows] == ["sms-inbound"]
        assert rows[0]["count"] == Decimal("12")
        assert rows[0]["price"] == Decimal("0.0996")
        assert rows[0]["usage_date"] == date(2026, 9, 1)


@pytest.mark.unit
class TestStoreDailyUsage:
    def test_replaces_the_fetched_window(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        row = {
            "usage_date": date(2026, 9, 1),
            "category": "sms-inbound",
            "description": "SMS inbound",
            "count": Decimal("1"),
            "count_unit": "messages",
            "usage": Decimal("1"),
            "usage_unit": "segments",
            "price": Decimal("0.0083"),
            "price_unit": "usd",
        }

        store_daily_usage(conn, [row], date(2026, 9, 1), date(2026, 9, 3))

        delete_sql, delete_params = cursor.execute.call_args_list[0].args
        assert delete_sql.startswith("DELETE FROM twilio_daily_usage")
        assert delete_params == (date(2026, 9, 1), date(2026, 9, 3))
        assert cursor.execute.call_args_list[1].args[1] is row
        conn.commit.assert_called_once()


@pytest.mark.unit
class TestSyncTwilioUsage:
    def test_backfill_chunks_from_account_creation(self, monkeypatch):
        import utils.twilio_usage as twilio_usage

        client = MagicMock()
        client.api.v2010.accounts.return_value.fetch.return_value.date_created.date.return_value = (
            date(2026, 8, 1)
        )
        windows = []
        monkeypatch.setattr(
            twilio_usage, "fetch_daily_usage", lambda _client, s, e: windows.append((s, e)) or []
        )
        monkeypatch.setattr(twilio_usage, "store_daily_usage", lambda *_args: None)

        result = sync_twilio_usage(backfill=True, client=client, conn=MagicMock())

        assert windows[0][0] == date(2026, 8, 1)
        assert all((e - s).days < twilio_usage.BACKFILL_CHUNK_DAYS for s, e in windows)
        for (_, prev_end), (next_start, _) in zip(windows, windows[1:], strict=False):
            assert (next_start - prev_end).days == 1
        assert result["start"] == "2026-08-01"


@pytest.mark.unit
class TestBuildTwilioCostDays:
    def test_totals_breakdown_messages_and_gap_days(self):
        usage_rows = [
            (date(2026, 9, 1), "totalprice", 0, Decimal("2.50")),
            (date(2026, 9, 1), "sms-inbound", 10, Decimal("0.08")),
            (date(2026, 9, 1), "sms-outbound", 12, Decimal("0.10")),
            (date(2026, 9, 1), "mms-inbound", 4, Decimal("0.04")),
            (date(2026, 9, 1), "phonenumbers", 1, Decimal("1.15")),
            (date(2026, 9, 3), "totalprice", 0, Decimal("0.30")),
        ]
        submissions = {date(2026, 9, 1): 5, date(2026, 9, 2): 3}

        days = build_twilio_cost_days(usage_rows, submissions, through=date(2026, 9, 3))

        assert [d["date"] for d in days] == ["2026-09-01", "2026-09-02", "2026-09-03"]
        first = days[0]
        assert first["total_price"] == 2.5
        assert first["submissions"] == 5
        assert first["messages"] == 26
        assert first["price_by_category"]["phonenumbers"] == 1.15
        assert first["price_by_category"]["other"] == pytest.approx(2.5 - 1.37)
        # A day with submissions but no Twilio usage still counts toward submissions.
        assert days[1] == {
            "date": "2026-09-02",
            "submissions": 3,
            "total_price": 0,
            "messages": 0,
            "price_by_category": dict.fromkeys(first["price_by_category"], 0),
        }

    def test_stops_at_through_date(self):
        usage_rows = [(date(2026, 9, 1), "totalprice", 0, Decimal("1"))]
        days = build_twilio_cost_days(usage_rows, {}, through=date(2026, 9, 1))
        assert len(days) == 1

    def test_no_usage_yields_no_days(self):
        assert build_twilio_cost_days([], {date(2026, 9, 1): 4}, through=date(2026, 9, 2)) == []
