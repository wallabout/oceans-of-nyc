"""Tests for plate OCR reading and known-plate matching."""

import io
import json
from unittest.mock import MagicMock

import pytest
from PIL import Image

from utils.plate_ocr import (
    extract_plate_from_image,
    match_plate,
    normalize_reading,
    plate_distance,
    prepare_image,
    read_plate,
)

KNOWN_PLATES = ["T731580C", "T731581C", "T731680C", "T123456C", "NO1BOSS"]


def make_image(width=3000, height=2000, mode="RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def make_client(text: str, stop_reason: str = "end_turn") -> MagicMock:
    response = MagicMock()
    response.stop_reason = stop_reason
    response.content = [MagicMock(type="text", text=text)]
    response.usage.input_tokens = 1500
    response.usage.output_tokens = 12
    client = MagicMock()
    client.messages.create.return_value = response
    return client


@pytest.mark.unit
class TestNormalizeReading:
    def test_standard_plate(self):
        assert normalize_reading("T731580C") == "T731580C"

    def test_shorthand_expanded(self):
        assert normalize_reading("731580") == "T731580C"
        assert normalize_reading("T731580") == "T731580C"

    def test_spaces_and_dashes_removed(self):
        assert normalize_reading("t 731-580 c") == "T731580C"

    def test_placeholders_kept_and_expanded(self):
        assert normalize_reading("T73?580C") == "T73?580C"
        assert normalize_reading("73?580") == "T73?580C"
        assert normalize_reading("T73?580") == "T73?580C"
        assert normalize_reading("73?580C") == "T73?580C"

    def test_nonstandard_plate_kept(self):
        assert normalize_reading("NO1BOSS") == "NO1BOSS"

    def test_empty(self):
        assert normalize_reading("") is None
        assert normalize_reading(None) is None
        assert normalize_reading(" - ") is None


@pytest.mark.unit
class TestPlateDistance:
    def test_exact(self):
        assert plate_distance("T731580C", "T731580C") == 0

    def test_substitution(self):
        assert plate_distance("T731589C", "T731580C") == 1

    def test_missing_character(self):
        assert plate_distance("T73580C", "T731580C") == 1

    def test_placeholder_is_free(self):
        assert plate_distance("T73?580C", "T731580C") == 0

    def test_confusable_swap_is_half(self):
        assert plate_distance("T731560C", "T731580C") == 0.5


@pytest.mark.unit
class TestMatchPlate:
    def test_exact_match_first(self):
        matches = match_plate("T731580C", KNOWN_PLATES)
        assert matches[0].plate == "T731580C"
        assert matches[0].distance == 0

    def test_close_misread_recovers_plate(self):
        matches = match_plate("T731S80C", ["T731580C", "T123456C"])
        assert [m.plate for m in matches] == ["T731580C"]

    def test_ambiguous_reading_returns_ranked_candidates(self):
        matches = match_plate("T7315?0C", KNOWN_PLATES)
        assert [m.plate for m in matches] == ["T731580C", "T731680C", "T731581C"]

    def test_confusable_swap_ranks_first(self):
        matches = match_plate("T744460C", ["T744461C", "T744480C"])
        assert [m.plate for m in matches] == ["T744480C", "T744461C"]

    def test_limit(self):
        assert len(match_plate("T731580C", KNOWN_PLATES, limit=1)) == 1

    def test_too_far_returns_nothing(self):
        assert match_plate("T999999C", KNOWN_PLATES) == []

    def test_mostly_illegible_returns_nothing(self):
        assert match_plate("T??????C", KNOWN_PLATES) == []

    def test_no_reading(self):
        assert match_plate(None, KNOWN_PLATES) == []

    def test_nonstandard_plate(self):
        assert match_plate("NO1BOSS", KNOWN_PLATES)[0].plate == "NO1BOSS"


@pytest.mark.unit
class TestPrepareImage:
    def test_downscales_to_max_edge(self):
        img = Image.open(io.BytesIO(prepare_image(make_image(4000, 3000))))
        assert img.format == "JPEG"
        assert max(img.size) == 1568

    def test_small_image_not_upscaled(self):
        img = Image.open(io.BytesIO(prepare_image(make_image(800, 600))))
        assert img.size == (800, 600)

    def test_converts_rgba(self):
        img = Image.open(io.BytesIO(prepare_image(make_image(100, 100, mode="RGBA"))))
        assert img.mode == "RGB"


@pytest.mark.unit
class TestReadPlate:
    def test_returns_reading_and_usage(self):
        client = make_client(json.dumps({"plate": "T731580C"}))
        assert read_plate(make_image(), client=client) == ("T731580C", 1500, 12)

        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-5-5"
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"

    def test_empty_plate_is_none(self):
        client = make_client(json.dumps({"plate": ""}))
        assert read_plate(make_image(), client=client)[0] is None

    def test_early_stop_is_none(self):
        client = make_client("", stop_reason="refusal")
        assert read_plate(make_image(), client=client)[0] is None

    def test_model_override(self):
        client = make_client(json.dumps({"plate": "T731580C"}))
        read_plate(make_image(), client=client, model="claude-haiku-4-5")
        assert client.messages.create.call_args.kwargs["model"] == "claude-haiku-4-5"


@pytest.mark.unit
class TestExtractPlateFromImage:
    def test_suggests_known_plates(self):
        client = make_client(json.dumps({"plate": "T73158?C"}))
        reading = extract_plate_from_image(make_image(), KNOWN_PLATES, client=client)

        assert reading.raw == "T73158?C"
        assert reading.best == "T731580C"
        assert [m.plate for m in reading.suggestions] == ["T731580C", "T731581C", "T731680C"]
        assert (reading.input_tokens, reading.output_tokens) == (1500, 12)

    def test_no_plate_visible(self):
        client = make_client(json.dumps({"plate": ""}))
        reading = extract_plate_from_image(make_image(), KNOWN_PLATES, client=client)

        assert reading.raw is None
        assert reading.best is None
        assert reading.suggestions == []
