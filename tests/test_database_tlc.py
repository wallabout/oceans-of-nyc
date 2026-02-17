"""Database tests for TLC vehicle validation.

These tests require a PostgreSQL test database.
Set TEST_DATABASE_URL environment variable to run these tests.
"""

import pytest

from validate.matcher import find_similar_plates, get_potential_matches, validate_plate
from validate.tlc import TLCDatabase


@pytest.mark.db
class TestTLCDatabase:
    """Test TLC database operations."""

    def test_get_vehicle_by_plate(self, test_db_url, sample_tlc_vehicles):
        """Test retrieving vehicle by license plate."""
        tlc = TLCDatabase(test_db_url)

        vehicle = tlc.get_vehicle_by_plate("T123456C")

        assert vehicle is not None
        # Check VIN is correct (column index depends on schema)
        assert "VCF1ABCD123456789" in str(vehicle)

    def test_get_vehicle_by_plate_not_found(self, test_db_url, clean_db):
        """Test retrieving non-existent vehicle."""
        tlc = TLCDatabase(test_db_url)

        vehicle = tlc.get_vehicle_by_plate("T999999C")

        assert vehicle is None

    def test_get_vehicle_count(self, test_db_url, sample_tlc_vehicles):
        """Test counting TLC vehicles."""
        tlc = TLCDatabase(test_db_url)

        count = tlc.get_vehicle_count()

        assert count == 3  # From sample_tlc_vehicles fixture

    def test_get_vehicle_count_empty(self, test_db_url, clean_db):
        """Test counting with no vehicles."""
        tlc = TLCDatabase(test_db_url)

        count = tlc.get_vehicle_count()

        assert count == 0

    def test_get_all_plates(self, test_db_url, sample_tlc_vehicles):
        """Test getting all license plates."""
        tlc = TLCDatabase(test_db_url)

        plates = tlc.get_all_plates()

        assert len(plates) == 3
        assert "T123456C" in plates
        assert "T234567C" in plates
        assert "T345678C" in plates

    def test_get_all_plates_sorted(self, test_db_url, sample_tlc_vehicles):
        """Test that plates are returned in sorted order."""
        tlc = TLCDatabase(test_db_url)

        plates = tlc.get_all_plates()

        assert plates == sorted(plates)

    def test_search_plates_wildcard_exact(self, test_db_url, sample_tlc_vehicles):
        """Test wildcard search with exact match."""
        tlc = TLCDatabase(test_db_url)

        results = tlc.search_plates_wildcard("T123456C")

        assert len(results) == 1
        assert results[0][0] == "T123456C"

    def test_search_plates_wildcard_pattern(self, test_db_url, sample_tlc_vehicles):
        """Test wildcard search with pattern."""
        tlc = TLCDatabase(test_db_url)

        # Search for T*23456C (should match T123456C and T223456C if it existed)
        results = tlc.search_plates_wildcard("T*23456C")

        assert len(results) == 1
        assert results[0][0] == "T123456C"

    def test_search_plates_wildcard_multiple_wildcards(self, test_db_url, sample_tlc_vehicles):
        """Test wildcard search with multiple wildcards."""
        tlc = TLCDatabase(test_db_url)

        # Search for T*****C (should match all T plates ending in C)
        results = tlc.search_plates_wildcard("T******C")

        assert len(results) == 3

    def test_search_plates_wildcard_no_match(self, test_db_url, sample_tlc_vehicles):
        """Test wildcard search with no matches."""
        tlc = TLCDatabase(test_db_url)

        results = tlc.search_plates_wildcard("Z******Z")

        assert len(results) == 0

    def test_filter_fisker_vehicles(self, test_db_url, clean_db):
        """Test filtering to only Fisker vehicles."""
        tlc = TLCDatabase(test_db_url)
        cursor = tlc._get_connection().cursor()

        # Add mix of Fisker and non-Fisker vehicles
        cursor.execute(
            """
            INSERT INTO tlc_vehicles (dmv_license_plate_number, vehicle_vin_number, vehicle_year)
            VALUES
                ('T111111C', 'VCF1FISKER111', 2023),
                ('T222222C', 'NOTAFISKER22', 2023),
                ('T333333C', 'VCF1FISKER333', 2023)
        """
        )
        # Also populate tlc_vehicles_minimal
        cursor.execute(
            """
            INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
            VALUES
                ('VCF1FISKER111', 'T111111C', '2023-01-01', '2023-01-01'),
                ('NOTAFISKER22', 'T222222C', '2023-01-01', '2023-01-01'),
                ('VCF1FISKER333', 'T333333C', '2023-01-01', '2023-01-01')
            ON CONFLICT (vin, license_plate) DO NOTHING
        """
        )
        cursor.connection.commit()
        cursor.close()

        # Filter to only Fisker
        fisker_count = tlc.filter_fisker_vehicles()

        assert fisker_count == 2

        # Verify only Fisker remain
        all_plates = tlc.get_all_plates()
        assert "T111111C" in all_plates
        assert "T222222C" not in all_plates
        assert "T333333C" in all_plates


