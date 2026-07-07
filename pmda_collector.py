#!/usr/bin/env python3
"""
pmda_collector.py
=================
A resilient, multi-threaded, and resumable data collector for Japan's PMDA
(Pharmaceuticals and Medical Devices Agency) approvals and review reports.

Features:
  1. Dynamic Table Parsing: Adapts to table structures across Drugs, Devices,
     Regenerative Products, and Quasi-Drugs using dynamic header mapping.
  2. Robust Thread-Safe Checkpoint System: Real-time progress tracking in JSON.
     Allows seamless resumption after interruptions.
  3. Multi-Threaded PDF Downloader: Concurrently downloads English and Japanese
     review reports politely with exponential backoff retries.
  4. Multiple Links/Files Handling: Handles rows with multiple PDF links (e.g.,
     Japanese No.1, Japanese No.2) by downloading all of them and recording
     them cleanly in the metadata.
  5. Atomic Writes: Prevents corrupted PDFs and metadata by downloading to
     temporary files and renaming on success, guarded by thread locks.

Requirements:
    pip install requests beautifulsoup4
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
from pathlib import Path
from urllib.parse import urljoin, urlparse
import concurrent.futures
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup

# Optional progress indicator
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# -- Configuration & Constants -----------------------------------------------
BASE_URL = "https://www.pmda.go.jp"

# English Review Reports portals
PORTALS = {
    "drug": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0001.html",
    "device": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/devices/0003.html",
    "regenerative": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/0004.html",
    "quasi_drug": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/0005.html"
}

# English Approved Product list portals (for master PDFs)
MASTER_PORTALS = {
    "drug": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0002.html",
    "device": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/devices/0001.html",
    "regenerative": "https://www.pmda.go.jp/english/review-services/reviews/approved-information/0002.html"
}

MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"
}

# -- Threading and Lock Controls ---------------------------------------------
checkpoint_lock = threading.Lock()
csv_lock = threading.Lock()
log = logging.getLogger("pmda_collector")

# -- Logging Setup -----------------------------------------------------------
def setup_logging(output_dir: Path):
    """Sets up file and console logging."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "pmda_collector.log"

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
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    session.headers.update({
        "User-Agent": "BiolytInternPMDADownloader/1.0 (Python; requests; BeautifulSoup)"
    })
    return session

# -- Date Parser -------------------------------------------------------------
def parse_approval_date(date_str: str) -> str:
    """Parses date string like 'September 2019' or 'July 2024 (Conditional...)' into 'YYYY-MM'."""
    if not date_str:
        return "unknown"
    
    cleaned = date_str.strip().lower()
    # Find a 4-digit year
    year = None
    words = cleaned.split()
    for w in words:
        # Strip punctuation from word
        w_clean = "".join(c for c in w if c.isdigit())
        if len(w_clean) == 4:
            year = w_clean
            break
            
    if not year:
        return "unknown"
        
    # Find month
    month_num = "00"
    for m_name, m_num in MONTH_MAP.items():
        if m_name in cleaned:
            month_num = m_num
            break
            
    return f"{year}-{month_num}"

