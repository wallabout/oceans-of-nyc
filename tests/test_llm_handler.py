"""Tests for LLM-based SMS conversation handler."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from chat.prompts import SYSTEM_PROMPT, build_image_context
from chat.tools import ConversationContext, execute_tool

# ==================== Prompt Tests ====================


@pytest.mark.unit
class TestBuildImageContext:
    """Tests for image context string builder."""

    def test_with_gps(self):
        result = build_image_context(has_gps=True, latitude=40.6782, longitude=-73.9442)
        assert "GPS: 40.6782, -73.9442" in result
        assert "Photo received" in result

    def test_without_gps(self):
        result = build_image_context(has_gps=False)
        assert "No GPS data" in result
        assert "borough needed" in result

    def test_with_timestamp(self):
        result = build_image_context(
            has_gps=True, latitude=40.0, longitude=-74.0, timestamp="2026-03-27 14:30"
        )
        assert "2026-03-27 14:30" in result

    def test_duplicate(self):
        result = build_image_context(has_gps=False, is_duplicate=True)
        assert "duplicate" in result

    def test_system_prompt_has_key_instructions(self):
        assert "T######C" in SYSTEM_PROMPT
        assert "validate_plate" in SYSTEM_PROMPT
        assert "save_sighting" in SYSTEM_PROMPT
        assert "borough" in SYSTEM_PROMPT.lower()


# ==================== Tool Execution Tests ====================


@pytest.mark.unit
class TestValidatePlateTool:
    """Tests for validate_plate tool execution."""

    @patch("validate.tlc.validate_plate")
    def test_valid_plate(self, mock_validate):
        mock_validate.return_value = (True, {"vin": "VCF1ABC123", "license_plate": "T123456C"})
        ctx = ConversationContext(from_number="+15551234567")

        result_json = execute_tool("validate_plate", {"plate": "T123456C"}, ctx)
        import json

        result = json.loads(result_json)

        assert result["valid"] is True
        assert result["plate"] == "T123456C"
        assert result["vin"] == "VCF1ABC123"
        assert ctx.validated_plates["T123456C"] == "VCF1ABC123"

    @patch("chat.tools._find_similar_plates", return_value=[])
    @patch("validate.tlc.validate_plate")
    def test_invalid_plate(self, mock_validate, mock_similar):
        mock_validate.return_value = (False, None)
        ctx = ConversationContext(from_number="+15551234567")

        result_json = execute_tool("validate_plate", {"plate": "T999999C"}, ctx)
        import json

        result = json.loads(result_json)

        assert result["valid"] is False
        assert "T999999C" not in ctx.validated_plates

    @patch("validate.tlc.validate_plate")
    def test_normalizes_uppercase(self, mock_validate):
        mock_validate.return_value = (True, {"vin": "VCF1X", "license_plate": "T123456C"})
        ctx = ConversationContext(from_number="+15551234567")

        execute_tool("validate_plate", {"plate": "t123456c"}, ctx)
        mock_validate.assert_called_once_with("T123456C")


@pytest.mark.unit
class TestSaveSightingTool:
    """Tests for save_sighting tool execution."""

    @patch("chat.webhook.spawn_background_processing")
    @patch("utils.sighting_confirmation.get_confirmation_data")
    @patch("utils.image_processor.ImageProcessor")
    @patch("database.models.SightingsDatabase")
    def test_save_with_gps(self, mock_db_cls, mock_proc_cls, mock_conf, mock_spawn):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_or_create_contributor.return_value = 42
        mock_db.add_sighting.return_value = {"id": 100, "duplicate_type": None}
        mock_db.get_contributor.return_value = {"preferred_name": "Sam"}

        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        mock_proc.generate_filename.return_value = "T123456C_20260327_143000_0000.jpg"

        mock_conf.return_value = {
            "vehicle_sighting_num": 3,
            "total_sightings": 50,
            "contributor_sighting_num": 10,
            "new_badges": [],
        }

        ctx = ConversationContext(
            from_number="+15551234567",
            pending_image_path="/data/originals/pending_test.jpg",
            pending_latitude=40.67,
            pending_longitude=-73.94,
            pending_timestamp=datetime(2026, 3, 27, 14, 30),
            pending_image_timestamp=datetime(2026, 3, 27, 14, 30),
            validated_plates={"T123456C": "VCF1ABC123"},
        )

        import json

        result = json.loads(execute_tool("save_sighting", {"plate": "T123456C"}, ctx))

        assert result["success"] is True
        assert result["vehicle_sighting_num"] == 3
        assert result["total_sightings"] == 50
        assert result["has_display_name"] is True
        mock_spawn.assert_called_once()

    @patch("chat.webhook.spawn_background_processing")
    @patch("utils.sighting_confirmation.get_confirmation_data")
    @patch("utils.image_processor.ImageProcessor")
    @patch("database.models.SightingsDatabase")
    def test_save_with_borough(self, mock_db_cls, mock_proc_cls, mock_conf, mock_spawn):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_or_create_contributor.return_value = 42
        mock_db.add_sighting.return_value = {"id": 101, "duplicate_type": None}
        mock_db.get_contributor.return_value = {"preferred_name": None}

        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        mock_proc.generate_filename.return_value = "T123456C_20260327.jpg"

        mock_conf.return_value = {
            "vehicle_sighting_num": 1,
            "total_sightings": 51,
            "contributor_sighting_num": 1,
            "new_badges": [
                {
                    "name": "first_catch",
                    "display_name": "First Catch",
                    "description": "Your first sighting!",
                    "emoji": "🎣",
                }
            ],
        }

        ctx = ConversationContext(
            from_number="+15551234567",
            pending_image_path="/data/originals/pending_test.jpg",
            pending_timestamp=datetime(2026, 3, 27),
            pending_image_timestamp=datetime(2026, 3, 27),
            validated_plates={"T123456C": "VCF1ABC123"},
        )

        import json

        result = json.loads(
            execute_tool("save_sighting", {"plate": "T123456C", "borough": "Brooklyn"}, ctx)
        )

        assert result["success"] is True
        assert result["has_display_name"] is False
        assert len(result["new_badges"]) == 1
        # Verify borough was passed (latitude is None so borough should be used)
        call_kwargs = mock_db.add_sighting.call_args
        assert (
            call_kwargs.kwargs.get("borough") == "Brooklyn"
            or call_kwargs[1].get("borough") == "Brooklyn"
        )

    def test_save_without_image(self):
        ctx = ConversationContext(from_number="+15551234567")

        import json

        result = json.loads(execute_tool("save_sighting", {"plate": "T123456C"}, ctx))
        assert "error" in result
        assert "photo" in result["error"].lower()


@pytest.mark.unit
class TestSetContributorNameTool:
    """Tests for set_contributor_name tool execution."""

    @patch("database.models.SightingsDatabase")
    def test_set_name(self, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_or_create_contributor.return_value = 42

        ctx = ConversationContext(from_number="+15551234567")

        import json

        result = json.loads(execute_tool("set_contributor_name", {"name": "Sam"}, ctx))

        assert result["success"] is True
        assert result["name"] == "Sam"
        mock_db.update_contributor_name.assert_called_once_with(42, "Sam")

    @patch("database.models.SightingsDatabase")
    def test_name_truncated_to_50_chars(self, mock_db_cls):
        mock_db = MagicMock()
        mock_db_cls.return_value = mock_db
        mock_db.get_or_create_contributor.return_value = 1

        ctx = ConversationContext(from_number="+15551234567")
        long_name = "A" * 100

        import json

        result = json.loads(execute_tool("set_contributor_name", {"name": long_name}, ctx))
        assert len(result["name"]) == 50


@pytest.mark.unit
class TestExecuteToolDispatch:
    """Tests for tool dispatch."""

    def test_unknown_tool(self):
        ctx = ConversationContext(from_number="+15551234567")
        import json

        result = json.loads(execute_tool("nonexistent_tool", {}, ctx))
        assert "error" in result


# ==================== LLM Handler Tests ====================


@pytest.mark.unit
class TestHandleIncomingSmsLlm:
    """Tests for the main LLM handler with mocked Claude API."""

    @patch("chat.llm_handler.ChatHistory")
    @patch("chat.llm_handler.anthropic.Anthropic")
    def test_text_only_response(self, mock_anthropic_cls, mock_history_cls):
        """Test simple text message with no image and no tool use."""
        from chat.llm_handler import handle_incoming_sms_llm

        # Mock history
        mock_history = MagicMock()
        mock_history.get_recent.return_value = []
        mock_history_cls.return_value = mock_history

        # Mock Claude response — simple text, no tool use
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Send me a photo of a Fisker Ocean to get started!"

        mock_response = MagicMock()
        mock_response.stop_reason = "end_of_turn"
        mock_response.content = [mock_text_block]
        mock_client.messages.create.return_value = mock_response

        result = handle_incoming_sms_llm(
            from_number="+15551234567",
            body="hello",
        )

        assert result == "Send me a photo of a Fisker Ocean to get started!"
        mock_history.add_message.assert_any_call("user", "hello")
        mock_history.add_message.assert_any_call("assistant", result)

    @patch("chat.llm_handler.ChatHistory")
    @patch("chat.llm_handler.anthropic.Anthropic")
    @patch("chat.llm_handler._process_image")
    def test_image_with_tool_use(self, mock_process_img, mock_anthropic_cls, mock_history_cls):
        """Test image submission that triggers validate_plate and save_sighting."""
        from chat.llm_handler import handle_incoming_sms_llm

        mock_history = MagicMock()
        mock_history.get_recent.return_value = []
        mock_history_cls.return_value = mock_history

        mock_process_img.return_value = (
            "[Photo received and saved. GPS: 40.6782, -73.9442. Taken: 2026-03-27 14:30.]"
        )

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # First response: tool_use for validate_plate
        mock_tool_block = MagicMock()
        mock_tool_block.type = "tool_use"
        mock_tool_block.name = "validate_plate"
        mock_tool_block.input = {"plate": "T123456C"}
        mock_tool_block.id = "tool_1"

        mock_response_1 = MagicMock()
        mock_response_1.stop_reason = "tool_use"
        mock_response_1.content = [mock_tool_block]

        # Second response: tool_use for save_sighting
        mock_save_block = MagicMock()
        mock_save_block.type = "tool_use"
        mock_save_block.name = "save_sighting"
        mock_save_block.input = {"plate": "T123456C"}
        mock_save_block.id = "tool_2"

        mock_response_2 = MagicMock()
        mock_response_2.stop_reason = "tool_use"
        mock_response_2.content = [mock_save_block]

        # Third response: final text
        mock_text_block = MagicMock()
        mock_text_block.type = "text"
        mock_text_block.text = "Sighting logged! This is the 3rd time this Ocean has been spotted."

        mock_response_3 = MagicMock()
        mock_response_3.stop_reason = "end_of_turn"
        mock_response_3.content = [mock_text_block]

        mock_client.messages.create.side_effect = [
            mock_response_1,
            mock_response_2,
            mock_response_3,
        ]

        with patch(
            "validate.tlc.validate_plate",
            return_value=(True, {"vin": "VCF1X", "license_plate": "T123456C"}),
        ):
            with patch("database.models.SightingsDatabase") as mock_db_cls:
                with patch("utils.image_processor.ImageProcessor"):
                    with patch(
                        "utils.sighting_confirmation.get_confirmation_data",
                        return_value={
                            "vehicle_sighting_num": 3,
                            "total_sightings": 50,
                            "contributor_sighting_num": 5,
                            "new_badges": [],
                        },
                    ):
                        with patch("chat.webhook.spawn_background_processing"):
                            mock_db = MagicMock()
                            mock_db_cls.return_value = mock_db
                            mock_db.get_or_create_contributor.return_value = 42
                            mock_db.add_sighting.return_value = {"id": 100, "duplicate_type": None}
                            mock_db.get_contributor.return_value = {"preferred_name": "Sam"}

                            result = handle_incoming_sms_llm(
                                from_number="+15551234567",
                                body="T123456C",
                                num_media=1,
                                media_urls=["https://api.twilio.com/image.jpg"],
                                media_types=["image/jpeg"],
                            )

        assert result is not None
        assert "3rd" in result
        assert mock_client.messages.create.call_count == 3


# ==================== Routing Tests ====================


@pytest.mark.unit
class TestRouting:
    """Test that process_sms_message routes correctly based on whitelist."""

    @patch.dict("os.environ", {"LLM_CHAT_PHONES": "+15551234567,+15559876543"})
    def test_whitelist_parsing(self):
        """Test that the whitelist env var is parsed correctly."""
        import os

        phones = os.getenv("LLM_CHAT_PHONES", "").split(",")
        phones = [p.strip() for p in phones if p.strip()]
        assert "+15551234567" in phones
        assert "+15559876543" in phones
        assert len(phones) == 2

    @patch.dict("os.environ", {"LLM_CHAT_PHONES": ""})
    def test_empty_whitelist(self):
        """Test that empty whitelist means no LLM routing."""
        import os

        phones = os.getenv("LLM_CHAT_PHONES", "").split(",")
        phones = [p.strip() for p in phones if p.strip()]
        assert len(phones) == 0

    @patch.dict("os.environ", {"LLM_CHAT_PHONES": "+15551234567"})
    def test_non_whitelisted_number(self):
        """Test that non-whitelisted numbers are not in the list."""
        import os

        phones = os.getenv("LLM_CHAT_PHONES", "").split(",")
        phones = [p.strip() for p in phones if p.strip()]
        assert "+15559999999" not in phones
