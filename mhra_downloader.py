#!/usr/bin/env python3
"""
mhra_downloader.py
==================
An intelligent, resilient, multi-threaded, and resumable data collector for
UK Medicines and Healthcare products Regulatory Agency (MHRA) drug approvals.

Features:
  1. Direct Azure Search Integration: Bypasses slow web scraping, HTML parsing,
     and 503 gateway proxy errors by querying their underlying Azure AI Search
     service directly.
  2. Resumable Checkpoint System: Progress is recorded in a thread-safe JSON
     checkpoint. Restarting the script resumes exactly where it stopped.
  3. Multi-Threaded Downloader: Concurrently downloads PDFs polite-fully using a
     thread pool with custom headers and exponential backoff retries.
  4. Atomic Writes: Downloads files to a temporary location (.tmp) first,
     preventing file corruption in case of unexpected termination.
  5. Windows-Safe Filename Sanitization: Sanitizes and structures filenames
     by document type and product name, avoiding duplicate and illegal path issues.
  6. Filtering & Limits: Allows filtering by document type and setting a
     download limit for testing purposes.

Requirements:
    pip install requests
    (Optional) pip install tqdm
"""

import os
import sys
import time
import json
import csv
import logging
import argparse
import hashlib
import threading
import re
from pathlib import Path
from urllib.parse import urlparse
import concurrent.futures
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# Optional progress indicator
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# -- Configuration & Constants -----------------------------------------------
SEARCH_ENDPOINT = "https://mhraproducts4853.search.windows.net/indexes/products-index/docs"
API_KEY = "17CCFC430C1A78A169B392A35A99C49D"
API_VERSION = "2017-11-11"

# -- Threading and Lock Controls ---------------------------------------------
checkpoint_lock = threading.Lock()
csv_lock = threading.Lock()
log = logging.getLogger("mhra_downloader")

