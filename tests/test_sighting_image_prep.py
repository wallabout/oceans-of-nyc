"""Tests for the copy-based pending -> final image flow.

Regression tests for the "phantom image" bug: a second plate texted for the same
photo used to be recorded against a filename whose file was never created.
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from chat.session import ChatSession
from chat.webhook import PhotoUnavailableError, prepare_sighting_image
from utils.image_processor import ImageProcessor, SightingImageMissingError


@pytest.fixture
def processor(tmp_path, monkeypatch):
    monkeypatch.delenv("SIGHTING_ORIGINAL_STORAGE_PATH", raising=False)
    monkeypatch.delenv("SIGHTING_WEB_STORAGE_PATH", raising=False)
    return ImageProcessor(volume_path=str(tmp_path))


def _make_pending(processor: ImageProcessor, name="pending_20260904_001919_123_1076.jpg") -> str:
    os.makedirs(processor.originals_path, exist_ok=True)
    path = f"{processor.originals_path}/{name}"
    Image.new("RGB", (1600, 1200), color="teal").save(path, "JPEG")
    return path


@pytest.mark.unit
class TestMaterializeFinal:
    def test_copies_original_and_builds_web_version(self, processor):
        pending = _make_pending(processor)
        final = processor.materialize_final(pending, "T720104C_20260904_001919_3199.jpg")

        assert os.path.exists(final)
        assert os.path.exists(processor.get_web_path("T720104C_20260904_001919_3199.jpg"))
        # Source is kept so the same photo can back another plate
        assert os.path.exists(pending)

    def test_two_plates_from_one_photo_both_get_files(self, processor):
        """The exact scenario behind the broken links."""
        pending = _make_pending(processor)
        first = processor.materialize_final(pending, "T720104C_20260904_001919_3199.jpg")
        second = processor.materialize_final(pending, "T666155C_20260904_001919_3199.jpg")

        assert os.path.exists(first)
        assert os.path.exists(second)
        assert os.path.getsize(first) == os.path.getsize(second)

    def test_missing_source_raises_instead_of_silently_passing(self, processor):
        with pytest.raises(SightingImageMissingError):
            processor.materialize_final(
                f"{processor.originals_path}/pending_nope.jpg", "T1_20260904_001919_3199.jpg"
            )

    def test_idempotent_when_final_exists_but_source_is_gone(self, processor):
        pending = _make_pending(processor)
        final_name = "T720104C_20260904_001919_3199.jpg"
        processor.materialize_final(pending, final_name)
        os.remove(pending)
        os.remove(processor.get_web_path(final_name))

        # Original already final; web version is regenerated from it
        processor.materialize_final(pending, final_name)
        assert os.path.exists(processor.get_web_path(final_name))

    def test_copies_pending_web_version_when_present(self, processor):
        pending = _make_pending(processor)
        web_bytes, _ = processor.create_web_version(pending)
        processor.save_web_version_local(web_bytes, os.path.basename(pending))
        final_name = "T720104C_20260904_001919_3199.jpg"

        processor.materialize_final(pending, final_name)

        with open(processor.get_web_path(final_name), "rb") as f:
            assert f.read() == web_bytes

    def test_rename_to_final_alias_now_copies(self, processor):
        pending = _make_pending(processor)
        processor.rename_to_final(pending, "T720104C_20260904_001919_3199.jpg")
        assert os.path.exists(pending)

    def test_remove_pending_only_touches_pending_files(self, processor):
        pending = _make_pending(processor)
        final = processor.materialize_final(pending, "T720104C_20260904_001919_3199.jpg")
        processor.remove_pending(final)  # not a pending file: ignored
        assert os.path.exists(final)
        processor.remove_pending(pending)
        assert not os.path.exists(pending)


@pytest.mark.unit
class TestPrepareSightingImage:
    def test_missing_photo_raises_outside_modal(self, processor):
        with patch("chat.webhook._get_volume", return_value=None):
            with pytest.raises(PhotoUnavailableError):
                prepare_sighting_image(processor, "/nowhere/pending.jpg", "T1_20260904_001919_3199.jpg")

    def test_reloads_volume_then_retries_and_commits(self, processor):
        """Pending file committed by another container becomes visible after reload."""
        pending_path = f"{processor.originals_path}/pending_20260904_001919_123_1076.jpg"
        volume = MagicMock()
        volume.reload.side_effect = lambda: _make_pending(processor)

        with patch("chat.webhook._get_volume", return_value=volume):
            final = prepare_sighting_image(processor, pending_path, "T1_20260904_001919_3199.jpg")

        assert os.path.exists(final)
        volume.reload.assert_called_once()
        volume.commit.assert_called_once()

    def test_commit_failure_is_not_swallowed(self, processor):
        pending = _make_pending(processor)
        volume = MagicMock()
        volume.commit.side_effect = RuntimeError("volume busy")

        with patch("chat.webhook._get_volume", return_value=volume):
            with pytest.raises(PhotoUnavailableError):
                prepare_sighting_image(processor, pending, "T1_20260904_001919_3199.jpg")


@pytest.mark.unit
class TestSessionReuseWindow:
    def _session_with(self, data):
        session = ChatSession("+15550001076", db_url="postgresql://unused")
        session._data = data
        return session

    def test_recent_saved_session_can_reuse(self):
        now = datetime(2026, 9, 4, 0, 19, 29)
        s = self._session_with(
            {
                "state": ChatSession.SAVED,
                "pending_image_path": "/data/sightings/original/pending_x.jpg",
                "updated_at": datetime(2026, 9, 4, 0, 19, 23),
            }
        )
        assert s.can_reuse_image(now=now)

    def test_expired_saved_session_cannot_reuse(self):
        now = datetime(2026, 9, 4, 1, 0, 0)
        s = self._session_with(
            {
                "state": ChatSession.SAVED,
                "pending_image_path": "/data/sightings/original/pending_x.jpg",
                "updated_at": datetime(2026, 9, 4, 0, 19, 23),
            }
        )
        assert not s.can_reuse_image(now=now)

    def test_non_saved_state_cannot_reuse(self):
        s = self._session_with(
            {
                "state": ChatSession.IDLE,
                "pending_image_path": "/data/sightings/original/pending_x.jpg",
                "updated_at": datetime(2026, 9, 4, 0, 19, 23),
            }
        )
        assert not s.can_reuse_image(now=datetime(2026, 9, 4, 0, 19, 29))