# -- Scraping Logic ----------------------------------------------------------
def scrape_portal(category: str, url: str, session: requests.Session) -> list:
    """Scrapes a PMDA English review reports portal and returns list of product records."""
    log.info(f"Scraping {category.upper()} portal: {url}")
    records = []
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Find all tables of class normal-table
        tables = soup.find_all('table', class_='normal-table')
        if not tables:
            log.warning(f"No tables found on {category} portal.")
            return records
            
        table_count = 0
        for table in tables:
            rows = table.find_all('tr')
            if not rows:
                continue
                
            # Check if this is the 'Browse by letter' index table
            # If all links in the table start with '#', skip it
            first_row_links = table.find_all('a')
            if first_row_links and all(a.get('href', '').startswith('#') for a in first_row_links):
                log.debug("Skipping letter index table.")
                continue
                
            # Parse headers dynamically
            header_row = rows[0]
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]
            
            # Map column indexes
            brand_idx = -1
            generic_idx = -1
            date_idx = -1
            en_idx = -1
            
            for idx, h in enumerate(headers):
                if "brand" in h:
                    brand_idx = idx
                elif "non-proprietary" in h or "term name" in h or "generic" in h:
                    generic_idx = idx
                elif "approved in" in h or "approved date" in h:
                    date_idx = idx
                elif "english" in h or "report (en)" in h:
                    en_idx = idx
            
            # Fallbacks in case the table doesn't have a structured header or it's misaligned
            if brand_idx == -1 and len(headers) >= 4:
                # Assume standard structure: Brand | Generic | Approved | EN PDF
                brand_idx = 0
                generic_idx = 1
                date_idx = 2
                en_idx = 3
                
            if brand_idx == -1:
                log.debug("Could not determine table columns. Skipping table.")
                continue
                
            table_count += 1
            log.debug(f"Parsing table {table_count} with header mapping: brand={brand_idx}, generic={generic_idx}, date={date_idx}, en={en_idx}")
            
            for row in rows[1:]:
                cols = row.find_all(['td', 'th'])
                if len(cols) <= max(brand_idx, generic_idx, date_idx):
                    continue
                    
                # Extract Brand Name (clean up any superscript tags)
                brand_cell = cols[brand_idx]
                # Extract clean text, but note if there's a superscript change approval
                superscript = brand_cell.find('sup')
                approval_type = "Initial Approval"
                if superscript:
                    sup_text = superscript.get_text(strip=True)
                    if "change" in sup_text.lower() or "partial" in sup_text.lower():
                        approval_type = "Partial Change Approval"
                    superscript.extract() # remove it to clean the brand name
                    
                brand_name = brand_cell.get_text(" ", strip=True)
                if not brand_name or brand_name.lower() == "brand name":
                    continue
                    
                # Extract Generic Name
                generic_name = "-"
                if generic_idx != -1 and generic_idx < len(cols):
                    generic_name = cols[generic_idx].get_text(strip=True)
                    
                # Extract Date
                approval_date_raw = "unknown"
                if date_idx != -1 and date_idx < len(cols):
                    approval_date_raw = cols[date_idx].get_text(strip=True)
                approval_date = parse_approval_date(approval_date_raw)
                
                # Extract English PDF links
                en_urls = []
                if en_idx != -1 and en_idx < len(cols):
                    en_links = cols[en_idx].find_all('a')
                    for a in en_links:
                        href = a.get('href')
                        if href and href.lower().endswith('.pdf'):
                            en_urls.append(urljoin(BASE_URL, href))
                            
                # Create records
                # If there are no PDFs, we still keep the metadata
                records.append({
                    "category": category,
                    "brand_name": brand_name,
                    "approval_type": approval_type,
                    "generic_name": generic_name,
                    "approval_date_raw": approval_date_raw,
                    "approval_date": approval_date,
                    "en_urls": en_urls
                })
                
        log.info(f"Successfully scraped {len(records)} records from {category} portal.")
    except Exception as e:
        log.error(f"Error scraping {category} portal: {e}")
    return records

def scrape_master_pdf(category: str, url: str, session: requests.Session) -> str:
    """Scrapes the master list portal and returns the absolute URL of the cumulative PDF."""
    log.info(f"Scraping master PDF URL from {category.upper()} portal: {url}")
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Look for links containing '.pdf' and having text like 'April 2004' or 'September 2025' or 'List of Approved Products'
        links = soup.find_all('a')
        for a in links:
            href = a.get('href', '')
            text = a.get_text(strip=True).lower()
            if href.lower().endswith('.pdf') and ('2004' in text or 'approved' in text or 'products' in text):
                pdf_url = urljoin(BASE_URL, href)
                log.info(f"Found {category} master PDF URL: {pdf_url}")
                return pdf_url
    except Exception as e:
        log.error(f"Error scraping master PDF URL for {category}: {e}")
    return None

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
        "scraping_completed": {cat: False for cat in PORTALS}
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

