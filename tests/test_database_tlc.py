"""Database tests for TLC vehicle validation.

These tests require a PostgreSQL test database.
Set TEST_DATABASE_URL environment variable to run these tests.
"""

import pytest

from validate.tlc import TLCDatabase, validate_plate


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
