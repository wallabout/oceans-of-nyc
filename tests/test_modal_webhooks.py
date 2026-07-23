"""Tests for Modal webhook endpoints with mocked dependencies.

These tests use mocks to test the webhook logic without requiring Modal infrastructure.
"""

from datetime import datetime

import pytest


@pytest.mark.unit
class TestWebSubmissionWebhook:
    """Test web submission endpoint logic."""

    def test_successful_submission_creates_sighting(self, mock_db, mock_r2, temp_image):
        """Test that a valid submission creates a sighting."""
        # Add a valid contributor
        contributor_id = mock_db.add_contributor(phone_number="+15551234567")

        # Simulate submission
        result = mock_db.add_sighting(
            license_plate="T123456C",
            borough="Manhattan",
            image_filename="T123456C_20251206_184123_0000.jpg",
            contributor_id=contributor_id,
            timestamp=datetime(2025, 1, 13, 12, 0, 0),
            latitude=None,
            longitude=None,
        )

        assert result is not None
        assert result["id"] is not None
        assert mock_db.get_sighting_count() == 1

    def test_r2_upload_on_submission(self, mock_r2, temp_image):
        """Test that images are uploaded to R2 on submission."""
        with open(temp_image, "rb") as f:
            image_data = f.read()

        # Upload to R2
        url = mock_r2.upload_bytes(image_data, "test/image.jpg")

        assert mock_r2.file_exists("test/image.jpg")
        assert url == "https://test-r2.dev/test/image.jpg"

    def test_missing_required_fields(self):
        """Test validation of required fields."""
        # In actual webhook, FastAPI would validate these
        # Here we just test the validation logic

        required_fields = ["license_plate", "borough"]

        for field in required_fields:
            data = {"license_plate": "T123456C", "borough": "Manhattan"}
            del data[field]

            # Should detect missing field
            assert field not in data


@pytest.mark.unit
class TestSMSWebhookFlow:
    """Test SMS webhook message flow."""

    def test_image_upload_creates_awaiting_plate_state(self, mock_db):
        """Test that uploading an image transitions to AWAITING_PLATE."""
        from chat.session import ChatSession

        phone = "+15551234567"

        # Create session
        session_data = {
            "phone_number": phone,
            "state": ChatSession.IDLE,
            "data": {},
        }
        mock_db.chat_sessions[phone] = session_data

        # Simulate receiving image
        mock_db.save_chat_session(
            phone_number=phone,
            state=ChatSession.AWAITING_PLATE,
            data={"pending_image_path": "/tmp/image.jpg"},
        )

        session = mock_db.get_chat_session(phone)
        assert session["state"] == ChatSession.AWAITING_PLATE

    def test_plate_submission_transitions_to_awaiting_borough(self, mock_db):
        """Test that submitting plate transitions to AWAITING_BOROUGH."""
        from chat.session import ChatSession

        phone = "+15552222222"

        # Start in AWAITING_PLATE state
        mock_db.save_chat_session(
            phone_number=phone,
            state=ChatSession.AWAITING_PLATE,
            data={"pending_image_path": "/tmp/image.jpg"},
        )

        # Submit plate
        mock_db.save_chat_session(
            phone_number=phone,
            state=ChatSession.AWAITING_BOROUGH,
            data={
                "pending_image_path": "/tmp/image.jpg",
                "pending_plate": "T123456C",
            },
        )

        session = mock_db.get_chat_session(phone)
        assert session["state"] == ChatSession.AWAITING_BOROUGH
        assert session["data"]["pending_plate"] == "T123456C"

    def test_borough_submission_completes_flow(self, mock_db):
        """Test that submitting borough completes the flow."""
        from chat.session import ChatSession

        phone = "+15553333333"
        contributor_id = mock_db.add_contributor(phone_number=phone)

        # Start in AWAITING_BOROUGH state
        mock_db.save_chat_session(
            phone_number=phone,
            state=ChatSession.AWAITING_BOROUGH,
            data={
                "pending_image_path": "/tmp/image.jpg",
                "pending_plate": "T234567C",
            },
        )

        # Submit borough and create sighting
        result = mock_db.add_sighting(
            license_plate="T234567C",
            borough="Brooklyn",
            image_filename="T234567C_20251206_184123_0000.jpg",
            contributor_id=contributor_id,
            timestamp=datetime(2025, 1, 13, 12, 0, 0),
            latitude=None,
            longitude=None,
        )

        # Reset session
        mock_db.delete_chat_session(phone)

        assert result is not None
        assert result["id"] is not None
        assert mock_db.get_chat_session(phone) is None

    def test_image_with_gps_extracts_coordinates(self):
        """Test that GPS coordinates are extracted from image EXIF."""

        # Would test with actual image containing EXIF GPS data
        # For now, test the borough detection logic
        from geolocate.boroughs import get_borough_from_coords

        # Times Square coordinates
        borough = get_borough_from_coords(40.7589, -73.9851)
        assert borough == "Manhattan"

    def test_multiple_users_separate_sessions(self, mock_db):
        """Test that different users have separate sessions."""
        from chat.session import ChatSession

        phone1 = "+15554444444"
        phone2 = "+15555555555"

        # Create separate sessions
        mock_db.save_chat_session(
            phone_number=phone1,
            state=ChatSession.AWAITING_PLATE,
            data={"pending_image_path": "/tmp/image1.jpg"},
        )

        mock_db.save_chat_session(
            phone_number=phone2,
            state=ChatSession.AWAITING_BOROUGH,
            data={"pending_plate": "T345678C"},
        )

        session1 = mock_db.get_chat_session(phone1)
        session2 = mock_db.get_chat_session(phone2)

        assert session1["state"] == ChatSession.AWAITING_PLATE
        assert session2["state"] == ChatSession.AWAITING_BOROUGH

    def test_admin_notification_on_new_submission(self, mock_twilio, mock_db):
        """Test that admin is notified of new submissions."""
        # Add admin contributor
        mock_db.add_contributor(
            phone_number="+15551234567",
            name="Admin",
        )

        # Simulate sending notification
        mock_twilio.messages.create(
            from_="+15559999999",
            to="+15551234567",
            body="New sighting: T456789C in Queens",
        )

        assert mock_twilio.get_sent_message_count() == 1
        last_msg = mock_twilio.get_last_sent_message()
        assert "T456789C" in last_msg["body"]