# -- Unified Metadata Exporter -----------------------------------------------
def write_metadata(output_dir: Path, records: list):
    """Writes the unified metadata to CSV and JSON files."""
    csv_file = output_dir / "metadata.csv"
    json_file = output_dir / "metadata.json"
    
    fields = [
        "id", "category", "brand_name", "approval_type", "generic_name",
        "approval_date_raw", "approval_date", "en_pdf_urls", "en_pdf_paths"
    ]
    
    try:
        with csv_lock:
            # 1. Write CSV
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for r in records:
                    # Format list fields as semicolon-separated strings for CSV
                    row_data = r.copy()
                    row_data["en_pdf_urls"] = ";".join(r.get("en_urls", []))
                    row_data["en_pdf_paths"] = ";".join(r.get("en_paths", []))
                    # Remove temp lists
                    row_data.pop("en_urls", None)
                    row_data.pop("en_paths", None)
                    writer.writerow(row_data)
                    
            # 2. Write JSON
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
                
        log.info("Successfully updated unified metadata files (metadata.csv and metadata.json).")
    except Exception as e:
        log.error(f"Error writing metadata files: {e}")

def cleanup_pmda_files(output_dir: Path):
    """Deletes temporary/unneeded files (checkpoint JSON, metadata JSON, and log file) after successful completion."""
    # 1. Delete checkpoint.json
    checkpoint_file = output_dir / "checkpoint.json"
    if checkpoint_file.exists():
        try:
            checkpoint_file.unlink()
            print(f"Cleaned up checkpoint file: {checkpoint_file}")
        except Exception as e:
            print(f"Error deleting checkpoint file: {e}")

    # 2. Delete metadata.json
    metadata_json = output_dir / "metadata.json"
    if metadata_json.exists():
        try:
            metadata_json.unlink()
            print(f"Cleaned up metadata JSON file: {metadata_json}")
        except Exception as e:
            print(f"Error deleting metadata JSON file: {e}")

    # 3. Shutdown logging so we can delete the log file on Windows
    log_file = output_dir / "pmda_collector.log"
    if log_file.exists():
        try:
            logging.shutdown()  # Closes and flushes all log handlers
            log_file.unlink()
            print(f"Cleaned up log file: {log_file}")
        except Exception as e:
            print(f"Error deleting log file: {e}")