# -- Logging Setup -----------------------------------------------------------
def setup_logging(output_dir: Path):
    """Sets up file and console logging."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "mhra_downloader.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

# -- HTTP Session Builder ----------------------------------------------------
def build_session(max_retries: int) -> requests.Session:
    """Builds a requests.Session with retries and custom headers."""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

# -- Metadata Harvester ------------------------------------------------------
def harvest_metadata(session: requests.Session, limit: int = None) -> list:
    """
    Harvests the complete metadata of all documents from the Azure search index.
    Paginates using $skip and $top.
    """
    log.info("Starting Phase 1: Metadata Harvesting from Azure AI Search...")
    all_records = []
    skip = 0
    top = 1000
    total_count = None
    
    headers = {
        "api-key": API_KEY
    }
    
    while True:
        params = {
            "api-version": API_VERSION,
            "search": "*",
            "$top": str(top),
            "$skip": str(skip),
            "$count": "true"
        }
        
        log.info(f"Querying Azure index: skip={skip}, top={top}...")
        try:
            r = session.get(SEARCH_ENDPOINT, params=params, headers=headers, timeout=20)
            if r.status_code != 200:
                log.error(f"Azure Search API returned HTTP {r.status_code}: {r.text[:500]}")
                break
                
            data = r.json()
            
            # Record total count on first page
            if total_count is None:
                total_count = data.get("@odata.count", 0)
                log.info(f"Total documents reported in Azure index: {total_count:,}")
                
            values = data.get("value", [])
            if not values:
                log.info("No more documents returned from search index. Stopping.")
                break
                
            all_records.extend(values)
            log.info(f"Retrieved {len(values)} records. Total harvested so far: {len(all_records):,}")
            
            # Apply limit if specified during harvest
            if limit and len(all_records) >= limit:
                all_records = all_records[:limit]
                log.info(f"Harvest limit of {limit} reached.")
                break
                
            # Stop if we retrieved all documents
            if len(values) < top:
                log.info("Last page of search index reached.")
                break
                
            skip += top
            time.sleep(0.1)  # Polite pause between pages
            
        except Exception as e:
            log.error(f"Error querying search index: {e}")
            break
            
    log.info(f"Metadata harvesting complete. Total records: {len(all_records):,}")
    return all_records

# -- Checkpoint and State Management -----------------------------------------
def load_checkpoint(output_dir: Path) -> dict:
    """Loads checkpoint file or initializes a new one."""
    checkpoint_file = output_dir / "checkpoint.json"
    if checkpoint_file.exists():
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Failed to load checkpoint file: {e}. Starting fresh.")
            
    return {
        "downloads": {},
        "metadata_harvested": False
    }

def save_checkpoint(output_dir: Path, state: dict):
    """Saves checkpoint file atomically using a temporary file."""
    checkpoint_file = output_dir / "checkpoint.json"
    temp_file = output_dir / "checkpoint.json.tmp"
    try:
        with checkpoint_lock:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            temp_file.replace(checkpoint_file)
    except Exception as e:
        log.error(f"Failed to save checkpoint file: {e}")

# -- File Downloader ---------------------------------------------------------
def download_file(url: str, dest_path: Path, session: requests.Session, timeout: int) -> bool:
    """Downloads a file streaming to a temporary location and renaming on success."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".tmp")
    
    try:
        log.debug(f"Starting download: {url} -> {dest_path}")
        with session.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(temp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
        # Atomic rename on success
        temp_path.replace(dest_path)
        log.debug(f"Finished download: {dest_path.name}")
        return True
    except Exception as e:
        log.warning(f"Failed to download {url}: {e}")
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return False

# -- Filename Sanitizer ------------------------------------------------------
def sanitize_filename(product_name: str, doc_type: str, pl_number: str, original_filename: str) -> str:
    """
    Creates a clean, Windows-safe, descriptive filename.
    Resolves potential duplicate paths.
    """
    # Clean product name
    prod_clean = str(product_name).strip().upper()
    prod_clean = re.sub(r'[^a-zA-Z0-9\s_\-]', '', prod_clean) # keep alphanumeric, space, underscore, hyphen
    prod_clean = re.sub(r'\s+', '_', prod_clean) # replace multiple spaces with underscore
    
    # Get PL Number (use first one if a list)
    pl_clean = ""
    if pl_number:
        if isinstance(pl_number, list):
            pl_clean = pl_number[0]
        else:
            pl_clean = str(pl_number)
        pl_clean = re.sub(r'[^a-zA-Z0-9]', '', pl_clean)
        
    # Get original ext, fallback to .pdf
    ext = ".pdf"
    if original_filename:
        orig_ext = Path(original_filename).suffix
        if orig_ext.lower() in ['.pdf', '.txt', '.doc', '.docx']:
            ext = orig_ext
            
    # Combine components
    doc_type_clean = str(doc_type).lower()
    
    parts = []
    if prod_clean:
        parts.append(prod_clean[:80]) # limit product name to 80 chars
    if pl_clean:
        parts.append(pl_clean)
    parts.append(doc_type_clean)
    
    filename = "_".join(parts) + ext
    return filename

# -- Unified Metadata Exporter -----------------------------------------------
def write_metadata(output_dir: Path, records: list):
    """Writes the unified metadata to CSV and JSON files."""
    csv_file = output_dir / "metadata.csv"
    json_file = output_dir / "metadata.json"
    
    fields = [
        "id", "product_name", "doc_type", "pl_number", "substance_name",
        "title", "created", "metadata_storage_size", "original_filename",
        "azure_blob_url", "local_pdf_path"
    ]
    
    try:
        with csv_lock:
            # 1. Write CSV
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for r in records:
                    row_data = {
                        "id": r.get("id"),
                        "product_name": r.get("product_name"),
                        "doc_type": r.get("doc_type"),
                        "pl_number": ";".join(r.get("pl_number", [])) if isinstance(r.get("pl_number"), list) else r.get("pl_number"),
                        "substance_name": ";".join(r.get("substance_name", [])) if isinstance(r.get("substance_name"), list) else r.get("substance_name"),
                        "title": r.get("title"),
                        "created": r.get("created"),
                        "metadata_storage_size": r.get("metadata_storage_size"),
                        "original_filename": r.get("file_name"),
                        "azure_blob_url": r.get("metadata_storage_path"),
                        "local_pdf_path": r.get("local_pdf_path")
                    }
                    writer.writerow(row_data)
                    
            # 2. Write JSON
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
                
        log.info("Successfully updated unified metadata files (metadata.csv and metadata.json).")
    except Exception as e:
        log.error(f"Error writing metadata files: {e}")

def json_to_csv(json_path: Path, csv_path: Path):
    """Converts a JSON file (list of dicts) to a CSV file."""
    if not json_path.exists():
        print(f"Warning: {json_path} does not exist. Cannot convert to CSV.")
        return
        
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        if not isinstance(data, list):
            data = [data]
            
        if not data:
            print(f"Warning: {json_path} is empty. Creating empty CSV.")
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                pass
            return
            
        # Extract all unique keys from all records to use as header
        headers = set()
        for record in data:
            if isinstance(record, dict):
                headers.update(record.keys())
        headers = sorted(list(headers))
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for record in data:
                if not isinstance(record, dict):
                    continue
                row = {}
                for k in headers:
                    val = record.get(k, "")
                    if isinstance(val, list):
                        if all(isinstance(x, (str, int, float)) for x in val):
                            row[k] = ";".join(str(x) for x in val)
                        else:
                            row[k] = json.dumps(val, ensure_ascii=False)
                    elif isinstance(val, dict):
                        row[k] = json.dumps(val, ensure_ascii=False)
                    else:
                        row[k] = val
                writer.writerow(row)
        print(f"Successfully transformed {json_path.name} to {csv_path.name}")
    except Exception as e:
        print(f"Error converting {json_path} to CSV: {e}")

def cleanup_and_transform(output_dir: Path):
    """
    Deletes checkpoint.json and mhra_downloader.log.
    Transforms raw_metadata.json and metadata.json to CSV files.
    """
    checkpoint_file = output_dir / "checkpoint.json"
    log_file = output_dir / "mhra_downloader.log"
    raw_json = output_dir / "raw_metadata.json"
    raw_csv = output_dir / "raw_metadata.csv"
    meta_json = output_dir / "metadata.json"
    meta_csv = output_dir / "metadata.csv"

    print("\nStarting post-download cleanup and transformation...")

    # 1. Delete checkpoint.json
    if checkpoint_file.exists():
        try:
            checkpoint_file.unlink()
            print(f"Deleted checkpoint file: {checkpoint_file.name}")
        except Exception as e:
            print(f"Failed to delete checkpoint file: {e}")

    # 2. Close logging to release file lock, then delete mhra_downloader.log
    if log_file.exists():
        try:
            # Close all file handlers in the logger
            for handler in logging.root.handlers[:]:
                handler.close()
                logging.root.removeHandler(handler)
            
            # Re-configure a basic stdout logger so print/logging still goes somewhere if needed
            logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stdout)])
            
            log_file.unlink()
            print(f"Deleted log file: {log_file.name}")
        except Exception as e:
            print(f"Failed to delete log file: {e}")

    # 3. Transform raw_metadata.json to raw_metadata.csv and delete JSON
    if raw_json.exists():
        json_to_csv(raw_json, raw_csv)
        try:
            raw_json.unlink()
            print(f"Deleted JSON file: {raw_json.name}")
        except Exception as e:
            print(f"Failed to delete JSON file: {e}")

    # 4. Transform metadata.json to metadata.csv and delete JSON
    if meta_json.exists():
        json_to_csv(meta_json, meta_csv)
        try:
            meta_json.unlink()
            print(f"Deleted JSON file: {meta_json.name}")
        except Exception as e:
            print(f"Failed to delete JSON file: {e}")

