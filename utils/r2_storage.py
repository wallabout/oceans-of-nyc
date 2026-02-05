"""Enhanced Cloudflare R2 storage utilities with retry logic and better error handling."""

import io
import os
import time
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError


class R2UploadError(Exception):
    """Base exception for R2 upload failures."""

    pass


class R2TransientError(R2UploadError):
    """Transient error that may succeed on retry."""

    pass


class R2PermanentError(R2UploadError):
    """Permanent error that won't succeed on retry."""

    pass


class R2Storage:
    """
    Enhanced Cloudflare R2 storage client with retry logic and verification.

    Features:
    - Exponential backoff retry for transient failures
    - Upload verification to confirm files exist
    - Better error classification and logging
    - Configurable retry behavior
    """

    # Transient errors that should be retried
    TRANSIENT_ERROR_CODES = {
        "RequestTimeout",
        "ServiceUnavailable",
        "ThrottlingException",
        "TooManyRequestsException",
        "InternalError",
        "SlowDown",
        "RequestTimeTooSkewed",
    }

    def __init__(
        self,
        account_id: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        bucket_name: str | None = None,
        public_url_base: str | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize R2 storage client with retry configuration.

        Args:
            account_id: Cloudflare account ID
            access_key_id: R2 access key ID
            secret_access_key: R2 secret access key
            bucket_name: R2 bucket name
            public_url_base: Public URL base for accessing images
            max_retries: Maximum number of retry attempts (default: 3)
            retry_delay: Initial retry delay in seconds (default: 1.0)

        Environment variables (if args not provided):
            CLOUDFLARE_ACCOUNT_ID
            R2_ACCESS_KEY_ID
            R2_SECRET_ACCESS_KEY
            R2_BUCKET_NAME
            R2_PUBLIC_URL_BASE
        """
        self.account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID")
        self.access_key_id = access_key_id or os.getenv("R2_ACCESS_KEY_ID")
        self.secret_access_key = secret_access_key or os.getenv("R2_SECRET_ACCESS_KEY")
        self.bucket_name = bucket_name or os.getenv("R2_BUCKET_NAME")
        self.public_url_base = public_url_base or os.getenv("R2_PUBLIC_URL_BASE")
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        if not all([self.account_id, self.access_key_id, self.secret_access_key, self.bucket_name]):
            raise ValueError(
                "R2 credentials not provided. Set CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, and R2_BUCKET_NAME environment variables."
            )

        # Initialize S3-compatible client with more aggressive timeouts and retries
        config = Config(
            signature_version="s3v4",
            retries={
                "max_attempts": max_retries + 1,  # boto3's internal retry + our retry
                "mode": "adaptive",  # Adaptive retry mode for better handling
            },
            connect_timeout=10,  # 10 seconds to establish connection
            read_timeout=30,  # 30 seconds to read response
        )

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=f"https://{self.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            config=config,
        )

    def _classify_error(self, error: Exception) -> type[R2UploadError]:
        """
        Classify an error as transient or permanent.

        Args:
            error: The exception to classify

        Returns:
            R2TransientError if error is transient, R2PermanentError otherwise
        """
        if isinstance(error, ClientError):
            error_code = error.response.get("Error", {}).get("Code", "")
            if error_code in self.TRANSIENT_ERROR_CODES:
                return R2TransientError
            # Check for HTTP status codes indicating transient errors
            status_code = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code in (408, 429, 500, 502, 503, 504):
                return R2TransientError

        if isinstance(error, BotoCoreError):
            # Most BotoCoreErrors are network-related and transient
            return R2TransientError

        # Unknown errors are treated as permanent by default
        return R2PermanentError

    def _retry_with_backoff(self, operation, *args, **kwargs):
        """
        Execute an operation with exponential backoff retry.

        Args:
            operation: Callable to execute
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation

        Returns:
            Result of operation

        Raises:
            R2UploadError: If all retries are exhausted
        """
        last_error = None
        delay = self.retry_delay

        for attempt in range(self.max_retries + 1):
            try:
                result = operation(*args, **kwargs)
                if attempt > 0:
                    print(f"✓ Upload succeeded on retry attempt {attempt}")
                return result
            except Exception as e:
                error_type = self._classify_error(e)
                last_error = error_type(str(e))

                # Don't retry permanent errors
                if error_type == R2PermanentError:
                    print(f"✗ Permanent upload error: {e}")
                    raise last_error

                # Don't retry if this was the last attempt
                if attempt >= self.max_retries:
                    print(f"✗ Upload failed after {attempt + 1} attempts: {e}")
                    raise last_error

                # Transient error - retry with exponential backoff
                print(
                    f"⚠ Transient upload error (attempt {attempt + 1}/{self.max_retries + 1}): {e}"
                )
                print(f"  Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff

        # Should never reach here, but just in case
        raise last_error

    def upload_file(
        self,
        file_path: str,
        object_key: str,
        content_type: str = "image/jpeg",
        verify: bool = True,
    ) -> str:
        """
        Upload a file to R2 storage with retry logic.

        Args:
            file_path: Local path to file
            object_key: Key/path in R2 bucket (e.g., "sightings/image_123.jpg")
            content_type: MIME type of the file
            verify: Verify file exists after upload (default: True)

        Returns:
            Public URL of the uploaded file

        Raises:
            R2UploadError: If upload fails after all retries
        """
        with open(file_path, "rb") as f:
            return self.upload_fileobj(f, object_key, content_type, verify=verify)

    def upload_fileobj(
        self,
        fileobj: BinaryIO,
        object_key: str,
        content_type: str = "image/jpeg",
        cache_control: str | None = None,
        verify: bool = True,
    ) -> str:
        """
        Upload a file object to R2 storage with retry logic.

        Args:
            fileobj: File-like object to upload
            object_key: Key/path in R2 bucket
            content_type: MIME type of the file
            cache_control: Cache-Control header value (default: 1 year for images)
            verify: Verify file exists after upload (default: True)

        Returns:
            Public URL of the uploaded file

        Raises:
            R2UploadError: If upload fails after all retries
        """
        if cache_control is None:
            cache_control = "public, max-age=31536000"  # 1 year default for images

        # Need to read content into memory for potential retries
        # (file objects can't be re-read after upload attempt)
        content = fileobj.read()
        file_size = len(content)

        def _upload():
            # Reset to beginning for each attempt
            upload_obj = io.BytesIO(content)
            self.s3_client.upload_fileobj(
                upload_obj,
                self.bucket_name,
                object_key,
                ExtraArgs={"ContentType": content_type, "CacheControl": cache_control},
            )

        # Execute upload with retry
        self._retry_with_backoff(_upload)

        # Verify upload if requested
        if verify:
            self._verify_upload(object_key, expected_size=file_size)

        # Return public URL
        return self._get_public_url(object_key)

    def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str = "image/jpeg",
        cache_control: str | None = None,
        verify: bool = True,
    ) -> str:
        """
        Upload bytes to R2 storage with retry logic.

        Args:
            data: Bytes to upload
            object_key: Key/path in R2 bucket
            content_type: MIME type of the data
            cache_control: Cache-Control header value (default: 1 year for images)
            verify: Verify file exists after upload (default: True)

        Returns:
            Public URL of the uploaded file

        Raises:
            R2UploadError: If upload fails after all retries
        """
        return self.upload_fileobj(
            io.BytesIO(data), object_key, content_type, cache_control, verify
        )

    def _verify_upload(self, object_key: str, expected_size: int | None = None) -> None:
        """
        Verify that a file exists in R2 and optionally check its size.

        Args:
            object_key: Key/path to check
            expected_size: Expected file size in bytes (optional)

        Raises:
            R2UploadError: If verification fails
        """
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=object_key)
            actual_size = response.get("ContentLength")

            if expected_size is not None and actual_size != expected_size:
                raise R2PermanentError(
                    f"Upload verification failed: size mismatch. "
                    f"Expected {expected_size} bytes, got {actual_size} bytes"
                )

            print(f"✓ Upload verified: {object_key} ({actual_size} bytes)")

        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                raise R2PermanentError(
                    f"Upload verification failed: file not found in R2: {object_key}"
                )
            raise R2TransientError(f"Upload verification failed: {e}")

    def delete_file(self, object_key: str) -> None:
        """
        Delete a file from R2 storage.

        Args:
            object_key: Key/path of file to delete
        """
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_key)

    def file_exists(self, object_key: str) -> bool:
        """
        Check if a file exists in R2 storage.

        Args:
            object_key: Key/path to check

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError:
            return False

    def _get_public_url(self, object_key: str) -> str:
        """
        Get the public URL for an object.

        Args:
            object_key: Key/path in R2 bucket

        Returns:
            Public URL
        """
        if self.public_url_base:
            return f"{self.public_url_base}/{object_key}"
        return f"https://{self.bucket_name}.{self.account_id}.r2.dev/{object_key}"
