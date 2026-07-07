#!/usr/bin/env python3
"""
ema_downloader.py
=================
A resilient, multi-threaded, and resumable data collector and PDF downloader 
for the European Medicines Agency (EMA) centralized approvals (EPARs) and regulatory data.

Features:
  1. Dynamic Schema Mapping: Reads EMA medicines Excel database, cleans headers, 
     and dynamically creates/adapts the SQLite database schema.
  2. Resilient Checkpointing: Keeps track of page crawling and PDF downloading 
     using a local SQLite database, enabling immediate resumption after crashes.
  3. Multi-Threaded Concurrency: Concurrently crawls EPAR pages and downloads 
     documents using a thread pool executor.
  4. Polite Crawling & Retries: Uses realistic browser headers and implements 
     robust exponential backoff retries (handles HTTP 429, 5xx, timeouts).
  5. Atomic PDF Downloads: Downloads to *.tmp files, renaming to *.pdf only 
     on success, protecting against corrupted files.
  6. Smart Language Filtering: Only downloads English (en) documents by default 
     to save massive bandwidth, but allows downloading other/all languages.
  7. Additional Tables: Option to download all 10 extra EMA Excel data sheets 
     (shortages, orphan drugs, referrals, etc.) and export them to CSV.

Requirements:
    pip install requests pandas openpyxl beautifulsoup4
"""

import os
import sys
import hashlib
import time
import json
import csv
import re
import sqlite3
import logging
import argparse
import threading
import pathlib
import urllib.parse
from pathlib import Path
import concurrent.futures
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup
import pandas as pd

# Optional progress bar
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# -- Global Constants --------------------------------------------------------
BASE_URL = "https://www.ema.europa.eu"
MEDICINES_EXCEL_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx"
DOWNLOAD_PAGE_URL = "https://www.ema.europa.eu/en/medicines/download-medicine-data"

ADDITIONAL_TABLES = {
    "post_authorisation": "https://www.ema.europa.eu/en/documents/report/medicines-output-post_authorisation-report_en.xlsx",
    "orphan_designations": "https://www.ema.europa.eu/en/documents/report/medicines-output-orphan_designations-report_en.xlsx",
    "referrals": "https://www.ema.europa.eu/en/documents/report/medicines-output-referrals-report_en.xlsx",
    "opinions_outside_eu": "https://www.ema.europa.eu/en/documents/report/medicines-output-opinions_outside_eu-report_en.xlsx",
    "paediatric_investigation_plans": "https://www.ema.europa.eu/en/documents/report/medicines-output-paediatric_investigation_plans-report_en.xlsx",
    "herbal_medicines": "https://www.ema.europa.eu/en/documents/report/medicines-output-herbal_medicines-report_en.xlsx",
    "periodic_safety_update_report_single_assessments": "https://www.ema.europa.eu/en/documents/report/medicines-output-periodic_safety_update_report_single_assessments-report_en.xlsx",
    "dhpc": "https://www.ema.europa.eu/en/documents/report/medicines-output-dhpc-report_en.xlsx",
    "shortages": "https://www.ema.europa.eu/en/documents/report/medicines-output-shortages-report_en.xlsx",
    "maximum_residue_limits": "https://www.ema.europa.eu/en/documents/report/medicines-output-maximum_residue_limits-report_en.xlsx"
}

# Logger setup
log = logging.getLogger("ema_downloader")

