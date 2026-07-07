#!/usr/bin/env python3
"""
openfda_faers_downloader.py
===========================
A robust, professional, and highly resilient data collector for the FDA's Adverse
Event Reporting System (FAERS) via openFDA.

Features:
  1. download-bulk (Recommended for large scale):
     - Dynamically queries openFDA download metadata for all available drug event partitions (1,700+ files).
     - Lock-Free Partition Isolation: Downloads and extracts each partition into its own directory,
       enabling 100% thread-safe parallel processing without write locking or database contention.
     - Relational Normalization: Splits nested JSON cases into three clean relational CSV tables:
       * reports.csv (case demographics and metadata)
       * report_drugs.csv (drug details and openFDA enrichments)
       * report_reactions.csv (MedDRA preferred terms)
       This prevents combinatorial file size explosion, saving hundreds of gigabytes!
     - Range-Based Resumption: Uses HTTP Range headers to resume interrupted ZIP downloads.
     - Progress Checkpointing: Saves state dynamically in 'faers_progress.json'. Resumes seamlessly from interruptions.
     - Storage Optimization: Optional flags to clean up raw ZIPs and JSONLs after extraction to save disk space.
  2. api-harvest:
     - Concurrently or sequentially harvests the live FAERS database via the REST API for a targeted query.
     - Bypasses the 25,000 skip limit using the 'search_after' cursor from Link headers.
  3. search:
     - Queries local processed datasets by safetyreportid, drug, or reaction.
     - Falls back to the live API if local data is not found or is incomplete.
  4. consolidate:
     - Consolidation utility to stream and merge partition-level CSVs into single consolidated master files.

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
import zipfile
import io
import threading
from pathlib import Path
from urllib.parse import urlparse, parse_qs
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
API_BASE_URL = "https://api.fda.gov/drug/event.json"
METADATA_URL = "https://api.fda.gov/download.json"

DEFAULT_OUTPUT_DIR = "Safety & Pharmacovigilance/openfda_faers_data"
MAX_RETRIES = 5
DEFAULT_THREADS = 4

# Normalized CSV Schemas
REPORT_FIELDS = [
    "safetyreportid",
    "transmissiondate",
    "serious",
    "seriousnessdeath",
    "seriousnesslifethreatening",
    "seriousnesshospitalization",
    "seriousnessdisabling",
    "seriousnesscongenitalanomoly",
    "seriousnessother",
    "receivedate",
    "receiptdate",
    "reportercountry",
    "companynumb",
    "senderorganization",
    "patient_age",
    "patient_age_unit",
    "patient_sex",
    "patient_death_date"
]

DRUG_FIELDS = [
    "safetyreportid",
    "drugcharacterization",
    "medicinalproduct",
    "drugdosagetext",
    "drugadministrationroute",
    "drugindication",
    "openfda_brand_name",
    "openfda_generic_name",
    "openfda_manufacturer_name",
    "openfda_substance_name",
    "openfda_pharm_class_pe"
]

REACTION_FIELDS = [
    "safetyreportid",
    "reactionmeddrapt"
]

# -- Logging Setup -----------------------------------------------------------
log = logging.getLogger("openfda_faers")

def setup_logging(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "openfda_faers.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

# -- HTTP Session Configuration ----------------------------------------------
def build_session(api_key: str = None) -> requests.Session:
    """Builds a requests.Session with retries and default headers."""
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    headers = {
        "Accept": "application/json",
        "User-Agent": "BiolytInternOpenFDAFAERSDownloader/1.0 (Python; requests)"
    }
    if api_key:
        headers["X-Api-Key"] = api_key
        
    session.headers.update(headers)
    return session

# -- Data Extractor & Relational Flattener ------------------------------------
def extract_and_normalize_record(record: dict) -> tuple[dict, list[dict], list[dict]]:
    """
    Extracts nested openFDA FAERS safety report into normalized records:
    1. A report dict (one row).
    2. A list of drug dicts (one row per drug).
    3. A list of reaction dicts (one row per reaction).
    """
    def safe_str(val) -> str:
        if val is None:
            return ""
        return str(val).strip()

    safetyreportid = safe_str(record.get("safetyreportid"))
    
    # 1. Extract Report Metadata
    transmissiondate = safe_str(record.get("transmissiondate"))
    serious = safe_str(record.get("serious"))
    seriousnessdeath = safe_str(record.get("seriousnessdeath"))
    seriousnesslifethreatening = safe_str(record.get("seriousnesslifethreatening"))
    seriousnesshospitalization = safe_str(record.get("seriousnesshospitalization"))
    seriousnessdisabling = safe_str(record.get("seriousnessdisabling"))
    seriousnesscongenitalanomoly = safe_str(record.get("seriousnesscongenitalanomoly"))
    seriousnessother = safe_str(record.get("seriousnessother"))
    receivedate = safe_str(record.get("receivedate"))
    receiptdate = safe_str(record.get("receiptdate"))
    
    # Primary Source Country
    primarysource = record.get("primarysource") or {}
    reportercountry = safe_str(primarysource.get("reportercountry"))
    
    companynumb = safe_str(record.get("companynumb"))
    
    # Sender Organization
    sender = record.get("sender") or {}
    senderorganization = safe_str(sender.get("senderorganization"))
    
    # Patient details
    patient = record.get("patient") or {}
    patient_age = safe_str(patient.get("patientonsetage"))
    patient_age_unit = safe_str(patient.get("patientonsetageunit"))
    patient_sex = safe_str(patient.get("patientsex"))
    
    # Patient Death Date
    patientdeath = patient.get("patientdeath") or {}
    patient_death_date = safe_str(patientdeath.get("patientdeathdate"))

    report_row = {
        "safetyreportid": safetyreportid,
        "transmissiondate": transmissiondate,
        "serious": serious,
        "seriousnessdeath": seriousnessdeath,
        "seriousnesslifethreatening": seriousnesslifethreatening,
        "seriousnesshospitalization": seriousnesshospitalization,
        "seriousnessdisabling": seriousnessdisabling,
        "seriousnesscongenitalanomoly": seriousnesscongenitalanomoly,
        "seriousnessother": seriousnessother,
        "receivedate": receivedate,
        "receiptdate": receiptdate,
        "reportercountry": reportercountry,
        "companynumb": companynumb,
        "senderorganization": senderorganization,
        "patient_age": patient_age,
        "patient_age_unit": patient_age_unit,
        "patient_sex": patient_sex,
        "patient_death_date": patient_death_date
    }

    # 2. Extract Drugs
    drug_rows = []
    drugs = patient.get("drug") or []
    for drug in drugs:
        drugcharacterization = safe_str(drug.get("drugcharacterization"))
        medicinalproduct = safe_str(drug.get("medicinalproduct"))
        drugdosagetext = safe_str(drug.get("drugdosagetext"))
        drugadministrationroute = safe_str(drug.get("drugadministrationroute"))
        drugindication = safe_str(drug.get("drugindication"))
        
        # openfda enrichments
        openfda = drug.get("openfda") or {}
        
        def get_openfda_list(key):
            val = openfda.get(key, [])
            if isinstance(val, list):
                return " | ".join(safe_str(v) for v in val if safe_str(v))
            return safe_str(val)

        of_brand = get_openfda_list("brand_name")
        of_generic = get_openfda_list("generic_name")
        of_mfr = get_openfda_list("manufacturer_name")
        of_substance = get_openfda_list("substance_name")
        of_class_pe = get_openfda_list("pharm_class_pe")

        drug_row = {
            "safetyreportid": safetyreportid,
            "drugcharacterization": drugcharacterization,
            "medicinalproduct": medicinalproduct,
            "drugdosagetext": drugdosagetext,
            "drugadministrationroute": drugadministrationroute,
            "drugindication": drugindication,
            "openfda_brand_name": of_brand,
            "openfda_generic_name": of_generic,
            "openfda_manufacturer_name": of_mfr,
            "openfda_substance_name": of_substance,
            "openfda_pharm_class_pe": of_class_pe
        }
        drug_rows.append(drug_row)

    # 3. Extract Reactions
    reaction_rows = []
    reactions = patient.get("reaction") or []
    for reaction in reactions:
        reactionmeddrapt = safe_str(reaction.get("reactionmeddrapt"))
        if reactionmeddrapt:
            reaction_row = {
                "safetyreportid": safetyreportid,
                "reactionmeddrapt": reactionmeddrapt
            }
            reaction_rows.append(reaction_row)

    return report_row, drug_rows, reaction_rows

# -- Downloader Class --------------------------------------------------------
class OpenFDAFAERSDownloader:
    def __init__(self, output_dir: Path, session: requests.Session, delay: float = 1.5, write_jsonl: bool = False, clean_zips: bool = False):
        self.output_dir = output_dir
        self.session = session
        self.delay = delay
        self.write_jsonl = write_jsonl
        self.clean_zips = clean_zips
        self.progress_lock = threading.Lock()

        # Paths
        self.zips_dir = self.output_dir / "zips"
        self.processed_dir = self.output_dir / "processed"
        self.progress_path = self.output_dir / "faers_progress.json"

        # Ensure output directories exist
        self.zips_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Progress & Checkpointing
    # -------------------------------------------------------------------------
    def load_progress(self) -> dict:
        """Loads or queries and initializes progress state from disk."""
        if self.progress_path.exists():
            try:
                with open(self.progress_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
                log.info("Loaded existing progress checkpoint state.")
                if "partitions" in state:
                    return state
            except Exception as e:
                log.warning(f"Could not parse progress file: {e}. Rebuilding checkpoint from metadata.")

        # Rebuild fresh progress state from API download metadata
        log.info("Fetching openFDA download metadata to build partition list...")
        try:
            resp = self.session.get(METADATA_URL, timeout=30)
            resp.raise_for_status()
            metadata = resp.json()
            
            event_meta = metadata.get("results", {}).get("drug", {}).get("event", {})
            partitions = event_meta.get("partitions", [])
            
            if not partitions:
                raise ValueError("No partitions found in openFDA metadata under 'drug.event'.")
            
            log.info(f"Metadata fetched. Total FAERS partitions: {len(partitions)}")
            
            state = {
                "completed": False,
                "timestamp": time.time(),
                "partitions": {}
            }
            
            for p in partitions:
                url = p.get("file")
                size_mb = p.get("size_mb", "0")
                records = p.get("records", 0)
                
                if not url:
                    continue
                
                # Extract quarter and filename
                parsed = urlparse(url)
                path_parts = parsed.path.strip("/").split("/")
                quarter = path_parts[-2] if len(path_parts) >= 2 else "unknown"
                filename = path_parts[-1]
                
                key = f"{quarter}/{filename}"
                
                state["partitions"][key] = {
                    "url": url,
                    "quarter": quarter,
                    "filename": filename,
                    "size_mb": size_mb,
                    "records": records,
                    "status": "pending",
                    "error": None
                }
                
            self.save_progress(state)
            return state
            
        except Exception as e:
            log.error(f"Critical failure building checkpoint state: {e}")
            sys.exit(1)

    def save_progress(self, state: dict):
        """Thread-safe save of the progress state."""
        with self.progress_lock:
            state["timestamp"] = time.time()
            try:
                with open(self.progress_path, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
            except Exception as e:
                log.warning(f"Failed to save progress checkpoint: {e}")

    # -------------------------------------------------------------------------
    # Bulk Download Mode & Worker Pipeline
    # -------------------------------------------------------------------------
    def process_partition(self, key: str, part_state: dict, progress_state: dict) -> bool:
        """Worker pipeline: Downloads, extracts, normalizes, and cleans up a partition."""
        thread_name = threading.current_thread().name
        url = part_state["url"]
        quarter = part_state["quarter"]
        filename = part_state["filename"]
        base_name = filename.replace(".json.zip", "")

        # Target file paths
        part_zip_dir = self.zips_dir / quarter
        part_zip_dir.mkdir(parents=True, exist_ok=True)
        local_zip_path = part_zip_dir / filename

        part_proc_dir = self.processed_dir / quarter
        part_proc_dir.mkdir(parents=True, exist_ok=True)
        
        reports_csv = part_proc_dir / f"{base_name}_reports.csv"
        drugs_csv = part_proc_dir / f"{base_name}_drugs.csv"
        reactions_csv = part_proc_dir / f"{base_name}_reactions.csv"
        jsonl_out = part_proc_dir / f"{base_name}.jsonl"

        # Check if already processed
        if reports_csv.exists() and drugs_csv.exists() and reactions_csv.exists():
            log.info(f"[{thread_name}] Partition {key} already normalized. Skipping.")
            part_state["status"] = "completed"
            self.save_progress(progress_state)
            # Cleanup zip if requested and exists
            if self.clean_zips and local_zip_path.exists():
                local_zip_path.unlink()
            return True

        part_state["status"] = "downloading"
        self.save_progress(progress_state)

        # 1. Download ZIP with Range Resumption
        success = self._download_zip_range(url, local_zip_path, key, thread_name)
        if not success:
            part_state["status"] = "failed"
            part_state["error"] = "Download failed."
            self.save_progress(progress_state)
            return False

        # 2. Extract, Normalize and Stream Parse
        part_state["status"] = "extracting"
        self.save_progress(progress_state)
        log.info(f"[{thread_name}] Extracting and normalizing partition {key}...")
        
        try:
            with zipfile.ZipFile(local_zip_path, "r") as zf:
                file_list = zf.namelist()
                json_files = [f for f in file_list if f.endswith(".json")]
                if not json_files:
                    raise ValueError("No JSON file found in ZIP archive.")
                
                target_json = json_files[0]
                with zf.open(target_json) as jf:
                    # JSON payload load
                    payload = json.load(jf)
            
            results = payload.get("results", [])
            log.info(f"[{thread_name}] Parsing {len(results):,} cases from {key}...")

            # Write relational CSVs
            with open(reports_csv, "w", newline="", encoding="utf-8") as f_rep, \
                 open(drugs_csv, "w", newline="", encoding="utf-8") as f_drg, \
                 open(reactions_csv, "w", newline="", encoding="utf-8") as f_rea:
                
                rep_writer = csv.DictWriter(f_rep, fieldnames=REPORT_FIELDS)
                drg_writer = csv.DictWriter(f_drg, fieldnames=DRUG_FIELDS)
                rea_writer = csv.DictWriter(f_rea, fieldnames=REACTION_FIELDS)

                rep_writer.writeheader()
                drg_writer.writeheader()
                rea_writer.writeheader()

                f_jl = None
                if self.write_jsonl:
                    f_jl = open(jsonl_out, "w", encoding="utf-8")

                try:
                    for record in results:
                        if f_jl:
                            f_jl.write(json.dumps(record) + "\n")
                        
                        rep_row, drug_rows, reaction_rows = extract_and_normalize_record(record)
                        
                        rep_writer.writerow(rep_row)
                        for drg in drug_rows:
                            drg_writer.writerow(drg)
                        for rea in reaction_rows:
                            rea_writer.writerow(rea)
                finally:
                    if f_jl:
                        f_jl.close()

            # Successfully processed
            part_state["status"] = "completed"
            part_state["error"] = None
            self.save_progress(progress_state)
            log.info(f"[{thread_name}] Partition {key} processed successfully.")

            # 3. Aggressive Disk Space Management
            if self.clean_zips and local_zip_path.exists():
                local_zip_path.unlink()
                log.info(f"[{thread_name}] Deleted raw ZIP: {local_zip_path.name}")
            return True

        except Exception as e:
            log.error(f"[{thread_name}] Error processing partition {key}: {e}", exc_info=True)
            part_state["status"] = "failed"
            part_state["error"] = str(e)
            self.save_progress(progress_state)
            return False

    def _download_zip_range(self, url: str, local_path: Path, key: str, thread_name: str) -> bool:
        """Downloads a partition ZIP with HTTP Range-Based Resumption."""
        try:
            head_resp = self.session.head(url, timeout=20)
            head_resp.raise_for_status()
            remote_size = int(head_resp.headers.get("content-length", 0))
            accept_ranges = head_resp.headers.get("accept-ranges", "").lower()
        except Exception as e:
            log.warning(f"[{thread_name}] HEAD request failed for {key}: {e}. Downloading without range validation.")
            remote_size = 0
            accept_ranges = "none"

        headers = {}
        local_size = 0
        file_mode = "wb"

        if local_path.exists():
            local_size = local_path.stat().st_size
            if remote_size > 0 and local_size == remote_size:
                log.info(f"[{thread_name}] {key} ZIP already fully downloaded.")
                return True
            elif remote_size > 0 and local_size < remote_size:
                if "bytes" in accept_ranges or accept_ranges == "yes":
                    headers["Range"] = f"bytes={local_size}-"
                    file_mode = "ab"
                    log.info(f"[{thread_name}] Resuming {key} download from byte {local_size}...")
                else:
                    log.info(f"[{thread_name}] Server does not support Ranges. Re-downloading {key} from scratch.")
                    local_path.unlink()
                    local_size = 0
            else:
                log.info(f"[{thread_name}] Local file size mismatch. Re-downloading {key} from scratch.")
                local_path.unlink()
                local_size = 0

        # Stream the download
        try:
            resp = self.session.get(url, headers=headers, stream=True, timeout=60)
            resp.raise_for_status()

            if resp.status_code == 200 and file_mode == "ab":
                log.warning(f"[{thread_name}] Server ignored Range request; downloading full file from scratch.")
                file_mode = "wb"
                local_size = 0

            downloaded = local_size
            chunk_size = 256 * 1024  # 256 KB chunks
            
            with open(local_path, file_mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
            
            if remote_size > 0 and downloaded < remote_size:
                raise IOError(f"Incomplete download: {downloaded}/{remote_size} bytes written.")
                
            log.info(f"[{thread_name}] Downloaded {key} successfully.")
            return True
        except Exception as e:
            log.error(f"[{thread_name}] Download failed for {key}: {e}")
            return False

    def run_bulk_download(self, threads: int, limit_partitions: int | None = None) -> bool:
        """Orchestrates multi-threaded bulk downloads and normalization."""
        progress_state = self.load_progress()
        
        # Identify pending partitions
        pending_keys = [k for k, v in progress_state["partitions"].items() if v["status"] != "completed"]
        
        if not pending_keys:
            log.info("All partitions are already completed successfully!")
            return True

        if limit_partitions is not None:
            pending_keys = pending_keys[:limit_partitions]
            log.info(f"Testing Limit active: Processing up to {len(pending_keys)} partitions.")

        total_to_process = len(pending_keys)
        log.info(f"Starting bulk pipeline: {total_to_process} partitions to process with {threads} threads.")

        # Setup master progress bar
        global_pbar = None
        if tqdm:
            global_pbar = tqdm(total=total_to_process, desc="FAERS Partitions", unit="part")

        # Concurrently execute worker pipeline
        success_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=threads, thread_name_prefix="FAERSWorker") as executor:
            future_to_key = {
                executor.submit(self.process_partition, key, progress_state["partitions"][key], progress_state): key
                for key in pending_keys
            }
            
            for future in concurrent.futures.as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    success = future.result()
                    if success:
                        success_count += 1
                except Exception as exc:
                    log.error(f"Partition {key} generated an exception: {exc}")
                
                if global_pbar:
                    global_pbar.update(1)

        if global_pbar:
            global_pbar.close()

        log.info(f"Bulk pipeline round completed: {success_count}/{total_to_process} partitions processed successfully.")
        
        # Check if all partitions in the checkpoint are completed
        all_completed = all(v["status"] == "completed" for v in progress_state["partitions"].values())
        if all_completed:
            progress_state["completed"] = True
            self.save_progress(progress_state)
            log.info("Awesome! The entire FAERS dataset has been fully collected and normalized!")
            
        if success_count == total_to_process:
            log.info(f"All {success_count} scheduled partitions in this run completed successfully.")
            return True
        else:
            log.warning(f"Some partitions in this run failed ({success_count}/{total_to_process} succeeded). Please rerun the downloader to resume failed partitions.")
            return False

# -----------------------------------------------------------------------------
# Live API Harvesting Mode (Targeted Query)
# -----------------------------------------------------------------------------
def run_api_harvest(session: requests.Session, query: str, limit: int, output_dir: Path, output_name: str, write_jsonl: bool, delay: float):
    """Harvests the live FAERS API matching a search query, with pagination."""
    harvest_dir = output_dir / "harvested"
    harvest_dir.mkdir(parents=True, exist_ok=True)
    
    reports_csv = harvest_dir / f"{output_name}_reports.csv"
    drugs_csv = harvest_dir / f"{output_name}_drugs.csv"
    reactions_csv = harvest_dir / f"{output_name}_reactions.csv"
    jsonl_out = harvest_dir / f"{output_name}.jsonl"

    log.info(f"Initiating live API harvest for query: '{query}' (Limit: {limit} records)")
    
    # 1. Fetch total matching records
    params = {
        "search": query,
        "limit": 1
    }
    try:
        resp = session.get(API_BASE_URL, params=params, timeout=20)
        resp.raise_for_status()
        total_available = resp.json().get("meta", {}).get("results", {}).get("total", 0)
        log.info(f"Total matching records available on openFDA: {total_available:,}")
    except Exception as e:
        log.error(f"Failed to query live endpoint: {e}")
        return False

    target_to_fetch = min(limit, total_available)
    if target_to_fetch == 0:
        log.info("No matching records found to harvest.")
        return True

    # Open CSV files
    with open(reports_csv, "w", newline="", encoding="utf-8") as f_rep, \
         open(drugs_csv, "w", newline="", encoding="utf-8") as f_drg, \
         open(reactions_csv, "w", newline="", encoding="utf-8") as f_rea:
        
        rep_writer = csv.DictWriter(f_rep, fieldnames=REPORT_FIELDS)
        drg_writer = csv.DictWriter(f_drg, fieldnames=DRUG_FIELDS)
        rea_writer = csv.DictWriter(f_rea, fieldnames=REACTION_FIELDS)

        rep_writer.writeheader()
        drg_writer.writeheader()
        rea_writer.writeheader()

        f_jl = None
        if write_jsonl:
            f_jl = open(jsonl_out, "w", encoding="utf-8")

        downloaded = 0
        search_after = None
        consecutive_failures = 0

        pbar = tqdm(total=target_to_fetch, desc="Harvesting Live Cases", unit="case") if tqdm else None

        try:
            while downloaded < target_to_fetch:
                page_limit = min(100, target_to_fetch - downloaded) # Max API page limit is 100
                
                # Fetch page
                api_params = {
                    "search": query,
                    "limit": page_limit,
                    "sort": "receivedate:asc"
                }
                if search_after:
                    api_params["search_after"] = search_after

                try:
                    resp = session.get(API_BASE_URL, params=api_params, timeout=30)
                    
                    if resp.status_code == 429:
                        log.warning("Rate limited (429). Backing off for 15 seconds...")
                        time.sleep(15.0)
                        continue
                        
                    if resp.status_code == 404:
                        log.info("Reached end of records.")
                        break
                        
                    resp.raise_for_status()
                    payload = resp.json()
                    
                except Exception as e:
                    consecutive_failures += 1
                    log.warning(f"API Request exception: {e}")
                    if consecutive_failures >= 5:
                        log.error("5 consecutive API failures. Halting harvest.")
                        break
                    time.sleep(2.0 * consecutive_failures)
                    continue

                consecutive_failures = 0
                results = payload.get("results", [])
                
                if not results:
                    log.info("No more records returned from API.")
                    break

                # Extract and write
                for record in results:
                    if f_jl:
                        f_jl.write(json.dumps(record) + "\n")
                    
                    rep_row, drug_rows, reaction_rows = extract_and_normalize_record(record)
                    
                    rep_writer.writerow(rep_row)
                    for drg in drug_rows:
                        drg_writer.writerow(drg)
                    for rea in reaction_rows:
                        rea_writer.writerow(rea)

                downloaded += len(results)
                if pbar:
                    pbar.update(len(results))
                else:
                    log.info(f"Harvested {downloaded}/{target_to_fetch} records...")

                # Resolve next search_after from response Link header
                next_token = None
                link_header = resp.headers.get("Link") or resp.headers.get("link")
                if link_header:
                    parts = link_header.split(",")
                    for part in parts:
                        if 'rel="next"' in part.lower():
                            url_start = part.find("<") + 1
                            url_end = part.find(">")
                            if url_start > 0 and url_end > 0:
                                next_url = part[url_start:url_end]
                                parsed_url = urlparse(next_url)
                                query_params = parse_qs(parsed_url.query)
                                tokens = query_params.get("search_after", [])
                                if tokens:
                                    next_token = tokens[0]
                                    break
                
                # Fallback: if search_after not in Link headers, pull receivedate of last record
                if not next_token and results:
                    next_token = results[-1].get("receivedate")

                search_after = next_token
                
                if not search_after:
                    log.info("No next token found. Harvesting complete.")
                    break

                time.sleep(delay)

        finally:
            if f_jl:
                f_jl.close()
            if pbar:
                pbar.close()

    log.info(f"Harvest complete. Saved analytical tables in: {harvest_dir.resolve()}")
    return True

# -----------------------------------------------------------------------------
# Consolidation / Merging Mode
# -----------------------------------------------------------------------------
def stream_merge_csvs(file_list: list[Path], output_path: Path, fieldnames: list[str]):
    """Streams and merges multiple partition CSV files into a master file."""
    log.info(f"Merging {len(file_list)} partition files into master file: {output_path.name}...")
    
    with open(output_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        
        for fp in tqdm(file_list, desc=f"Merging {output_path.name}") if tqdm else file_list:
            if not fp.exists() or fp.stat().st_size == 0:
                continue
            try:
                with open(fp, "r", encoding="utf-8") as in_f:
                    reader = csv.DictReader(in_f)
                    for row in reader:
                        writer.writerow(row)
            except Exception as e:
                log.error(f"Failed to stream merge file {fp.name}: {e}")

def run_consolidation(output_dir: Path):
    """Finds all processed partition CSV files and merges them."""
    processed_dir = output_dir / "processed"
    if not processed_dir.exists():
        log.error("No processed partition folder found. Cannot consolidate.")
        return False
        
    reports_files = sorted(list(processed_dir.glob("**/*_reports.csv")))
    drugs_files = sorted(list(processed_dir.glob("**/*_drugs.csv")))
    reactions_files = sorted(list(processed_dir.glob("**/*_reactions.csv")))
    
    if not reports_files:
        log.warning("No processed files found to consolidate.")
        return True

    log.info(f"Found {len(reports_files)} processed partitions. Starting consolidation...")

    stream_merge_csvs(reports_files, output_dir / "faers_reports_compiled.csv", REPORT_FIELDS)
    stream_merge_csvs(drugs_files, output_dir / "faers_drugs_compiled.csv", DRUG_FIELDS)
    stream_merge_csvs(reactions_files, output_dir / "faers_reactions_compiled.csv", REACTION_FIELDS)
    
    log.info("Consolidation finished! Master datasets saved:")
    log.info(f"  - Reports   : {output_dir / 'faers_reports_compiled.csv'}")
    log.info(f"  - Drugs     : {output_dir / 'faers_drugs_compiled.csv'}")
    log.info(f"  - Reactions : {output_dir / 'faers_reactions_compiled.csv'}")
    return True

# -----------------------------------------------------------------------------
# Search & API Fallback Mode
# -----------------------------------------------------------------------------
def perform_local_search(processed_dir: Path, term: str) -> list[dict]:
    """Searches through local processed files for a case matching ID, drug, or reaction."""
    if not processed_dir.exists():
        log.warning("Local processed dataset not found.")
        return []

    log.info(f"Searching local partition files for term '{term}'...")
    term_upper = term.upper()
    matches = {} # safetyreportid -> full safety report details
    
    # We will search partition reports, drugs, and reactions
    report_paths = list(processed_dir.glob("**/*_reports.csv"))
    
    # 1. Search in reports CSVs
    matched_ids = set()
    for rp in report_paths:
        with open(rp, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                s_id = row["safetyreportid"]
                if (term_upper in s_id.upper() or 
                    term_upper in row["companynumb"].upper() or 
                    term_upper in row["senderorganization"].upper()):
                    matched_ids.add(s_id)
                    matches[s_id] = {
                        "report": row,
                        "drugs": [],
                        "reactions": []
                    }
                    if len(matches) >= 5: # Cap search results
                        break
        if len(matches) >= 5:
            break
            
    # 2. Search in drugs and reactions CSVs for these matched IDs, or search them directly for term match
    drug_paths = list(processed_dir.glob("**/*_drugs.csv"))
    reaction_paths = list(processed_dir.glob("**/*_reactions.csv"))

    # Search drugs for matches to the search term (if not already fully capped)
    if len(matches) < 5:
        for dp in drug_paths:
            with open(dp, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    s_id = row["safetyreportid"]
                    if (term_upper in row["medicinalproduct"].upper() or 
                        term_upper in row["openfda_brand_name"].upper() or 
                        term_upper in row["openfda_generic_name"].upper() or 
                        term_upper in row["openfda_substance_name"].upper()):
                        matched_ids.add(s_id)
                        if s_id not in matches:
                            matches[s_id] = {"report": None, "drugs": [], "reactions": []}
                        if len(matches) >= 5:
                            break
            if len(matches) >= 5:
                break

    # Search reactions for matches to the search term
    if len(matches) < 5:
        for rap in reaction_paths:
            with open(rap, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    s_id = row["safetyreportid"]
                    if term_upper in row["reactionmeddrapt"].upper():
                        matched_ids.add(s_id)
                        if s_id not in matches:
                            matches[s_id] = {"report": None, "drugs": [], "reactions": []}
                        if len(matches) >= 5:
                            break
            if len(matches) >= 5:
                break

    # Populate matching reports details
    for s_id in list(matches.keys()):
        # Retrieve report row if not found
        if matches[s_id]["report"] is None:
            for rp in report_paths:
                with open(rp, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["safetyreportid"] == s_id:
                            matches[s_id]["report"] = row
                            break
                if matches[s_id]["report"] is not None:
                    break

        # Retrieve drugs
        for dp in drug_paths:
            with open(dp, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["safetyreportid"] == s_id:
                        matches[s_id]["drugs"].append(row)
            
        # Retrieve reactions
        for rap in reaction_paths:
            with open(rap, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["safetyreportid"] == s_id:
                        matches[s_id]["reactions"].append(row)

    return list(matches.values())

def perform_api_search(session: requests.Session, term: str) -> list[dict]:
    """Queries the live openFDA API for matching adverse events."""
    log.info(f"Querying live openFDA API for term '{term}'...")
    
    api_query = (
        f'safetyreportid:"{term}" OR '
        f'patient.drug.medicinalproduct:"{term}" OR '
        f'patient.drug.openfda.brand_name:"{term}" OR '
        f'patient.reaction.reactionmeddrapt:"{term}"'
    )
    params = {
        "search": api_query,
        "limit": 5
    }
    try:
        resp = session.get(API_BASE_URL, params=params, timeout=20)
        if resp.status_code == 200:
            results = resp.json().get("results", [])
            formatted = []
            for rec in results:
                rep_row, drug_rows, reaction_rows = extract_and_normalize_record(rec)
                formatted.append({
                    "report": rep_row,
                    "drugs": drug_rows,
                    "reactions": reaction_rows
                })
            return formatted
        elif resp.status_code == 404:
            log.info("No matching records found on the live openFDA API.")
            return []
        else:
            log.error(f"API search failed with status {resp.status_code}: {resp.text}")
    except Exception as e:
        log.error(f"API search failed with exception: {e}")
    return []

# -- Main Execution -----------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="openFDA FAERS Downloader: Resilient, multi-threaded collector for US adverse event reports.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("mode", choices=["download-bulk", "api-harvest", "consolidate", "search", "metadata-only"],
                        help="Mode of operation. 'download-bulk' is the full pipeline. "
                             "'api-harvest' fetches a live query. 'consolidate' merges partitions. "
                             "'search' queries cases. 'metadata-only' checks available partitions.")
    
    # Configuration options
    parser.add_argument("-o", "--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
                        help="Output directory for storing logs, checkpoints, and data.")
    parser.add_argument("-t", "--threads", type=int, default=DEFAULT_THREADS,
                        help="Number of concurrent worker threads for bulk downloads.")
    parser.add_argument("-d", "--delay", type=float, default=None,
                        help="Polite delay between API requests. Default: 1.5s (public) or 0.25s (with API key).")
    parser.add_argument("-l", "--limit", type=int, default=None,
                        help="Harvest limit (api-harvest) or partition limit (download-bulk).")
    parser.add_argument("--api-key", type=str, default=None,
                        help="Optional openFDA API key for higher rate limits (240 requests/min).")
    parser.add_argument("--query", type=str, default=None,
                        help="Search query term (for 'search' or 'api-harvest' modes).")
    parser.add_argument("--output-name", type=str, default="harvested_events",
                        help="Filename prefix for live harvested datasets.")
    parser.add_argument("--write-jsonl", action="store_true",
                        help="Write high-fidelity raw JSONL files in addition to normalized CSVs.")
    parser.add_argument("--clean-zips", action="store_true",
                        help="Delete raw ZIP files immediately after extraction to save disk space.")
    parser.add_argument("--no-resume", action="store_true",
                        help="Start bulk download fresh, ignoring the progress checkpoint.")

    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    setup_logging(output_dir)

    log.info("=" * 70)
    log.info("      openFDA FAERS ADVERSE EVENT DATA COLLECTOR")
    log.info("=" * 70)
    log.info(f"Mode             : {args.mode}")
    log.info(f"Output Directory : {output_dir.resolve()}")
    
    session = build_session(args.api_key)

    # Delay resolution
    delay = args.delay
    if delay is None:
        delay = 0.25 if args.api_key else 1.5

    # Checkpoint reset if requested
    if args.no_resume:
        progress_path = output_dir / "faers_progress.json"
        if progress_path.exists():
            log.info("Fresh run requested. Removing existing progress checkpoint...")
            progress_path.unlink()

    if args.mode == "metadata-only":
        # Simply load progress which queries and dumps metadata
        downloader = OpenFDAFAERSDownloader(output_dir, session)
        state = downloader.load_progress()
        total_size_gb = sum(float(v["size_mb"]) for v in state["partitions"].values()) / 1024.0
        total_records = sum(int(v["records"]) for v in state["partitions"].values())
        log.info(f"Total partitions available: {len(state['partitions']):,}")
        log.info(f"Total zipped size         : {total_size_gb:.2f} GB")
        log.info(f"Total reports available   : {total_records:,}")
        sys.exit(0)

    elif args.mode == "download-bulk":
        downloader = OpenFDAFAERSDownloader(
            output_dir=output_dir,
            session=session,
            delay=delay,
            write_jsonl=args.write_jsonl,
            clean_zips=args.clean_zips
        )
        success = downloader.run_bulk_download(threads=args.threads, limit_partitions=args.limit)
        if success:
            log.info("Bulk download and normalization pipeline completed successfully.")
            sys.exit(0)
        sys.exit(1)

    elif args.mode == "api-harvest":
        if not args.query:
            log.error("Live API harvest mode requires a query. Use --query '<term>'")
            sys.exit(1)
        harvest_limit = args.limit if args.limit is not None else 1000
        success = run_api_harvest(
            session=session,
            query=args.query,
            limit=harvest_limit,
            output_dir=output_dir,
            output_name=args.output_name,
            write_jsonl=args.write_jsonl,
            delay=delay
        )
        if success:
            sys.exit(0)
        sys.exit(1)

    elif args.mode == "consolidate":
        success = run_consolidation(output_dir)
        if success:
            sys.exit(0)
        sys.exit(1)

    elif args.mode == "search":
        if not args.query:
            log.error("Search mode requires a query term. Use --query '<term>'")
            sys.exit(1)
        
        # 1. Search locally
        downloader = OpenFDAFAERSDownloader(output_dir, session)
        results = perform_local_search(downloader.processed_dir, args.query)
        
        # 2. Fallback to live API
        if not results:
            log.info("No matching records found locally. Falling back to live openFDA API search...")
            results = perform_api_search(session, args.query)
        else:
            log.info(f"Found {len(results)} matching records locally.")

        if not results:
            log.info("No matching records found anywhere.")
            sys.exit(0)

        # Output results beautifully
        print("\n" + "=" * 75)
        print(f" FAERS SEARCH RESULTS FOR: '{args.query}'")
        print("=" * 75)
        for idx, item in enumerate(results, 1):
            rep = item["report"]
            drugs = item["drugs"]
            reactions = item["reactions"]
            
            print(f"\n[{idx}] Safety Report ID: {rep.get('safetyreportid')}")
            print(f"    Received Date     : {rep.get('receivedate')} | Transmission Date: {rep.get('transmissiondate')}")
            print(f"    Seriousness       : Serious={rep.get('serious')} | Death={rep.get('seriousnessdeath')} | Hosp={rep.get('seriousnesshospitalization')}")
            print(f"    Primary Country   : {rep.get('reportercountry')} | Company Case #: {rep.get('companynumb')}")
            print(f"    Patient           : Age={rep.get('patient_age')} {rep.get('patient_age_unit')} | Sex={rep.get('patient_sex')}")
            if rep.get('patient_death_date'):
                print(f"    Patient Death Date: {rep.get('patient_death_date')}")
            
            # Print Drugs
            print("    Suspect/Concomitant Drugs:")
            for d in drugs[:5]: # Cap drug list print at 5
                role_map = {"1": "Suspect", "2": "Concomitant", "3": "Interacting"}
                role = role_map.get(d.get("drugcharacterization"), "Unknown")
                print(f"      - {d.get('medicinalproduct')} [{role}] | Indication: {d.get('drugindication')}")
                if d.get("openfda_brand_name"):
                    print(f"        openFDA Brand: {d.get('openfda_brand_name')}")
            if len(drugs) > 5:
                print(f"      ... and {len(drugs) - 5} more drugs.")
                
            # Print Reactions
            rx_list = [r.get("reactionmeddrapt") for r in reactions]
            print(f"    Adverse Reactions : {', '.join(rx_list)}")
            print("-" * 75)

if __name__ == "__main__":
    main()
