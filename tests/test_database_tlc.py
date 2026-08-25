"""Database tests for TLC vehicle validation.

These tests require a PostgreSQL test database.
Set TEST_DATABASE_URL environment variable to run these tests.
"""

import pytest

from validate.tlc import TLCDatabase, validate_plate, validate_plate_candidates


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

    def test_filter_fisker_vehicles(self, test_db_url, clean_db):
        """Test filtering to only Fisker vehicles."""
        tlc = TLCDatabase(test_db_url)
        cursor = tlc._get_connection().cursor()

        # Also populate tlc_vehicles
        cursor.execute(
            """
            INSERT INTO tlc_vehicles (vin, license_plate, first_reported_on, most_recently_reported_on)
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

    def test_validate_plate_non_conforming(self, test_db_url, sample_tlc_vehicles):
        """A plate in the database is valid even if it isn't in T######C format."""
        is_valid, vehicle = validate_plate("NO1BOSS", test_db_url)

        assert is_valid is True
        assert vehicle is not None


@pytest.mark.db
class TestGetVehiclesByPlates:
    """Test batched plate lookups."""

    def test_returns_only_plates_in_registry(self, test_db_url, sample_tlc_vehicles):
        """Unknown plates are absent from the result, known ones are keyed by plate."""
        tlc = TLCDatabase(test_db_url)

        vehicles = tlc.get_vehicles_by_plates(["T123456C", "NO1BOSS", "T999999C"])

        assert set(vehicles) == {"T123456C", "NO1BOSS"}
        assert vehicles["T123456C"]["vin"] == "VCF1ABCD123456789"

    def test_empty_input(self, test_db_url, clean_db):
        """No candidates means no query and no results."""
        tlc = TLCDatabase(test_db_url)

        assert tlc.get_vehicles_by_plates([]) == {}


@pytest.mark.db
class TestValidatePlateCandidates:
    """Test candidate-based validation, where the database is the authority."""

    def test_first_matching_candidate_wins(self, test_db_url, sample_tlc_vehicles):
        """Candidates are tried in order, so the best guess is preferred."""
        plate, vehicle = validate_plate_candidates(
            ["T999999C", "T123456C", "T234567C"], test_db_url
        )

        assert plate == "T123456C"
        assert vehicle["vin"] == "VCF1ABCD123456789"

    def test_non_conforming_candidate(self, test_db_url, sample_tlc_vehicles):
        """A non-conforming plate validates when it's in the registry."""
        plate, vehicle = validate_plate_candidates(["NO1BOSS"], test_db_url)

        assert plate == "NO1BOSS"
        assert vehicle is not None

    def test_candidates_are_normalized(self, test_db_url, sample_tlc_vehicles):
        """Candidates are upper-cased and de-duplicated before lookup."""
        plate, _ = validate_plate_candidates([" no1boss ", "NO1BOSS", ""], test_db_url)

        assert plate == "NO1BOSS"

    def test_no_matching_candidate(self, test_db_url, sample_tlc_vehicles):
        """Nothing in the registry means no plate."""
        plate, vehicle = validate_plate_candidates(["T999999C", "NOTAPLATE"], test_db_url)

        assert plate is None
        assert vehicle is None

    def test_no_candidates(self, test_db_url, clean_db):
        """An empty candidate list short-circuits."""
        plate, vehicle = validate_plate_candidates([], test_db_url)

        assert plate is None
        assert vehicle is None
