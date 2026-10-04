"""Helpers for the web bulk-upload flow.

The browser keeps each photo until the contributor submits, so the extract step
never stores anything. For each photo it sends a downscaled copy (for the plate
reader) plus the first EXIF_HEAD_BYTES of the original, which is where a JPEG
keeps its EXIF block, so GPS and timestamp can be read without uploading the
full-size file twice.
"""

import contextlib
import io
import time
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

from geolocate.boroughs import get_borough_from_coords
from geolocate.exif import ExifDataError, get_coordinates

# The browser downsizes before uploading, so anything bigger is not our page.
MAX_EXTRACT_IMAGE_BYTES = 5 * 1024 * 1024

# EXIF lives in the APP1 segment at the start of a JPEG and is capped at 64KB,
# but some phones put other segments first. 256KB leaves plenty of room.
EXIF_HEAD_BYTES = 256 * 1024

# Each extract call costs about $0.006 in Claude usage. A bulk upload of a few
# dozen photos stays well under the per-client limit; the global limit caps
# the worst-case daily spend at roughly $12.
EXTRACTS_PER_CLIENT_PER_HOUR = 120
EXTRACTS_PER_DAY = 2000

KNOWN_PLATES_TTL_SECONDS = 3600


@dataclass
class PhotoMetadata:
    """What a photo's EXIF block says about where and when it was taken."""

    latitude: float | None = None
    longitude: float | None = None
    image_timestamp: datetime | None = None

    @property
    def borough(self) -> str | None:
        if self.latitude is None or self.longitude is None:
            return None
        return get_borough_from_coords(self.latitude, self.longitude)


def read_photo_metadata(image_bytes: bytes) -> PhotoMetadata:
    """
    Read GPS coordinates and capture time from a photo's EXIF data.

    Works on a truncated file as long as it includes the EXIF block, which is
    all the bulk-upload page sends. Anything unreadable comes back as None;
    a photo with no metadata is normal (screenshots, stripped uploads).
    """
    metadata = PhotoMetadata()
    try:
        image = Image.open(io.BytesIO(image_bytes))
        exif_data = image._getexif()  # type: ignore[attr-defined]
    except Exception:
        return metadata
    if not exif_data:
        return metadata

    exif = {TAGS.get(tag_id, tag_id): value for tag_id, value in exif_data.items()}

    taken = exif.get("DateTimeOriginal") or exif.get("DateTime")
    if taken:
        with contextlib.suppress(TypeError, ValueError):
            metadata.image_timestamp = datetime.strptime(taken, "%Y:%m:%d %H:%M:%S")

    gps_raw = exif.get("GPSInfo")
    if isinstance(gps_raw, dict):
        gps_info = {GPSTAGS.get(key, key): value for key, value in gps_raw.items()}
        with contextlib.suppress(ExifDataError, TypeError, ValueError, ZeroDivisionError):
            metadata.latitude, metadata.longitude = get_coordinates(gps_info)

    return metadata


class UsageLimiter:
    """
    Cap plate-extraction calls per client and per day.

    Counts live in a shared key-value store (a modal.Dict in production) so
    every container sees the same totals. Reads and writes aren't atomic, so a
    burst can overshoot by a few calls; that's fine for a spending guard.
    """

    def __init__(
        self,
        store: MutableMapping,
        per_client_per_hour: int = EXTRACTS_PER_CLIENT_PER_HOUR,
        per_day: int = EXTRACTS_PER_DAY,
    ):
        self.store = store
        self.per_client_per_hour = per_client_per_hour
        self.per_day = per_day

    def allow(self, client_key: str, now: datetime | None = None) -> bool:
        """Record one call for client_key, or return False if over a limit."""
        now = now or datetime.now(UTC)
        client_count_key = f"client:{client_key}:{now:%Y%m%d%H}"
        daily_count_key = f"day:{now:%Y%m%d}"

        client_count = self.store.get(client_count_key, 0)
        daily_count = self.store.get(daily_count_key, 0)
        if client_count >= self.per_client_per_hour or daily_count >= self.per_day:
            return False

        self.store[client_count_key] = client_count + 1
        self.store[daily_count_key] = daily_count + 1
        return True


class KnownPlatesCache:
    """Keep the TLC plate list in memory, reloading it every hour or so."""

    def __init__(
        self,
        loader: Callable[[], list[str]],
        ttl_seconds: float = KNOWN_PLATES_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.loader = loader
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._plates: list[str] = []
        self._loaded_at: float | None = None

    def get(self) -> list[str]:
        now = self.clock()
        if self._loaded_at is None or now - self._loaded_at > self.ttl_seconds:
            self._plates = self.loader()
            self._loaded_at = now
        return self._plates
