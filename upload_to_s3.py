#!/usr/bin/env python3
"""
AWS S3 Upload Utility
=====================
A robust, professional script to upload files or directories to AWS S3.

Features:
  1. Support for single file or entire directory uploads.
  2. Flexible authentication:
     - Automatically uses the default AWS credential chain (AWS CLI config, IAM role, etc.).
     - Loads credentials from a local `.env` file if present.
     - Accepts explicit command-line arguments for keys and token.
     - Supports named AWS profiles.
  3. Visual progress indicator (uses tqdm if installed; falls back to a clean text progress bar).
  4. Automatic MIME-type detection.

Requirements:
    pip install boto3
    (Optional) pip install tqdm python-dotenv

Usage:
    # Upload a single file
    python upload_to_s3.py --file "Regulatory & Approvals/openfda_data/openfda_drugs.csv" --bucket my-bucket-name

    # Upload an entire directory
    python upload_to_s3.py --dir "Regulatory & Approvals/orangebook_data" --bucket my-bucket-name --key-prefix orangebook/
"""

import os
import sys
import argparse
import mimetypes
from pathlib import Path

# Try to import boto3
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("\n[ERROR] 'boto3' library is required to run this script.", file=sys.stderr)
    print("Please install it using: pip install boto3\n", file=sys.stderr)
    sys.exit(1)

# Try to import tqdm for progress bar
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# Helper to load a .env file manually to avoid dependency on python-dotenv
def load_env_file(env_path: Path):
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                os.environ[key] = val

class ProgressPercentage(object):
    """Callback class to show upload progress."""
    def __init__(self, filename, filesize):
        self._filename = filename
        self._size = filesize
        self._seen_so_far = 0
        self._pbar = None
        if tqdm:
            self._pbar = tqdm(
                total=self._size,
                unit='B',
                unit_scale=True,
                desc=f"Uploading {os.path.basename(filename)}"
            )

    def __call__(self, bytes_amount):
        self._seen_so_far += bytes_amount
        if self._pbar:
            self._pbar.update(bytes_amount)
        else:
            percentage = (self._seen_so_far / self._size) * 100 if self._size > 0 else 100
            sys.stdout.write(
                f"\rUploading {os.path.basename(self._filename)}: "
                f"{self._seen_so_far}/{self._size} bytes ({percentage:.2f}%)"
            )
            sys.stdout.flush()

    def close(self):
        if self._pbar:
            self._pbar.close()
        else:
            sys.stdout.write("\n")
            sys.stdout.flush()

def get_s3_client(args):
    """Initializes and returns the boto3 S3 client based on credentials."""
    # 1. Load from .env if specified or if default .env exists
    env_file = Path(args.env) if args.env else Path(".env")
    if env_file.exists():
        load_env_file(env_file)

    # 2. Extract credentials (CLI args take precedence, then env variables)
    aws_access_key = args.access_key or os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_key = args.secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
    aws_token = args.session_token or os.environ.get("AWS_SESSION_TOKEN")
    region = args.region or os.environ.get("AWS_DEFAULT_REGION")

    # 3. Create session
    if args.profile:
        print(f"Using AWS Profile: {args.profile}")
        session = boto3.Session(profile_name=args.profile)
    elif aws_access_key and aws_secret_key:
        print("Using explicit AWS credentials (provided via arguments or env variables)")
        session = boto3.Session(
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            aws_session_token=aws_token,
            region_name=region
        )
    else:
        print("Using default AWS credential chain (boto3 default session)")
        session = boto3.Session(region_name=region)

    return session.client("s3")