@pytest.mark.db
class TestValidatePlate:
    """Test plate validation functions."""

    def test_validate_plate_valid(self, test_db_url, sample_tlc_vehicles):
        """Test validating a valid plate."""
        is_valid, vehicle = validate_plate("T123456C", test_db_url)

        assert is_valid is True
        assert vehicle is not None

    def test_validate_plate_invalid(self, test_db_url, clean_db):
        """Test validating an invalid plate."""
        is_valid, vehicle = validate_plate("T999999C", test_db_url)

        assert is_valid is False
        assert vehicle is None

    def test_get_potential_matches_wildcard(self, test_db_url, sample_tlc_vehicles):
        """Test getting potential matches with wildcard."""
        matches = get_potential_matches("T*23456C", test_db_url, max_results=10)

        assert "T123456C" in matches

    def test_get_potential_matches_multiple_wildcards(self, test_db_url, sample_tlc_vehicles):
        """Test getting matches with multiple wildcards."""
        matches = get_potential_matches("T******C", test_db_url, max_results=10)

        assert len(matches) >= 3

    def test_get_potential_matches_max_results(self, test_db_url, sample_tlc_vehicles):
        """Test max_results limiting."""
        matches = get_potential_matches("T******C", test_db_url, max_results=2)

        assert len(matches) <= 2

    def test_get_potential_matches_no_matches(self, test_db_url, clean_db):
        """Test when no matches found."""
        matches = get_potential_matches("Z******Z", test_db_url, max_results=10)

        assert len(matches) == 0


@pytest.mark.db
class TestFindSimilarPlates:
    """Test finding similar plates (typo correction)."""

    def test_find_similar_plates_one_char_diff(self, test_db_url, sample_tlc_vehicles):
        """Test finding plates with one character difference."""
        # T123456C exists, test with T123457C (last digit different)
        similar = find_similar_plates("T123457C", test_db_url, max_results=5)

        assert "T123456C" in similar

    def test_find_similar_plates_two_char_diff(self, test_db_url, sample_tlc_vehicles):
        """Test finding plates with two character differences."""
        # T123456C exists, test with T123457D (last two chars different)
        similar = find_similar_plates("T123457D", test_db_url, max_results=5)

        # Should find T123456C since it differs by 2 characters
        assert "T123456C" in similar

    def test_find_similar_plates_exact_match_excluded(self, test_db_url, sample_tlc_vehicles):
        """Test that exact matches are excluded from similar results."""
        # T123456C exists exactly
        similar = find_similar_plates("T123456C", test_db_url, max_results=5)

        # Exact match should not be in "similar" results
        # (similar plates have diff_count > 0)
        assert "T123456C" not in similar

    def test_find_similar_plates_too_different(self, test_db_url, sample_tlc_vehicles):
        """Test that plates differing by >2 chars are not found."""
        # T123456C exists, test with completely different plate
        similar = find_similar_plates("T999999C", test_db_url, max_results=5)

        # Should not find T123456C (differs by 6 characters)
        assert "T123456C" not in similar

    def test_find_similar_plates_sorted_by_similarity(self, test_db_url, clean_db):
        """Test that results are sorted by similarity (fewest differences first)."""
        tlc = TLCDatabase(test_db_url)
        cursor = tlc._get_connection().cursor()

        # Add plates with varying similarity
        cursor.execute(
            """
            INSERT INTO tlc_vehicles (dmv_license_plate_number, vehicle_vin_number, vehicle_year)
            VALUES
                ('T111111C', 'VCF1TEST1', 2023),
                ('T111112C', 'VCF1TEST2', 2023),
                ('T111122C', 'VCF1TEST3', 2023)
        """
        )
        # Also populate tlc_vehicles_minimal
        cursor.execute(
            """
            INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
            VALUES
                ('VCF1TEST1', 'T111111C', '2023-01-01', '2023-01-01'),
                ('VCF1TEST2', 'T111112C', '2023-01-01', '2023-01-01'),
                ('VCF1TEST3', 'T111122C', '2023-01-01', '2023-01-01')
            ON CONFLICT (vin, license_plate) DO NOTHING
        """
        )
        cursor.connection.commit()
        cursor.close()

        # Search for T111113C
        similar = find_similar_plates("T111113C", test_db_url, max_results=5)

        # T111111C differs by 1 (pos 7: 1→3), T111112C differs by 1 (pos 7: 2→3)
        # T111122C differs by 2 (pos 6: 2→1, pos 7: 2→3)
        # Both T111111C and T111112C have 1 diff, alphabetically T111111C comes first
        assert similar[0] == "T111111C"
        # T111122C should be last (2 diffs)
        assert similar[-1] == "T111122C"

    def test_find_similar_plates_max_results(self, test_db_url, clean_db):
        """Test max_results limiting."""
        tlc = TLCDatabase(test_db_url)
        cursor = tlc._get_connection().cursor()

        # Add many similar plates
        for i in range(10):
            cursor.execute(
                """
                INSERT INTO tlc_vehicles (dmv_license_plate_number, vehicle_vin_number, vehicle_year)
                VALUES (%s, %s, 2023)
            """,
                (f"T11111{i}C", f"VCF1TEST{i}"),
            )
            # Also populate tlc_vehicles_minimal
            cursor.execute(
                """
                INSERT INTO tlc_vehicles_minimal (vin, license_plate, first_reported_on, most_recently_reported_on)
                VALUES (%s, %s, '2023-01-01', '2023-01-01')
                ON CONFLICT (vin, license_plate) DO NOTHING
            """,
                (f"VCF1TEST{i}", f"T11111{i}C"),
            )
        cursor.connection.commit()
        cursor.close()

        # Search with max_results=3
        similar = find_similar_plates("T111119C", test_db_url, max_results=3)

        assert len(similar) <= 3

    def test_find_similar_plates_different_length(self, test_db_url, sample_tlc_vehicles):
        """Test that plates of different length are not matched."""
        # Search with shorter plate
        similar = find_similar_plates("T12345C", test_db_url, max_results=5)

        # Should not find T123456C (different length)
        assert "T123456C" not in similar

    def test_find_similar_plates_case_insensitive(self, test_db_url, sample_tlc_vehicles):
        """Test that matching is case insensitive."""
        # T123456C exists, search with different case
        similar = find_similar_plates("t123457c", test_db_url, max_results=5)

        # Should find T123456C regardless of case
        assert "T123456C" in similar
