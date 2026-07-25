"""Database tests for sightings operations.

These tests require a PostgreSQL test database.
Set TEST_DATABASE_URL environment variable to run these tests.

Example:
    TEST_DATABASE_URL=postgresql://localhost/oceansofnyc_test pytest tests/test_database_sightings.py
"""

from datetime import datetime

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

        # Add multiple sightings for same plate
        for i, _img in enumerate(temp_images):
            db.add_sighting(
                license_plate="T111111C",
                timestamp=datetime.now(),
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
class TestPostingLock:
    """Test the advisory lock that serializes Bluesky batch posting."""

    def test_second_acquire_is_refused_while_held(self, test_db_url):
        """A second worker cannot acquire the posting lock while the first holds it."""
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set - skipping database test")
        db = SightingsDatabase(test_db_url)

        conn_a = db.acquire_posting_lock()
        assert conn_a is not None, "first acquire should succeed"

        try:
            # A concurrent worker (separate session) must be refused.
            conn_b = db.acquire_posting_lock()
            assert conn_b is None, "second acquire must be refused while lock is held"
        finally:
            db.release_posting_lock(conn_a)

    def test_lock_is_reacquirable_after_release(self, test_db_url):
        """Once released, the lock can be acquired again."""
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set - skipping database test")
        db = SightingsDatabase(test_db_url)

        conn_a = db.acquire_posting_lock()
        assert conn_a is not None
        db.release_posting_lock(conn_a)

        conn_b = db.acquire_posting_lock()
        assert conn_b is not None, "lock should be free after release"
        db.release_posting_lock(conn_b)


@pytest.mark.db
class TestClaimSightingsForPosting:
    """Test the atomic claim that guards against duplicate Bluesky posts.

    Unlike the advisory lock, this claim is a plain UPDATE ... RETURNING, so it
    stays exclusive even when the caller's connections don't share a session
    (e.g. behind a transaction-pooled connection string).
    """

    def test_second_claim_on_same_ids_gets_nothing(
        self, test_db_url, sample_contributor, temp_image
    ):
        """A sighting already claimed can't be claimed again while the claim is fresh."""
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set - skipping database test")
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T444444C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T444444C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
        )
        sighting_id = result["id"]

        first = db.claim_sightings_for_posting([sighting_id])
        assert first == [sighting_id]

        second = db.claim_sightings_for_posting([sighting_id])
        assert second == [], "a fresh claim must not be granted twice"

    def test_claim_is_reusable_after_release(self, test_db_url, sample_contributor, temp_image):
        """Releasing a claim (e.g. after a failed post) lets it be claimed again."""
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set - skipping database test")
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T555555C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T555555C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
        )
        sighting_id = result["id"]

        db.claim_sightings_for_posting([sighting_id])
        db.release_sighting_claims([sighting_id])

        reclaimed = db.claim_sightings_for_posting([sighting_id])
        assert reclaimed == [sighting_id]

    def test_claim_excludes_already_posted_sighting(
        self, test_db_url, sample_contributor, temp_image
    ):
        """A sighting that already has a post_uri can never be (re-)claimed."""
        if not test_db_url:
            pytest.skip("TEST_DATABASE_URL not set - skipping database test")
        db = SightingsDatabase(test_db_url)

        result = db.add_sighting(
            license_plate="T666666C",
            timestamp=datetime.now(),
            latitude=40.7589,
            longitude=-73.9851,
            image_filename="T666666C_20251206_184123_0000.jpg",
            contributor_id=sample_contributor,
        )
        sighting_id = result["id"]
        db.mark_as_posted(sighting_id, "at://did:plc:test/app.bsky.feed.post/xyz789")

        claimed = db.claim_sightings_for_posting([sighting_id])
        assert claimed == []


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
