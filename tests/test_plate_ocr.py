"""Tests for plate_ocr module."""

from unittest.mock import MagicMock, patch


class TestNormalizeCandidate:
    """Test _normalize_candidate() for all plate format variants."""

    def _norm(self, text):
        from utils.plate_ocr import _normalize_candidate
        return _normalize_candidate(text)

    def test_full_format(self):
        assert self._norm("T123456C") == "T123456C"

    def test_full_format_lowercase(self):
        assert self._norm("t123456c") == "T123456C"

    def test_six_digits_only(self):
        assert self._norm("123456") == "T123456C"

    def test_missing_suffix(self):
        assert self._norm("T123456") == "T123456C"

    def test_missing_prefix(self):
        assert self._norm("123456C") == "T123456C"

    def test_whitespace_stripped(self):
        assert self._norm("  T 123456 C  ") == "T123456C"

    def test_too_few_digits(self):
        assert self._norm("T1234C") is None

    def test_too_many_digits(self):
        assert self._norm("T1234567C") is None

    def test_empty(self):
        assert self._norm("") is None

    def test_random_text(self):
        assert self._norm("HELLO") is None


def _make_jpeg():
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


def _mock_client(response_text):
    """Build a mock anthropic.Anthropic() whose .messages.create() returns response_text."""
    content_block = MagicMock()
    content_block.text = response_text
    message = MagicMock()
    message.content = [content_block]
    client = MagicMock()
    client.messages.create.return_value = message
    return client


class TestExtractPlateFromImage:
    """Unit tests for extract_plate_from_image() with mocked dependencies."""

    def test_returns_valid_plate(self):
        """Returns the first candidate that validates against TLC."""
        client = _mock_client('{"candidates": ["T123456C", "T999999C"]}')
        with patch("anthropic.Anthropic", return_value=client), \
             patch("validate.tlc.validate_plate", side_effect=[
                 (True, {"license_plate": "T123456C"}),
                 (False, None),
             ]):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) == "T123456C"

    def test_tries_all_candidates(self):
        """Tries each candidate in order, returns first valid one."""
        client = _mock_client('{"candidates": ["T000000C", "T654321C"]}')
        with patch("anthropic.Anthropic", return_value=client), \
             patch("validate.tlc.validate_plate", side_effect=[
                 (False, None),
                 (True, {"license_plate": "T654321C"}),
             ]):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) == "T654321C"

    def test_normalizes_six_digit_candidate(self):
        """Normalizes bare 6-digit strings to full plate format before validating."""
        client = _mock_client('{"candidates": ["654321"]}')
        with patch("anthropic.Anthropic", return_value=client), \
             patch("validate.tlc.validate_plate", return_value=(True, {"license_plate": "T654321C"})):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) == "T654321C"

    def test_returns_none_when_no_valid_plate(self):
        """Returns None when no candidate validates."""
        client = _mock_client('{"candidates": ["T000000C"]}')
        with patch("anthropic.Anthropic", return_value=client), \
             patch("validate.tlc.validate_plate", return_value=(False, None)):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) is None

    def test_returns_none_on_empty_candidates(self):
        """Returns None when Claude finds no plates."""
        client = _mock_client('{"candidates": []}')
        with patch("anthropic.Anthropic", return_value=client):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) is None

    def test_fallback_regex_on_malformed_json(self):
        """Falls back to regex extraction when Claude returns non-JSON."""
        client = _mock_client("I see T123456C on the bumper.")
        with patch("anthropic.Anthropic", return_value=client), \
             patch("validate.tlc.validate_plate", return_value=(True, {"license_plate": "T123456C"})):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) == "T123456C"

    def test_returns_none_on_api_error(self):
        """API errors are caught and None is returned."""
        import anthropic
        client = MagicMock()
        client.messages.create.side_effect = anthropic.APIError(
            "fail", request=MagicMock(), body=None
        )
        with patch("anthropic.Anthropic", return_value=client):
            from utils.plate_ocr import extract_plate_from_image
            assert extract_plate_from_image(_make_jpeg()) is None

    def test_png_media_type_detected(self):
        """PNG magic bytes result in image/png media type being passed to the API."""
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        client = _mock_client('{"candidates": []}')
        with patch("anthropic.Anthropic", return_value=client):
            from utils.plate_ocr import extract_plate_from_image
            extract_plate_from_image(png_bytes)

        image_block = client.messages.create.call_args[1]["messages"][0]["content"][0]
        assert image_block["source"]["media_type"] == "image/png"
