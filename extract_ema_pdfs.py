#!/usr/bin/env python3
"""
extract_ema_pdfs.py
===================
A robust, multi-threaded clinical data extractor that streams EMA PDFs from AWS S3,
utilizes the MiniMax-M3 LLM API to extract structured regulatory/clinical fields
matching user-specified naming conventions (composition, therapeutic_indications, etc.),
extracts 15 detailed clinical trial fields (nct_id, sponsor, outcomes, country, etc.),
records checkpoints in SQLite, and exports document-level, consolidated drug-level,
and trial-level CSV reports.
"""

import os
import sys
import io
import re
import json
import time
import sqlite3
import logging
import argparse
import threading
from pathlib import Path
import concurrent.futures
import pandas as pd

# Optional progress bar
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

# AWS S3 library
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:
    print("[ERROR] 'boto3' is required. Please run: pip install boto3")
    sys.exit(1)

# PDF library
try:
    from pypdf import PdfReader
except ImportError:
    print("[ERROR] 'pypdf' is required. Please run: pip install pypdf")
    sys.exit(1)

# OpenAI SDK for MiniMax API
try:
    from openai import OpenAI
except ImportError:
    print("[ERROR] 'openai' (OpenAI SDK) is required. Please run: pip install openai")
    sys.exit(1)

# Logger setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("ema_extractor")

# Default API configurations
DEFAULT_MINIMAX_API_KEY = "sk-cp-4dv75c8NnpSDVNhWMDl0uAyzR1raupBgSpTf9Fxt3-rnP_LCAXRFtbjKLHOmgy9fRqUYkbExiLFnlqoj4kU76TmUtKvxLngbZZdn9ErAI0Okiy0On8eTVLM"
MINIMAX_BASE_URL = "https://api.minimax.io/v1"

# Setup thread-safe database connection helpers
def get_db_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def initialize_extractions_table(db_path: Path):
    """Creates/updates the pdf_extractions schema if it does not exist."""
    # Check if table exists and drop it if it is legacy (missing composition column)
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pdf_extractions';")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(pdf_extractions);")
            cols = [info[1] for info in cursor.fetchall()]
            if 'composition' not in cols:
                log.info("Dropping legacy pdf_extractions table to update schema to match new column names...")
                conn.execute("DROP TABLE pdf_extractions;")
                conn.commit()

    query = """
    CREATE TABLE IF NOT EXISTS pdf_extractions (
        document_url TEXT PRIMARY KEY,
        ema_product_number TEXT,
        medicine_name TEXT,
        document_type TEXT,
        extraction_status TEXT DEFAULT 'pending',
        extraction_error TEXT,
        extracted_at TEXT,
        nct_numbers TEXT,
        composition TEXT,
        therapeutic_indications TEXT,
        posology TEXT,
        contraindications TEXT,
        undesirable_effects TEXT,
        benefits_in_studies TEXT,
        benefit_risk_balance TEXT,
        document_summary TEXT,
        clinical_trials_json TEXT,
        document_procedure_dates TEXT
    );
    """
    with get_db_connection(db_path) as conn:
        conn.execute(query)
        conn.commit()
    log.info("Initialized pdf_extractions schema table.")