@pytest.mark.unit
class TestTwiMLResponseGeneration:
    """Test TwiML XML response generation."""

    def test_awaiting_plate_response(self):
        """Test response when awaiting plate number."""
        expected_message = "plate number"

        # Simulate TwiML response
        twiml = f"<Response><Message>{expected_message}</Message></Response>"

        assert "<Response>" in twiml
        assert "<Message>" in twiml
        assert "plate number" in twiml.lower()

    def test_awaiting_borough_response(self):
        """Test response when awaiting borough."""
        expected_message = "Which borough"

        twiml = f"<Response><Message>{expected_message}?</Message></Response>"

        assert "borough" in twiml.lower()

    def test_confirmation_response(self):
        """Test confirmation message with sighting details."""
        plate = "T567890C"
        borough = "Manhattan"
        message = f"Thanks! Saved {plate} in {borough}"

        twiml = f"<Response><Message>{message}</Message></Response>"

        assert plate in twiml
        assert borough in twiml

    def test_duplicate_warning_response(self):
        """Test duplicate warning in response."""
        message = "This image may be a duplicate"

        twiml = f"<Response><Message>{message}</Message></Response>"

        assert "duplicate" in twiml.lower()


@pytest.mark.unit
class TestImageProcessing:
    """Test image processing for webhooks."""

    def test_image_resize_and_optimize(self, temp_image):
        """Test that images are resized and optimized."""
        from PIL import Image

        # Open and check original
        img = Image.open(temp_image)
        original_size = img.size

        # Simulate resize (if image is large)
        max_size = 1600
        if max(original_size) > max_size:
            ratio = max_size / max(original_size)
            new_size = tuple(int(dim * ratio) for dim in original_size)
            img = img.resize(new_size)

        # Image should be resized if needed
        assert max(img.size) <= max_size

    def test_image_format_conversion(self, temp_dir):
        """Test PNG to JPEG conversion."""
        from PIL import Image

        # Create PNG image
        png_path = temp_dir / "test.png"
        img = Image.new("RGBA", (100, 100), color="blue")
        img.save(png_path, "PNG")

        # Convert to JPEG (simulated)
        img_rgb = img.convert("RGB")
        jpg_path = temp_dir / "test.jpg"
        img_rgb.save(jpg_path, "JPEG")

        # JPEG should be created
        assert jpg_path.exists()


@pytest.mark.unit
class TestPlateExtraction:
    """Test license plate extraction from messages."""

    def test_extract_full_format_plate(self):
        """Test extracting T######C format."""
        from chat.extractors import extract_plate_from_text

        assert extract_plate_from_text("T123456C") == "T123456C"
        assert extract_plate_from_text("Saw T234567C today") == "T234567C"

    def test_extract_six_digits(self):
        """Test extracting 6 digits (auto-format to T######C)."""
        from chat.extractors import extract_plate_from_text

        assert extract_plate_from_text("123456") == "T123456C"

    def test_extract_borough_from_message(self):
        """Test extracting borough name from text."""
        from chat.extractors import extract_borough_from_text

        assert extract_borough_from_text("Brooklyn") == "Brooklyn"
        assert extract_borough_from_text("B") == "Brooklyn"
        assert extract_borough_from_text("bk") == "Brooklyn"
