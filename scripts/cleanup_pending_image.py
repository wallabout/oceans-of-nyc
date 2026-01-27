"""
One-off script to clean up a partially submitted image.

Usage:
    modal run scripts/cleanup_pending_image.py

This will:
1. Rename the pending original to the final filename
2. Create the web version from the original
3. Upload the web version to R2
"""

import modal

app = modal.App("cleanup-pending-image")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "pillow>=10.0.0",
        "boto3>=1.42.23",
    )
    .add_local_python_source("utils")
)

secrets = [
    modal.Secret.from_name("cloudflare-r2"),
]

volume = modal.Volume.from_name("oceans-of-nyc", create_if_missing=True)
VOLUME_PATH = "/data"


@app.local_entrypoint()
def main():
    cleanup.remote()


@app.function(
    image=image,
    secrets=secrets,
    volumes={VOLUME_PATH: volume},
)
def cleanup():
    """Clean up the pending image."""
    import os
    import shutil

    from utils.image_processor import ImageProcessor
    from utils.r2_storage import R2Storage

    # Configuration
    pending_filename = "pending_20260124_204827_4904.jpg"
    final_filename = "T663263C_20260124_204827_4904.jpg"

    originals_path = f"{VOLUME_PATH}/sightings/original"
    web_path = f"{VOLUME_PATH}/sightings/web"

    pending_path = f"{originals_path}/{pending_filename}"
    final_path = f"{originals_path}/{final_filename}"
    final_web_path = f"{web_path}/{final_filename}"

    # Check if pending file exists
    if not os.path.exists(pending_path):
        print(f"ERROR: Pending file not found: {pending_path}")
        print("\nListing files in originals directory:")
        for f in sorted(os.listdir(originals_path))[-20:]:
            print(f"  {f}")
        return

    print(f"Found pending file: {pending_path}")
    print(f"File size: {os.path.getsize(pending_path)} bytes")

    # Step 1: Rename pending to final
    print(f"\n1. Renaming to: {final_path}")
    shutil.move(pending_path, final_path)
    print("   Done!")

    # Step 2: Create web version
    print("\n2. Creating web version...")
    processor = ImageProcessor(VOLUME_PATH)
    web_bytes, _ = processor.create_web_version(final_path)
    print(f"   Web version size: {len(web_bytes)} bytes")

    # Save web version locally
    os.makedirs(web_path, exist_ok=True)
    with open(final_web_path, "wb") as f:
        f.write(web_bytes)
    print(f"   Saved to: {final_web_path}")

    # Step 3: Upload to R2
    print("\n3. Uploading to R2...")
    r2 = R2Storage()
    r2_key = f"sightings/{final_filename}"
    url = r2.upload_bytes(web_bytes, r2_key)
    print(f"   Uploaded to: {url}")

    # Commit volume changes
    volume.commit()
    print("\n4. Volume committed!")

    print("\nCleanup complete!")
