"""Tests for the one-message submission tip appended to sighting confirmations."""

from unittest.mock import MagicMock, patch

import pytest

from chat import messages
from chat.webhook import _complete_sighting

CONFIRMATION_DATA = {
    "vehicle_sighting_num": 2,
    "total_sightings": 100,
    "contributor_sighting_num": 5,
    "new_badges": [],
    "ocean_points": None,
    "global_unique_sighting_index": None,
    "contributor_vehicle_sighting_num": 1,
}


def _run(
    single_message: bool,
    tip_available: bool = True,
    preferred_name: str | None = "Sam",
    tip_error: Exception | None = None,
):
    db = MagicMock()
    db.get_or_create_contributor.return_value = 7
    db.add_sighting.return_value = {"id": 42}
    db.get_contributor.return_value = {"id": 7, "preferred_name": preferred_name}
    db.claim_one_message_tip.return_value = tip_available
    db.claim_one_message_tip.side_effect = tip_error
    session = MagicMock()

    with (
        patch("chat.webhook.prepare_sighting_image"),
        patch("chat.webhook.get_confirmation_data", return_value=CONFIRMATION_DATA),
        patch("chat.webhook.spawn_background_processing"),
    ):
        response = _complete_sighting(
            session=session,
            session_data={"pending_image_path": "/data/pending.jpg"},
            plate="T702788C",
            vin="VIN123",
            borough="Brooklyn",
            from_number="+15555550100",
            db=db,
            volume_path="/tmp",
            single_message=single_message,
        )
    return response, db


TIP_MARKER = "log a sighting in one text"


@pytest.mark.unit
class TestOneMessageTip:
    def test_multi_message_submission_gets_tip(self):
        response, db = _run(single_message=False)
        assert TIP_MARKER in response
        db.claim_one_message_tip.assert_called_once_with(7)

    def test_single_message_submission_gets_no_tip(self):
        response, db = _run(single_message=True)
        assert TIP_MARKER not in response
        db.claim_one_message_tip.assert_not_called()

    def test_no_tip_within_cooldown(self):
        response, db = _run(single_message=False, tip_available=False)
        assert TIP_MARKER not in response
        db.claim_one_message_tip.assert_called_once_with(7)

    def test_no_tip_when_asking_for_name(self):
        response, db = _run(single_message=False, preferred_name=None)
        assert TIP_MARKER not in response
        assert "set a name" in response
        db.claim_one_message_tip.assert_not_called()

    def test_tip_failure_still_confirms_sighting(self):
        response, _ = _run(single_message=False, tip_error=RuntimeError("db down"))
        assert "sighting logged" in response
        assert TIP_MARKER not in response

    def test_tip_is_gsm7(self):
        """Non-GSM characters would force UCS-2 and multiply segment count."""
        tip = messages.one_message_tip()
        assert tip.isascii()
        assert len(tip) <= 160

    def test_tip_example_parses_as_one_message(self):
        from chat.extractors import extract_borough_from_text, extract_plate_candidates

        example = "702788 in Brooklyn"
        assert example in messages.one_message_tip()
        assert extract_borough_from_text(example) == "Brooklyn"
        assert "702788" in extract_plate_candidates(example)