def upload_file(s3_client, local_path: Path, bucket: str, s3_key: str, skip_existing: bool = False):
    """Uploads a single file to S3 with a progress indicator."""
    if not local_path.exists():
        print(f"[ERROR] Local file does not exist: {local_path}", file=sys.stderr)
        return False

    file_size = local_path.stat().st_size

    if skip_existing:
        try:
            response = s3_client.head_object(Bucket=bucket, Key=s3_key)
            s3_size = response.get('ContentLength', 0)
            if s3_size == file_size:
                print(f"Skipping: {local_path.name} (already exists with same size: {file_size} bytes)")
                return True
        except ClientError as e:
            # 404 means the file does not exist, which is expected.
            # Any other status code is logged as a warning.
            if e.response.get('Error', {}).get('Code') != '404':
                print(f"[WARNING] Error checking S3 object s3://{bucket}/{s3_key}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[WARNING] Error checking S3 object s3://{bucket}/{s3_key}: {e}", file=sys.stderr)

    content_type, _ = mimetypes.guess_type(str(local_path))
    if not content_type:
        content_type = "binary/octet-stream"

    extra_args = {
        "ContentType": content_type
    }

    print(f"Destination: s3://{bucket}/{s3_key} ({content_type})")
    progress = ProgressPercentage(str(local_path), file_size)
    try:
        s3_client.upload_file(
            Filename=str(local_path),
            Bucket=bucket,
            Key=s3_key,
            ExtraArgs=extra_args,
            Callback=progress
        )
        progress.close()
        print(f"Successfully uploaded: {local_path.name}")
        return True
    except (BotoCoreError, ClientError) as e:
        progress.close()
        print(f"\n[ERROR] Failed to upload {local_path.name}: {e}", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Upload files or directories to AWS S3.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # File / Directory Targets
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-f", "--file", type=str, help="Path to the local file to upload.")
    group.add_argument("-d", "--dir", type=str, help="Path to the local directory to upload.")

    # S3 Destination
    parser.add_argument("-b", "--bucket", type=str, default="moine-data", help="Target S3 bucket name.")
    parser.add_argument("-k", "--key", type=str, help="S3 Key (destination path). For directory uploads, this acts as a prefix.")
    parser.add_argument("--key-prefix", type=str, help="Prefix to prepend to S3 keys (useful for directory uploads).")

    # AWS Credentials / Configuration
    parser.add_argument("--access-key", type=str, help="AWS Access Key ID.")
    parser.add_argument("--secret-key", type=str, help="AWS Secret Access Key.")
    parser.add_argument("--session-token", type=str, help="AWS Session Token (if using temporary credentials).")
    parser.add_argument("--profile", type=str, default="moine", help="AWS Profile name to use from ~/.aws/credentials.")
    parser.add_argument("--region", type=str, default="us-east-1", help="AWS Region (e.g., us-east-1).")
    parser.add_argument("--env", type=str, help="Path to a custom .env file to load credentials from.")
    parser.add_argument("--overwrite", action="store_true", help="Force overwrite files even if they already exist on S3 with the same size.")
    parser.add_argument("--only-csv", action="store_true", help="Only upload CSV files, ignoring other file extensions.")

    args = parser.parse_args()

    # Initialize client
    try:
        s3_client = get_s3_client(args)
    except Exception as e:
        print(f"[ERROR] Failed to initialize AWS Session: {e}", file=sys.stderr)
        sys.exit(1)

    # Handle Single File Upload
    if args.file:
        local_file = Path(args.file)
        # Determine S3 Key
        s3_key = args.key
        if not s3_key:
            # Fallback to the file's basename
            s3_key = local_file.name
            if args.key_prefix:
                s3_key = f"{args.key_prefix.rstrip('/')}/{s3_key}"

        print(f"Uploading file: {local_file}")
        success = upload_file(s3_client, local_file, args.bucket, s3_key, skip_existing=not args.overwrite)
        sys.exit(0 if success else 1)

    # Handle Directory Upload
    elif args.dir:
        local_dir = Path(args.dir)
        if not local_dir.is_dir():
            print(f"[ERROR] Provided path is not a directory: {local_dir}", file=sys.stderr)
            sys.exit(1)

        print(f"Uploading directory: {local_dir}")
        prefix = args.key_prefix or args.key or ""
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        # Resolve relative paths from workspace root to preserve structure
        workspace_root = Path.cwd().resolve()
        try:
            # Check if local_dir is inside the workspace_root
            local_dir.resolve().relative_to(workspace_root)
            base_dir = workspace_root
        except ValueError:
            # Fallback to local_dir if run from outside the workspace
            base_dir = local_dir

        files_to_upload = [p for p in local_dir.rglob("*") if p.is_file()]
        if args.only_csv:
            files_to_upload = [p for p in files_to_upload if p.suffix.lower() == ".csv"]

        print(f"Found {len(files_to_upload)} files to upload.")

        success_count = 0
        for local_file in files_to_upload:
            # Compute relative path using the resolved base directory to maintain project structure
            rel_path = local_file.resolve().relative_to(base_dir.resolve())
            s3_key = f"{prefix}{rel_path.as_posix()}"
            
            print(f"\n--- [{success_count + 1}/{len(files_to_upload)}] ---")
            if upload_file(s3_client, local_file, args.bucket, s3_key, skip_existing=not args.overwrite):
                success_count += 1

        print(f"\nUpload completed: {success_count}/{len(files_to_upload)} files uploaded successfully.")
        sys.exit(0 if success_count == len(files_to_upload) else 1)

if __name__ == "__main__":
    main()