# Prompt builders based on document type
def get_prompt_for_doc_type(doc_type: str) -> str:
    # Common clinical trial structured fields requested in JSON format
    clinical_trials_spec = """
You must also identify and extract structured information for each clinical trial or study mentioned in the text. Return this in a key "clinical_trials" which must be a list of objects, where each object contains these exact keys (use null for any missing details):
- "nct_id": The registry identifier (e.g. NCT03361748).
- "brief_title": Short title of the study.
- "official_title": Full official scientific title of the study.
- "overall_status": Status of the trial (e.g., active, completed, recruiting, terminated).
- "start_date": Trial start date.
- "sponsor": Lead sponsor / developer.
- "condition": Condition or disease being studied (e.g., Multiple Myeloma).
- "phase": The phase of the trial (e.g., Phase 3, Phase 1/2, Pivotal, Supportive).
- "intervention_name": Name of the drug or therapy (e.g. idecabtagene vicleucel).
- "intervention_type": Type of intervention (e.g. biological, gene therapy, small molecule, vaccine).
- "primary_outcome": Description of the primary efficacy outcomes/endpoints.
- "secondary_outcome": Description of secondary outcomes/endpoints.
- "country": Location or country where the trial was conducted (e.g., multinational, EU, US).
- "study_type": Study type (e.g., interventional, observational, randomized, open-label).
- "enrollment": Number of patients enrolled/randomized.

Also extract:
- "document_procedure_dates": Dates associated with the regulatory procedure, CHMP opinion date, publication date, or version date of this document. Return null if not found.

Make sure the values are precise, complete, and directly extracted or summarized from the text.
Do not include markdown code block formatting (like ```json) in your response. Just return the JSON object."""

    if doc_type == "overview":
        return """You are an expert clinical data extraction assistant.
Your task is to extract relevant clinical and regulatory information from the provided European Medicines Agency (EMA) EPAR Medicine Overview document text.
You must return a valid JSON object with the following keys:
1. "nct_numbers": A list of clinical trial registry IDs (like NCT00000000) found in the text. Return an empty list if none are found.
2. "composition": Qualitative and quantitative composition details of active substance.
3. "therapeutic_indications": What the medicine is used for / approved indications.
4. "posology": How the medicine is used/administered.
5. "contraindications": Contraindications (who should not take it).
6. "undesirable_effects": Side effects and risks.
7. "benefits_in_studies": Efficacy and benefits shown in studies.
8. "benefit_risk_balance": Summary of why the medicine was approved (benefit-risk balance).
""" + clinical_trials_spec

    elif doc_type == "product-information":
        return """You are an expert clinical data extraction assistant.
Your task is to extract relevant prescribing information from the provided Summary of Product Characteristics (SmPC).
You must return a valid JSON object with the following keys:
1. "nct_numbers": A list of clinical trial registry IDs (like NCT00000000) found in the text. Return an empty list if none are found.
2. "composition": Qualitative and quantitative composition details of active substance.
3. "therapeutic_indications": Approved therapeutic indications.
4. "posology": Posology and method of administration.
5. "contraindications": Documented contraindications.
6. "undesirable_effects": Undesirable effects / side effects.
""" + clinical_trials_spec

    elif doc_type == "assessment-report":
        return """You are an expert clinical data extraction assistant.
Your task is to extract relevant clinical efficacy and safety details from the EPAR Assessment Report.
You must return a valid JSON object with the following keys:
1. "nct_numbers": A list of clinical trial registry IDs (like NCT00000000) found in the text. Return an empty list if none are found.
2. "benefits_in_studies": Summary of the clinical trial efficacy results.
3. "benefit_risk_balance": Detailed conclusions on the benefit-risk balance.
""" + clinical_trials_spec

    else:
        return """You are an expert clinical data extraction assistant.
Your task is to extract a brief summary and any clinical trial numbers from this regulatory document.
You must return a valid JSON object with the following keys:
1. "nct_numbers": A list of clinical trial registry IDs (like NCT00000000) found in the text. Return an empty list if none are found.
2. "document_summary": A detailed summary of the content and purpose of this document.
""" + clinical_trials_spec

def clean_and_parse_json(raw_text: str) -> dict:
    """Strips LLM reasoning/thinking blocks and extracts a parseable JSON dictionary."""
    # Strip <think>...</think> tags if present (MiniMax M3 reasoning feature)
    cleaned = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    
    # Locate first { and last } to extract JSON body
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace == -1 or last_brace == -1:
        raise ValueError("Could not find outer JSON braces in the LLM response.")
        
    json_str = cleaned[first_brace:last_brace+1]
    return json.loads(json_str)

