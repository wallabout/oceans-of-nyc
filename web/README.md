# Oceans of NYC - Static Site

A full-bleed tiled layout displaying all TLC Fisker Ocean vehicles and their sightings.

## Features

- **Grid Layout**: Each tile represents one vehicle from the `tlc_vehicles_minimal` table
- **Sightings**: Tiles with sightings show the actual photo
- **Placeholders**: Tiles without sightings show a grey car silhouette
- **Stats**: Live stats showing total vehicles, sighted count, and progress percentage
- **Hover Info**: Hover over tiles to see license plate and borough

## Setup

### 1. Generate Data

```bash
cd web
uv run python3 generate_data.py
```

This creates `vehicles.json` with all vehicle and sighting data.

### 2. View Locally

Start a simple HTTP server:

```bash
# Simple server (images won't load from Modal)
python3 -m http.server 8000

# Or use the custom server (shows helpful error messages)
python3 serve_images.py 8000
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

**Note**: For local development, the actual vehicle images won't display since they're stored in Modal's volume. You'll see:
- Grey car placeholders for vehicles without sightings (working as intended)
- Missing images for vehicles with sightings (need image access configured)

## Data Structure

The `vehicles.json` file contains:

```json
{
  "vehicles": [
    {
      "plate": "T101587C",
      "vin": "VCF1EBU27PG008370",
      "image": "/data/images/PXL_20251115_163247809.jpg",
      "borough": "Manhattan",
      "timestamp": "2025-11-15T11:32:47"
    }
  ],
  "total": 2128,
  "sighted": 76
}
```

## Image Storage

Currently, images are stored in Modal's persistent storage volume. The image paths in the database are relative paths like `/data/images/filename.jpg`.

To make images accessible for the static site, you'll need to either:

1. **Export images**: Copy images from Modal to a web-accessible location (S3, CDN, etc.)
2. **API endpoint**: Create a Modal endpoint that serves images by path
3. **Local development**: Mount Modal volume locally or use symlinks

## Current Status

- ✅ HTML/CSS layout complete
- ✅ Data generation script working
- ✅ Grid rendering with placeholders
- ⏳ Image URLs need to be configured for production
