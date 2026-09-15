# Image Management

This directory contains utilities for managing sighting images with multi-tier storage.

## Architecture

### Storage Tiers

1. **Original Images** (`/data/images/originals/`)
   - Full-resolution original photos from contributors
   - Stored in Modal volume for archival and processing
   - Never modified or compressed

2. **Web-Optimized Images** (`/data/images/web/`)
   - Resized (max 1200x1200) and compressed (85% quality)
   - Stored both locally (backup) and in Cloudflare R2
   - Used for the static website

3. **Bluesky Images** (processed on-demand)
   - Compressed to <950KB using `post/bluesky.py`
   - Created from original when posting to Bluesky
   - Not permanently stored

### Processing Flow

```
Incoming Image (from Twilio MMS)
        ↓
ImageProcessor.process_sighting_image()
        ↓
   ┌────────────────────────────────┐
   │                                │
   ↓                                ↓
Save Original                  Create Web Version
/data/images/originals/        (resize, compress)
        │                            │
        │                      ┌─────┴─────┐
        │                      ↓           ↓
        │              Save Local    Upload to R2
        │              /data/images/  (Cloudflare)
        │              web/                │
        │                                  ↓
        └──────────────────────────────────┤
                                          │
                    Save to Database      │
                    - image_path          │
                    - image_path_original │
                    - image_url_web ──────┘
```

### Pending → final (one photo, several plates)

An incoming SMS photo is first stored as `pending_YYYYMMDD_HHMMSS_mmm_XXXX.jpg`
(processing time + last four digits of the phone number). When a plate is
confirmed, `ImageProcessor.materialize_final()` **copies** the pending original
and web version to `{plate}_{image_timestamp}.jpg`. Copying, not moving, is
deliberate: a contributor can text several plates for one picture (multiple
Oceans in frame) and each sighting gets its own file backed by the same photo.

`materialize_final()` raises `SightingImageMissingError` when neither the pending
nor the final file exists. `chat.webhook.prepare_sighting_image()` wraps it: it
reloads the Modal volume once (the pending file may have been committed by
another container moments ago), then commits the volume, and only after that
does the caller insert the sighting row. A sighting must never be recorded
against a filename that has no file behind it.

Stale `pending_*` files are swept by the hourly `cleanup_missing_r2_uploads`
job (default: older than 7 days). Sightings whose file is missing can be
repaired with `modal run modal_app.py --command=repair-phantoms`.

## Modules

### `image_processor.py`

Handles image processing and storage:
- `save_original()` - Save full-resolution image to Modal volume
- `create_web_version()` - Create optimized version (resize + compress)
- `save_web_version_local()` - Save web version to local volume
- `process_sighting_image()` - Full pipeline (original + web + R2)
- `materialize_final()` - Copy pending → final filename (raises if the photo is missing)
- `remove_pending()` - Best-effort cleanup of a pending original + web version

### `r2_storage.py`

Cloudflare R2 client (S3-compatible):
- `upload_file()` - Upload from file path
- `upload_fileobj()` - Upload from file object
- `upload_bytes()` - Upload from bytes
- `delete_file()` - Remove from R2
- `file_exists()` - Check existence

## Configuration

### Environment Variables

```bash
# Cloudflare R2
CLOUDFLARE_ACCOUNT_ID=your-account-id
R2_ACCESS_KEY_ID=your-access-key
R2_SECRET_ACCESS_KEY=your-secret-key
R2_BUCKET_NAME=your-bucket-name
R2_PUBLIC_URL_BASE=https://pub-xyz.r2.dev  # Optional, for custom domain
```

### Modal Secrets

```bash
modal secret create cloudflare-r2 \
  CLOUDFLARE_ACCOUNT_ID=<id> \
  R2_ACCESS_KEY_ID=<key> \
  R2_SECRET_ACCESS_KEY=<secret> \
  R2_BUCKET_NAME=<bucket> \
  R2_PUBLIC_URL_BASE=<url>
```

## Database Schema

The `sightings` table includes:

- `image_path` - Path in Modal volume (for Bluesky posting)
- `image_path_original` - Path to original full-resolution image
- `image_url_web` - Public R2 URL for web display

## Usage

### In Webhook Handler

```python
from utils.image_processor import ImageProcessor

processor = ImageProcessor(volume_path="/data")

# Process incoming image
image_paths = processor.process_sighting_image(
    image_data=bytes_from_twilio,
    filename="sighting_20240101_123456_1234.jpg",
    upload_to_r2=True,
    r2_folder="sightings"
)

# Save to database
db.add_sighting(
    image_path=image_paths["original_path"],
    image_path_original=image_paths["original_path"],
    image_url_web=image_paths.get("web_url"),
    # ... other fields
)
```

### Direct R2 Usage

```python
from utils.r2_storage import R2Storage

r2 = R2Storage()

# Upload
url = r2.upload_file("local/path.jpg", "sightings/image.jpg")
print(f"Uploaded to: {url}")

# Check existence
if r2.file_exists("sightings/image.jpg"):
    print("File exists")

# Delete
r2.delete_file("sightings/image.jpg")
```

## Web Site Integration

The static site in `/web` uses `image_url_web` for display:

```python
# web/generate_data.py
cursor.execute("""
    SELECT COALESCE(s.image_url_web, s.image_path) as image
    FROM sightings s
    ...
""")
```

This provides:
- Fast CDN delivery from R2
- Fallback to Modal volume paths
- Automatic optimization for web viewing