# -- Helper Functions --------------------------------------------------------
def setup_logging(output_dir: Path):
    """Configures file and console logging."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "ema_downloader.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def clean_column_name(col_name: str) -> str:
    """Converts Excel column headers into clean, lower_snake_case SQL identifiers."""
    cleaned = re.sub(r'[^a-zA-Z0-9]', '_', str(col_name).lower())
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned.strip('_')

def slugify(text: str) -> str:
    """Creates a Windows-safe filename or directory name by stripping illegal characters."""
    if not text:
        return "unnamed"
    cleaned = re.sub(r'[\\/*?:"<>|]', "", str(text))
    cleaned = re.sub(r'\s+', "_", cleaned).strip("_")
    return cleaned[:80]  # Truncate to prevent path length issues

def extract_language_and_type(url: str) -> tuple:
    """Extracts the language code and document type category from an EMA document URL."""
    # Language: look for two-letter code after domain, or fallback to file suffix e.g. _en.pdf
    lang_match = re.search(r'https?://[^/]+/([a-z]{2})/documents/', url)
    if lang_match:
        lang = lang_match.group(1)
    else:
        suffix_match = re.search(r'_([a-z]{2})\.pdf$', url.lower())
        lang = suffix_match.group(1) if suffix_match else 'unknown'
        
    # Document Type: segment after /documents/
    type_match = re.search(r'/documents/([^/]+)/', url)
    doc_type = type_match.group(1) if type_match else 'other'
    
    return lang, doc_type

# -- HTTP Session Builder ----------------------------------------------------
def build_session(max_retries: int) -> requests.Session:
    """Builds a requests.Session mimicking a browser with exponential backoff retries."""
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    })
    return session

# -- Database Manager --------------------------------------------------------
class DatabaseManager:
    """Thread-safe SQLite database manager for checkpointing and progress tracking."""
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.lock = threading.Lock()
        
    def execute(self, query: str, params: tuple = None):
        """Executes a single write query inside a thread lock."""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                conn.commit()
                return cursor.fetchall()

    def query(self, query: str, params: tuple = None) -> list:
        """Executes a read query inside a thread lock."""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
                return cursor.fetchall()

    def initialize_fixed_tables(self):
        """Creates the documents and downloads tables."""
        # Documents table
        self.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                document_url TEXT PRIMARY KEY,
                ema_product_number TEXT,
                medicine_name TEXT,
                document_title TEXT,
                language TEXT,
                document_type TEXT,
                scraped_at TEXT
            );
        """)
        
        # Downloads table (the PDF queue)
        self.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                document_url TEXT PRIMARY KEY,
                local_path TEXT,
                status TEXT DEFAULT 'pending',
                error_message TEXT,
                retries INTEGER DEFAULT 0,
                download_timestamp TEXT,
                file_size INTEGER
            );
        """)
        log.info("Initialized system schema tables.")

    def create_dynamic_medicines_table(self, clean_columns: list):
        """Dynamically creates the medicines table based on Excel columns."""
        fields = []
        for col in clean_columns:
            if col == "ema_product_number":
                fields.append(f"{col} TEXT PRIMARY KEY")
            else:
                fields.append(f"{col} TEXT")
                
        # Add tracking fields
        fields.append("scrape_status TEXT DEFAULT 'pending'")
        fields.append("scrape_error TEXT")
        fields.append("scraped_at TEXT")
        
        query = f"CREATE TABLE IF NOT EXISTS medicines ({', '.join(fields)});"
        self.execute(query)
        log.info(f"Dynamically mapped medicines table with {len(clean_columns)} fields.")

    def insert_medicines(self, df, clean_columns: list):
        """Inserts medicines into the database using a fast executemany statement."""
        # Convert NaN to None for SQL NULL compatibility
        df_clean = df.where(pd.notnull(df), None)
        
        # Ensure we don't insert rows with empty product numbers
        prod_col = "ema_product_number"
        if prod_col in df_clean.columns:
            df_clean = df_clean[df_clean[prod_col].notna() & (df_clean[prod_col] != "")]
            
        columns_str = ", ".join(clean_columns)
        placeholders = ", ".join(["?"] * len(clean_columns))
        query = f"INSERT OR REPLACE INTO medicines ({columns_str}) VALUES ({placeholders});"
        
        rows = [tuple(r) for r in df_clean.values]
        
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany(query, rows)
                conn.commit()
                
        log.info(f"Successfully inserted/updated {len(rows)} medicine records.")

    def claim_next_medicine(self) -> tuple:
        """Claims a pending medicine record for EPAR page crawling in a thread-safe transaction."""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT ema_product_number, name_of_medicine, medicine_url 
                    FROM medicines 
                    WHERE scrape_status = 'pending' 
                    LIMIT 1;
                """)
                row = cursor.fetchone()
                if row:
                    prod_num, name, url = row
                    cursor.execute("""
                        UPDATE medicines 
                        SET scrape_status = 'crawling' 
                        WHERE ema_product_number = ?;
                    """, (prod_num,))
                    conn.commit()
                    return prod_num, name, url
                return None

    def update_medicine_status(self, prod_num: str, status: str, error: str = None):
        """Updates the crawling status of a medicine."""
        self.execute("""
            UPDATE medicines 
            SET scrape_status = ?, scrape_error = ?, scraped_at = datetime('now') 
            WHERE ema_product_number = ?;
        """, (status, error, prod_num))

    def insert_documents_and_downloads(self, docs: list, downloads: list):
        """Inserts documents and download queue tasks inside a single transaction."""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Insert documents
                if docs:
                    cursor.executemany("""
                        INSERT OR IGNORE INTO documents 
                        (document_url, ema_product_number, medicine_name, document_title, language, document_type, scraped_at) 
                        VALUES (?, ?, ?, ?, ?, ?, datetime('now'));
                    """, docs)
                    
                # Insert downloads queue
                if downloads:
                    cursor.executemany("""
                        INSERT OR IGNORE INTO downloads 
                        (document_url, local_path, status) 
                        VALUES (?, ?, 'pending');
                    """, downloads)
                conn.commit()

    def claim_next_download(self) -> tuple:
        """Claims a pending PDF download and retrieves the parent medicine EPAR URL as Referer."""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT dl.document_url, dl.local_path, m.medicine_url 
                    FROM downloads dl
                    JOIN documents d ON dl.document_url = d.document_url
                    JOIN medicines m ON d.ema_product_number = m.ema_product_number
                    WHERE dl.status = 'pending' 
                    LIMIT 1;
                """)
                row = cursor.fetchone()
                if row:
                    url, local_path, referer = row
                    cursor.execute("""
                        UPDATE downloads 
                        SET status = 'downloading' 
                        WHERE document_url = ?;
                    """, (url,))
                    conn.commit()
                    return url, local_path, referer
                return None

    def update_download_status(self, url: str, status: str, size: int = 0, error: str = None):
        """Updates the status of a PDF download, incrementing retries if failed."""
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if status == 'completed':
                    cursor.execute("""
                        UPDATE downloads 
                        SET status = 'completed', file_size = ?, error_message = NULL, download_timestamp = datetime('now') 
                        WHERE document_url = ?;
                    """, (size, url))
                else:  # failed
                    cursor.execute("""
                        UPDATE downloads 
                        SET status = 'failed', error_message = ?, retries = retries + 1 
                        WHERE document_url = ?;
                    """, (error, url))
                    
                    # Reset retries that are under limits back to pending for next cycle
                    cursor.execute("""
                        UPDATE downloads 
                        SET status = 'pending' 
                        WHERE status = 'failed' AND retries < 5;
                    """)
                conn.commit()

# -- Core Downloader Logic ---------------------------------------------------
class EMADataCollector:
    """Manages downloading the master Excel and crawling individual medicine EPAR pages."""
    def __init__(self, db: DatabaseManager, session: requests.Session, output_dir: Path, languages: list):
        self.db = db
        self.session = session
        self.output_dir = output_dir
        self.languages = languages  # e.g., ['en'] or ['en', 'fr'] or ['all']

    def download_and_parse_master(self) -> bool:
        """Downloads the main EMA medicines Excel database and imports it into SQLite."""
        excel_path = self.output_dir / "medicines_report.xlsx"
        log.info(f"Checking for master Excel database at: {excel_path}")
        
        # If it doesn't exist, download it
        if not excel_path.exists():
            log.info(f"Downloading EMA master Excel database from {MEDICINES_EXCEL_URL}...")
            excel_path.parent.mkdir(parents=True, exist_ok=True)
            
            try:
                r = self.session.get(MEDICINES_EXCEL_URL, stream=True, timeout=30)
                if r.status_code != 200:
                    log.error(f"Failed to download medicines Excel. Status: {r.status_code}")
                    return False
                
                tmp_path = excel_path.with_suffix(".xlsx.tmp")
                with open(tmp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                tmp_path.rename(excel_path)
                log.info("Downloaded master medicines Excel successfully.")
            except Exception as e:
                log.error(f"Error downloading master Excel: {e}")
                return False

        # Parse Excel using pandas
        try:
            log.info("Parsing medicines Excel spreadsheet...")
            # The header is at row 8 (0-indexed index 8 is the 9th row in Excel)
            import pandas as pd
            df = pd.read_excel(excel_path, header=8)
            
            # Clean columns and map
            clean_cols = [clean_column_name(col) for col in df.columns]
            df.columns = clean_cols
            
            # Initialize database tables
            self.db.initialize_fixed_tables()
            self.db.create_dynamic_medicines_table(clean_cols)
            
            # Insert into database
            self.db.insert_medicines(df, clean_cols)
            
            # Export clean CSV as well
            csv_path = self.output_dir / "ema_medicines.csv"
            df.to_csv(csv_path, index=False, encoding='utf-8')
            log.info(f"Exported clean medicines metadata to CSV: {csv_path}")
            
            return True
        except Exception as e:
            log.error(f"Error parsing/storing Excel data: {e}")
            return False

    def crawl_medicine_page(self, prod_num: str, name: str, url: str) -> int:
        """Crawls a single medicine's EPAR page and extracts eligible PDF document links."""
        log.info(f"Crawling EPAR page for '{name}': {url}")
        
        try:
            r = self.session.get(url, timeout=20)
            if r.status_code != 200:
                log.warning(f"Failed to fetch EPAR page for {name} (Status: {r.status_code})")
                self.db.update_medicine_status(prod_num, 'failed', f"HTTP Status {r.status_code}")
                return 0
                
            soup = BeautifulSoup(r.text, 'html.parser')
            links = soup.find_all('a')
            
            docs_to_insert = []
            downloads_to_insert = []
            
            for link in links:
                href = link.get('href')
                title = link.text.strip()
                if not href:
                    continue
                
                href_lower = href.lower()
                # Check if it is a document link
                if href_lower.endswith('.pdf') or '/document/' in href_lower or 'pdf' in href_lower:
                    absolute_url = urllib.parse.urljoin(url, href)
                    lang, doc_type = extract_language_and_type(absolute_url)
                    
                    # Language Filter
                    if 'all' not in self.languages and lang not in self.languages:
                        continue  # Skip unwanted languages
                        
                    # Create Windows-safe local path
                    safe_medicine_name = slugify(name)
                    
                    # Extract original filename from the URL path (e.g. tecvayli-epar-medicine-overview_en.pdf)
                    parsed_url = urllib.parse.urlparse(absolute_url)
                    url_filename = os.path.basename(parsed_url.path)
                    
                    if url_filename and url_filename.lower().endswith('.pdf'):
                        # Keep it, but ensure it is Windows-safe by slugifying the stem
                        stem = Path(url_filename).stem
                        local_filename = f"{slugify(stem)}_{lang}.pdf"
                    else:
                        safe_doc_title = slugify(title if title else Path(absolute_url).stem)
                        # If title is a generic word like 'view', use a hash to prevent collisions
                        if safe_doc_title.lower() in ['view', 'download', 'pdf', 'link']:
                            url_hash = hashlib.md5(absolute_url.encode('utf-8')).hexdigest()[:8]
                            safe_doc_title = f"document_{url_hash}"
                        local_filename = f"{safe_doc_title}_{lang}.pdf"
                        
                    local_path = str(Path("pdfs") / safe_medicine_name / local_filename)
                    
                    docs_to_insert.append((
                        absolute_url, prod_num, name, title, lang, doc_type
                    ))
                    
                    downloads_to_insert.append((
                        absolute_url, local_path
                    ))
                    
            # Insert batch into database
            if docs_to_insert:
                self.db.insert_documents_and_downloads(docs_to_insert, downloads_to_insert)
                
            self.db.update_medicine_status(prod_num, 'completed')
            log.info(f"Successfully scraped EPAR page for '{name}'. Found {len(docs_to_insert)} eligible PDF links.")
            return len(docs_to_insert)
            
        except Exception as e:
            log.error(f"Error crawling EPAR page for '{name}': {e}")
            self.db.update_medicine_status(prod_num, 'failed', str(e))
            return 0

    def crawl_all_medicines(self, max_workers: int, limit: int = None):
        """Crawls EPAR pages in parallel using ThreadPoolExecutor."""
        log.info("Starting multi-threaded EPAR page crawling...")
        
        # Get count of pending medicines
        pending_count = self.db.query("SELECT COUNT(*) FROM medicines WHERE scrape_status = 'pending';")[0][0]
        log.info(f"Found {pending_count} pending medicines to crawl.")
        
        if pending_count == 0:
            log.info("No pending medicines to crawl.")
            return
            
        if limit:
            log.info(f"Limiting crawling to {limit} medicines.")
            
        processed_count = 0
        
        # Thread worker
        def worker():
            nonlocal processed_count
            while True:
                if limit and processed_count >= limit:
                    break
                item = self.db.claim_next_medicine()
                if not item:
                    break
                
                prod_num, name, url = item
                self.crawl_medicine_page(prod_num, name, url)
                processed_count += 1
                
                # Polite scraping delay
                time.sleep(0.5)

        # Launch thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Crawler") as executor:
            futures = [executor.submit(worker) for _ in range(max_workers)]
            concurrent.futures.wait(futures)
            
        log.info("EPAR page crawling finished.")

