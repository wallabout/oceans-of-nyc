"""Pytest configuration and fixtures for all tests."""

import os
import tempfile
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==================== Test Database Fixtures ====================


@pytest.fixture(scope="session")
def test_db_url():
    """
    Get test database URL from environment.

    Set TEST_DATABASE_URL environment variable to run database tests.
    If not set, database tests will be skipped.
    """
    return os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def apply_migrations(test_db_url):
    """
    Apply all database migrations to the test database once per test session.

    This ensures the test database schema is up to date with all migrations.
    """
    if not test_db_url:
        return

    from pathlib import Path

    import psycopg2

    migrations_dir = Path(__file__).parent.parent / "database" / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    conn = psycopg2.connect(test_db_url)
    cursor = conn.cursor()

    for migration_file in migration_files:
        with open(migration_file) as f:
            migration_sql = f.read()
        try:
            cursor.execute(migration_sql)
            conn.commit()
        except Exception:
            # Migrations may have already been applied - that's okay
            conn.rollback()

    conn.close()


@pytest.fixture
def db_connection(test_db_url, apply_migrations):
    """
    Provide a clean database connection for tests.

    Automatically rolls back all changes after each test.
    """
    if not test_db_url:
        pytest.skip("TEST_DATABASE_URL not set - skipping database test")

    import psycopg2

    conn = psycopg2.connect(test_db_url)
    conn.autocommit = False

    yield conn

    # Rollback any changes
    conn.rollback()
    conn.close()


@pytest.fixture
def clean_db(db_connection):
    """
    Provide a clean database with all tables cleared.

    Use this for tests that need an empty database.
    """
    cursor = db_connection.cursor()

    # Clear all tables in reverse dependency order
    cursor.execute("DELETE FROM sightings")
    cursor.execute("DELETE FROM chat_sessions")
    # Clear badges before contributors due to foreign key
    cursor.execute("DELETE FROM contributors_badges")
    cursor.execute("DELETE FROM contributors")
    cursor.execute("DELETE FROM tlc_vehicles")

    db_connection.commit()

    yield db_connection

    # Rollback is handled by db_connection fixture


@pytest.fixture
def sample_contributor(clean_db):
    """Create a sample contributor for testing."""
    cursor = clean_db.cursor()

    cursor.execute(
        """
        INSERT INTO contributors (phone_number, bluesky_handle, preferred_name)
        VALUES (%s, %s, %s)
        RETURNING id
    """,
        ("+15551234567", "test.bsky.social", "Test User"),
    )

    contributor_id = cursor.fetchone()[0]
    clean_db.commit()

    return contributor_id


@pytest.fixture
def sample_tlc_vehicles(clean_db):
    """Create sample TLC vehicle records for testing."""
    cursor = clean_db.cursor()

    vehicles = [
        ("T123456C", "VCF1ABCD123456789", 2023),
        ("T234567C", "VCF1ABCD234567890", 2023),
        ("T345678C", "VCF1ABCD345678901", 2023),
    ]

    for plate, vin, year in vehicles:
        cursor.execute(
            """
            INSERT INTO tlc_vehicles (dmv_license_plate_number, vehicle_vin_number, vehicle_year)
            VALUES (%s, %s, %s)
        """,
            (plate, vin, year),
        )

    clean_db.commit()

    return vehicles


# ==================== Mock Service Fixtures ====================


@pytest.fixture
def mock_r2():
    """Provide a clean MockR2Storage instance."""
    from tests.mocks import MockR2Storage

    storage = MockR2Storage()
    yield storage
    storage.clear()


@pytest.fixture
def mock_bluesky():
    """Provide a clean MockBlueskyClient instance."""
    from tests.mocks import MockBlueskyClient

    client = MockBlueskyClient()
    yield client
    client.clear()


@pytest.fixture
def mock_twilio():
    """Provide a clean MockTwilioClient instance."""
    from tests.mocks import MockTwilioClient

    client = MockTwilioClient()
    yield client
    client.clear()


@pytest.fixture
def mock_db():
    """Provide a clean MockSightingsDatabase instance."""
    from tests.mocks import MockSightingsDatabase

    db = MockSightingsDatabase()
    yield db
    db.clear()


# ==================== File System Fixtures ====================


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_image(temp_dir):
    """Create a temporary test image."""
    from PIL import Image

    image_path = temp_dir / "test_image.jpg"
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(image_path, "JPEG")

    return image_path


@pytest.fixture
def temp_images(temp_dir):
    """Create multiple temporary test images with different content."""
    from PIL import Image

    images = []
    for i, color in enumerate(["red", "green", "blue"]):
        image_path = temp_dir / f"test_image_{i}.jpg"
        img = Image.new("RGB", (100, 100), color=color)
        img.save(image_path, "JPEG")
        images.append(image_path)

    return images


# ==================== Pytest Configuration ====================


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, no external dependencies)")
    config.addinivalue_line("markers", "integration: Integration tests (require external services)")
    config.addinivalue_line("markers", "e2e: End-to-end tests (full workflow)")
    config.addinivalue_line("markers", "slow: Tests that take >1s to run")
    config.addinivalue_line("markers", "db: Tests that require database connection")
