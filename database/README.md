# Database Module

This module handles all database operations for the Oceans of NYC project using Neon PostgreSQL.

## Setup

This app uses [Neon](https://neon.tech) for PostgreSQL hosting:
1. Sign up for a free account at [neon.tech](https://neon.tech)
2. Create a new project
3. Copy the connection string to your `.env` file as `DATABASE_URL`

```bash
DATABASE_URL=postgresql://user:password@host/database
```

The database schema is automatically created on first run.

## Schema

### Tables

#### `sightings`
Stores Fisker Ocean sighting records:
- `id` - Auto-incrementing primary key
- `license_plate` - License plate number (required, non-nullable)
- `timestamp` - ISO timestamp when the vehicle was spotted
- `latitude` - GPS latitude (nullable)
- `longitude` - GPS longitude (nullable)
- `image_path` - Path to sighting image
- `created_at` - When the record was created
- `post_uri` - Bluesky post URI (null if not yet posted)
- `contributor_id` - Foreign key to contributors table

#### `contributors`
Stores contributor information:
- `id` - Auto-incrementing primary key
- `phone_number` - Phone number (for SMS submissions)
- `bluesky_handle` - Bluesky handle (for attribution)
- `preferred_name` - Display name for attribution

#### `tlc_vehicles`
Stores NYC TLC vehicle data:
- `dmv_license_plate_number` - License plate (primary key)
- `vehicle_vin_number` - VIN
- `vehicle_year` - Year
- `name` - Owner name
- `base_name` - Base company name
- `base_type` - Base type (e.g., BLACK-CAR)

## Usage

### Initialize Database

```python
from database import SightingsDatabase

db = SightingsDatabase()
```

### Add a Sighting

```python
sighting_id = db.add_sighting(
    license_plate="T731580C",
    timestamp="2025-11-15T11:18:06",
    latitude=40.7224,
    longitude=-73.9804,
    image_path="/path/to/image.jpg",
    contributor_id=1
)
```

### Get Unposted Sightings

```python
sightings = db.get_unposted_sightings()
for sighting in sightings:
    print(f"Plate: {sighting[1]}, Timestamp: {sighting[2]}")
```

### Mark as Posted

```python
db.mark_as_posted(sighting_id, post_uri="at://did:plc:xyz/app.bsky.feed.post/abc123")
```

## Module Structure

- `models.py` - SightingsDatabase class with all database operations
- `__init__.py` - Public API exports
