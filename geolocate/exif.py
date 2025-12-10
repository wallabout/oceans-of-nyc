"""EXIF metadata extraction from images."""

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS
from datetime import datetime
from typing import Optional


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
    if 'GPSInfo' not in exif:
        raise ExifDataError("No GPS data found in EXIF")

    gps_info = {}
    for key, value in exif['GPSInfo'].items():
        decode = GPSTAGS.get(key, key)
        gps_info[decode] = value

    return gps_info


def convert_to_degrees(value) -> float:
    """Convert GPS coordinates to degrees in float format."""
    d, m, s = value
    return d + (m / 60.0) + (s / 3600.0)


def get_coordinates(gps_info: dict) -> tuple[float, float]:
    """Extract latitude and longitude from GPS info."""
    if 'GPSLatitude' not in gps_info or 'GPSLongitude' not in gps_info:
        raise ExifDataError("GPS coordinates not found in EXIF data")

    lat = convert_to_degrees(gps_info['GPSLatitude'])
    lon = convert_to_degrees(gps_info['GPSLongitude'])

    if gps_info.get('GPSLatitudeRef') == 'S':
        lat = -lat
    if gps_info.get('GPSLongitudeRef') == 'W':
        lon = -lon

    return lat, lon


def get_timestamp(exif: dict) -> str:
    """Extract timestamp from EXIF data."""
    datetime_original = exif.get('DateTimeOriginal') or exif.get('DateTime')

    if not datetime_original:
        raise ExifDataError("No timestamp found in EXIF data")

    try:
        dt = datetime.strptime(datetime_original, '%Y:%m:%d %H:%M:%S')
        return dt.isoformat()
    except ValueError:
        return datetime_original


def extract_image_metadata(image_path: str) -> dict:
    """
    Extract all metadata from an image.

    Returns:
        dict with keys: timestamp, latitude (may be None), longitude (may be None)

    Note:
        If EXIF data or timestamp is missing, uses current time as fallback.
        GPS data is optional and will be None if not available.
    """
    # Try to get EXIF data, but don't fail if it's missing
    try:
        exif = get_exif_data(image_path)
    except ExifDataError:
        # No EXIF data - use current time and no GPS
        return {
            'timestamp': datetime.now().isoformat(),
            'latitude': None,
            'longitude': None
        }

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

    return {
        'timestamp': timestamp,
        'latitude': lat,
        'longitude': lon
    }


# Convenience functions for simple usage
def extract_gps_from_exif(image_path: str) -> Optional[tuple[float, float]]:
    """
    Extract GPS coordinates from an image's EXIF data.

    Returns:
        Tuple of (latitude, longitude) or None if not available
    """
    metadata = extract_image_metadata(image_path)
    if metadata['latitude'] is not None and metadata['longitude'] is not None:
        return (metadata['latitude'], metadata['longitude'])
    return None


def extract_timestamp_from_exif(image_path: str) -> str:
    """
    Extract timestamp from an image's EXIF data.

    Returns:
        ISO format timestamp string (falls back to current time if not available)
    """
    metadata = extract_image_metadata(image_path)
    return metadata['timestamp']
