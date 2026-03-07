"""
One-time migration script: upload all existing local images to S3.
Run: python migrate_to_s3.py

Does NOT delete local files.
"""
import os
import sys
import mimetypes
from config import UPLOAD_DIR
import s3_storage


def main():
    if not s3_storage.is_configured():
        print("S3 not configured. Set S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET in .env")
        sys.exit(1)

    upload_dir = UPLOAD_DIR
    if not os.path.isdir(upload_dir):
        print(f"Upload directory not found: {upload_dir}")
        sys.exit(1)

    files = [f for f in os.listdir(upload_dir) if os.path.isfile(os.path.join(upload_dir, f)) and f != '.gitkeep']
    if not files:
        print("No files to migrate.")
        return

    print(f"Found {len(files)} files to upload to S3...")
    success = 0
    failed = 0

    for filename in files:
        filepath = os.path.join(upload_dir, filename)
        content_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            if s3_storage.upload(data, filename, content_type):
                success += 1
                print(f"  OK: {filename}")
            else:
                failed += 1
                print(f"  FAIL: {filename}")
        except Exception as e:
            failed += 1
            print(f"  ERROR: {filename} - {e}")

    print(f"\nDone. Uploaded: {success}, Failed: {failed}")
    if failed == 0:
        print("All files migrated successfully. Local files were NOT deleted.")


if __name__ == '__main__':
    main()
