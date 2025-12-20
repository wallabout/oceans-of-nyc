"""EXIF metadata extraction from images."""

from datetime import datetime
from typing import Any

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS


class ExifDataError(Exception):
    """Raised when image lacks required EXIF data."""

    pass


def get_exif_data(image_path: str) -> dict:
    """Extract EXIF data from an image."""
    try:
        image = Image.open(image_path)
        exif_data = image._getexif()

        if not exif_data:
            raise ExifDataError(f"No EXIF data found in image: {image_path}")

        exif = {}
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            exif[tag] = value

        return exif
    except AttributeError:
        raise ExifDataError(f"No EXIF data found in image: {image_path}")
    except FileNotFoundError:
        raise ExifDataError(f"Image file not found: {image_path}")


def get_gps_data(exif: dict) -> dict:
    """Extract GPS data from EXIF dictionary."""
    if "GPSInfo" not in exif:
        raise ExifDataError("No GPS data found in EXIF")

    gps_info = {}
    for key, value in exif["GPSInfo"].items():
        decode = GPSTAGS.get(key, key)
        gps_info[decode] = value

    return gps_info


def convert_to_degrees(value) -> float:
    """Convert GPS coordinates to degrees in float format."""
    d, m, s = value
    return d + (m / 60.0) + (s / 3600.0)


def get_coordinates(gps_info: dict) -> tuple[float, float]:
    """Extract latitude and longitude from GPS info."""
    if "GPSLatitude" not in gps_info or "GPSLongitude" not in gps_info:
        raise ExifDataError("GPS coordinates not found in EXIF data")

    lat = convert_to_degrees(gps_info["GPSLatitude"])
    lon = convert_to_degrees(gps_info["GPSLongitude"])

    if gps_info.get("GPSLatitudeRef") == "S":
        lat = -lat
    if gps_info.get("GPSLongitudeRef") == "W":
        lon = -lon

    return lat, lon


def get_timestamp(exif: dict) -> str:
    """Extract timestamp from EXIF data."""
    datetime_original = exif.get("DateTimeOriginal") or exif.get("DateTime")

    if not datetime_original:
        raise ExifDataError("No timestamp found in EXIF data")

    try:
        dt = datetime.strptime(datetime_original, "%Y:%m:%d %H:%M:%S")
        return dt.isoformat()
    except ValueError:
        return datetime_original


def extract_image_metadata(image_path: str, calculate_hashes: bool = True) -> dict[str, Any]:
    """
    Extract all metadata from an image.

    Args:
        image_path: Path to the image file
        calculate_hashes: Whether to calculate image hashes (default: True)

    Returns:
        dict with keys:
            - timestamp: ISO format timestamp
            - latitude: GPS latitude (may be None)
            - longitude: GPS longitude (may be None)
            - image_hash_sha256: SHA-256 hash (if calculate_hashes=True)
            - image_hash_perceptual: Perceptual hash (if calculate_hashes=True)

    Note:
        If EXIF data or timestamp is missing, uses current time as fallback.
        GPS data is optional and will be None if not available.
        Hash calculation failures are logged but don't prevent metadata extraction.
    """
    # Try to get EXIF data, but don't fail if it's missing
    try:
        exif = get_exif_data(image_path)
    except ExifDataError:
        # No EXIF data - use current time and no GPS
        result: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "latitude": None,
            "longitude": None,
        }

        # Calculate hashes even if EXIF is missing
        if calculate_hashes:
            sha256, phash = _calculate_hashes_safe(image_path)
            result["image_hash_sha256"] = sha256
            result["image_hash_perceptual"] = phash

        return result

    # Try to get timestamp from EXIF, fall back to current time
    try:
        timestamp = get_timestamp(exif)
    except ExifDataError:
        timestamp = datetime.now().isoformat()

    # Try to get GPS data, but don't fail if it's missing
    try:
        gps_info = get_gps_data(exif)
        lat, lon = get_coordinates(gps_info)
    except ExifDataError:
        # GPS data is optional
        lat, lon = None, None

    result: dict[str, Any] = {"timestamp": timestamp, "latitude": lat, "longitude": lon}

    # Calculate image hashes if requested
    if calculate_hashes:
        sha256, phash = _calculate_hashes_safe(image_path)
        result["image_hash_sha256"] = sha256
        result["image_hash_perceptual"] = phash

    return result


def _calculate_hashes_safe(image_path: str) -> tuple[str | None, str | None]:
    """
    Calculate image hashes with error handling.

    Returns:
        Tuple of (sha256_hash, perceptual_hash), where either may be None on error
    """
    try:
        from utils.image_hashing import calculate_both_hashes

        sha256, phash = calculate_both_hashes(image_path)
        return sha256, phash
    except (ImportError, Exception) as e:
        # Log error but don't fail metadata extraction
        print(f"Warning: Failed to calculate hashes for {image_path}: {e}")
        return None, None


# Convenience functions for simple usage
def extract_gps_from_exif(image_path: str) -> tuple[float, float] | None:
    """
    Extract GPS coordinates from an image's EXIF data.

    Returns:
        Tuple of (latitude, longitude) or None if not available
    """
    metadata = extract_image_metadata(image_path)
    if metadata["latitude"] is not None and metadata["longitude"] is not None:
        return (metadata["latitude"], metadata["longitude"])
    return None


def extract_timestamp_from_exif(image_path: str) -> str:
    """
    Extract timestamp from an image's EXIF data.

    Returns:
        ISO format timestamp string (falls back to current time if not available)
    """
    metadata = extract_image_metadata(image_path)
    return metadata["timestamp"]