class EMARecoveryProcessor:
    def __init__(self, db_path: Path, bucket: str, s3_prefix: str, aws_profile: str, api_key: str):
        self.db_path = db_path
        self.bucket = bucket
        self.s3_prefix = s3_prefix.rstrip("/")
        self.aws_profile = aws_profile
        self.api_key = api_key
        
        # Initialize OpenAI client for MiniMax
        self.openai_client = OpenAI(api_key=self.api_key, base_url=MINIMAX_BASE_URL)
        
        # Thread safety locks
        self.db_lock = threading.Lock()
        
    def get_s3_client(self):
        """Creates an S3 client instance for the current thread."""
        if self.aws_profile:
            session = boto3.Session(profile_name=self.aws_profile)
        else:
            session = boto3.Session()
        return session.client("s3")

    def fetch_pending_downloads(self, limit: int = None, medicine_filter: str = None) -> list:
        """Fetches files that were successfully downloaded but haven't been successfully extracted yet."""
        query = """
        SELECT d.document_url, d.ema_product_number, d.medicine_name, d.document_type, dl.local_path
        FROM downloads dl
        JOIN documents d ON dl.document_url = d.document_url
        WHERE dl.status = 'completed'
          AND d.document_url NOT IN (
              SELECT document_url FROM pdf_extractions WHERE extraction_status = 'completed'
          )
        """
        params = []
        if medicine_filter:
            query += " AND d.medicine_name LIKE ?"
            params.append(f"%{medicine_filter}%")
            
        if limit:
            query += f" LIMIT {limit}"
            
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.fetchall()

    def update_status(self, doc_url: str, prod_num: str, med_name: str, doc_type: str, 
                      status: str, error: str = None, data: dict = None):
        """Thread-safe update of the checkpoint database with extraction results."""
        nct_str = ",".join(data.get("nct_numbers", [])) if data and "nct_numbers" in data else None
        
        # Serialize clinical trials list to JSON string
        trials_json = None
        if data and "clinical_trials" in data:
            trials_json = json.dumps(data["clinical_trials"])
            
        def safe_str(val):
            if val is None:
                return None
            if isinstance(val, (dict, list)):
                return json.dumps(val)
            return str(val)

        query = """
        INSERT INTO pdf_extractions (
            document_url, ema_product_number, medicine_name, document_type,
            extraction_status, extraction_error, extracted_at, nct_numbers,
            composition, therapeutic_indications, posology, contraindications,
            undesirable_effects, benefits_in_studies, benefit_risk_balance,
            document_summary, clinical_trials_json, document_procedure_dates
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_url) DO UPDATE SET
            extraction_status = excluded.extraction_status,
            extraction_error = excluded.extraction_error,
            extracted_at = excluded.extracted_at,
            nct_numbers = excluded.nct_numbers,
            composition = excluded.composition,
            therapeutic_indications = excluded.therapeutic_indications,
            posology = excluded.posology,
            contraindications = excluded.contraindications,
            undesirable_effects = excluded.undesirable_effects,
            benefits_in_studies = excluded.benefits_in_studies,
            benefit_risk_balance = excluded.benefit_risk_balance,
            document_summary = excluded.document_summary,
            clinical_trials_json = excluded.clinical_trials_json,
            document_procedure_dates = excluded.document_procedure_dates;
        """
        
        params = (
            doc_url, prod_num, med_name, doc_type, status, safe_str(error), nct_str,
            safe_str(data.get("composition")) if data else None,
            safe_str(data.get("therapeutic_indications")) if data else None,
            safe_str(data.get("posology")) if data else None,
            safe_str(data.get("contraindications")) if data else None,
            safe_str(data.get("undesirable_effects")) if data else None,
            safe_str(data.get("benefits_in_studies")) if data else None,
            safe_str(data.get("benefit_risk_balance")) if data else None,
            safe_str(data.get("document_summary")) if data else None,
            trials_json,
            safe_str(data.get("document_procedure_dates")) if data else None
        )
        
        with self.db_lock:
            with get_db_connection(self.db_path) as conn:
                conn.execute(query, params)
                conn.commit()

    def process_document(self, task: tuple) -> bool:
        """Processes a single PDF document: download, magic-check, parse, LLM-extract, checkpoint."""
        doc_url, prod_num, med_name, doc_type, local_path = task
        s3_key = f"{self.s3_prefix}/{local_path.replace('\\', '/')}"
        
        s3_client = self.get_s3_client()
        
        # 1. Download stream from S3
        try:
            response = s3_client.get_object(Bucket=self.bucket, Key=s3_key)
            pdf_bytes = response['Body'].read()
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_msg = f"S3 Download Failed ({error_code}): {e}"
            log.warning(f"[{med_name}] Error downloading {s3_key}: {error_msg}")
            self.update_status(doc_url, prod_num, med_name, doc_type, 'failed', error_msg)
            return False
        except Exception as e:
            error_msg = f"Download error: {e}"
            log.warning(f"[{med_name}] Error downloading {s3_key}: {error_msg}")
            self.update_status(doc_url, prod_num, med_name, doc_type, 'failed', error_msg)
            return False
            
        # 2. Check Magic Header Bytes (resiliency check)
        if not pdf_bytes.startswith(b"%PDF-"):
            error_msg = f"Corrupted file: Magic bytes {pdf_bytes[:5]} do not start with %PDF-"
            log.warning(f"[{med_name}] Validation check failed for {s3_key}: {error_msg}")
            self.update_status(doc_url, prod_num, med_name, doc_type, 'corrupted', error_msg)
            return False
            
        # 3. Extract text from PDF using pypdf with optimized page boundaries
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            total_pages = len(reader.pages)
            
            # Smart page limits to avoid LLM token overflow
            max_pages = total_pages
            if doc_type == "product-information":
                max_pages = min(total_pages, 15)  # SPC details are at the front
            elif doc_type == "assessment-report":
                max_pages = min(total_pages, 30)  # Core clinical discussion limit
            elif doc_type not in ["overview"]:
                max_pages = min(total_pages, 10)  # Other short updates
                
            pdf_text = ""
            for i in range(max_pages):
                page_text = reader.pages[i].extract_text()
                if page_text:
                    pdf_text += page_text + "\n"
                    
            pdf_text = pdf_text.strip()
            if not pdf_text:
                error_msg = "Empty PDF text extracted."
                log.warning(f"[{med_name}] Empty content: {s3_key}")
                self.update_status(doc_url, prod_num, med_name, doc_type, 'empty_text', error_msg)
                return False
                
        except Exception as e:
            error_msg = f"PDF text parsing failed: {e}"
            log.warning(f"[{med_name}] Parser error for {s3_key}: {error_msg}")
            self.update_status(doc_url, prod_num, med_name, doc_type, 'failed', error_msg)
            return False
            
        # 4. Invoke MiniMax LLM API to extract structured fields
        system_prompt = get_prompt_for_doc_type(doc_type)
        user_prompt = f"Document Text:\n{pdf_text}"
        
        api_retries = 3
        api_backoff = 2.0
        for attempt in range(api_retries):
            try:
                response = self.openai_client.chat.completions.create(
                    model="MiniMax-M3",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    timeout=90.0
                )
                raw_reply = response.choices[0].message.content
                extracted_data = clean_and_parse_json(raw_reply)
                
                # Checkpoint successful extraction
                self.update_status(doc_url, prod_num, med_name, doc_type, 'completed', data=extracted_data)
                return True
                
            except Exception as e:
                log.warning(f"[{med_name}] MiniMax API call attempt {attempt+1} failed: {e}")
                if attempt < api_retries - 1:
                    time.sleep(api_backoff * (attempt + 1))
                else:
                    error_msg = f"MiniMax API Failure after {api_retries} attempts: {e}"
                    self.update_status(doc_url, prod_num, med_name, doc_type, 'failed', error_msg)
                    return False

