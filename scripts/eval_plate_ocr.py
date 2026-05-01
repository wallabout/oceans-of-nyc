#!/usr/bin/env python3
"""
Evaluate plate OCR accuracy against labeled sightings.

Usage:
    python scripts/eval_plate_ocr.py [--sample N] [--seed S]

Randomly samples N sightings from sightings_export (where both image_filename
and license_plate are present), runs extract_plate_from_image on each, and
reports how often the extracted plate matches the known value.
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

import os

from database import SightingsDatabase
from utils.plate_ocr import extract_plate_from_image
from utils.r2_storage import R2Storage


def fetch_sample(n: int, seed: int | None) -> list[tuple[str, str]]:
    """Return up to n (image_filename, license_plate) pairs from sightings_export."""
    db = SightingsDatabase()
    conn = db._get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT image_filename, license_plate
        FROM sightings_export
        WHERE image_filename IS NOT NULL
          AND license_plate  IS NOT NULL
    """)
    rows = cursor.fetchall()
    conn.close()

    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:n]


def download_image(r2: R2Storage, image_filename: str) -> bytes | None:
    """Download original image bytes from R2; returns None on error."""
    object_key = f"sightings/{image_filename}"
    try:
        response = r2.s3_client.get_object(Bucket=r2.bucket_name, Key=object_key)
        return response["Body"].read()
    except Exception as e:
        print(f"  ⚠ download failed for {image_filename}: {e}")
        return None


def run_eval(sample_size: int, seed: int | None) -> None:
    print(f"Sampling {sample_size} sightings (seed={seed})…")
    rows = fetch_sample(sample_size, seed)
    if not rows:
        print("No labeled sightings found.")
        return

    actual_n = len(rows)
    if actual_n < sample_size:
        print(f"Only {actual_n} labeled sightings available; using all of them.")

    r2 = R2Storage()

    correct = 0
    wrong = 0
    no_result = 0
    download_errors = 0

    for i, (image_filename, known_plate) in enumerate(rows, 1):
        prefix = f"[{i}/{actual_n}]"
        image_bytes = download_image(r2, image_filename)
        if image_bytes is None:
            download_errors += 1
            print(f"{prefix} SKIP  {image_filename}")
            continue

        extracted = extract_plate_from_image(image_bytes)

        if extracted is None:
            no_result += 1
            status = "MISS "
        elif extracted == known_plate:
            correct += 1
            status = "OK   "
        else:
            wrong += 1
            status = "WRONG"

        print(f"{prefix} {status}  known={known_plate}  extracted={extracted}  ({image_filename})")

    evaluated = correct + wrong + no_result
    print()
    print("─" * 50)
    print(f"Evaluated : {evaluated}")
    print(f"Correct   : {correct}")
    print(f"Wrong     : {wrong}")
    print(f"No result : {no_result}")
    if download_errors:
        print(f"Skipped   : {download_errors} (download errors)")
    if evaluated:
        accuracy = correct / evaluated * 100
        recall = correct / (correct + no_result) * 100 if (correct + no_result) else 0.0
        print(f"Accuracy  : {accuracy:.1f}%  (correct / evaluated)")
        print(f"Recall    : {recall:.1f}%  (correct / (correct + no result))")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate plate OCR accuracy.")
    parser.add_argument("--sample", type=int, default=50, metavar="N",
                        help="Number of sightings to evaluate (default: 50)")
    parser.add_argument("--seed", type=int, default=None, metavar="S",
                        help="Random seed for reproducibility (default: random)")
    args = parser.parse_args()
    run_eval(args.sample, args.seed)
