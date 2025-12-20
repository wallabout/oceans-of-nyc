"""Image hashing utilities for duplicate detection.

This module provides both cryptographic (SHA-256) and perceptual hashing
for detecting exact and near-duplicate images.
"""

import hashlib

import imagehash
from PIL import Image


class ImageHashError(Exception):
    """Raised when image hashing fails."""

    pass


def calculate_sha256(image_path: str) -> str:
    """
    Calculate SHA-256 hash of image file.

    This provides exact duplicate detection - any modification to the file
    will result in a different hash.

    Args:
        image_path: Path to image file

    Returns:
        64-character hex string of SHA-256 hash

    Raises:
        ImageHashError: If file cannot be read
    """
    try:
        sha256_hash = hashlib.sha256()
        with open(image_path, "rb") as f:
            # Read file in chunks to handle large images efficiently
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except OSError as e:
        raise ImageHashError(f"Failed to read image file {image_path}: {e}")


def calculate_perceptual_hash(image_path: str) -> str:
    """
    Calculate perceptual hash (dHash) of image.

    Perceptual hashing generates similar hashes for visually similar images,
    making it resistant to minor edits like resizing, compression, or rotation.
    Uses dHash (difference hash) algorithm for speed and robustness.

    Args:
        image_path: Path to image file

    Returns:
        16-character hex string representing 64-bit perceptual hash

    Raises:
        ImageHashError: If image cannot be opened or processed
    """
    try:
        with Image.open(image_path) as img:
            # Use dHash (difference hash) - good balance of speed and accuracy
            # Hash size of 8 gives us 64 bits = 16 hex characters
            phash = imagehash.dhash(img, hash_size=8)
            return str(phash)
    except OSError as e:
        raise ImageHashError(f"Failed to open image file {image_path}: {e}")
    except Exception as e:
        raise ImageHashError(f"Failed to calculate perceptual hash for {image_path}: {e}")


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Calculate Hamming distance between two perceptual hashes.

    Hamming distance measures the number of differing bits between two hashes.
    Lower distance = more similar images.

    Args:
        hash1: First perceptual hash (hex string)
        hash2: Second perceptual hash (hex string)

    Returns:
        Number of differing bits (0-64 for 64-bit hash)

    Raises:
        ValueError: If hashes are not the same length or invalid hex
    """
    if len(hash1) != len(hash2):
        raise ValueError(f"Hash lengths must match: {len(hash1)} != {len(hash2)}")

    try:
        # Convert hex to binary and count differing bits
        bits1 = bin(int(hash1, 16))[2:].zfill(len(hash1) * 4)
        bits2 = bin(int(hash2, 16))[2:].zfill(len(hash2) * 4)
        return sum(b1 != b2 for b1, b2 in zip(bits1, bits2, strict=False))
    except ValueError as e:
        raise ValueError(f"Invalid hex hash: {e}")


def calculate_both_hashes(image_path: str) -> tuple[str, str]:
    """
    Calculate both SHA-256 and perceptual hashes for an image.

    Convenience function for getting both hashes at once.

    Args:
        image_path: Path to image file

    Returns:
        Tuple of (sha256_hash, perceptual_hash)

    Raises:
        ImageHashError: If image cannot be processed
    """
    sha256 = calculate_sha256(image_path)
    phash = calculate_perceptual_hash(image_path)
    return sha256, phash


def find_similar_images(
    db_connection,
    perceptual_hash: str,
    threshold: int = 5,
) -> list[dict]:
    """
    Find images in database with similar perceptual hash.

    Args:
        db_connection: Active database connection
        perceptual_hash: Perceptual hash to compare against
        threshold: Maximum Hamming distance to consider similar (0-64)
                  Lower = stricter matching. Recommended: 5-10

    Returns:
        List of dicts with keys: id, image_path, created_at, image_hash_perceptual, distance
        Sorted by distance (most similar first)

    Example:
        >>> conn = psycopg2.connect(DATABASE_URL)
        >>> similar = find_similar_images(conn, "abc123...", threshold=5)
        >>> if similar:
        ...     print(f"Found {len(similar)} similar images")
        ...     print(f"Most similar: {similar[0]['image_path']} (distance: {similar[0]['distance']})")
    """
    cursor = db_connection.cursor()

    # Get all sightings with perceptual hashes
    cursor.execute(
        """
        SELECT id, image_path, created_at, image_hash_perceptual
        FROM sightings
        WHERE image_hash_perceptual IS NOT NULL
        """
    )

    results = []
    for row in cursor.fetchall():
        sighting_id, image_path, created_at, db_hash = row
        try:
            distance = hamming_distance(perceptual_hash, db_hash)
            if distance <= threshold:
                results.append(
                    {
                        "id": sighting_id,
                        "image_path": image_path,
                        "created_at": created_at,
                        "image_hash_perceptual": db_hash,
                        "distance": distance,
                    }
                )
        except ValueError:
            # Skip invalid hashes
            continue

    # Sort by distance (most similar first)
    results.sort(key=lambda x: x["distance"])
    return results


def check_exact_duplicate(db_connection, sha256_hash: str) -> dict | None:
    """
    Check if an exact duplicate exists in the database.

    Args:
        db_connection: Active database connection
        sha256_hash: SHA-256 hash to check

    Returns:
        Dict with sighting info if found, None otherwise
        Keys: id, image_path, created_at, license_plate

    Example:
        >>> conn = psycopg2.connect(DATABASE_URL)
        >>> sha256 = calculate_sha256("/path/to/image.jpg")
        >>> duplicate = check_exact_duplicate(conn, sha256)
        >>> if duplicate:
        ...     print(f"Exact duplicate found: sighting #{duplicate['id']}")
    """
    cursor = db_connection.cursor()

    cursor.execute(
        """
        SELECT id, image_path, created_at, license_plate
        FROM sightings
        WHERE image_hash_sha256 = %s
        LIMIT 1
        """,
        (sha256_hash,),
    )

    row = cursor.fetchone()
    if row:
        return {
            "id": row[0],
            "image_path": row[1],
            "created_at": row[2],
            "license_plate": row[3],
        }
    return None
