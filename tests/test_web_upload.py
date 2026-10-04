"""Tests for the web bulk-upload helpers."""

import io
import os
from datetime import UTC, datetime

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from utils.web_upload import (
    EXIF_HEAD_BYTES,
    KnownPlatesCache,
    UsageLimiter,
    read_photo_metadata,
)

EXIF_IFD = 0x8769
GPS_IFD = 0x8825
DATETIME_ORIGINAL = 0x9003


def dms(value: float) -> tuple:
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = round(((value - degrees) * 60 - minutes) * 60 * 100)
    return (IFDRational(degrees, 1), IFDRational(minutes, 1), IFDRational(seconds, 100))


def make_photo(
    lat: float | None = None,
    lon: float | None = None,
    taken: str | None = None,
    size: tuple[int, int] = (64, 64),
    noise: bool = False,
) -> bytes:
    """A JPEG with optional GPS and capture-time EXIF."""
    if noise:
        img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    else:
        img = Image.new("RGB", size, "blue")
    exif = Image.Exif()
    if taken:
        exif.get_ifd(EXIF_IFD)[DATETIME_ORIGINAL] = taken
    if lat is not None and lon is not None:
        gps = exif.get_ifd(GPS_IFD)
        gps[1] = "N" if lat >= 0 else "S"
        gps[2] = dms(abs(lat))
        gps[3] = "E" if lon >= 0 else "W"
        gps[4] = dms(abs(lon))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


@pytest.mark.unit
class TestReadPhotoMetadata:
    def test_gps_and_timestamp(self):
        metadata = read_photo_metadata(
            make_photo(lat=40.6930, lon=-73.9870, taken="2026:05:01 12:34:56")
        )
        assert metadata.latitude == pytest.approx(40.6930, abs=1e-4)
        assert metadata.longitude == pytest.approx(-73.9870, abs=1e-4)
        assert metadata.image_timestamp == datetime(2026, 5, 1, 12, 34, 56)
        assert metadata.borough == "Brooklyn"

    def test_truncated_file_keeps_exif(self):
        photo = make_photo(
            lat=40.7589, lon=-73.9851, taken="2026:05:01 12:34:56", size=(1500, 1500), noise=True
        )
        assert len(photo) > EXIF_HEAD_BYTES

        metadata = read_photo_metadata(photo[:EXIF_HEAD_BYTES])
        assert metadata.borough == "Manhattan"
        assert metadata.image_timestamp == datetime(2026, 5, 1, 12, 34, 56)

    def test_timestamp_without_gps(self):
        metadata = read_photo_metadata(make_photo(taken="2026:05:01 12:34:56"))
        assert metadata.latitude is None
        assert metadata.borough is None
        assert metadata.image_timestamp is not None

    def test_outside_nyc(self):
        metadata = read_photo_metadata(make_photo(lat=34.05, lon=-118.24))
        assert metadata.latitude is not None
        assert metadata.borough is None

    def test_no_exif(self):
        metadata = read_photo_metadata(make_photo())
        assert (metadata.latitude, metadata.image_timestamp, metadata.borough) == (
            None,
            None,
            None,
        )

    def test_not_an_image(self):
        assert read_photo_metadata(b"not a photo").image_timestamp is None

    def test_bad_timestamp_ignored(self):
        assert read_photo_metadata(make_photo(taken="yesterday")).image_timestamp is None


@pytest.mark.unit
class TestUsageLimiter:
    NOW = datetime(2026, 10, 4, 15, 30, tzinfo=UTC)

    def test_per_client_hourly_limit(self):
        limiter = UsageLimiter({}, per_client_per_hour=2, per_day=100)
        assert limiter.allow("a", self.NOW)
        assert limiter.allow("a", self.NOW)
        assert not limiter.allow("a", self.NOW)
        assert limiter.allow("b", self.NOW)

    def test_client_limit_resets_next_hour(self):
        limiter = UsageLimiter({}, per_client_per_hour=1, per_day=100)
        assert limiter.allow("a", self.NOW)
        assert not limiter.allow("a", self.NOW)
        assert limiter.allow("a", self.NOW.replace(hour=16))

    def test_daily_limit_across_clients(self):
        limiter = UsageLimiter({}, per_client_per_hour=100, per_day=2)
        assert limiter.allow("a", self.NOW)
        assert limiter.allow("b", self.NOW)
        assert not limiter.allow("c", self.NOW)

    def test_rejected_calls_are_not_counted(self):
        store: dict = {}
        limiter = UsageLimiter(store, per_client_per_hour=1, per_day=100)
        limiter.allow("a", self.NOW)
        limiter.allow("a", self.NOW)
        assert store["day:20261004"] == 1


@pytest.mark.unit
class TestKnownPlatesCache:
    def test_loads_once_within_ttl(self):
        calls = []
        now = [0.0]
        cache = KnownPlatesCache(
            lambda: calls.append(1) or ["T123456C"], ttl_seconds=60, clock=lambda: now[0]
        )
        assert cache.get() == ["T123456C"]
        now[0] = 30
        cache.get()
        assert len(calls) == 1

    def test_reloads_after_ttl(self):
        calls = []
        now = [0.0]
        cache = KnownPlatesCache(
            lambda: calls.append(1) or ["T123456C"], ttl_seconds=60, clock=lambda: now[0]
        )
        cache.get()
        now[0] = 61
        cache.get()
        assert len(calls) == 2
