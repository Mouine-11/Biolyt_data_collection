#!/usr/bin/env python3
"""
drugbank_downloader.py
======================
A professional, robust, and memory-efficient Python script to retrieve and 
extract drug and target data from DrugBank (https://go.drugbank.com).

Modes of Operation:
  1. parse-xml: Memory-efficient streaming parser for the official DrugBank 
     full database XML dump (O(1) memory footprint using ElementTree.iterparse).
  2. scrape: Polite, rate-limited HTML scraper to extract drug metadata, 
     chemical properties, and target details for specific drug IDs or search terms.

Author: Biolyt Intern Coding Assistant
Date: June 2026
"""

import os
import sys
import time
import argparse
import csv
import json
import logging
import re
import random
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, quote

# Third-party imports with graceful fallbacks
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("Error: 'requests' library is required. Install it using 'pip install requests'.", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: 'beautifulsoup4' library is required. Install it using 'pip install beautifulsoup4'.", file=sys.stderr)
    sys.exit(1)

# Optional progress bar for bulk operations
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://go.drugbank.com"
SEARCH_URL = "https://go.drugbank.com/unearth/q"
DEFAULT_DELAY_S = 2.0             # Seconds between scraper requests
REQUEST_TIMEOUT = 30              # Timeout per HTTP request
MAX_RETRIES = 5                   # HTTP connection retries
XML_NS = "{http://www.drugbank.ca}" # DrugBank XML namespace

# A list of realistic User-Agents to prevent simple anti-bot blocking
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]


# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
def setup_logging(output_dir: Path) -> logging.Logger:
    """Configures logging to both console and a log file in the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "drugbank_downloader.log"
    
    # Avoid duplicate handlers if setup_logging is called multiple times
    logger = logging.getLogger("DrugBankDownloader")
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    
    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    return logger


# ---------------------------------------------------------------------------
# HTTP Session Builder
# ---------------------------------------------------------------------------
def build_session() -> requests.Session:
    """Builds a requests Session equipped with retries and randomized headers."""
    session = requests.Session()
    
    # Configure retry adapter with exponential back-off
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=2.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    # Default headers
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    })
    return session


# ---------------------------------------------------------------------------
# Mode 1: Web Scraper Implementation
# ---------------------------------------------------------------------------
class DrugBankWebScraper:
    """Polite, robust HTML scraper to extract drug data from go.drugbank.com."""
    
    def __init__(self, session: requests.Session, log: logging.Logger, delay: float = DEFAULT_DELAY_S, randomize: bool = True):
        self.session = session
        self.log = log
        self.delay = delay
        self.randomize = randomize

    def _apply_delay(self):
        """Applies a polite delay, optionally randomized, between requests."""
        if self.delay <= 0:
            return
        
        sleep_time = self.delay
        if self.randomize:
            # Randomize by +/- 50%
            sleep_time = random.uniform(self.delay * 0.5, self.delay * 1.5)
            
        self.log.debug(f"Polite delay: sleeping for {sleep_time:.2f} seconds...")
        time.sleep(sleep_time)

    def resolve_drug_id(self, query: str) -> str | None:
        """
        Resolves a search query (e.g., "Aspirin") to a DrugBank ID.
        If the query is already a valid DrugBank ID (DBxxxxx), returns it directly.
        """
        query = query.strip()
        # Check if already a DrugBank ID
        if re.match(r"^DB\d{5}$", query, re.IGNORECASE):
            return query.upper()
            
        self.log.info(f"Resolving query '{query}' to a DrugBank ID...")
        self._apply_delay()
        
        # Prepare session headers with a random User-Agent
        self.session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        
        params = {
            "utf8": "✓",
            "query": query,
            "searcher": "drugs"
        }
        
        try:
            resp = self.session.get(SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            
            # 1. Direct redirect: if we are redirected directly to a drug details page
            final_url = resp.url
            match = re.search(r"/drugs/(DB\d{5})", final_url, re.IGNORECASE)
            if match:
                resolved_id = match.group(1).upper()
                self.log.info(f"  -> Direct match found: {resolved_id}")
                return resolved_id
                
            # 2. Search results page: parse links to find the best match
            soup = BeautifulSoup(resp.text, "html.parser")
            # Look for links containing /drugs/DBxxxxx
            links = soup.find_all("a", href=True)
            for link in links:
                href = link["href"]
                m = re.search(r"/drugs/(DB\d{5})", href, re.IGNORECASE)
                if m:
                    resolved_id = m.group(1).upper()
                    self.log.info(f"  -> Match found in search results: {resolved_id} ({link.get_text(strip=True)})")
                    return resolved_id
                    
            self.log.warning(f"Could not resolve query '{query}' to any DrugBank ID.")
            return None
            
        except Exception as e:
            self.log.error(f"Error resolving query '{query}': {e}")
            return None

    def scrape_drug(self, drug_id: str) -> dict | None:
        """
        Scrapes a specific drug page from DrugBank and extracts its details.
        Returns a dict containing structured fields and a list of targets.
        """
        drug_id = drug_id.upper().strip()
        url = f"{BASE_URL}/drugs/{drug_id}"
        
        self.log.info(f"Scraping drug page: {url}")
        self._apply_delay()
        
        self.session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        
        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                self.log.warning(f"Drug {drug_id} not found (404).")
                return None
            resp.raise_for_status()
        except Exception as e:
            self.log.error(f"HTTP request failed for {drug_id}: {e}")
            return None
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Get drug name from h1
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else ""
        # DrugBank title is often "DrugName (DBID)" or just "DrugName"
        if name and "(" in name:
            name = name.split("(")[0].strip()
            
        # Parse definition list (dt/dd pairs) which contains almost all properties
        dts = soup.find_all("dt")
        dds = soup.find_all("dd")
        
        details = {}
        for dt, dd in zip(dts, dds):
            key = dt.get_text(strip=True).replace(":", "")
            val = dd.get_text(strip=True)
            details[key] = val
            
        # Map fields to our target schema
        drug_data = {
            "drugbank_id": drug_id,
            "name": name or details.get("Name", ""),
            "type": details.get("Type", ""),
            "description": details.get("Description", ""),
            "indication": details.get("Indication", ""),
            "pharmacodynamics": details.get("Pharmacodynamics", ""),
            "mechanism_of_action": details.get("Mechanism of action", ""),
            "cas_number": details.get("CAS number", details.get("CAS Number", "")),
            "formula": details.get("Chemical Formula", details.get("Formula", "")),
            "smiles": details.get("SMILES", ""),
            "inchi": details.get("InChI", ""),
            "inchikey": details.get("InChI Key", ""),
            "synonyms": details.get("Synonyms", "")
        }
        
        # Clean up lists that might contain noise
        for k, v in drug_data.items():
            if isinstance(v, str):
                # Replace multiple whitespaces and newlines with a single space
                drug_data[k] = re.sub(r"\s+", " ", v).strip()
                
        # Parse Targets
        # Targets are represented in "relation-card" containers in DrugBank's modern layout
        targets = []
        target_cards = soup.find_all(class_=re.compile(r"relation-card|target-card", re.I))
        
        # Fallback: find any cards within a section that has id="targets"
        if not target_cards:
            targets_sec = soup.find(id="targets") or soup.find(id="drug-targets")
            if targets_sec:
                target_cards = targets_sec.find_all(class_="card")
                
        for card in target_cards:
            # Name & ID
            header = card.find(class_=re.compile(r"card-header|relation-name|target-name", re.I))
            t_name = ""
            t_id = ""
            
            if header:
                t_name = header.get_text(strip=True)
                # Find link inside header to resolve Target ID
                link = header.find("a", href=True)
                if link:
                    m = re.search(r"/(targets|bio_entities|proteins)/(BE\d+|T\d+|BT\d+|\w+)", link["href"], re.I)
                    if m:
                        t_id = m.group(2)
                        
            # If no name/id found, skip
            if not t_name:
                continue
                
            # Parse target organism and actions inside card
            t_organism = ""
            t_actions = []
            
            card_dts = card.find_all("dt")
            card_dds = card.find_all("dd")
            for c_dt, c_dd in zip(card_dts, card_dds):
                c_key = c_dt.get_text(strip=True).lower()
                c_val = c_dd.get_text(strip=True)
                if "organism" in c_key:
                    t_organism = c_val
                elif "actions" in c_key:
                    # Often actions are comma-separated or list items
                    t_actions = [a.strip() for a in re.split(r",|;", c_val) if a.strip()]
                    
            targets.append({
                "target_id": t_id,
                "target_name": t_name,
                "organism": t_organism,
                "actions": "|".join(t_actions)
            })
            
        drug_data["targets"] = targets
        self.log.info(f"  -> Extracted '{drug_data['name']}' with {len(targets)} target(s).")
        return drug_data


# ---------------------------------------------------------------------------
# Mode 2: XML Parser Implementation (Memory-Optimized)
# ---------------------------------------------------------------------------
class DrugBankXMLParser:
    """Streaming, memory-optimized XML parser for bulk DrugBank XML releases."""
    
    def __init__(self, xml_path: Path, out_dir: Path, file_format: str, log: logging.Logger):
        self.xml_path = xml_path
        self.out_dir = out_dir
        self.file_format = file_format.lower()
        self.log = log
        
        # Setup output filenames
        self.drugs_file = out_dir / f"drugbank_drugs.{self.file_format}"
        self.targets_file = out_dir / f"drugbank_targets.{self.file_format}"
        self.synonyms_file = out_dir / f"drugbank_synonyms.{self.file_format}"
        self.ext_ids_file = out_dir / f"drugbank_external_ids.{self.file_format}"

    def _get_writer(self, file_path: Path, fieldnames: list):
        """Returns a CSV writer or JSON handler based on format."""
        delim = "\t" if self.file_format == "tsv" else ","
        fh = open(file_path, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=delim)
        writer.writeheader()
        return fh, writer

    def parse(self):
        """Parses the XML database in a streaming fashion, saving structured results."""
        self.log.info(f"Opening DrugBank XML database: {self.xml_path}")
        if not self.xml_path.exists():
            self.log.error(f"XML file not found: {self.xml_path}")
            return
            
        self.out_dir.mkdir(parents=True, exist_ok=True)
        
        # Define fields
        drug_fields = [
            "drugbank_id", "name", "type", "description", "indication",
            "pharmacodynamics", "mechanism_of_action", "cas_number",
            "smiles", "inchi", "inchikey", "formula"
        ]
        target_fields = [
            "drugbank_id", "target_id", "target_name", "organism",
            "actions", "uniprot_id", "gene_name"
        ]
        synonym_fields = ["drugbank_id", "synonym", "language", "coder"]
        ext_fields = ["drugbank_id", "resource", "identifier"]
        
        # Open output files
        self.log.info(f"Initializing output files in: {self.out_dir}")
        drugs_fh, drugs_writer = self._get_writer(self.drugs_file, drug_fields)
        targets_fh, targets_writer = self._get_writer(self.targets_file, target_fields)
        synonyms_fh, synonyms_writer = self._get_writer(self.synonyms_file, synonym_fields)
        ext_fh, ext_writer = self._get_writer(self.ext_ids_file, ext_fields)
        
        count = 0
        target_count = 0
        
        try:
            # ElementTree iterparse is highly memory efficient
            context = ET.iterparse(self.xml_path, events=("start", "end"))
            context = iter(context)
            event, root = next(context)
            
            self.log.info("Parsing XML elements...")
            
            for event, elem in context:
                if event == "end" and elem.tag == f"{XML_NS}drug":
                    # Parse primary drug ID
                    primary_id = elem.findtext(f"{XML_NS}drugbank-id[@primary='true']")
                    if not primary_id:
                        # Clear to release memory and skip
                        elem.clear()
                        root.clear()
                        continue
                        
                    name = elem.findtext(f"{XML_NS}name")
                    drug_type = elem.attrib.get("type", "")
                    desc = elem.findtext(f"{XML_NS}description") or ""
                    ind = elem.findtext(f"{XML_NS}indication") or ""
                    pd = elem.findtext(f"{XML_NS}pharmacodynamics") or ""
                    moa = elem.findtext(f"{XML_NS}mechanism-of-action") or ""
                    cas = elem.findtext(f"{XML_NS}cas-number") or ""
                    
                    # Extract calculated properties (SMILES, InChI, etc.)
                    smiles = ""
                    inchi = ""
                    inchikey = ""
                    formula = ""
                    
                    calc_props = elem.find(f"{XML_NS}calculated-properties")
                    if calc_props is not None:
                        for prop in calc_props.findall(f"{XML_NS}property"):
                            kind = prop.findtext(f"{XML_NS}kind")
                            val = prop.findtext(f"{XML_NS}value")
                            if kind == "SMILES":
                                smiles = val
                            elif kind == "InChI":
                                inchi = val
                            elif kind == "InChIKey":
                                inchikey = val
                            elif kind == "Molecular Formula":
                                formula = val
                                
                    # If SMILES/Formula not in calculated-properties, check experimental-properties
                    exp_props = elem.find(f"{XML_NS}experimental-properties")
                    if exp_props is not None:
                        for prop in exp_props.findall(f"{XML_NS}property"):
                            kind = prop.findtext(f"{XML_NS}kind")
                            val = prop.findtext(f"{XML_NS}value")
                            if kind == "Molecular Formula" and not formula:
                                formula = val
                            elif kind == "SMILES" and not smiles:
                                smiles = val
                                
                    # Write Drug Row
                    drugs_writer.writerow({
                        "drugbank_id": primary_id,
                        "name": name,
                        "type": drug_type,
                        "description": desc.strip(),
                        "indication": ind.strip(),
                        "pharmacodynamics": pd.strip(),
                        "mechanism_of_action": moa.strip(),
                        "cas_number": cas,
                        "smiles": smiles,
                        "inchi": inchi,
                        "inchikey": inchikey,
                        "formula": formula
                    })
                    
                    # Extract Synonyms
                    synonyms_elem = elem.find(f"{XML_NS}synonyms")
                    if synonyms_elem is not None:
                        for syn in synonyms_elem.findall(f"{XML_NS}synonym"):
                            synonyms_writer.writerow({
                                "drugbank_id": primary_id,
                                "synonym": syn.text,
                                "language": syn.attrib.get("language", ""),
                                "coder": syn.attrib.get("coder", "")
                            })
                            
                    # Extract External Identifiers
                    ext_elem = elem.find(f"{XML_NS}external-identifiers")
                    if ext_elem is not None:
                        for ext_id in ext_elem.findall(f"{XML_NS}external-identifier"):
                            ext_writer.writerow({
                                "drugbank_id": primary_id,
                                "resource": ext_id.findtext(f"{XML_NS}resource"),
                                "identifier": ext_id.findtext(f"{XML_NS}identifier")
                            })
                            
                    # Extract Targets
                    targets_elem = elem.find(f"{XML_NS}targets")
                    if targets_elem is not None:
                        for target in targets_elem.findall(f"{XML_NS}target"):
                            t_id = target.findtext(f"{XML_NS}id")
                            t_name = target.findtext(f"{XML_NS}name")
                            t_org = target.findtext(f"{XML_NS}organism")
                            
                            # Join multiple actions with |
                            actions_elem = target.find(f"{XML_NS}actions")
                            actions = []
                            if actions_elem is not None:
                                actions = [a.text for a in actions_elem.findall(f"{XML_NS}action") if a.text]
                                
                            # Extract UniProt ID & Gene Name from Polypeptide
                            uniprot_id = ""
                            gene_name = ""
                            poly = target.find(f"{XML_NS}polypeptide")
                            if poly is not None:
                                gene_name = poly.findtext(f"{XML_NS}gene-name") or ""
                                
                                # Search polypeptide external identifiers for UniProt
                                p_ext_elem = poly.find(f"{XML_NS}external-identifiers")
                                if p_ext_elem is not None:
                                    for p_ext in p_ext_elem.findall(f"{XML_NS}external-identifier"):
                                        resource = p_ext.findtext(f"{XML_NS}resource")
                                        if resource == "UniProtKB":
                                            uniprot_id = p_ext.findtext(f"{XML_NS}identifier")
                                            break
                                            
                            targets_writer.writerow({
                                "drugbank_id": primary_id,
                                "target_id": t_id,
                                "target_name": t_name,
                                "organism": t_org,
                                "actions": "|".join(actions),
                                "uniprot_id": uniprot_id,
                                "gene_name": gene_name
                            })
                            target_count += 1
                            
                    count += 1
                    if count % 1000 == 0:
                        self.log.info(f"  Parsed {count:,} drugs and {target_count:,} targets...")
                        
                    # CRITICAL: Clear sub-elements to keep memory usage low (O(1) footprint)
                    elem.clear()
                    root.clear()
                    
            self.log.info(f"Successfully completed bulk parsing. Total drugs: {count:,}, Total targets: {target_count:,}")
            
        except Exception as e:
            self.log.error(f"XML parsing failed: {e}")
            raise
        finally:
            # Close files
            drugs_fh.close()
            targets_fh.close()
            synonyms_fh.close()
            ext_fh.close()


# ---------------------------------------------------------------------------
# Main CLI Entrypoint
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Professional DrugBank Data Downloader and Parser Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  1. Scrape specific drugs by ID or query name politely:
     python drugbank_downloader.py scrape --drugs DB00316 DB00191 "Ibuprofen" --out-dir data_scraped

  2. Scrape from a file containing drug queries (one per line):
     python drugbank_downloader.py scrape --drugs-file drug_queries.txt --out-dir data_scraped

  3. Parse full official DrugBank XML database in a memory-optimized way:
     python drugbank_downloader.py parse-xml --xml-path drugbank_all.xml --out-dir data_parsed
"""
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommands")
    
    # Subcommand: scrape
    scrape_parser = subparsers.add_parser("scrape", help="Politely scrape individual drugs from go.drugbank.com")
    scrape_group = scrape_parser.add_mutually_exclusive_group(required=True)
    scrape_group.add_argument("--drugs", nargs="+", help="Space-separated list of DrugBank IDs (e.g. DB00316) or search queries (e.g. 'Aspirin')")
    scrape_group.add_argument("--drugs-file", type=str, help="Path to a text file containing drug queries/IDs (one per line)")
    scrape_parser.add_argument("--out-dir", type=str, default="drugbank_scraped", help="Directory to save scraped data (default: drugbank_scraped)")
    scrape_parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output file format (default: csv)")
    scrape_parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_S, help=f"Polite delay in seconds between requests (default: {DEFAULT_DELAY_S})")
    scrape_parser.add_argument("--no-randomize", action="store_true", help="Disable randomization of request delays")
    
    # Subcommand: parse-xml
    xml_parser = subparsers.add_parser("parse-xml", help="Memory-optimized parser for official DrugBank XML database files")
    xml_parser.add_argument("--xml-path", type=str, required=True, help="Path to the DrugBank XML file")
    xml_parser.add_argument("--out-dir", type=str, default="drugbank_parsed", help="Directory to save parsed data (default: drugbank_parsed)")
    xml_parser.add_argument("--format", choices=["csv", "tsv"], default="csv", help="Output file format (default: csv)")
    
    args = parser.parse_args()
    
    # Initialize directory and logger
    out_dir = Path(args.out_dir)
    log = setup_logging(out_dir)
    
    log.info("Starting DrugBank Downloader and Parser Utility")
    
    if args.command == "scrape":
        # Build drug list
        drugs_list = []
        if args.drugs:
            drugs_list = [d.strip() for d in args.drugs if d.strip()]
        elif args.drugs_file:
            fp = Path(args.drugs_file)
            if not fp.exists():
                log.error(f"Drugs file not found: {fp}")
                sys.exit(1)
            with open(fp, "r", encoding="utf-8") as f:
                drugs_list = [line.strip() for line in f if line.strip()]
                
        if not drugs_list:
            log.warning("No drug queries or IDs provided. Exiting.")
            return
            
        log.info(f"Loaded {len(drugs_list)} drug queries to process.")
        
        session = build_session()
        scraper = DrugBankWebScraper(
            session=session,
            log=log,
            delay=args.delay,
            randomize=not args.no_randomize
        )
        
        scraped_data = []
        
        for query in drugs_list:
            # 1. Resolve to DBID
            db_id = scraper.resolve_drug_id(query)
            if not db_id:
                log.warning(f"Skipping query '{query}' - failed to resolve to a DrugBank ID.")
                continue
                
            # 2. Scrape drug details
            drug_info = scraper.scrape_drug(db_id)
            if drug_info:
                scraped_data.append(drug_info)
                
        if not scraped_data:
            log.warning("No drug data was successfully scraped.")
            return
            
        # Write outputs
        if args.format == "json":
            out_file = out_dir / "scraped_drugs.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(scraped_data, f, indent=2, ensure_ascii=False)
            log.info(f"Scraped data successfully saved to {out_file}")
        else:
            # Flat CSV output
            out_file = out_dir / "scraped_drugs.csv"
            # Define CSV fields
            fields = [
                "drugbank_id", "name", "type", "description", "indication",
                "pharmacodynamics", "mechanism_of_action", "cas_number",
                "formula", "smiles", "inchi", "inchikey", "synonyms", "targets"
            ]
            
            with open(out_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for drug in scraped_data:
                    # Flatten targets to a readable string for the primary CSV
                    targets_flat = []
                    for t in drug["targets"]:
                        action_str = f" ({t['actions']})" if t["actions"] else ""
                        targets_flat.append(f"{t['target_name']}{action_str}")
                    
                    row = drug.copy()
                    row["targets"] = " | ".join(targets_flat)
                    writer.writerow(row)
                    
            log.info(f"Scraped data successfully saved to {out_file}")
            
    elif args.command == "parse-xml":
        xml_path = Path(args.xml_path)
        parser = DrugBankXMLParser(
            xml_path=xml_path,
            out_dir=out_dir,
            file_format=args.format,
            log=log
        )
        parser.parse()


if __name__ == "__main__":
    main()