# -- Main Execution Pipeline -------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Resumable and multi-threaded PMDA Japan approvals and review reports collector."
    )
    parser.add_argument(
        "--output-dir", default="Regulatory & Approvals/pmda_data", help="Directory to save downloaded files and metadata."
    )
    parser.add_argument(
        "--threads", type=int, default=5, help="Number of concurrent download threads."
    )
    parser.add_argument(
        "--max-retries", type=int, default=5, help="Maximum retries for failed downloads."
    )
    parser.add_argument(
        "--timeout", type=int, default=15, help="Timeout in seconds for HTTP requests."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Scrape metadata without downloading PDF files."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit the number of products to download (for testing)."
    )
    
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    
    # Setup logging
    setup_logging(output_dir)
    log.info("PMDA Data Collector started.")
    
    session = build_session(args.max_retries)
    checkpoint = load_checkpoint(output_dir)
    
    # -- Phase 1: Scrape Portals for Metadata & PDF Links ---------------------
    all_records = []
    
    for category, portal_url in PORTALS.items():
        records = scrape_portal(category, portal_url, session)
        all_records.extend(records)
        
    log.info(f"Total product records discovered: {len(all_records)}")
    
    # Discover Master lists of Approved Products
    master_links = {}
    for category, portal_url in MASTER_PORTALS.items():
        master_url = scrape_master_pdf(category, portal_url, session)
        if master_url:
            master_links[category] = master_url
            
    # Add unique IDs to records
    for r in all_records:
        # Unique ID based on category, brand, and approval date
        hash_input = f"{r['category']}_{r['brand_name']}_{r['approval_date']}"
        r["id"] = hashlib.md5(hash_input.encode('utf-8')).hexdigest()[:8]
        r["en_paths"] = []
        
    # Apply limit if specified
    if args.limit:
        log.info(f"Limiting download queue to first {args.limit} records.")
        all_records = all_records[:args.limit]
        
    if args.dry_run:
        log.info("Dry-run flag is active. Writing metadata files without downloading PDFs.")
        write_metadata(output_dir, all_records)
        log.info("Dry-run execution completed successfully.")
        cleanup_pmda_files(output_dir)
        return
        
    # -- Phase 2: Build Download Queue ----------------------------------------
    download_queue = []
    
    # 1. Queue master PDFs
    for category, url in master_links.items():
        dest_filename = f"{category}_master.pdf"
        dest_path = output_dir / "master_lists" / dest_filename
        
        state_record = checkpoint["downloads"].get(url, {})
        if state_record.get("status") == "completed" and dest_path.exists():
            log.debug(f"Master PDF already downloaded: {dest_filename}")
        else:
            download_queue.append({
                "url": url,
                "dest_path": dest_path,
                "type": "master",
                "category": category,
                "lang": "all"
            })
            
    # 2. Queue review reports PDFs
    for r in all_records:
        brand_clean = "".join(c for c in r["brand_name"] if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
        date_str = r["approval_date"]
        
        # English PDFs
        for idx, url in enumerate(r["en_urls"]):
            suffix = f"_{idx+1}" if len(r["en_urls"]) > 1 else ""
            dest_filename = f"{brand_clean}_{date_str}_en{suffix}.pdf"
            dest_path = output_dir / "pdfs" / f"{r['category']}s" / "en" / dest_filename
            r["en_paths"].append(str(dest_path.relative_to(output_dir)))
            
            state_record = checkpoint["downloads"].get(url, {})
            if state_record.get("status") == "completed" and dest_path.exists():
                log.debug(f"English PDF already downloaded: {dest_filename}")
            else:
                download_queue.append({
                    "url": url,
                    "dest_path": dest_path,
                    "type": "report",
                    "category": r["category"],
                    "lang": "en"
                })
                
    log.info(f"Total files in queue for download: {len(download_queue)}")
    
    if not download_queue:
        log.info("All files are already up-to-date. Writing final metadata files.")
        write_metadata(output_dir, all_records)
        log.info("PMDA Data Collector finished.")
        cleanup_pmda_files(output_dir)
        return
        
    # -- Phase 3: Concurrent Downloader ---------------------------------------
    download_success_count = 0
    download_fail_count = 0
    
    # Progress indicator
    pbar = None
    if tqdm:
        pbar = tqdm(total=len(download_queue), desc="Downloading PDFs", unit="file")
        
    def worker(task):
        nonlocal download_success_count, download_fail_count
        url = task["url"]
        dest_path = task["dest_path"]
        
        # Update checkpoint to pending
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
            
    # Execute Thread Pool
    log.info(f"Launching downloader pool with {args.threads} worker threads...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads, thread_name_prefix="Downloader") as executor:
        futures = [executor.submit(worker, task) for task in download_queue]
        concurrent.futures.wait(futures)
        
    if pbar:
        pbar.close()
        
    # -- Phase 4: Final Metadata Save & Summary -------------------------------
    write_metadata(output_dir, all_records)
    
    log.info("==================================================")
    log.info("             PMDA scraping Summary")
    log.info("==================================================")
    log.info(f"Total product records: {len(all_records)}")
    log.info(f"Files downloaded successfully: {download_success_count}")
    log.info(f"Files failed: {download_fail_count}")
    log.info(f"Output files saved to: {output_dir.resolve()}")
    log.info("PMDA Data Collector finished.")
    cleanup_pmda_files(output_dir)

if __name__ == "__main__":
    main()
