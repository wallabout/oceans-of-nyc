# Modal Setup Guide

This guide walks you through deploying the Fisker Ocean bot on Modal's serverless platform.

## Prerequisites

1. **Modal Account**: Sign up at [modal.com](https://modal.com)
2. **Modal CLI**: Already installed via `uv add modal`

## Initial Setup

### 1. Authenticate with Modal

```bash
modal token new
```

This will open your browser to authenticate and set up your Modal token.

### 2. Create Modal Secrets

You need to create two secrets in Modal for your credentials:

#### Bluesky Credentials

```bash
modal secret create bluesky-credentials \
  BLUESKY_HANDLE=oceansofnyc.bsky.social \
  BLUESKY_PASSWORD=your-app-password
```

#### Neon Database

```bash
modal secret create neon-db \
  DATABASE_URL=postgresql://user:password@host/database
```

Replace the values with your actual credentials from `.env`.

### 3. Deploy the App

Deploy your Modal app to the cloud:

```bash
modal deploy modal_app.py
```

This will:
- Build the container image with all dependencies
- Deploy the scheduled function (runs every 6 hours)
- Make your functions available for remote execution

## Usage

### Run Functions Locally

Test functions locally before deploying:

```bash
# Get database stats
modal run modal_app.py --command=stats

# Test batch posting (dry run)
modal run modal_app.py --command=post --limit=3 --dry-run=true

# Actually post (limited to 3)
modal run modal_app.py --command=post --limit=3
```

### Run Functions Remotely

After deploying, you can trigger functions remotely:

```bash
# Trigger batch post manually
modal run modal_app.py::batch_post --limit=5

# Get stats
modal run modal_app.py::get_stats
```

### View Logs

Monitor your scheduled runs:

```bash
# View recent logs
modal app logs fisker-ocean-bot

# Follow logs in real-time
modal app logs fisker-ocean-bot --follow
```

### Manage Scheduled Functions

```bash
# List all scheduled functions
modal app list

# Stop the scheduled function
modal app stop fisker-ocean-bot

# Restart it
modal deploy modal_app.py
```

## Scheduled Behavior

The `scheduled_batch_post` function runs automatically every 6 hours and:
- Posts up to 3 unposted sightings per run
- Waits 10 seconds between posts
- Respects Nominatim's rate limit for geocoding

## Architecture

```
modal_app.py
├── batch_post()           - Main posting function
├── scheduled_batch_post() - Runs every 6 hours
├── get_stats()           - Database statistics
└── main()                - Local CLI for testing
```

## Cost Optimization

Modal pricing is based on compute time. Our setup:
- **Scheduled runs**: ~2-5 minutes per run (4 runs/day = ~10-20 min/day)
- **Modal free tier**: 30 free compute hours/month
- **Estimated cost**: $0/month (well within free tier)

## Monitoring

View your app dashboard:
```bash
modal app show fisker-ocean-bot
```

Or visit the web UI at: https://modal.com/apps

## Troubleshooting

### Secret Not Found
If you get a "secret not found" error:
```bash
# List your secrets
modal secret list

# Recreate if needed
modal secret create bluesky-credentials BLUESKY_HANDLE=... BLUESKY_PASSWORD=...
```

### Import Errors
The Modal function copies your source files. Make sure:
- All dependencies are in `requirements.txt` or specified in `image.pip_install()`
- Your local imports work correctly

### Database Connection Issues
Verify your Neon connection string:
```bash
# Test connection locally first
uv run python -c "from database import SightingsDatabase; db = SightingsDatabase(); print('Connected!')"
```

## Advanced: Image Handling

Currently, the Modal app posts text only. To add image support:

1. **Option A: Cloud Storage**
   - Upload images to S3/GCS/R2
   - Reference URLs in database
   - Download in Modal function

2. **Option B: Modal Volume**
   - Mount persistent volume in local environment
   - Copy images to volume
   - Access in Modal function

Example for S3 integration:
```python
from modal import CloudBucketMount

volume = CloudBucketMount(
    bucket_name="fisker-ocean-images",
    secret=modal.Secret.from_name("aws-credentials")
)
```

## Development Workflow

1. **Local testing**: Use `modal run modal_app.py`
2. **Deploy changes**: Run `modal deploy modal_app.py`
3. **Monitor**: Check logs with `modal app logs fisker-ocean-bot`
4. **Iterate**: Update code and redeploy

## Useful Commands

```bash
# View all Modal apps
modal app list

# Delete an app
modal app stop fisker-ocean-bot

# View container image details
modal image list

# Force rebuild image
modal deploy modal_app.py --force-build
```