# -- PDF Downloader Logic ----------------------------------------------------
class EMAPDFDownloader:
    """Manages downloading PDF documents from the queue with atomic writes and retries."""
    def __init__(self, db: DatabaseManager, session: requests.Session, output_dir: Path):
        self.db = db
        self.session = session
        self.output_dir = output_dir

    def download_file(self, url: str, rel_path: str, referer: str) -> bool:
        """Downloads a single PDF to a .tmp file, and atomically renames it on success, using a Referer header."""
        local_path = self.output_dir / rel_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Skip if already exists and not empty
        if local_path.exists() and local_path.stat().st_size > 0:
            log.info(f"File already exists: {rel_path}. Skipping.")
            self.db.update_download_status(url, 'completed', local_path.stat().st_size)
            return True
            
        log.info(f"Downloading PDF: {url} -> {rel_path}")
        tmp_path = local_path.with_suffix(".tmp")
        
        try:
            headers = {}
            if referer:
                headers["Referer"] = referer
                
            r = self.session.get(url, stream=True, timeout=30, headers=headers)
            if r.status_code != 200:
                log.warning(f"Failed to download PDF {url} (Status: {r.status_code})")
                self.db.update_download_status(url, 'failed', error=f"HTTP Status {r.status_code}")
                return False
                
            with open(tmp_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            # Atomic rename
            tmp_path.rename(local_path)
            size = local_path.stat().st_size
            self.db.update_download_status(url, 'completed', size)
            log.info(f"Downloaded successfully: {rel_path} ({size} bytes)")
            return True
            
        except Exception as e:
            log.error(f"Error downloading PDF {url}: {e}")
            if tmp_path.exists():
                tmp_path.unlink()  # clean up temp file
            self.db.update_download_status(url, 'failed', error=str(e))
            return False

    def download_all_queued(self, max_workers: int, limit: int = None):
        """Downloads queued PDFs in parallel using ThreadPoolExecutor."""
        log.info("Starting multi-threaded PDF downloads...")
        
        # Get count of pending downloads
        pending_count = self.db.query("SELECT COUNT(*) FROM downloads WHERE status = 'pending';")[0][0]
        log.info(f"Found {pending_count} pending downloads in queue.")
        
        if pending_count == 0:
            log.info("No pending PDFs to download.")
            return
            
        if limit:
            log.info(f"Limiting downloads to {limit} files.")
            
        downloaded_count = 0
        
        # Progress bar setup (tqdm if available, otherwise simple prints)
        pbar = None
        if tqdm:
            total_items = min(pending_count, limit) if limit else pending_count
            pbar = tqdm(total=total_items, desc="Downloading PDFs", unit="file")
            
        # Thread worker
        def worker():
            nonlocal downloaded_count
            while True:
                if limit and downloaded_count >= limit:
                    break
                item = self.db.claim_next_download()
                if not item:
                    break
                
                url, local_path, referer = item
                success = self.download_file(url, local_path, referer)
                if success:
                    downloaded_count += 1
                    
                if pbar:
                    pbar.update(1)
                    
                # Polite delay between downloads
                time.sleep(0.3)

        # Launch thread pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="Downloader") as executor:
            futures = [executor.submit(worker) for _ in range(max_workers)]
            concurrent.futures.wait(futures)
            
        if pbar:
            pbar.close()
            
        log.info("PDF downloads finished.")

# -- Additional Tables Exporter ----------------------------------------------
def download_all_additional_tables(session: requests.Session, output_dir: Path):
    """Downloads all 10 additional EMA Excel tables and exports them as CSVs."""
    log.info("Starting download of additional regulatory tables...")
    add_dir = output_dir / "additional_tables"
    add_dir.mkdir(parents=True, exist_ok=True)
    
    import pandas as pd
    
    for name, url in ADDITIONAL_TABLES.items():
        log.info(f"Processing additional table '{name}'...")
        excel_path = add_dir / f"{name}.xlsx"
        
        # Download Excel
        try:
            r = session.get(url, stream=True, timeout=30)
            if r.status_code != 200:
                log.error(f"Failed to download '{name}' table (Status: {r.status_code})")
                continue
                
            with open(excel_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            log.info(f"Downloaded '{name}' Excel table.")
            
            # Convert to CSV
            # Look for header row (typically row 8, similar to medicines sheet)
            try:
                df = pd.read_excel(excel_path, header=8)
                # Clean headers
                df.columns = [clean_column_name(col) for col in df.columns]
                csv_path = add_dir / f"{name}.csv"
                df.to_csv(csv_path, index=False, encoding='utf-8')
                log.info(f"Exported '{name}' to CSV: {csv_path}")
            except Exception as ex_parse:
                # If row 8 fails, try row 0
                try:
                    df = pd.read_excel(excel_path, header=0)
                    df.columns = [clean_column_name(col) for col in df.columns]
                    csv_path = add_dir / f"{name}.csv"
                    df.to_csv(csv_path, index=False, encoding='utf-8')
                    log.info(f"Exported '{name}' to CSV (fallback header=0): {csv_path}")
                except Exception as ex_fallback:
                    log.error(f"Could not parse '{name}' Excel table: {ex_fallback}")
                    
        except Exception as e:
            log.error(f"Error downloading '{name}': {e}")
            
    log.info("Additional regulatory tables processing complete.")

# -- CSV Documents Exporter --------------------------------------------------
def export_documents_metadata(db: DatabaseManager, output_dir: Path):
    """Exports scraped documents metadata from SQLite to a clean CSV file."""
    log.info("Exporting documents metadata to CSV...")
    csv_path = output_dir / "ema_documents.csv"
    
    try:
        rows = db.query("""
            SELECT d.ema_product_number, d.medicine_name, d.document_title, 
                   d.language, d.document_type, d.document_url, dl.status, dl.local_path, dl.file_size
            FROM documents d
            LEFT JOIN downloads dl ON d.document_url = dl.document_url;
        """)
        
        headers = [
            "ema_product_number", "medicine_name", "document_title", 
            "language", "document_type", "document_url", "download_status", "local_path", "file_size_bytes"
        ]
        
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
            
        log.info(f"Exported {len(rows)} documents metadata rows to CSV: {csv_path}")
    except Exception as e:
        log.error(f"Failed to export documents metadata: {e}")

# -- Command Line Interface & Main -------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Resilient, multi-threaded, and resumable downloader for EMA centralized approvals (EPARs) and regulatory data."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="Regulatory & Approvals/ema_data",
        help="Directory to save downloaded files, SQLite database, and logs (default: 'Regulatory & Approvals/ema_data')."
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=5,
        help="Maximum concurrent threads for crawling and downloading (default: 5)."
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="Maximum HTTP request retries with exponential backoff (default: 5)."
    )
    parser.add_argument(
        "--languages",
        type=str,
        default="en",
        help="Comma-separated list of document language codes to download, or 'all' (default: 'en')."
    )
    parser.add_argument(
        "--skip-pdfs",
        action="store_true",
        help="Only scrape metadata and populate SQLite/CSV; do not download PDF files."
    )
    parser.add_argument(
        "--limit-medicines",
        type=int,
        default=None,
        help="Limit the number of medicine EPAR pages to crawl (useful for testing)."
    )
    parser.add_argument(
        "--limit-downloads",
        type=int,
        default=None,
        help="Limit the number of PDFs to download (useful for testing)."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset the SQLite database and start fresh (warning: clears progress checkpoints)."
    )
    parser.add_argument(
        "--download-all-tables",
        action="store_true",
        help="Download and export all 10 additional EMA Excel tables (Shortages, Orphans, Referrals, etc.) to CSV."
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Configure Logging
    setup_logging(output_dir)
    log.info("Starting EMA EPAR Downloader...")
    
    # Clean language list
    langs = [l.strip().lower() for l in args.languages.split(",") if l.strip()]
    log.info(f"Target languages configured: {langs}")
    
    # Initialize SQLite Database
    db_path = output_dir / "ema_database.db"
    
    if args.reset and db_path.exists():
        log.warning(f"Reset flag set. Deleting database at {db_path}...")
        try:
            db_path.unlink()
        except Exception as e:
            log.error(f"Could not delete database: {e}")
            
    db = DatabaseManager(db_path)
    
    # Build HTTP Session
    session = build_session(args.max_retries)
    
    # Step 1: Download & Parse Master Excel
    collector = EMADataCollector(db, session, output_dir, langs)
    success = collector.download_and_parse_master()
    if not success:
        log.error("Failed to download or parse master medicines Excel. Exiting.")
        sys.exit(1)
        
    # Optional: Download all additional tables
    if args.download_all_tables:
        download_all_additional_tables(session, output_dir)
        
    # Step 2: Crawl individual EPAR pages for PDF links
    collector.crawl_all_medicines(max_workers=args.threads, limit=args.limit_medicines)
    
    # Step 3: Download queued PDFs (if not skipped)
    if not args.skip_pdfs:
        downloader = EMAPDFDownloader(db, session, output_dir)
        downloader.download_all_queued(max_workers=args.threads, limit=args.limit_downloads)
    else:
        log.info("Skipping PDF downloads as --skip-pdfs was specified.")
        
    # Step 4: Export metadata from database to CSV
    export_documents_metadata(db, output_dir)
    
    log.info("EMA Downloader process completed successfully.")

if __name__ == "__main__":
    main()
