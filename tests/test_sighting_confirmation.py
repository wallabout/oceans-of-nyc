"""Tests for vehicle history in sighting confirmations."""

from unittest.mock import MagicMock, patch

import pytest

from utils.sighting_confirmation import format_duration, get_confirmation_data

HOUR = 3600
DAY = 24 * HOUR


@pytest.mark.unit
class TestFormatDuration:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "less than an hour"),
            (59 * 60, "less than an hour"),
            (HOUR, "1 hour"),
            (5 * HOUR, "5 hours"),
            (47 * HOUR, "47 hours"),
            (2 * DAY, "2 days"),
            (59 * DAY, "59 days"),
            (60 * DAY, "2 months"),
            (365 * DAY, "12 months"),
            (729 * DAY, "24 months"),
            (730 * DAY, "2 years"),
            (-5, "less than an hour"),
        ],
    )
    def test_formats(self, seconds, expected):
        assert format_duration(seconds) == expected

    def test_date_only_skips_hours(self):
        assert format_duration(0, hours=False) == "less than a day"
        assert format_duration(DAY, hours=False) == "1 day"
        assert format_duration(30 * DAY, hours=False) == "30 days"


def _mock_db(history):
    db = MagicMock()
    db.get_sighting_count_by_vin.return_value = 3
    db.get_total_sighting_count.return_value = 500
    db.get_contributor_sighting_count.return_value = 10
    db.get_sighting_export_data.return_value = None
    db.get_vehicle_history.return_value = history
    return db


@pytest.mark.unit
@patch("utils.sighting_confirmation.evaluate_and_save_badges", return_value=[])
class TestVehicleHistory:
    def test_repeat_sighting(self, _badges):
        db = _mock_db({"first_sighted_seconds_ago": 3 * DAY, "introduced_days_ago": 250})

        conf = get_confirmation_data(db, "T123456C", 42, vin="VIN1", sighting_id=7)

        db.get_vehicle_history.assert_called_once_with("VIN1", exclude_sighting_id=7)
        assert conf["vehicle_first_sighted_ago"] == "3 days"
        assert conf["vehicle_introduced_ago"] == "8 months"

    def test_first_sighting(self, _badges):
        db = _mock_db({"first_sighted_seconds_ago": None, "introduced_days_ago": 40})

        conf = get_confirmation_data(db, "T123456C", 42, vin="VIN1", sighting_id=7)

        assert conf["vehicle_first_sighted_ago"] is None
        assert conf["vehicle_introduced_ago"] == "40 days"

    def test_no_vin(self, _badges):
        db = _mock_db(None)
        db.get_sighting_count.return_value = 1

        conf = get_confirmation_data(db, "T123456C", 42, vin=None, sighting_id=7)

        db.get_vehicle_history.assert_not_called()
        assert conf["vehicle_first_sighted_ago"] is None
        assert conf["vehicle_introduced_ago"] is None

    def test_history_failure_does_not_break_confirmation(self, _badges):
        db = _mock_db(None)
        db.get_vehicle_history.side_effect = RuntimeError("db down")

        conf = get_confirmation_data(db, "T123456C", 42, vin="VIN1", sighting_id=7)

        assert conf["vehicle_sighting_num"] == 3
        assert conf["vehicle_first_sighted_ago"] is None
