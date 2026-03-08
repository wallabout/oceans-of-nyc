"""Tests for batch posting trigger logic."""

from datetime import datetime, timedelta

from post.batch_trigger import get_batch_post_stats, should_trigger_batch_post


def create_mock_sighting(hours_ago: float = 0) -> tuple:
    """Create a mock sighting tuple for testing.

    Schema matches get_unposted_sightings() return format:
    (id, license_plate, created_at, latitude, longitude, image_filename, borough, created_at,
     post_uri, contributor_id, preferred_name, bluesky_handle, phone_number)
    """
    created_at = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    return (
        1,  # id
        "T123456C",  # license_plate
        created_at,  # created_at (index 2)
        None,  # latitude
        None,  # longitude
        "T123456C_20251206_184123_0000.jpg",  # image_filename
        "Manhattan",  # borough (index 6)
        created_at,  # created_at (index 7)
        None,  # post_uri
        1,  # contributor_id
        "Test User",  # preferred_name
        None,  # bluesky_handle
        None,  # phone_number
    )


class TestShouldTriggerBatchPost:
    """Tests for should_trigger_batch_post function."""

    def test_empty_list_returns_false(self):
        """Should return False when there are no unposted sightings."""
        assert should_trigger_batch_post([]) is False

    def test_four_sightings_triggers(self):
        """Should return True when there are exactly 4 sightings waiting."""
        sightings = [create_mock_sighting(hours_ago=1) for _ in range(4)]
        assert should_trigger_batch_post(sightings) is True

    def test_five_sightings_triggers(self):
        """Should return True when there are more than 4 sightings waiting."""
        sightings = [create_mock_sighting(hours_ago=1) for _ in range(5)]
        assert should_trigger_batch_post(sightings) is True

    def test_three_sightings_recent_does_not_trigger(self):
        """Should return False when there are only 3 recent sightings."""
        sightings = [create_mock_sighting(hours_ago=1) for _ in range(3)]
        assert should_trigger_batch_post(sightings) is False

    def test_one_sighting_24_hours_old_triggers(self):
        """Should return True when oldest sighting is exactly 24 hours old."""
        sightings = [create_mock_sighting(hours_ago=24)]
        assert should_trigger_batch_post(sightings) is True

    def test_one_sighting_25_hours_old_triggers(self):
        """Should return True when oldest sighting is more than 24 hours old."""
        sightings = [create_mock_sighting(hours_ago=25)]
        assert should_trigger_batch_post(sightings) is True

    def test_one_sighting_23_hours_old_does_not_trigger(self):
        """Should return False when oldest sighting is less than 24 hours old."""
        sightings = [create_mock_sighting(hours_ago=23)]
        assert should_trigger_batch_post(sightings) is False

    def test_multiple_sightings_oldest_matters(self):
        """Should check oldest sighting when there are multiple."""
        # Newest sighting is 1 hour old, oldest is 25 hours old
        sightings = [
            create_mock_sighting(hours_ago=25),  # Oldest
            create_mock_sighting(hours_ago=10),
            create_mock_sighting(hours_ago=1),  # Newest
        ]
        assert should_trigger_batch_post(sightings) is True

    def test_datetime_object_created_at(self):
        """Should handle created_at as datetime object (not just string)."""
        # Create a sighting with datetime object instead of string
        created_at = datetime.now() - timedelta(hours=25)
        sighting = list(create_mock_sighting(hours_ago=1))
        sighting[7] = created_at  # Replace created_at with datetime object
        sightings = [tuple(sighting)]
        assert should_trigger_batch_post(sightings) is True


class TestGetBatchPostStats:
    """Tests for get_batch_post_stats function."""

    def test_empty_list_returns_zeros(self):
        """Should return appropriate values for empty list."""
        stats = get_batch_post_stats([])
        assert stats["count"] == 0
        assert stats["oldest_hours"] is None
        assert stats["should_post"] is False

    def test_returns_correct_count(self):
        """Should return correct count of sightings."""
        sightings = [create_mock_sighting(hours_ago=1) for _ in range(3)]
        stats = get_batch_post_stats(sightings)
        assert stats["count"] == 3

    def test_calculates_oldest_hours(self):
        """Should calculate hours for oldest sighting."""
        sightings = [create_mock_sighting(hours_ago=25)]
        stats = get_batch_post_stats(sightings)
        assert stats["oldest_hours"] is not None
        assert stats["oldest_hours"] >= 24.9  # Account for test execution time
        assert stats["oldest_hours"] <= 25.1

    def test_should_post_reflects_trigger_logic(self):
        """Should_post should match should_trigger_batch_post result."""
        # Test with 4 sightings (should trigger)
        sightings = [create_mock_sighting(hours_ago=1) for _ in range(4)]
        stats = get_batch_post_stats(sightings)
        assert stats["should_post"] is True

        # Test with 3 recent sightings (should not trigger)
        sightings = [create_mock_sighting(hours_ago=1) for _ in range(3)]
        stats = get_batch_post_stats(sightings)
        assert stats["should_post"] is False

        # Test with 1 old sighting (should trigger)
        sightings = [create_mock_sighting(hours_ago=25)]
        stats = get_batch_post_stats(sightings)
        assert stats["should_post"] is True
