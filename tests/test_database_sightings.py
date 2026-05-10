"""Database tests for sightings operations.

These tests require a PostgreSQL test database.
Set TEST_DATABASE_URL environment variable to run these tests.

Example:
    TEST_DATABASE_URL=postgresql://localhost/oceansofnyc_test pytest tests/test_database_sightings.py
"""

from datetime import datetime, timedelta

import pytest

from database.models import SightingsDatabase


@pytest.mark.db
class TestAddSighting:
    """Test add_sighting() method."""

    def test_add_sighting_basic(self, test_db_url, sample_contributor, temp_image):
        """Test adding a basic sighting."""
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T123456C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T123456C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
            borough="Manhattan",
        )

        assert result is not None
        assert result["id"] is not None

    def test_add_sighting_with_gps_auto_borough(self, test_db_url, sample_contributor, temp_image):
        """Test that borough is auto-populated from GPS coordinates."""
        db = SightingsDatabase(test_db_url)

        # Times Square coordinates
        result = db.add_sighting(
            license_plate="T234567C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T234567C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
            # No borough provided - should auto-detect
        )

        assert result is not None
        sighting = db.get_sighting_by_id(result["id"])
        # Borough should be detected as Manhattan from coordinates
        assert sighting["borough"] == "Manhattan"

    def test_add_sighting_with_image_filename(self, test_db_url, sample_contributor, temp_image):
        """Test adding sighting with image filename."""
        db = SightingsDatabase(test_db_url)
        image_timestamp = datetime.now()

        result = db.add_sighting(
            license_plate="T890123C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T890123C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
            image_timestamp=image_timestamp,
        )

        assert result is not None
        sighting = db.get_sighting_by_id(result["id"])
        assert sighting["image_filename"] == "T890123C_20251206_184123_0000.jpg"

    def test_add_sighting_without_gps(self, test_db_url, sample_contributor, temp_image):
        """Test adding sighting without GPS coordinates."""
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T901234C",
            timestamp=datetime.now(),
            latitude=None,
            longitude=None,
            image_filename="T901234C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
            borough="Brooklyn",  # Manually specified
        )

        assert result is not None
        sighting = db.get_sighting_by_id(result["id"])
        assert sighting["borough"] == "Brooklyn"


@pytest.mark.db
class TestSightingQueries:
    """Test sighting query methods."""

    def test_get_sighting_count(self, test_db_url, sample_contributor, temp_images):
        """Test counting sightings for a plate."""
        db = SightingsDatabase(test_db_url)

        # Add multiple sightings for same plate on different days
        base_date = datetime(2025, 12, 1)
        for i, img in enumerate(temp_images):
            db.add_sighting(
                license_plate="T111111C",
                timestamp=base_date + timedelta(days=i),
                latitude=40.7589,
                longitude=-73.9851,
                image_filename=f"T111111C_20251206_18412{i}_0000.jpg",
                contributor_id=sample_contributor,
            )

        count = db.get_sighting_count("T111111C")
        assert count == 3

    def test_get_unposted_sightings(self, test_db_url, sample_contributor, temp_image):
        """Test retrieving unposted sightings."""
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T222222C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T222222C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
        )

        # Get unposted sightings
        unposted = db.get_unposted_sightings()
        assert len(unposted) > 0

        # Find our sighting
        found = any(s[0] == result["id"] for s in unposted)
        assert found

    def test_mark_as_posted(self, test_db_url, sample_contributor, temp_image):
        """Test marking a sighting as posted."""
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T333333C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T333333C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
        )

        # Mark as posted
        post_uri = "at://did:plc:test/app.bsky.feed.post/abc123"
        db.mark_as_posted(result["id"], post_uri)

        # Verify it's no longer in unposted
        unposted = db.get_unposted_sightings()
        found = any(s[0] == result["id"] for s in unposted)
        assert not found


@pytest.mark.db
class TestContributorOperations:
    """Test contributor CRUD operations."""

    def test_get_or_create_contributor_new(self, test_db_url, clean_db):
        """Test creating a new contributor."""
        db = SightingsDatabase(test_db_url)

        contributor_id = db.get_or_create_contributor(
            phone_number="+15559998888",
            bluesky_handle="newuser.bsky.social",
        )

        assert contributor_id is not None
        contributor = db.get_contributor(contributor_id=contributor_id)
        assert contributor["phone_number"] == "+15559998888"

    def test_get_or_create_contributor_existing(self, test_db_url, sample_contributor):
        """Test getting an existing contributor."""
        db = SightingsDatabase(test_db_url)

        # Try to create with same phone number
        contributor_id = db.get_or_create_contributor(phone_number="+15551234567")

        # Should return existing ID
        assert contributor_id == sample_contributor

    def test_update_contributor_name(self, test_db_url, sample_contributor):
        """Test updating contributor preferred name."""
        db = SightingsDatabase(test_db_url)

        db.update_contributor_name(sample_contributor, "New Name")

        contributor = db.get_contributor(contributor_id=sample_contributor)
        assert contributor["preferred_name"] == "New Name"
