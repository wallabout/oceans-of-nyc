# Geolocate Module

This module handles GPS coordinate extraction, geocoding, and map generation for sighting locations.

## Features

### EXIF Data Extraction
- Extracts GPS coordinates (latitude/longitude) from image EXIF data
- Extracts timestamps from image metadata
- Handles images without GPS data gracefully

### Reverse Geocoding
- Uses **Nominatim** (OpenStreetMap) for reverse geocoding
- Converts GPS coordinates to human-readable NYC neighborhoods (e.g., "Fort Greene, Brooklyn")
- No API key required
- Respects Nominatim's 1 request/second rate limit

### Map Generation
- Uses the **staticmap** Python library to generate map images from OpenStreetMap tiles
- Adds a red marker at the sighting location
- No API key required
- Generates static PNG images for posting

## Usage

### Extract EXIF Metadata

```python
from geolocate.exif import extract_image_metadata

metadata = extract_image_metadata("path/to/image.jpg")
# Returns: {'timestamp': '2025-11-15T11:18:06', 'latitude': 40.7224, 'longitude': -73.9804}
```

### Reverse Geocode Coordinates

```python
from geolocate import reverse_geocode

neighborhood = reverse_geocode(40.7224, -73.9804)
# Returns: "Alphabet City, Manhattan"
```

### Generate Map Image

```python
from geolocate import generate_map

generate_map(
    latitude=40.7224,
    longitude=-73.9804,
    output_path="maps/sighting_map.png"
)
```

## Module Structure

- `exif.py` - EXIF data extraction from images
- `geocoding.py` - Reverse geocoding and address lookup
- `maps.py` - Static map generation
- `__init__.py` - Public API exports
