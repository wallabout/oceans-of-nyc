# Oceans of NYC

A community scavenger hunt app for tracking Fisker Ocean cars operating in NYC. Extracts GPS data from images, validates license plates against NYC TLC records, and posts sightings to Bluesky.

## Quick Start

```bash
# Install dependencies
uv sync

# Configure credentials
cp .env.example .env
# Edit .env with your Bluesky and Neon credentials

# Process images and save to database
uv run python main.py batch-process

# Post to Bluesky
uv run python main.py batch-post
```

## Tech Stack

- **Python 3.13+** with **uv** for environment management
- **Neon PostgreSQL** - Cloud database for sightings ([setup guide](database/README.md))
- **Bluesky (atproto)** - Social posting platform ([setup guide](post/README.md))
- **Modal** - Serverless deployment (optional)
- **Twilio** - SMS/MMS webhook for community submissions ([setup guide](chat/README.md))

## Configuration

Create a `.env` file with your credentials:

```bash
# Bluesky Credentials (see post/README.md)
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password

# Neon Database (see database/README.md)
DATABASE_URL=postgresql://user:password@host/database

# Twilio (optional, for SMS submissions - see chat/README.md)
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1234567890
```

## Usage

### 1. Batch Process Images

Process multiple unprocessed images interactively:

```bash
uv run python main.py batch-process
```

**Workflow:**
1. Opens each unprocessed image for viewing
2. Prompts for license plate (supports wildcards like `T73**580C`)
3. Validates plate against NYC TLC database
4. Prompts for optional contributor name
5. Extracts GPS coordinates and timestamp from EXIF data
6. Generates map image
7. Saves to database (does NOT post)

**Controls:**
- Enter `s` to skip an image
- Enter `q` to quit batch processing
- Use wildcards `*` in license plates to search and select
- Press Enter to skip contributor name

### 2. Batch Post to Bluesky

Post all unposted sightings:

```bash
# Post all unposted sightings
uv run python main.py batch-post

# Limit to first 5
uv run python main.py batch-post --limit 5
```

**Features:**
- Posts in chronological order (oldest first)
- Shows preview with neighborhood name before posting
- Asks for confirmation (default: Yes)
- Posts both sighting photo and map image
- Includes contributor attribution
- Generates alt text for accessibility

**Post Format:**
```
🌊 Fisker Ocean sighting!

🚗 Plate: T731580C
📈 2 out of 2053 Oceans collected
🔢 This is the 1st sighting of this vehicle
📅 November 15, 2025 at 11:18 AM
📍 Spotted in Alphabet City, Manhattan

🙏 Contributed by @spotter.bsky.social
```

### 3. Other Commands

```bash
# Process a single image
uv run python main.py process <image_path> <license_plate>

# List all sightings
uv run python main.py list-sightings

# List sightings for a specific plate
uv run python main.py list-sightings --plate T731580C

# Post a specific sighting by ID
uv run python main.py post <sighting_id>
```

## Modules

Each module has its own detailed documentation:

- **[validate/](validate/README.md)** - NYC TLC vehicle data import and validation
- **[database/](database/README.md)** - Neon PostgreSQL database operations
- **[geolocate/](geolocate/README.md)** - GPS extraction, geocoding, and map generation
- **[post/](post/README.md)** - Bluesky posting and image handling
- **[chat/](chat/README.md)** - SMS/MMS webhook for community submissions

## Serverless Deployment

Deploy to Modal for automated posting on a schedule:

```bash
# Run the setup script
./setup_modal.sh

# Deploy
uv run modal deploy modal_app.py
```

Once deployed, the bot will automatically:
- Run every 6 hours
- Post up to 3 unposted sightings per run
- Handle rate limiting and error recovery

**Manual operations:**
```bash
# Get database stats
uv run modal run modal_app.py --command=stats

# Test posting (dry run)
uv run modal run modal_app.py --command=post --limit=3 --dry-run=true

# View logs
uv run modal app logs fisker-ocean-bot --follow
```

See [MODAL_SETUP.md](MODAL_SETUP.md) for detailed documentation.

## Features

### Data Collection
- ✅ Batch image processing with interactive prompts
- ✅ Auto-detection of unprocessed images
- ✅ GPS coordinate and timestamp extraction from EXIF
- ✅ SMS/MMS submissions via Twilio webhook
- ✅ Contributor tracking and attribution

### NYC TLC Integration
- ✅ Import 100,000+ NYC for-hire vehicle records
- ✅ Wildcard plate search (e.g., `T73**580C`)
- ✅ Real-time plate validation during batch processing
- ✅ Automatic Fisker filtering (VIN starts with `VCF1`)

### Progress Tracking
- ✅ Track unique Fisker Oceans posted
- ✅ Count sightings per vehicle
- ✅ Posted vs. queued status tracking
- ✅ Chronological posting (oldest first)

### Mapping & Location
- ✅ Static map generation with OpenStreetMap
- ✅ Reverse geocoding to NYC neighborhoods
- ✅ No API keys required

### Bluesky Integration
- ✅ Batch posting with confirmation prompts
- ✅ Automatic image compression
- ✅ Alt text for accessibility
- ✅ Post preview before publishing
- ✅ Contributor attribution

### Deployment
- ✅ Serverless deployment on Modal
- ✅ Scheduled automated posting
- ✅ Cost-effective (runs on free tier)
- ✅ Cloud integration with Neon PostgreSQL
