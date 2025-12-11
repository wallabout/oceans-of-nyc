# Post Module

This module handles posting sightings to Bluesky with images and formatted text.

## Setup

Create an app password in Bluesky:
1. Go to [Settings > App Passwords](https://bsky.app/settings/app-passwords)
2. Create a new app password
3. Add credentials to your `.env` file:

```bash
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
```

**Note:** Use the app password, not your account password.

## Features

- **Image Compression** - Automatically compresses images to meet Bluesky's 976KB limit
- **Alt Text** - Generates descriptive alt text for accessibility
- **Multi-Image Posts** - Posts both sighting photo and map image
- **Rich Text Formatting** - Creates formatted posts with emojis and data
- **Error Handling** - Robust error handling and retry logic

## Usage

### Initialize Client

```python
from post.bluesky import BlueskyClient

client = BlueskyClient()
```

### Create a Simple Post

```python
response = client.create_post("Hello from Oceans of NYC!")
print(f"Posted: {response.uri}")
```

### Create a Post with Images

```python
response = client.create_post(
    text="🌊 Fisker Ocean sighting!",
    images=["path/to/sighting.jpg", "path/to/map.png"],
    image_alts=[
        "Fisker Ocean spotted in Manhattan",
        "Map showing sighting location"
    ]
)
```

## Post Format

Posts follow this format:

```
🌊 Fisker Ocean sighting!

🚗 Plate: T731580C
📈 2 out of 2053 Oceans collected
🔢 This is the 1st sighting of this vehicle
📅 November 15, 2025 at 11:18 AM
📍 Spotted in Alphabet City, Manhattan

🙏 Contributed by @spotter.bsky.social
```

## Module Structure

- `bluesky.py` - BlueskyClient class for API interactions
- `__init__.py` - Public API exports
