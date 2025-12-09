# Fisker Ocean spotter Bluesky Bot

This bot automates the process of spotting Fisker Ocean vehicles and posting sightings to Bluesky. It extracts relevant data from images, verifies license plates, generates map images, and compiles posts for sharing on the Bluesky platform.

See the [plan.md](plan.md) file for a detailed breakdown of the steps involved in the process.

## Tech Stack
- **Python 3.13+** - Core scripting language
- **uv** - Python environment management
- **Neon PostgreSQL** - Cloud database for sightings
- **Click** - CLI framework
- **Pillow (PIL)** - Image EXIF extraction and compression
- **atproto** - Bluesky API client
- **python-dotenv** - Environment variable management

### Mapping & Geocoding
- Uses the **staticmap** Python library to generate map images from OpenStreetMap tiles
- Uses **Nominatim** (OpenStreetMap) for reverse geocoding to show neighborhood names
- No API key required
- Adds a red marker at the sighting location
- Respects Nominatim's 1 request/second rate limit

## Installation

```bash
# Install dependencies
uv sync
```

## NYC TLC Vehicle Data

This bot includes support for NYC TLC (Taxi & Limousine Commission) vehicle data, which helps identify and verify Fisker Ocean vehicles operating as for-hire vehicles in NYC.

### Data Source
The TLC vehicle data comes from NYC Open Data:
- **Dataset**: [For Hire Vehicles (FHV) - Active](https://data.cityofnewyork.us/Transportation/For-Hire-Vehicles-FHV-Active/8wbx-tsch/about_data)
- **Updates**: Nightly
- **Records**: 100,000+ active for-hire vehicles in NYC

### Importing TLC Data

Download the latest CSV from the NYC Open Data portal and import it:

```bash
uv run python main.py import-tlc data/For_Hire_Vehicles_(FHV)_-_Active_YYYYMMDD.csv
```

**Example output:**
```
✓ Successfully imported 104,821 TLC vehicle records
  - Total vehicles in database: 104,821
```

### Looking up Vehicle Information

Once imported, you can look up any TLC vehicle by license plate:

```bash
uv run python main.py lookup-tlc T731580C
```

**Example output:**
```
TLC Vehicle Information for T731580C:

  Active: YES
  Vehicle License Number: 5801620
  Owner Name: AMERICAN UNITED TRANSPORTATION INC
  License Type: FOR HIRE VEHICLE
  VIN: VCF1ZBU27PG004131
  Vehicle Year: 2023
  Base Name: UBER USA, LLC
  Base Type: BLACK-CAR
  Base Address: 1515 THIRD STREET SAN FRANCISCO CA 94158
```

This data helps verify that spotted vehicles are legitimate TLC-registered Fisker Oceans operating in NYC.

## Configuration

Create a `.env` file with your credentials:

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your credentials
```

Your `.env` file should contain:
```
# Bluesky Credentials
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password

# Neon Database
DATABASE_URL=postgresql://user:password@host/database
```

### Bluesky Setup
To create an app password:
1. Go to [Settings > App Passwords](https://bsky.app/settings/app-passwords) in Bluesky
2. Create a new app password
3. Use that password in your `.env` file (not your account password)

### Neon Database Setup
This app uses [Neon](https://neon.tech) for PostgreSQL hosting:
1. Sign up for a free account at [neon.tech](https://neon.tech)
2. Create a new project
3. Copy the connection string to your `.env` file as `DATABASE_URL`

The database schema will be automatically created on first run.

## Usage

The bot provides several commands for managing and posting sightings:

### 1. Process a sighting
Extract EXIF data from an image and save to database:

```bash
uv run python main.py process <image_path> <license_plate>
```

**Example:**
```bash
uv run python main.py process images/ocean.jpg T731580C
```

**Requirements:**
- Image must contain EXIF data with GPS coordinates (latitude/longitude)
- Timestamp will be extracted from EXIF data
- License plate must be provided manually

**Output:**
```
Processing image: images/ocean.jpg
License plate: T731580C
✓ Extracted EXIF data:
  - Timestamp: 2025-11-15T11:18:06
  - Location: 40.7224, -73.9804
✓ Sighting saved to database
  - This is sighting #1 for T731580C
```

### 2. List sightings
View all sightings in the database:

```bash
# List all sightings
uv run python main.py list-sightings

# Filter by specific license plate
uv run python main.py list-sightings --plate T731580C
```

**Output:**
```
Found 2 sighting(s):

ID: 2
  License Plate: T731580C
  Timestamp: 2025-11-15T11:18:06
  Location: 40.7224, -73.9804
  Image: /path/to/images/PXL_20251115_161806313.jpg
  Recorded: 2025-12-04T23:02:08.800436
```

### 3. Batch Process Images (Recommended)
Process multiple unprocessed images and save them to the database:

```bash
uv run python main.py batch-process
```

**Workflow:**
For each unprocessed image in the `images/` directory:
1. Opens the image for viewing
2. Prompts for license plate (supports wildcards like `T73**580C`)
3. Validates plate against TLC database
4. Prompts for optional contributor name
5. Extracts EXIF data and saves to database
6. Generates map image
7. **Does NOT post** (use `batch-post` for that)

**Controls:**
- Enter `s` to skip an image
- Enter `q` to quit batch processing
- Use wildcards `*` in license plates to search and select
- Press Enter to skip contributor name

**Example session:**
```
Found 5 unprocessed image(s) out of 23 total

============================================================
Processing image 1/5: PXL_20251115_161806313.jpg
============================================================

Enter license plate (or 's' to skip, 'q' to quit): T73**580C

Searching for plates matching pattern: T73**580C

Found 2 matching plate(s):

1. T731580C - 2023 (VIN: VCF1ZBU27PG004131)
   Owner: AMERICAN UNITED TRANSPORTATION INC
   Base: UBER USA, LLC

2. T732580C - 2023 (VIN: VCF1ZBU27PG004132)
   Owner: NYC TAXI CO
   Base: UBER USA, LLC

Select plate number (1-2): 1

✓ Extracted EXIF data:
  - Timestamp: 2025-11-15T11:18:06
  - Location: 40.7224, -73.9804

Contributor name (optional, press Enter to skip): @spotter.bsky.social

✓ Sighting saved to database
✓ Map saved to: maps/T731580C_20251115_111806.png
✓ Sighting ready to post (use batch-post command)
```

### 4. Batch Post to Bluesky
Post all unposted sightings from the database:

```bash
# Post all unposted sightings
uv run python main.py batch-post

# Post only the first 5 unposted sightings
uv run python main.py batch-post --limit 5
```

**Workflow:**
For each unposted sighting (ordered by timestamp, oldest first):
1. Shows post preview with neighborhood name
2. Asks for confirmation (default: Yes)
3. Posts to Bluesky with both images and alt text
4. Records post URI in database
5. Continues to next sighting

**Features:**
- Posts are ordered chronologically (oldest first)
- "Nth sighting" count reflects only previously **posted** sightings
- "X out of Y Oceans collected" counts only unique plates that have been posted
- Includes contributor attribution if provided
- Generates alt text for accessibility
- Can limit number of posts per run with `--limit`

**Example:**
```
Found 23 unposted sighting(s)

============================================================
Sighting 1/23 (ID: 5)
============================================================

POST PREVIEW
============================================================
🌊 Fisker Ocean sighting!

🚗 Plate: T731580C
📈 1 out of 2053 Oceans collected
🔢 This is the 1st sighting of this vehicle
📅 November 15, 2025 at 11:18 AM
📍 Spotted in Alphabet City, Manhattan

🙏 Contributed by @spotter.bsky.social

Images:
  1. /path/to/images/PXL_20251115_161806313.jpg
  2. maps/T731580C_20251115_111806.png
============================================================

Post this to Bluesky? [Y/n]:
```

### 5. Post Single Sighting to Bluesky
Post a specific sighting by ID to Bluesky:

```bash
uv run python main.py post <sighting_id>
```

**Example:**
```bash
# First, list sightings to get the ID
uv run python main.py list-sightings

# Then post using the ID
uv run python main.py post 2
```

**Features:**
- Shows a preview of the post before publishing
- Requires confirmation (y/n) before posting
- Automatically compresses images to fit Bluesky's 976KB limit
- Tracks sighting count per license plate
- Generates a map image showing the sighting location
- Posts both the vehicle photo and map image

**Post format:**
```
🌊 Fisker Ocean sighting!

🚗 Plate: T731580C
📈 2 out of 2053 Oceans collected
🔢 This is the 1st sighting of this vehicle
📅 November 15, 2025 at 11:18 AM
📍 Spotted in Alphabet City, Manhattan

🙏 Contributed by @spotter.bsky.social
```

**Alt Text (for accessibility):**
- Sighting image: "Spotted a Fisker Ocean with plate T731580C in Alphabet City, Manhattan"
- Map image: "Map of the location the Fisker Ocean was spotted in Alphabet City, Manhattan"

## Features

### Data Collection & Processing
- ✅ **Batch Image Processing** - Interactively process multiple unprocessed images in one session
- ✅ **Auto Image Detection** - Automatically identifies which images haven't been processed yet
- ✅ **EXIF Extraction** - Automatically extracts GPS coordinates and timestamp from images
- ✅ **Neon PostgreSQL** - Cloud-hosted database with automatic backups and scaling
- ✅ **Contributor Tracking** - Optional contributor attribution for community submissions

### NYC TLC Integration
- ✅ **TLC Data Import** - Import and query 100,000+ NYC for-hire vehicle records
- ✅ **Vehicle Lookup** - Verify license plates against official TLC database
- ✅ **Wildcard Plate Search** - Find plates with partial matches (e.g., T73**580C)
- ✅ **TLC Validation** - Validates entered plates against the TLC database during batch processing
- ✅ **Fisker Filtering** - Filters database to only Fisker vehicles (VIN starts with VCF1)

### Progress Tracking
- ✅ **Collection Progress** - Tracks how many unique Fisker Oceans have been posted
- ✅ **Sighting Counter** - Tracks how many times each vehicle has been posted
- ✅ **Posted Status** - Tracks which sightings have been posted vs. queued
- ✅ **Chronological Posting** - Posts sightings in chronological order (oldest first)
- ✅ **Accurate Counts** - "Nth sighting" and "X out of Y collected" reflect only posted sightings

### Mapping & Location
- ✅ **Map Generation** - Creates static map images showing sighting locations using OpenStreetMap
- ✅ **Neighborhood Geocoding** - Converts GPS coordinates to human-readable NYC neighborhoods (e.g., "Fort Greene, Brooklyn")
- ✅ **Red Location Markers** - Adds clear markers to generated maps

### Bluesky Integration
- ✅ **Batch Posting** - Post multiple queued sightings with confirmation prompts
- ✅ **Post Limiting** - Control how many posts to make per run (--limit option)
- ✅ **Image Compression** - Automatically compresses large images to meet Bluesky's size limits
- ✅ **Alt Text for Accessibility** - Generates descriptive alt text for both images
- ✅ **Post Preview** - Shows exactly what will be posted before publishing
- ✅ **Human-readable Formatting** - Converts timestamps and coordinates to friendly formats
- ✅ **Contributor Attribution** - Includes "Contributed by" line when provided