# -- Main Execution Pipeline -------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Resumable and multi-threaded MHRA UK approvals and regulatory documents collector."
    )
    parser.add_argument(
        "--output-dir", default="Regulatory & Approvals/mhra_data", help="Directory to save downloaded files and metadata."
    )
    parser.add_argument(
        "--threads", type=int, default=5, help="Number of concurrent download threads."
    )
    parser.add_argument(
        "--max-retries", type=int, default=5, help="Maximum retries for failed downloads."
    )
    parser.add_argument(
        "--timeout", type=int, default=20, help="Timeout in seconds for HTTP requests."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Scrape metadata index only, without downloading PDF files."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit the number of products to download (for testing)."
    )
    parser.add_argument(
        "--doc-types", default=None, help="Comma-separated document types to download (e.g., 'Par,Spc')."
    )
    
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    setup_logging(output_dir)
    log.info("MHRA UK approvals data collector started.")
    
    session = build_session(args.max_retries)
    checkpoint = load_checkpoint(output_dir)
    
    # -- Phase 1: Harvest/Load Metadata ---------------------------------------
    metadata_file = output_dir / "raw_metadata.json"
    all_records = []
    
    if metadata_file.exists() and checkpoint.get("metadata_harvested", False):
        log.info(f"Loading cached metadata from {metadata_file}...")
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                all_records = json.load(f)
            log.info(f"Loaded {len(all_records):,} records from local cache.")
        except Exception as e:
            log.error(f"Failed to load cached metadata: {e}. Re-harvesting from scratch.")
            all_records = []
            
    if not all_records:
        # Fetch fresh metadata from Azure Search index
        all_records = harvest_metadata(session)
        if not all_records:
            log.critical("Failed to retrieve any records from the search index. Exiting.")
            sys.exit(1)
            
        # Cache raw harvested metadata
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(all_records, f, indent=2, ensure_ascii=False)
            checkpoint["metadata_harvested"] = True
            save_checkpoint(output_dir, checkpoint)
            log.info(f"Cached raw metadata to {metadata_file}")
        except Exception as e:
            log.error(f"Failed to cache metadata: {e}")
            
    # Add unique IDs based on Azure storage path hash
    for r in all_records:
        url = r.get("metadata_storage_path", "")
        r["id"] = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
        r["local_pdf_path"] = ""
        
    # Apply doc-type filter if specified
    if args.doc_types:
        allowed_types = [t.strip().lower() for t in args.doc_types.split(',')]
        log.info(f"Filtering download queue by document types: {allowed_types}")
        all_records = [r for r in all_records if str(r.get("doc_type")).lower() in allowed_types]
        log.info(f"Records remaining after filter: {len(all_records):,}")
        
    # Apply testing limit
    if args.limit:
        log.info(f"Limiting download queue to first {args.limit} records.")
        all_records = all_records[:args.limit]
        
    if args.dry_run:
        log.info("Dry-run is active. Exporting metadata files without downloading PDFs...")
        write_metadata(output_dir, all_records)
        log.info("Dry-run execution completed successfully.")
        return
        
    # -- Phase 2: Build Download Queue ----------------------------------------
    download_queue = []
    
    for r in all_records:
        url = r.get("metadata_storage_path")
        if not url:
            continue
            
        doc_type = r.get("doc_type", "unknown").lower()
        product_name = r.get("product_name", "unknown")
        pl_number = r.get("pl_number", [])
        original_filename = r.get("file_name")
        
        # Determine destination filename and path
        dest_filename = sanitize_filename(product_name, doc_type, pl_number, original_filename)
        dest_path = output_dir / "pdfs" / doc_type / dest_filename
        r["local_pdf_path"] = str(dest_path.relative_to(output_dir))
        
        # Check if already completed in checkpoint
        state_record = checkpoint["downloads"].get(url, {})
        if state_record.get("status") == "completed" and dest_path.exists():
            log.debug(f"File already downloaded: {dest_filename}")
        else:
            download_queue.append({
                "url": url,
                "dest_path": dest_path,
                "product": product_name,
                "doc_type": doc_type
            })
            
    log.info(f"Total files in queue for download: {len(download_queue):,}")
    
    if not download_queue:
        log.info("All files are already up-to-date. Writing final metadata files...")
        write_metadata(output_dir, all_records)
        log.info("MHRA UK approvals downloader finished.")
        cleanup_and_transform(output_dir)
        return
        
    # -- Phase 3: Concurrent Downloader ---------------------------------------
    download_success_count = 0
    download_fail_count = 0
    
    pbar = None
    if tqdm:
        pbar = tqdm(total=len(download_queue), desc="Downloading PDFs", unit="file")
        
    def worker(task):
        nonlocal download_success_count, download_fail_count
        url = task["url"]
        dest_path = task["dest_path"]
        
        # Mark as pending in checkpoint
        with checkpoint_lock:
            checkpoint["downloads"][url] = {
                "status": "pending",
                "filepath": str(dest_path.relative_to(output_dir)),
                "size_bytes": 0,
                "downloaded_at": None,
                "error": None
            }
        save_checkpoint(output_dir, checkpoint)
        
        success = download_file(url, dest_path, session, args.timeout)
        
        with checkpoint_lock:
            if success:
                file_size = dest_path.stat().st_size
                checkpoint["downloads"][url].update({
                    "status": "completed",
                    "size_bytes": file_size,
                    "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error": None
                })
                download_success_count += 1
            else:
                checkpoint["downloads"][url].update({
                    "status": "failed",
                    "error": "Download failed or timed out"
                })
                download_fail_count += 1
                
        save_checkpoint(output_dir, checkpoint)
        
        if pbar:
            pbar.update(1)
            
    # Launch Thread Pool
    log.info(f"Launching downloader pool with {args.threads} worker threads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads, thread_name_prefix="Downloader") as executor:
        futures = [executor.submit(worker, task) for task in download_queue]
        concurrent.futures.wait(futures)
        
    if pbar:
        pbar.close()
        
    # -- Phase 4: Write Final Metadata & Summary ------------------------------
    write_metadata(output_dir, all_records)
    
    log.info("==================================================")
    log.info("             MHRA Downloading Summary             ")
    log.info("==================================================")
    log.info(f"Total product records: {len(all_records):,}")
    log.info(f"Files downloaded successfully: {download_success_count:,}")
    log.info(f"Files failed: {download_fail_count:,}")
    log.info(f"Output files saved to: {output_dir.resolve()}")
    log.info("MHRA UK approvals downloader completed successfully.")
    
    cleanup_and_transform(output_dir)

if __name__ == "__main__":
    main()