def compile_consolidated_data(df: pd.DataFrame) -> pd.DataFrame:
    """Groups EPAR extractions by drug product and merges fields into a single clinical profile."""
    grouped = df.groupby(["medicine_name", "ema_product_number"])
    rows = []
    
    for (med_name, prod_num), group in grouped:
        merged_row = {
            "medicine_name": med_name,
            "ema_product_number": prod_num,
            "active_substance": group["active_substance"].dropna().iloc[0] if not group["active_substance"].dropna().empty else None,
            "therapeutic_area_mesh": group["therapeutic_area_mesh"].dropna().iloc[0] if not group["therapeutic_area_mesh"].dropna().empty else None,
            "atc_code_human": group["atc_code_human"].dropna().iloc[0] if not group["atc_code_human"].dropna().empty else None,
            "marketing_authorisation_developer_applicant_holder": group["marketing_authorisation_developer_applicant_holder"].dropna().iloc[0] if not group["marketing_authorisation_developer_applicant_holder"].dropna().empty else None,
            "marketing_authorisation_date": group["marketing_authorisation_date"].dropna().iloc[0] if not group["marketing_authorisation_date"].dropna().empty else None,
        }
        
        # Merge all unique NCT Numbers
        ncts = set()
        for val in group["nct_numbers"].dropna():
            if val.strip():
                for n in val.split(","):
                    if n.strip():
                        ncts.add(n.strip())
        merged_row["nct_numbers"] = ",".join(sorted(ncts))
        
        # Text fields: select first non-null/non-empty value across documents
        text_cols = [
            "composition", "therapeutic_indications", "posology", "contraindications",
            "undesirable_effects", "benefits_in_studies", "benefit_risk_balance",
            "document_summary", "document_procedure_dates"
        ]
        
        for col in text_cols:
            non_empty = group[col].dropna()
            non_empty = non_empty[non_empty != ""]
            merged_row[col] = non_empty.iloc[0] if not non_empty.empty else None
            
        rows.append(merged_row)
        
    return pd.DataFrame(rows)

