"""Bluesky client for posting sightings."""

import io
import os

from atproto import Client, client_utils, models
from PIL import Image, ImageOps


class BlueskyClient:
    def __init__(self, handle: str | None = None, password: str | None = None):
        """
        Initialize Bluesky client with credentials.

        Args:
            handle: Bluesky handle (e.g., user.bsky.social). If not provided, reads from BLUESKY_HANDLE env var.
            password: Bluesky app password. If not provided, reads from BLUESKY_PASSWORD env var.
        """
        self.handle = handle or os.getenv("BLUESKY_HANDLE")
        self.password = password or os.getenv("BLUESKY_PASSWORD")

        if not self.handle or not self.password:
            raise ValueError(
                "Bluesky credentials not provided. "
                "Set BLUESKY_HANDLE and BLUESKY_PASSWORD environment variables "
                "or pass them as arguments."
            )

        self.client = Client()
        self.login()

    def login(self):
        """Authenticate with Bluesky."""
        self.client.login(self.handle, self.password)

    def compress_image(self, image_path: str, max_size_kb: int = 950) -> bytes:
        """
        Compress an image to fit within Bluesky's size limit.

        Args:
            image_path: Path to the image file
            max_size_kb: Maximum size in KB (default 950KB, under the 976KB limit)

        Returns:
            Compressed image data as bytes
        """
        img = ImageOps.exif_transpose(Image.open(image_path))

        # Convert RGBA to RGB if necessary
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Start with quality 85 and reduce if needed
        quality = 85
        max_size_bytes = max_size_kb * 1024

        while quality > 20:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            size = buffer.tell()

            if size <= max_size_bytes:
                buffer.seek(0)
                return buffer.read()

            quality -= 5

        # If still too large, resize the image
        scale = 0.9
        while quality <= 85:
            new_width = int(img.width * scale)
            new_height = int(img.height * scale)
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            resized.save(buffer, format="JPEG", quality=quality, optimize=True)
            size = buffer.tell()

            if size <= max_size_bytes:
                buffer.seek(0)
                return buffer.read()

            scale -= 0.1
            if scale < 0.3:
                quality += 5

        # Last resort: return whatever we have
        buffer.seek(0)
        return buffer.read()

    def upload_image(self, image_path: str, alt_text: str = "") -> models.AppBskyEmbedImages.Image:
        """
        Upload an image to Bluesky, compressing if necessary.

        Args:
            image_path: Path to the image file
            alt_text: Alternative text description for accessibility

        Returns:
            Image object that can be used in a post
        """
        image_data = self.compress_image(image_path)
        upload_response = self.client.upload_blob(image_data)
        return models.AppBskyEmbedImages.Image(alt=alt_text, image=upload_response.blob)

    def create_post(
        self, text: str, images: list[str] | None = None, image_alts: list[str] | None = None
    ) -> dict:
        """
        Create a post on Bluesky with optional images.

        Args:
            text: Post text content
            images: Optional list of image file paths (max 4)
            image_alts: Optional list of alt text for each image

        Returns:
            Post response from Bluesky API
        """
        embed = None

        if images:
            if len(images) > 4:
                raise ValueError("Bluesky supports a maximum of 4 images per post")

            # If no alt texts provided, use empty strings
            if image_alts is None:
                image_alts = [""] * len(images)

            # Ensure we have the same number of alt texts as images
            if len(image_alts) != len(images):
                raise ValueError("Number of alt texts must match number of images")

            uploaded_images = [
                self.upload_image(img, alt) for img, alt in zip(images, image_alts, strict=False)
            ]
            embed = models.AppBskyEmbedImages.Main(images=uploaded_images)

        response = self.client.send_post(text=text, embed=embed)
        return response

    def create_batch_sighting_post(
        self,
        sightings: list[tuple],
        unique_sighted: int,
        total_fiskers: int,
        contributor_stats: dict[int, int] | None = None,
    ) -> dict:
        """
        Create a unified post for one or more sightings.

        Args:
            sightings: List of sighting tuples from get_unposted_sightings()
                (id, license_plate, timestamp, lat, lon, image_filename, borough, created_at,
                 post_uri, contributor_id, preferred_name, bluesky_handle, phone_number)
            unique_sighted: Number of unique Fisker plates sighted
            total_fiskers: Total number of Fisker vehicles in TLC database
            contributor_stats: Optional dict mapping contributor_id to total all-time sighting count

        Returns:
            Post response from Bluesky API
        """
        if not sightings:
            raise ValueError("No sightings provided for batch post")

        if len(sightings) > 4:
            raise ValueError("Maximum 4 sightings per batch post (Bluesky image limit)")

        # Extract license plates
        plates = [sighting[1] for sighting in sightings]  # license_plate column

        # Build contributor statistics
        # contributor_id -> {display_name, count_in_batch, total_count}
        contributor_info = {}
        for sighting in sightings:
            contributor_id = sighting[9]  # contributor_id
            preferred_name = sighting[10]  # preferred_name
            bluesky_handle = sighting[11]  # bluesky_handle

            if contributor_id not in contributor_info:
                # Determine display name
                display_name = preferred_name if preferred_name else bluesky_handle
                if display_name is None:
                    display_name = "Anonymous"

                contributor_info[contributor_id] = {
                    "display_name": display_name,
                    "count_in_batch": 0,
                    "total_count": (
                        contributor_stats.get(contributor_id, 0) if contributor_stats else 0
                    ),
                }

            contributor_info[contributor_id]["count_in_batch"] += 1

        # Build post text
        text_builder = client_utils.TextBuilder()

        # Header with sighting count
        sighting_word = "sighting" if len(sightings) == 1 else "sightings"
        text_builder.text(f"🌊 +{len(sightings)} {sighting_word}\n")

        # License plates
        plates_text = ", ".join(plates)
        text_builder.text(f"🚗 {plates_text}\n")

        # Progress bar
        progress_bar = self._create_progress_bar(unique_sighted, total_fiskers)
        text_builder.text(f"📈 {progress_bar}")

        # Add contributor statistics
        if contributor_info:
            text_builder.text("\n\n")

            # Sort contributors by display name
            sorted_contributors = sorted(
                contributor_info.items(), key=lambda x: x[1]["display_name"].lower()
            )

            for _contributor_id, info in sorted_contributors:
                display_name = info["display_name"]
                count_in_batch = info["count_in_batch"]
                total_count = info["total_count"]

                # Format: * Sam +1 → 55
                text_builder.text("* ")

                # Add display name with mention support if it's a handle
                if display_name.startswith("@"):
                    handle = display_name[1:]
                    try:
                        # Resolve handle to DID for mention
                        profile = self.client.get_profile(handle)
                        text_builder.mention(display_name, profile.did)
                    except Exception as e:
                        # If resolution fails, fall back to plain text
                        print(f"Warning: Could not resolve handle {handle}, using plain text: {e}")
                        text_builder.text(display_name)
                else:
                    text_builder.text(display_name)

                text_builder.text(f" +{count_in_batch} → {total_count}\n")

        # Collect images (max 4)
        from utils.image_processor import ImageProcessor

        processor = ImageProcessor()
        images = []
        image_alts = []
        for sighting in sightings[:4]:  # Only take first 4 for image limit
            image_filename = sighting[5]  # image_filename column
            license_plate = sighting[1]  # license_plate column
            borough = sighting[6]  # borough column
            preferred_name = sighting[10]  # preferred_name column

            # Derive path from filename
            image_path = processor.get_original_path(image_filename)
            images.append(image_path)

            # Build alt text with plate, contributor, and location
            alt_text = f"Fisker Ocean with plate {license_plate}"
            if preferred_name:
                alt_text += f" by {preferred_name}"
            if borough:
                alt_text += f" in {borough}"
            image_alts.append(alt_text)

        # Upload images
        embed = None
        if images:
            uploaded_images = [
                self.upload_image(img, alt) for img, alt in zip(images, image_alts, strict=False)
            ]
            embed = models.AppBskyEmbedImages.Main(images=uploaded_images)

        # Send post
        response = self.client.send_post(text_builder, embed=embed)
        return response

    @staticmethod
    def _create_progress_bar(current: int, total: int, bar_length: int = 10) -> str:
        """
        Create a progress bar with percentage.

        Args:
            current: Number of items collected
            total: Total items to collect
            bar_length: Length of the progress bar in characters

        Returns:
            Formatted progress bar string like "1.5% █▒▒▒▒▒▒▒▒▒ (30 out of 2053)"
        """
        percentage = (current / total * 100) if total > 0 else 0
        filled = int(bar_length * current / total) if total > 0 else 0
        empty = bar_length - filled

        # Use filled and empty block characters
        filled_bar = "█" * filled
        empty_bar = "▒" * empty
        bar = filled_bar + empty_bar

        return f"{percentage:.1f}% {bar} ({current} out of {total})"
