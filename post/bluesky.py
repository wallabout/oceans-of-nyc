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

    def compress_image(self, image_path: str, max_size_kb: int = 1900) -> bytes:
        """
        Compress an image to fit within Bluesky's size limit.

        Args:
            image_path: Path to the image file
            max_size_kb: Maximum size in KB (default 1900KB, under the 2MB limit)

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
        new_badges: dict[int, list[str]] | None = None,
    ) -> dict:
        """
        Create a unified post for one or more sightings.

        Args:
            sightings: List of sighting tuples from get_unposted_sightings()
                (id, license_plate, created_at, lat, lon, image_filename, borough, created_at,
                 post_uri, contributor_id, preferred_name, bluesky_handle, phone_number,
                 global_sighting_index, global_unique_sighting_index,
                 contributor_sighting_index, contributor_unique_sighting_index)
            unique_sighted: Number of unique Fisker plates sighted
            total_fiskers: Total number of Fisker vehicles in TLC database
            new_badges: Optional dict mapping sighting_id to list of badge names earned

        Returns:
            Post response from Bluesky API
        """
        if not sightings:
            raise ValueError("No sightings provided for batch post")

        if len(sightings) > 4:
            raise ValueError("Maximum 4 sightings per batch post (Bluesky image limit)")

        text_builder = client_utils.TextBuilder()

        # Progress bar
        progress_bar = self._create_progress_bar(unique_sighted, total_fiskers)
        text_builder.text(f"📈 {progress_bar}")

        # Group sightings by contributor, preserving order of first appearance
        contributors: dict[int, list] = {}
        for sighting in sightings:
            contributor_id = sighting[9]
            if contributor_id not in contributors:
                contributors[contributor_id] = []
            contributors[contributor_id].append(sighting)

        GRAPHEME_LIMIT = 300
        # Leave a few chars of buffer; use len() as grapheme approximation
        # (content is ASCII + simple emoji, so len() == grapheme count in practice)
        truncated = False

        for contributor_sightings in contributors.values():
            if truncated:
                break

            preferred_name = contributor_sightings[0][10]
            bluesky_handle = contributor_sightings[0][11]

            display_name = bluesky_handle if bluesky_handle else preferred_name
            if display_name is None:
                display_name = "Anonymous"

            # contributor_sighting_index is their running total; max = their count after this batch
            total_count = max(s[15] for s in contributor_sightings)

            # Check if contributor header fits before adding it
            header_suffix = f" ({total_count:,})"
            header_candidate = f"\n\n{display_name}{header_suffix}"
            if len(text_builder.build_text()) + len(header_candidate) > GRAPHEME_LIMIT:
                truncated = True
                break

            # Contributor header: blank line before each contributor section
            text_builder.text("\n\n")

            if display_name.startswith("@"):
                handle = display_name[1:]
                try:
                    profile = self.client.get_profile(handle)
                    text_builder.mention(display_name, profile.did)
                except Exception as e:
                    print(f"Warning: Could not resolve handle {handle}, using plain text: {e}")
                    text_builder.text(display_name)
            else:
                text_builder.text(display_name)

            text_builder.text(header_suffix)

            # One line per sighting under this contributor
            for sighting in contributor_sightings:
                sighting_id = sighting[0]
                license_plate = sighting[1]
                global_sighting_index = sighting[13]
                global_unique_sighting_index = sighting[14]

                # Inline parts: 🌊 first (if unique), then badges
                inline_parts = []
                if global_unique_sighting_index is not None:
                    inline_parts.append(f"🌊 {global_unique_sighting_index:,}")

                sighting_badges = (new_badges or {}).get(sighting_id, [])
                if sighting_badges:
                    from badges.definitions import BADGE_BY_NAME

                    for badge_name in sighting_badges:
                        badge_def = BADGE_BY_NAME.get(badge_name)
                        if badge_def:
                            inline_parts.append(f"{badge_def.emoji} {badge_def.display_name}")

                line = f"\n  {global_sighting_index:,} | {license_plate}"
                if inline_parts:
                    line += f" | {' '.join(inline_parts)}"

                if len(text_builder.build_text()) + len(line) > GRAPHEME_LIMIT:
                    truncated = True
                    break

                text_builder.text(line)

        # Collect and upload images (max 4), skipping any missing files
        from utils.image_processor import ImageProcessor

        processor = ImageProcessor()
        images = []
        image_alts = []
        for sighting in sightings[:4]:
            image_filename = sighting[5]
            license_plate = sighting[1]
            borough = sighting[6]
            preferred_name = sighting[10]

            image_path = processor.get_original_path(image_filename)
            if not os.path.exists(image_path):
                print(f"⚠️ Missing image, skipping: {image_filename}")
                continue
            images.append(image_path)

            alt_text = f"Fisker Ocean with plate {license_plate}"
            if preferred_name:
                alt_text += f" by {preferred_name}"
            if borough:
                alt_text += f" in {borough}"
            image_alts.append(alt_text)

        embed = None
        if images:
            uploaded_images = [
                self.upload_image(img, alt) for img, alt in zip(images, image_alts, strict=False)
            ]
            embed = models.AppBskyEmbedImages.Main(images=uploaded_images)

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
        ratio = round(current / total, 3) if total > 0 else 0
        percentage = ratio * 100
        filled = int(bar_length * ratio)
        empty = bar_length - filled

        # Use filled and empty block characters
        filled_bar = "█" * filled
        empty_bar = "▒" * empty
        bar = filled_bar + empty_bar

        return f"{percentage:.1f}% {bar} (of {total})"