def compile_trials_table(df: pd.DataFrame) -> pd.DataFrame:
    """Unpacks the clinical_trials_json list from each record and flattens them into a clean organized table."""
    trial_rows = []
    
    for _, row in df.iterrows():
        trials_json = row.get("clinical_trials_json")
        if not trials_json:
            continue
            
        try:
            trials_list = json.loads(trials_json)
            if not isinstance(trials_list, list):
                continue
                
            for trial in trials_list:
                trial_rows.append({
                    "medicine_name": row.get("medicine_name"),
                    "ema_product_number": row.get("ema_product_number"),
                    "nct_id": trial.get("nct_id"),
                    "brief_title": trial.get("brief_title"),
                    "official_title": trial.get("official_title"),
                    "overall_status": trial.get("overall_status"),
                    "start_date": trial.get("start_date"),
                    "sponsor": trial.get("sponsor"),
                    "condition": trial.get("condition"),
                    "phase": trial.get("phase"),
                    "intervention_name": trial.get("intervention_name"),
                    "intervention_type": trial.get("intervention_type"),
                    "primary_outcome": trial.get("primary_outcome"),
                    "secondary_outcome": trial.get("secondary_outcome"),
                    "country": trial.get("country"),
                    "study_type": trial.get("study_type"),
                    "enrollment": trial.get("enrollment"),
                    "document_type": row.get("document_type"),
                    "document_url": row.get("document_url")
                })
        except Exception as e:
            log.warning(f"Error parsing clinical_trials_json for {row.get('medicine_name')}: {e}")
            
    return pd.DataFrame(trial_rows)

