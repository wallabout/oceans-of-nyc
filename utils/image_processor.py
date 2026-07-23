"""Image processing utilities for sightings."""

import io
import os
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps


class ImageProcessor:
    """Process and store sighting images in multiple formats."""

    def __init__(self, volume_path: str = "/data"):
        """
        Initialize image processor.

        Args:
            volume_path: Base path for Modal volume storage
        """
        self.volume_path = volume_path

        # Use env vars for paths, with backwards-compatible defaults
        self.originals_path = os.getenv(
            "SIGHTING_ORIGINAL_STORAGE_PATH", f"{volume_path}/sightings/original"
        )
        self.web_path = os.getenv("SIGHTING_WEB_STORAGE_PATH", f"{volume_path}/sightings/web")
        self.image_base_uri = os.getenv(
            "SIGHTING_IMAGE_BASE_URI", "https://cdn.oceansofnyc.com/sightings/"
        )

        # Handle relative paths (prepend volume_path)
        if not self.originals_path.startswith("/"):
            self.originals_path = f"{volume_path}/{self.originals_path}"
        if not self.web_path.startswith("/"):
            self.web_path = f"{volume_path}/{self.web_path}"

        # Directories are created lazily when files are first written

    def generate_filename(self, license_plate: str, image_timestamp: datetime) -> str:
        """
        Generate unified filename for a sighting image.

        Args:
            license_plate: Vehicle license plate (e.g., "T680368C")
            image_timestamp: Timestamp when image was taken

        Returns:
            Filename in format: {plate}_{yyyymmdd_hhmmss_ssss}.jpg
            Example: T680368C_20251206_184123_2345.jpg
        """
        ts_str = image_timestamp.strftime("%Y%m%d_%H%M%S")
        # Use microseconds / 100 to get 4-digit subsecond precision
        micros = f"{image_timestamp.microsecond // 100:04d}"
        return f"{license_plate}_{ts_str}_{micros}.jpg"

    def get_web_url(self, filename: str) -> str:
        """
        Construct full web URL for an image filename.

        Args:
            filename: Image filename (e.g., "T680368C_20251206_184123_2345.jpg")

        Returns:
            Full URL (e.g., "https://cdn.oceansofnyc.com/sightings/T680368C_20251206_184123_2345.jpg")
        """
        base = self.image_base_uri.rstrip("/")
        return f"{base}/{filename}"

    def get_original_path(self, filename: str) -> str:
        """
        Derive full path to original image from filename.

        Args:
            filename: Image filename (e.g., "T680368C_20251206_184123_2345.jpg")

        Returns:
            Full path (e.g., "/data/sightings/original/T680368C_20251206_184123_2345.jpg")
        """
        return f"{self.originals_path}/{filename}"

    def rename_to_final(self, temp_path: str, final_filename: str) -> str:
        """
        Rename a temp file to its final filename location.

        Args:
            temp_path: Current path to the temp file
            final_filename: The final filename (e.g., "T680368C_20251206_184123_2345.jpg")

        Returns:
            Path to the renamed file
        """
        import shutil

        final_path = self.get_original_path(final_filename)
        final_web_path = f"{self.web_path}/{final_filename}"

        # Rename original file
        if temp_path != final_path and os.path.exists(temp_path):
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            shutil.move(temp_path, final_path)

        # Also rename web version if it exists at temp location
        temp_filename = Path(temp_path).name
        temp_web_path = f"{self.web_path}/{temp_filename}"
        if os.path.exists(temp_web_path) and temp_web_path != final_web_path:
            shutil.move(temp_web_path, final_web_path)

        return final_path

    def save_original(self, image_data: bytes, filename: str, max_retries: int = 3) -> str:
        """
        Save original full-resolution image to volume with verification.

        Args:
            image_data: Raw image bytes
            filename: Filename to save as (e.g., "sighting_20240101_123456_1234.jpg")
            max_retries: Number of write attempts

        Returns:
            Path to saved original image

        Raises:
            IOError: If the file could not be saved after all retries
        """
        import time

        original_path = f"{self.originals_path}/{filename}"
        os.makedirs(self.originals_path, exist_ok=True)

        for attempt in range(1, max_retries + 1):
            with open(original_path, "wb") as f:
                f.write(image_data)
                f.flush()
                os.fsync(f.fileno())

            # Verify the file was written correctly
            if os.path.exists(original_path) and os.path.getsize(original_path) == len(image_data):
                return original_path

            print(
                f"⚠️ Original save verification failed (attempt {attempt}/{max_retries}): {filename}"
            )
            if attempt < max_retries:
                time.sleep(1)

        raise OSError(f"Failed to save original image after {max_retries} attempts: {filename}")

    def create_web_version(
        self, original_path: str, max_width: int = 1200, max_height: int = 1200, quality: int = 85
    ) -> tuple[bytes, str]:
        """
        Create web-optimized version of image.

        Args:
            original_path: Path to original image
            max_width: Maximum width for web version
            max_height: Maximum height for web version
            quality: JPEG quality (1-100)

        Returns:
            Tuple of (image_bytes, filename)
        """
        img: Image.Image = ImageOps.exif_transpose(Image.open(original_path))

        # Convert RGBA to RGB if necessary
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if needed
        if img.width > max_width or img.height > max_height:
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        image_bytes = buffer.getvalue()

        # Use same filename for web version (no web_ prefix in new scheme)
        original_filename = Path(original_path).name
        web_filename = original_filename

        return image_bytes, web_filename

    def create_web_version_from_bytes(
        self, image_bytes: bytes, max_width: int = 1200, max_height: int = 1200, quality: int = 85
    ) -> tuple[bytes, str]:
        """
        Create web-optimized version of image from bytes.

        Args:
            image_bytes: Raw image bytes
            max_width: Maximum width for web version
            max_height: Maximum height for web version
            quality: JPEG quality (1-100)

        Returns:
            Tuple of (processed_image_bytes, generic_filename)
        """
        img: Image.Image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes)))

        # Convert RGBA to RGB if necessary
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if needed
        if img.width > max_width or img.height > max_height:
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        # Save to bytes
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        processed_bytes = buffer.getvalue()

        web_filename = "web_image.jpg"
        return processed_bytes, web_filename

    def save_web_version_local(self, web_bytes: bytes, filename: str) -> str:
        """
        Save web version to local volume (for backup/caching).

        Args:
            web_bytes: Processed image bytes
            filename: Filename for web version

        Returns:
            Path to saved web image
        """
        web_path = f"{self.web_path}/{filename}"

        os.makedirs(self.web_path, exist_ok=True)
        with open(web_path, "wb") as f:
            f.write(web_bytes)

        return web_path

    def get_web_path(self, filename: str) -> str:
        """
        Derive full path to web image from filename.

        Args:
            filename: Image filename (e.g., "T680368C_20251206_184123_2345.jpg")

        Returns:
            Full path (e.g., "/data/sightings/web/T680368C_20251206_184123_2345.jpg")
        """
        return f"{self.web_path}/{filename}"

    def upload_web_version(self, filename: str, r2_folder: str = "sightings") -> str | None:
        """
        Upload the local web version to R2 using the final filename.

        Args:
            filename: Final image filename
            r2_folder: Folder path in R2 bucket

        Returns:
            Public URL if uploaded, otherwise None
        """
        web_path = self.get_web_path(filename)
        if not os.path.exists(web_path):
            print(f"⚠ Web file not found for upload: {web_path}")
            return None

        try:
            from utils.r2_storage import R2Storage

            r2 = R2Storage()
            object_key = f"{r2_folder}/{filename}"
            web_url = r2.upload_file(web_path, object_key, content_type="image/jpeg")
            print(f"✓ Uploaded to R2: {web_url}")
            return web_url
        except Exception as e:
            print(f"⚠ R2 upload failed: {e}")
            return None

    def process_sighting_image(
        self,
        image_data: bytes,
        filename: str,
        upload_to_r2: bool = True,
        r2_folder: str = "sightings",
    ) -> dict[str, str]:
        """
        Full processing pipeline: save original, create web version, optionally upload to R2.

        Args:
            image_data: Raw image bytes
            filename: Base filename
            upload_to_r2: Whether to upload web version to R2
            r2_folder: Folder path in R2 bucket

        Returns:
            Dictionary with paths:
                - original_path: Local path to original
                - web_path_local: Local path to web version
                - web_url: Public R2 URL (if uploaded)
        """
        # Save original
        original_path = self.save_original(image_data, filename)

        # Create web version
        web_bytes, web_filename = self.create_web_version(original_path)

        # Save web version locally
        web_path_local = self.save_web_version_local(web_bytes, web_filename)

        result = {
            "original_path": original_path,
            "web_path_local": web_path_local,
        }

        # Upload to R2 if requested
        if upload_to_r2:
            try:
                from utils.r2_storage import R2Storage

                r2 = R2Storage()
                object_key = f"{r2_folder}/{web_filename}"
                web_url = r2.upload_bytes(web_bytes, object_key, content_type="image/jpeg")
                result["web_url"] = web_url
                print(f"✓ Uploaded to R2: {web_url}")
            except Exception as e:
                print(f"⚠ R2 upload failed: {e}")
                # Continue without R2 URL - not critical for initial save

        return result
