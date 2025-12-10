"""Bluesky client for posting sightings."""

import os
import io
from pathlib import Path
from typing import Optional
from datetime import datetime
from PIL import Image
from atproto import Client, models, client_utils

from geolocate.geocoding import Geocoder


class BlueskyClient:
    def __init__(self, handle: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize Bluesky client with credentials.

        Args:
            handle: Bluesky handle (e.g., user.bsky.social). If not provided, reads from BLUESKY_HANDLE env var.
            password: Bluesky app password. If not provided, reads from BLUESKY_PASSWORD env var.
        """
        self.handle = handle or os.getenv('BLUESKY_HANDLE')
        self.password = password or os.getenv('BLUESKY_PASSWORD')

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
        img = Image.open(image_path)

        # Convert RGBA to RGB if necessary
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # Start with quality 85 and reduce if needed
        quality = 85
        max_size_bytes = max_size_kb * 1024

        while quality > 20:
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=quality, optimize=True)
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
            resized.save(buffer, format='JPEG', quality=quality, optimize=True)
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

    def upload_image(self, image_path: str, alt_text: str = '') -> models.AppBskyEmbedImages.Image:
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

    def create_post(self, text: str, images: Optional[list[str]] = None, image_alts: Optional[list[str]] = None) -> dict:
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
                image_alts = [''] * len(images)

            # Ensure we have the same number of alt texts as images
            if len(image_alts) != len(images):
                raise ValueError("Number of alt texts must match number of images")

            uploaded_images = [self.upload_image(img, alt) for img, alt in zip(images, image_alts)]
            embed = models.AppBskyEmbedImages.Main(images=uploaded_images)

        response = self.client.send_post(text=text, embed=embed)
        return response

    def _build_sighting_text_parts(
        self,
        license_plate: str,
        sighting_count: int,
        timestamp: str,
        latitude: float | None,
        longitude: float | None,
        unique_sighted: int,
        total_fiskers: int
    ) -> tuple[str, str, str | None, str | None]:
        """
        Build the core parts of a sighting post text.

        Returns:
            Tuple of (ordinal, formatted_time, progress_bar, location_text)
        """
        ordinal = self._get_ordinal(sighting_count)
        dt = datetime.fromisoformat(timestamp)
        formatted_time = dt.strftime("%B %d, %Y at %I:%M %p")
        progress_bar = self._create_progress_bar(unique_sighted, total_fiskers)

        # Get location text if GPS coordinates are available
        location_text = None
        if latitude is not None and longitude is not None:
            geocoder = Geocoder()
            location_text = geocoder.get_neighborhood_name(latitude, longitude)
            if not location_text:
                location_text = f"{latitude:.4f}, {longitude:.4f}"

        return ordinal, formatted_time, progress_bar, location_text

    def format_sighting_text(
        self,
        license_plate: str,
        sighting_count: int,
        timestamp: str,
        latitude: float | None,
        longitude: float | None,
        unique_sighted: int,
        total_fiskers: int,
        contributed_by: str | None = None
    ) -> str:
        """
        Format the text for a sighting post preview.

        Args:
            license_plate: Vehicle license plate
            sighting_count: Number of times this plate has been spotted
            timestamp: When the sighting occurred (ISO format)
            latitude: GPS latitude (may be None)
            longitude: GPS longitude (may be None)
            unique_sighted: Number of unique Fisker plates sighted
            total_fiskers: Total number of Fisker vehicles in TLC database
            contributed_by: Optional name of contributor

        Returns:
            Formatted post text
        """
        ordinal, formatted_time, progress_bar, location_text = self._build_sighting_text_parts(
            license_plate, sighting_count, timestamp, latitude, longitude,
            unique_sighted, total_fiskers
        )

        # Build post text
        post_text = (
            f"🌊 Fisker Ocean, plate {license_plate} spotted for the {ordinal} time\n"
            f"📈 {progress_bar}\n\n"
            f"📅 {formatted_time}"
        )

        # Add location if available
        if location_text:
            if latitude is not None and longitude is not None:
                # Check if it's coordinates or a neighborhood name
                if ',' in location_text and '.' in location_text:
                    post_text += f"\n📍 Spotted at {location_text}"
                else:
                    post_text += f"\n📍 Spotted in {location_text}"

        # Add contributor line if provided
        if contributed_by:
            post_text += f"\n\n🙏 Contributed by {contributed_by}"

        return post_text

    def create_sighting_post(
        self,
        license_plate: str,
        sighting_count: int,
        timestamp: str,
        latitude: float | None,
        longitude: float | None,
        images: list[str],
        unique_sighted: int,
        total_fiskers: int,
        contributed_by: str | None = None
    ) -> dict:
        """
        Create a formatted sighting post for Bluesky.

        Args:
            license_plate: Vehicle license plate
            sighting_count: Number of times this plate has been spotted
            timestamp: When the sighting occurred (ISO format)
            latitude: GPS latitude (may be None)
            longitude: GPS longitude (may be None)
            images: List of image paths (sighting image, and optionally map image)
            unique_sighted: Number of unique Fisker plates sighted
            total_fiskers: Total number of Fisker vehicles in TLC database
            contributed_by: Optional name/handle of contributor (if starts with @, creates mention)

        Returns:
            Post response from Bluesky API
        """
        # Build post using TextBuilder to support mentions
        text_builder = client_utils.TextBuilder()

        # Get text parts using shared logic
        ordinal, formatted_time, progress_bar, location_text = self._build_sighting_text_parts(
            license_plate, sighting_count, timestamp, latitude, longitude,
            unique_sighted, total_fiskers
        )

        # Add main post content
        text_builder.text(
            f"🌊 Fisker Ocean, plate {license_plate} spotted for the {ordinal} time\n"
            f"📈 {progress_bar}\n\n"
            f"📅 {formatted_time}"
        )

        # Add location if available
        if location_text:
            # Check if it's coordinates or a neighborhood name
            if ',' in location_text and '.' in location_text:
                text_builder.text(f"\n📍 Spotted at {location_text}")
            else:
                text_builder.text(f"\n📍 Spotted in {location_text}")

        # Add contributor with mention support
        if contributed_by:
            if contributed_by.startswith('@'):
                # Extract handle (remove @ prefix)
                handle = contributed_by[1:]

                try:
                    # Resolve handle to DID
                    profile = self.client.get_profile(handle)

                    # Add mention
                    text_builder.text("\n\n🙏 Contributed by ")
                    text_builder.mention(contributed_by, profile.did)
                except Exception as e:
                    # If resolution fails, fall back to plain text
                    print(f"Warning: Could not resolve handle {handle}, using plain text: {e}")
                    text_builder.text(f"\n\n🙏 Contributed by {contributed_by}")
            else:
                # Plain text contributor
                text_builder.text(f"\n\n🙏 Contributed by {contributed_by}")

        # Generate alt text for images
        image_alts = []

        # Alt text for sighting image
        if latitude is not None and longitude is not None:
            geocoder = Geocoder()
            location_text = geocoder.get_neighborhood_name(latitude, longitude)

            if location_text:
                location_for_alt = location_text
            else:
                location_for_alt = f"coordinates {latitude:.4f}, {longitude:.4f}"

            image_alts.append(f"Spotted a Fisker Ocean with plate {license_plate} in {location_for_alt}")
        else:
            image_alts.append(f"Spotted a Fisker Ocean with plate {license_plate}")

        # Alt text for map image (if present)
        if len(images) > 1:
            if latitude is not None and longitude is not None:
                geocoder = Geocoder()
                location_text = geocoder.get_neighborhood_name(latitude, longitude)

                if location_text:
                    location_for_alt = location_text
                else:
                    location_for_alt = f"coordinates {latitude:.4f}, {longitude:.4f}"

                image_alts.append(f"Map of the location the Fisker Ocean was spotted in {location_for_alt}")
            else:
                image_alts.append(f"Map image")

        # Upload images with alt text
        embed = None
        if images:
            if len(images) > 4:
                raise ValueError("Bluesky supports a maximum of 4 images per post")

            uploaded_images = [self.upload_image(img, alt) for img, alt in zip(images, image_alts)]
            embed = models.AppBskyEmbedImages.Main(images=uploaded_images)

        # Send post with TextBuilder
        response = self.client.send_post(text_builder, embed=embed)
        return response

    @staticmethod
    def _get_ordinal(n: int) -> str:
        """Convert number to ordinal string (1st, 2nd, 3rd, etc.)"""
        if 11 <= (n % 100) <= 13:
            suffix = 'th'
        else:
            suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
        return f"{n}{suffix}"

    def create_batch_sighting_post(
        self,
        sightings: list[tuple],
        unique_sighted: int,
        total_fiskers: int
    ) -> dict:
        """
        Create a batch post for multiple sightings.

        Args:
            sightings: List of sighting tuples from get_unposted_sightings()
                (id, license_plate, timestamp, lat, lon, image_path, created_at, post_uri,
                 contributor_id, preferred_name, bluesky_handle, phone_number)
            unique_sighted: Number of unique Fisker plates sighted
            total_fiskers: Total number of Fisker vehicles in TLC database

        Returns:
            Post response from Bluesky API
        """
        if not sightings:
            raise ValueError("No sightings provided for batch post")

        if len(sightings) > 4:
            raise ValueError("Maximum 4 sightings per batch post (Bluesky image limit)")

        # Extract unique contributors with display names
        # Sighting tuple: (id, license_plate, timestamp, lat, lon, image_path, created_at, post_uri,
        #                  contributor_id, preferred_name, bluesky_handle, phone_number)
        contributor_display_names = set()
        for sighting in sightings:
            preferred_name = sighting[9]  # preferred_name
            bluesky_handle = sighting[10]  # bluesky_handle

            if preferred_name:
                contributor_display_names.add(preferred_name)
            elif bluesky_handle:
                contributor_display_names.add(bluesky_handle)
            # If neither, they remain anonymous (not added to set)

        # Extract license plates
        plates = [sighting[1] for sighting in sightings]  # license_plate column

        # Build post text
        text_builder = client_utils.TextBuilder()

        # Header
        sighting_word = "sighting" if len(sightings) == 1 else "sightings"

        # Count total contributors (including anonymous)
        has_contributors = any(s[8] is not None for s in sightings)  # contributor_id not None
        unique_contributor_ids = set(s[8] for s in sightings if s[8] is not None)
        num_contributors = len(unique_contributor_ids)

        text_builder.text(f"🌊 {len(sightings)} new {sighting_word}")

        if num_contributors > 0:
            contributor_word = "contributor" if num_contributors == 1 else "contributors"
            text_builder.text(f" from {num_contributors} {contributor_word}\n")
        else:
            text_builder.text("\n")

        # Progress bar
        progress_bar = self._create_progress_bar(unique_sighted, total_fiskers)
        text_builder.text(f"📈 {progress_bar}\n\n")

        # License plates
        plates_text = ", ".join(plates)
        text_builder.text(f"🚗 {plates_text}")

        # Add contributors with mentions
        if contributor_display_names:
            text_builder.text("\n\n🙏 Thanks to: ")

            contributor_list = sorted(list(contributor_display_names))
            for i, display_name in enumerate(contributor_list):
                if display_name.startswith('@'):
                    # Extract handle (remove @ prefix)
                    handle = display_name[1:]

                    try:
                        # Resolve handle to DID
                        profile = self.client.get_profile(handle)
                        text_builder.mention(display_name, profile.did)
                    except Exception as e:
                        # If resolution fails, fall back to plain text
                        print(f"Warning: Could not resolve handle {handle}, using plain text: {e}")
                        text_builder.text(display_name)
                else:
                    # Plain text contributor name
                    text_builder.text(display_name)

                # Add comma separator if not last
                if i < len(contributor_list) - 1:
                    text_builder.text(", ")

        # Collect images (max 4)
        images = []
        image_alts = []
        for sighting in sightings[:4]:  # Only take first 4 for image limit
            image_path = sighting[5]  # image_path column
            license_plate = sighting[1]  # license_plate column

            images.append(image_path)
            image_alts.append(f"Fisker Ocean with plate {license_plate}")

        # Upload images
        embed = None
        if images:
            uploaded_images = [self.upload_image(img, alt) for img, alt in zip(images, image_alts)]
            embed = models.AppBskyEmbedImages.Main(images=uploaded_images)

        # Send post
        response = self.client.send_post(text_builder, embed=embed)
        return response

    @staticmethod
    def _get_ordinal(n: int) -> str:
        """Convert number to ordinal string (1st, 2nd, 3rd, etc.)"""
        if 11 <= (n % 100) <= 13:
            suffix = 'th'
        else:
            suffix = ['th', 'st', 'nd', 'rd', 'th'][min(n % 10, 4)]
        return f"{n}{suffix}"

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
        filled_bar = '█' * filled
        empty_bar = '▒' * empty
        bar = filled_bar + empty_bar

        return f"{percentage:.1f}% {bar} ({current} out of {total})"