def compile_single_flat_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Combines drug-level clinical facts and trial-level columns into a single flat CSV file."""
    # 1. Compile consolidated drug profiles first
    df_consolidated = compile_consolidated_data(df)
    
    # 2. Extract clinical trials from raw document extractions grouped by medicine and product number
    drug_trials = {}
    for _, row in df.iterrows():
        key = (row["medicine_name"], row["ema_product_number"])
        trials_json = row.get("clinical_trials_json")
        if trials_json:
            try:
                trials_list = json.loads(trials_json)
                if isinstance(trials_list, list):
                    if key not in drug_trials:
                        drug_trials[key] = []
                    # Avoid duplicate trials (checking nct_id or brief_title)
                    for trial in trials_list:
                        is_dup = False
                        for existing in drug_trials[key]:
                            if trial.get("nct_id") and existing.get("nct_id") == trial.get("nct_id"):
                                is_dup = True
                                break
                            if trial.get("brief_title") and existing.get("brief_title") == trial.get("brief_title"):
                                is_dup = True
                                break
                        if not is_dup:
                            drug_trials[key].append(trial)
            except Exception as e:
                log.warning(f"Error parsing clinical_trials_json: {e}")
                
    # 3. Create flattened rows
    flat_rows = []
    for _, drug_row in df_consolidated.iterrows():
        key = (drug_row["medicine_name"], drug_row["ema_product_number"])
        trials = drug_trials.get(key, [])
        
        # Base drug columns
        base_info = {
            "medicine_name": drug_row["medicine_name"],
            "ema_product_number": drug_row["ema_product_number"],
            "active_substance": drug_row["active_substance"],
            "therapeutic_area_mesh": drug_row["therapeutic_area_mesh"],
            "atc_code_human": drug_row["atc_code_human"],
            "marketing_authorisation_developer_applicant_holder": drug_row["marketing_authorisation_developer_applicant_holder"],
            "marketing_authorisation_date": drug_row["marketing_authorisation_date"],
            "nct_numbers": drug_row["nct_numbers"],
            "composition": drug_row["composition"],
            "therapeutic_indications": drug_row["therapeutic_indications"],
            "posology": drug_row["posology"],
            "contraindications": drug_row["contraindications"],
            "undesirable_effects": drug_row["undesirable_effects"],
            "benefits_in_studies": drug_row["benefits_in_studies"],
            "benefit_risk_balance": drug_row["benefit_risk_balance"],
            "document_summary": drug_row["document_summary"],
            "document_procedure_dates": drug_row["document_procedure_dates"]
        }
        
        if trials:
            for trial in trials:
                # Merge trial details with drug info
                row_copy = base_info.copy()
                row_copy.update({
                    "nct_id": trial.get("nct_id"),
                    "brief_title": trial.get("brief_title"),
                    "official_title": trial.get("official_title"),
                    "overall_status": trial.get("overall_status"),
                    "start_date": trial.get("start_date"),
                    "sponsor": trial.get("sponsor"),
                    "condition": trial.get("condition"),
                    "phase": trial.get("phase"),
                    "intervention_name": trial.get("intervention_name"),
                    "intervention_type": trial.get("intervention_type"),
                    "primary_outcome": trial.get("primary_outcome"),
                    "secondary_outcome": trial.get("secondary_outcome"),
                    "country": trial.get("country"),
                    "study_type": trial.get("study_type"),
                    "enrollment": trial.get("enrollment")
                })
                flat_rows.append(row_copy)
        else:
            # No trials, output one row with empty trial columns
            row_copy = base_info.copy()
            row_copy.update({
                "nct_id": None,
                "brief_title": None,
                "official_title": None,
                "overall_status": None,
                "start_date": None,
                "sponsor": None,
                "condition": None,
                "phase": None,
                "intervention_name": None,
                "intervention_type": None,
                "primary_outcome": None,
                "secondary_outcome": None,
                "country": None,
                "study_type": None,
                "enrollment": None
            })
            flat_rows.append(row_copy)
            
    return pd.DataFrame(flat_rows)

def export_compiled_csv(db_path: Path, output_csv: Path):
    """Gathers all checkpoints, joins with master medicines table, flattens, and exports to a single CSV."""
    log.info(f"Querying extracted dataset from {db_path}...")
    query = """
    SELECT
        pe.medicine_name,
        pe.ema_product_number,
        m.active_substance,
        m.therapeutic_area_mesh,
        m.atc_code_human,
        m.marketing_authorisation_developer_applicant_holder,
        m.marketing_authorisation_date,
        pe.document_type,
        pe.nct_numbers,
        pe.composition,
        pe.therapeutic_indications,
        pe.posology,
        pe.contraindications,
        pe.undesirable_effects,
        pe.benefits_in_studies,
        pe.benefit_risk_balance,
        pe.document_summary,
        pe.clinical_trials_json,
        pe.document_procedure_dates,
        pe.document_url
    FROM pdf_extractions pe
    LEFT JOIN medicines m ON pe.ema_product_number = m.ema_product_number
    WHERE pe.extraction_status = 'completed';
    """
    
    with get_db_connection(db_path) as conn:
        df = pd.read_sql_query(query, conn)
        
    if df.empty:
        log.warning("No successfully completed extractions found in database. Exiting export.")
        return
        
    # Define file paths
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    
    log.info("Compiling and merging clinical trials and drug-level profiles into a single flat dataset...")
    df_flat = compile_single_flat_dataset(df)
    
    log.info(f"Exporting {len(df_flat)} flat records to single CSV: {output_csv}")
    df_flat.to_csv(output_csv, index=False, encoding="utf-8")
    
    log.info("CSV export completed successfully.")

def main():
    parser = argparse.ArgumentParser(
        description="EMA EPAR PDF LLM-based Information Extractor.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("--db-path", type=str, default="Regulatory & Approvals/ema_data/ema_database.db",
                        help="Path to the SQLite checkpoint database.")
    parser.add_argument("--bucket", type=str, default="moine-data",
                        help="AWS S3 bucket where PDFs reside.")
    parser.add_argument("--s3-prefix", type=str, default="Regulatory & Approvals/ema_data",
                        help="Prefix folder path in your S3 bucket.")
    parser.add_argument("--aws-profile", type=str, default="moine",
                        help="AWS credentials profile name to use.")
    parser.add_argument("--api-key", type=str, default=None,
                        help="MiniMax API Key. If not provided, reads from MINIMAX_API_KEY environment variable.")
    parser.add_argument("--threads", type=int, default=5,
                        help="Number of concurrent worker threads.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit the number of PDFs to process (for testing).")
    parser.add_argument("--medicine", type=str, default=None,
                        help="Filter queue to only process documents containing this medicine name.")
    parser.add_argument("--export-only", action="store_true",
                        help="Skip extraction and immediately compile the final CSV from database records.")
    parser.add_argument("--export-path", type=str, default="Regulatory & Approvals/ema_data/ema_pdf_extractions.csv",
                        help="Path to export the final compiled CSV.")
                        
    args = parser.parse_args()
    
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[ERROR] Database file not found at: {db_path}", file=sys.stderr)
        sys.exit(1)
        
    export_path = Path(args.export_path)
    
    # 1. Handle Export-Only Request
    if args.export_only:
        export_compiled_csv(db_path, export_path)
        sys.exit(0)
        
    # Initialize/Migrate Schema Table
    initialize_extractions_table(db_path)
    
    # Resolve API Key
    api_key = args.api_key or os.environ.get("MINIMAX_API_KEY") or DEFAULT_MINIMAX_API_KEY
    
    # Initialize Recovery Processor
    processor = EMARecoveryProcessor(
        db_path=db_path,
        bucket=args.bucket,
        s3_prefix=args.s3_prefix,
        aws_profile=args.aws_profile,
        api_key=api_key
    )
    
    # 2. Fetch pending files
    log.info("Querying pending downloads queue...")
    pending_tasks = processor.fetch_pending_downloads(limit=args.limit, medicine_filter=args.medicine)
    total_tasks = len(pending_tasks)
    
    if total_tasks == 0:
        log.info("No pending PDFs to process in the download queue. Generating final CSV reports...")
        export_compiled_csv(db_path, export_path)
        sys.exit(0)
        
    log.info(f"Found {total_tasks} pending EPAR PDF documents to extract.")
    
    # 3. Process Batch Concurrently
    success_count = 0
    start_time = time.time()
    
    # Initialize tqdm progress bar if available
    pbar = None
    if tqdm:
        pbar = tqdm(total=total_tasks, desc="Extracting PDFs")
        
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads, thread_name_prefix="Worker") as executor:
        futures = {executor.submit(processor.process_document, task): task for task in pending_tasks}
        
        for future in concurrent.futures.as_completed(futures):
            task = futures[future]
            doc_url, _, med_name, doc_type, _ = task
            try:
                success = future.result()
                if success:
                    success_count += 1
            except Exception as e:
                log.error(f"Worker thread crashed on task {task}: {e}")
                
            if pbar:
                pbar.update(1)
            else:
                log.info(f"Progress: {success_count}/{total_tasks} completed successfully.")
                
    if pbar:
        pbar.close()
        
    duration = time.time() - start_time
    log.info(f"Batch extraction processing complete. {success_count}/{total_tasks} processed successfully in {duration:.2f} seconds.")
    
    # 4. Generate Compiled Output CSVs
    export_compiled_csv(db_path, export_path)

if __name__ == "__main__":
    main()
