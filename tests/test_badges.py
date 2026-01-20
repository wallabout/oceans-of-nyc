"""Tests for the Bumper Stickers badges feature."""

from datetime import datetime, timedelta

import pytest


@pytest.fixture
def db_with_badges(test_db_url):
    """Provide a SightingsDatabase instance configured for testing."""
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping database test")

    from database import SightingsDatabase

    return SightingsDatabase(test_db_url)


@pytest.fixture
def contributor_with_sightings(clean_db, sample_tlc_vehicles):
    """Create a contributor with multiple sightings for badge testing."""
    cursor = clean_db.cursor()

    # Create contributor
    cursor.execute(
        """
        INSERT INTO contributors (phone_number, preferred_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("+15559876543", "Badge Tester"),
    )
    contributor_id = cursor.fetchone()[0]

    # Add sightings with various characteristics for badge testing
    sightings_data = [
        # (license_plate, borough, timestamp_offset_days)
        ("T123456C", "Brooklyn", 0),
        ("T234567C", "Manhattan", 1),
        ("T345678C", "Queens", 2),
        ("T123456C", "Brooklyn", 3),  # Second sighting of same vehicle
        ("T123456C", "Brooklyn", 4),  # Third sighting of same vehicle
    ]

    for plate, borough, days_ago in sightings_data:
        timestamp = datetime.now() - timedelta(days=days_ago)
        cursor.execute(
            """
            INSERT INTO sightings (
                license_plate, timestamp, borough, contributor_id,
                image_filename, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (plate, timestamp, borough, contributor_id, f"{plate}_test.jpg", timestamp),
        )

    clean_db.commit()

    return contributor_id


class TestBadgeDefinitions:
    """Test badge definition module."""

    def test_badge_definitions_exist(self):
        """Verify badge definitions are loaded correctly."""
        from badges.definitions import BADGE_BY_NAME, BADGE_DEFINITIONS

        assert len(BADGE_DEFINITIONS) > 0
        assert "ocean_spotter" in BADGE_BY_NAME
        assert "10_club" in BADGE_BY_NAME
        assert "5_boro" in BADGE_BY_NAME

    def test_badge_has_required_fields(self):
        """Verify each badge has all required fields."""
        from badges.definitions import BADGE_DEFINITIONS

        for badge in BADGE_DEFINITIONS:
            assert badge.name, "Badge missing name"
            assert badge.display_name, f"Badge {badge.name} missing display_name"
            assert badge.description, f"Badge {badge.name} missing description"
            assert badge.sql_check, f"Badge {badge.name} missing sql_check"

    def test_get_badge(self):
        """Test getting a badge by name."""
        from badges.definitions import get_badge

        badge = get_badge("ocean_spotter")
        assert badge is not None
        assert badge.name == "ocean_spotter"
        assert badge.display_name == "Ocean Spotter"

        # Test non-existent badge
        assert get_badge("nonexistent") is None

    def test_get_all_badge_names(self):
        """Test getting all badge names."""
        from badges.definitions import get_all_badge_names

        names = get_all_badge_names()
        assert "ocean_spotter" in names
        assert "5_club" in names
        assert "brooklyn" in names


class TestBadgeDatabaseMethods:
    """Test badge-related database methods."""

    @pytest.mark.db
    def test_get_contributor_badges_empty(self, db_with_badges, sample_contributor):
        """Test getting badges for contributor with no badges."""
        badges = db_with_badges.get_contributor_badges(sample_contributor)
        assert badges == []

    @pytest.mark.db
    def test_save_and_get_badge(self, db_with_badges, sample_contributor):
        """Test saving and retrieving a badge."""
        # Save badge
        result = db_with_badges.save_badge(sample_contributor, "ocean_spotter")
        assert result is True

        # Get badge
        badges = db_with_badges.get_contributor_badges(sample_contributor)
        assert len(badges) == 1
        assert badges[0]["badge_name"] == "ocean_spotter"
        assert badges[0]["earned_on"] is not None

    @pytest.mark.db
    def test_save_duplicate_badge(self, db_with_badges, sample_contributor):
        """Test that saving the same badge twice returns False."""
        # Save badge first time
        result1 = db_with_badges.save_badge(sample_contributor, "ocean_spotter")
        assert result1 is True

        # Save badge second time
        result2 = db_with_badges.save_badge(sample_contributor, "ocean_spotter")
        assert result2 is False

        # Should still only have one badge
        badges = db_with_badges.get_contributor_badges(sample_contributor)
        assert len(badges) == 1

    @pytest.mark.db
    def test_save_multiple_badges(self, db_with_badges, sample_contributor):
        """Test saving multiple badges at once."""
        badge_names = ["ocean_spotter", "brooklyn", "5_club"]

        count = db_with_badges.save_badges(sample_contributor, badge_names)
        assert count == 3

        badges = db_with_badges.get_contributor_badges(sample_contributor)
        assert len(badges) == 3

        badge_names_saved = [b["badge_name"] for b in badges]
        assert "ocean_spotter" in badge_names_saved
        assert "brooklyn" in badge_names_saved
        assert "5_club" in badge_names_saved

    @pytest.mark.db
    def test_get_contributor_badge_names(self, db_with_badges, sample_contributor):
        """Test getting just the badge names."""
        db_with_badges.save_badges(sample_contributor, ["ocean_spotter", "brooklyn"])

        names = db_with_badges.get_contributor_badge_names(sample_contributor)
        assert "ocean_spotter" in names
        assert "brooklyn" in names
        assert len(names) == 2


class TestBadgeEvaluator:
    """Test badge evaluation logic."""

    @pytest.mark.db
    def test_evaluate_single_badge_ocean_spotter(self, db_with_badges, contributor_with_sightings):
        """Test evaluating the Ocean Spotter badge."""
        from badges.definitions import get_badge
        from badges.evaluator import evaluate_single_badge

        badge = get_badge("ocean_spotter")
        conn = db_with_badges._get_connection()

        result = evaluate_single_badge(conn, contributor_with_sightings, badge)
        conn.close()

        assert result is True

    @pytest.mark.db
    def test_evaluate_single_badge_5_club(self, db_with_badges, contributor_with_sightings):
        """Test evaluating the 5 Club badge (should have 5 sightings)."""
        from badges.definitions import get_badge
        from badges.evaluator import evaluate_single_badge

        badge = get_badge("5_club")
        conn = db_with_badges._get_connection()

        result = evaluate_single_badge(conn, contributor_with_sightings, badge)
        conn.close()

        assert result is True  # We created 5 sightings

    @pytest.mark.db
    def test_evaluate_single_badge_10_club_fails(self, db_with_badges, contributor_with_sightings):
        """Test that 10 Club badge fails with only 5 sightings."""
        from badges.definitions import get_badge
        from badges.evaluator import evaluate_single_badge

        badge = get_badge("10_club")
        conn = db_with_badges._get_connection()

        result = evaluate_single_badge(conn, contributor_with_sightings, badge)
        conn.close()

        assert result is False  # Only 5 sightings

    @pytest.mark.db
    def test_evaluate_badges_for_contributor(self, db_with_badges, contributor_with_sightings):
        """Test evaluating all badges for a contributor."""
        from badges.evaluator import evaluate_badges_for_contributor

        new_badges = evaluate_badges_for_contributor(db_with_badges, contributor_with_sightings)

        # Should earn several badges
        assert "ocean_spotter" in new_badges
        assert "5_club" in new_badges
        assert "brooklyn" in new_badges
        assert "manhattan" in new_badges
        assert "queens" in new_badges
        assert "seconds" in new_badges  # Has multiple sightings of same vehicle

        # Should NOT earn these
        assert "10_club" not in new_badges
        assert "5_boro" not in new_badges  # Only 3 boroughs

    @pytest.mark.db
    def test_evaluate_badges_excludes_existing(self, db_with_badges, contributor_with_sightings):
        """Test that existing badges are not returned."""
        from badges.evaluator import evaluate_badges_for_contributor

        # Save a badge first
        db_with_badges.save_badge(contributor_with_sightings, "ocean_spotter")

        # Evaluate again
        new_badges = evaluate_badges_for_contributor(db_with_badges, contributor_with_sightings)

        # ocean_spotter should not be in the new badges list
        assert "ocean_spotter" not in new_badges

        # But other badges should still be there
        assert "5_club" in new_badges

    @pytest.mark.db
    def test_evaluate_all_badges_for_backfill(self, db_with_badges, contributor_with_sightings):
        """Test evaluating all badges for backfill (ignores existing)."""
        from badges.evaluator import evaluate_all_badges_for_contributor

        # Even if we save a badge first
        db_with_badges.save_badge(contributor_with_sightings, "ocean_spotter")

        # evaluate_all_badges should still return it
        all_badges = evaluate_all_badges_for_contributor(db_with_badges, contributor_with_sightings)

        assert "ocean_spotter" in all_badges
        assert "5_club" in all_badges


class TestLocationBadges:
    """Test location-based badge evaluation."""

    @pytest.fixture
    def contributor_all_boroughs(self, clean_db, sample_tlc_vehicles):
        """Create a contributor with sightings in all 5 boroughs."""
        cursor = clean_db.cursor()

        # Create contributor
        cursor.execute(
            """
            INSERT INTO contributors (phone_number, preferred_name)
            VALUES (%s, %s)
            RETURNING id
            """,
            ("+15551111111", "5 Boro Tester"),
        )
        contributor_id = cursor.fetchone()[0]

        # Add sightings in each borough
        boroughs = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
        for i, borough in enumerate(boroughs):
            cursor.execute(
                """
                INSERT INTO sightings (
                    license_plate, timestamp, borough, contributor_id,
                    image_filename, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    "T123456C",
                    datetime.now() - timedelta(days=i),
                    borough,
                    contributor_id,
                    f"boro_{borough.lower()}.jpg",
                    datetime.now(),
                ),
            )

        clean_db.commit()
        return contributor_id

    @pytest.mark.db
    def test_5_boro_badge(self, db_with_badges, contributor_all_boroughs):
        """Test that 5 Boro badge is earned with sightings in all boroughs."""
        from badges.evaluator import evaluate_badges_for_contributor

        new_badges = evaluate_badges_for_contributor(db_with_badges, contributor_all_boroughs)

        assert "5_boro" in new_badges
        assert "manhattan" in new_badges
        assert "brooklyn" in new_badges
        assert "queens" in new_badges
        assert "bronx" in new_badges
        assert "staten_island" in new_badges


class TestSMSBadgeMessage:
    """Test SMS message formatting with badges."""

    def test_sighting_confirmed_with_single_badge(self):
        """Test confirmation message with one badge."""
        from chat.messages import sighting_confirmed

        badges = [
            {
                "name": "ocean_spotter",
                "display_name": "Ocean Spotter",
                "description": "Submitted your first sighting",
                "emoji": "🌊",
            }
        ]

        msg = sighting_confirmed("T123456C", 1, 100, 1, badges)

        assert "NEW BUMPER STICKER:" in msg
        assert "Ocean Spotter" in msg
        assert "Submitted your first sighting" in msg

    def test_sighting_confirmed_with_multiple_badges(self):
        """Test confirmation message with multiple badges."""
        from chat.messages import sighting_confirmed

        badges = [
            {"name": "ocean_spotter", "display_name": "Ocean Spotter", "emoji": "🌊"},
            {"name": "brooklyn", "display_name": "Brooklyn", "emoji": "🌉"},
        ]

        msg = sighting_confirmed("T123456C", 1, 100, 1, badges)

        assert "NEW BUMPER STICKERS:" in msg
        assert "Ocean Spotter" in msg
        assert "Brooklyn" in msg

    def test_sighting_confirmed_without_badges(self):
        """Test confirmation message without badges."""
        from chat.messages import sighting_confirmed

        msg = sighting_confirmed("T123456C", 1, 100, 1, None)

        assert "NEW BUMPER STICKER" not in msg
        assert "License plate validated" in msg

    def test_sighting_confirmed_with_empty_badges(self):
        """Test confirmation message with empty badges list."""
        from chat.messages import sighting_confirmed

        msg = sighting_confirmed("T123456C", 1, 100, 1, [])

        assert "NEW BUMPER STICKER" not in msg


class TestWebhookBadgeIntegration:
    """Test badge integration in webhook flow."""

    def test_evaluate_and_save_badges_helper(self, db_with_badges, contributor_with_sightings):
        """Test the webhook helper function for badge evaluation."""
        from chat.webhook import evaluate_and_save_badges

        # First call should return badges
        badges = evaluate_and_save_badges(db_with_badges, contributor_with_sightings)

        assert len(badges) > 0
        assert any(b["name"] == "ocean_spotter" for b in badges)

        # Verify badges have display info
        for badge in badges:
            assert "name" in badge
            assert "display_name" in badge
            assert "description" in badge
            assert "emoji" in badge

        # Second call should return empty (badges already saved)
        badges2 = evaluate_and_save_badges(db_with_badges, contributor_with_sightings)
        assert len(badges2) == 0
