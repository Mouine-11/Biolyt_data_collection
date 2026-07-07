# Biolyt Intern Workspace - Scripts & Data Mapping

This workspace contains data scrapers, downloaders, and analysis scripts organized by category. All scripts have been moved to the root directory for easy access, and they are configured to read from and write to their respective category data folders.

## Table of Contents
- [Clinical Trials & Pipeline Intelligence](#clinical-trials-pipeline-intelligence)
- [Drug & Substance Reference](#drug-substance-reference)
- [Regulatory & Approvals](#regulatory-approvals)
- [Safety & Pharmacovigilance](#safety-pharmacovigilance)
- [Utility Scripts](#utility-scripts)

## Clinical Trials & Pipeline Intelligence
*Scripts for crawling, downloading, and parsing clinical trial registry data.*

### `anzctr_downloader.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/anzctr_trials`
- **Description**: anzctr_downloader.py

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `chictr_downloader.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/chictr_trials`
- **Description**: chictr_downloader.py

**Usage and Parameters**:
```text
usage: chictr_downloader.py [-h] [--url URL] [--page-size PAGE_SIZE]
                            [--max-pages MAX_PAGES] [--download-xml]
                            [--output-dir OUTPUT_DIR] [--threads THREADS]
                            [--delay DELAY]

Scrape the Chinese Clinical Trial Registry (ChiCTR) using Virtual Page Sizes and Concurrency.

options:
  -h, --help            show this help message and exit
  --url URL             The ChiCTR search results page URL to scrape from.
                        Paste the URL containing your filters.
  --page-size PAGE_SIZE
                        Virtual page size (number of trials per batch).
                        Default is 50.
  --max-pages MAX_PAGES
                        Maximum number of VIRTUAL pages to scrape (each
                        containing --page-size trials).
  --download-xml        Visit each detail page and download the trial XML
                        file.
  --output-dir OUTPUT_DIR
                        Output directory to save results. Defaults to
                        'chictr_trails2'
  --threads THREADS     Number of concurrent threads to use for page fetches
                        and XML downloads. Set to 1 for sequential. Default:
                        5.
  --delay DELAY         Polite delay in seconds between sequential requests
                        (only active if --threads is 1).
```

---

### `chictr_downloader_details.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/chictr_trials`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments or failed to load help menu.
```

---

### `ctri_downloader.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/ctri_trials`
- **Description**: ctri_downloader.py

**Usage and Parameters**:
```text
usage: ctri_downloader.py [-h] {download,parse} ...

Intelligent and resilient clinical trial data collector for the Indian
Clinical Registry (CTRI).

positional arguments:
  {download,parse}  Subcommand to run
    download        Concurrently download trial HTML detail pages
    parse           Compile downloaded HTML files into structured CSV & JSONL

options:
  -h, --help        show this help message and exit
```

---

### `eu_ctr_downloader.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/eu_ctr_trials`
- **Description**: eu_ctr_downloader.py

**Usage and Parameters**:
```text
usage: eu_ctr_downloader.py [-h] [--output-dir OUTPUT_DIR] [--query QUERY]
                            [--start-page START_PAGE] [--end-page END_PAGE]
                            [--limit LIMIT] [--delay DELAY]
                            [--retries RETRIES] [--merge] [--no-merge]

Download trials data page-by-page from EU Clinical Trials Register.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR, -o OUTPUT_DIR
                        Directory to save downloaded page text files.
  --query QUERY, -q QUERY
                        Search query string (default: empty for all trials).
  --start-page START_PAGE, -s START_PAGE
                        Page number to start downloading from (default: 1).
  --end-page END_PAGE, -e END_PAGE
                        Page number to end downloading (default: last page).
  --limit LIMIT, -l LIMIT
                        Maximum number of pages to download in this run.
  --delay DELAY, -d DELAY
                        Delay in seconds between page requests (default:
                        1.0s).
  --retries RETRIES, -r RETRIES
                        Maximum retries per failed page (default: 5).
  --merge               Merge all page files after finishing (default: True).
  --no-merge            Do not merge page files after finishing.
```

---

### `isrctn_downloader.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/isrctn_trials`
- **Description**: isrctn_downloader.py

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `jrct_downloader.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/jrct_trials`
- **Description**: jrct_downloader.py

**Usage and Parameters**:
```text
usage: jrct_downloader.py [-h] [--url URL] [--max-pages MAX_PAGES]
                          [--output-dir OUTPUT_DIR] [--delay DELAY]
                          [--timeout TIMEOUT] [--max-trials MAX_TRIALS]
                          [--batch-size BATCH_SIZE] [--proxy PROXY]
                          [--proxy-file PROXY_FILE] [--auto-proxy]
                          [--vpn-rotate VPN_ROTATE]

Scrape and extract trial records from the Japan Registry of Clinical Trials (jRCT).

options:
  -h, --help            show this help message and exit
  --url URL             Initial jRCT search result listing page URL containing
                        query filters.
  --max-pages MAX_PAGES
                        Maximum search result pages to crawl (50 trials per
                        page).
  --output-dir OUTPUT_DIR
                        Target folder to save output CSV. Defaults to
                        'Clinical Trials & Pipeline Intelligence/jrct_trials'.
  --delay DELAY         Polite wait delay in seconds between details page
                        requests (default: 1.0s).
  --timeout TIMEOUT     Connection and read timeout in seconds (default: 60s).
  --max-trials MAX_TRIALS
                        Maximum number of trial detail pages to fetch and
                        parse.
  --batch-size BATCH_SIZE
                        Number of detail pages to scrape concurrently in each
                        batch (default: 5).
  --proxy PROXY         Proxy URL (e.g. 'http://user:pass@ip:port' or SOCKS5
                        'socks5h://127.0.0.1:9050').
  --proxy-file PROXY_FILE
                        File path containing a list of proxies (one proxy per
                        line) to rotate.
  --auto-proxy          Automatically fetch a list of free public proxies to
                        use for rotation.
  --vpn-rotate VPN_ROTATE
                        Shell command to run to rotate your VPN IP address
                        when blocked (e.g. 'nordvpn connect').
```

---

### `who_collector.py`
- **Data Storage Folder**: `[data]/Clinical Trials & Pipeline Intelligence/who_trials_csv`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
usage: who_collector.py [-h] [--output-dir OUTPUT_DIR] [--limit LIMIT]
                        [--country COUNTRY] [--delay DELAY]
                        [--csv-dir CSV_DIR] [--csv-only]

Download WHO ICTRP clinical trials XML data country-by-country.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR, -o OUTPUT_DIR
                        Directory to save XML files.
  --limit LIMIT, -l LIMIT
                        Maximum number of countries to download.
  --country COUNTRY, -c COUNTRY
                        Download only a single specific country (exact match).
  --delay DELAY, -d DELAY
                        Delay in seconds between country downloads.
  --csv-dir CSV_DIR     Directory to save the compiled CSV file. If specified,
                        XML files are merged into who_trials.csv.
  --csv-only            Skip downloading and only convert existing XML files
                        to CSV.
```

---

## Drug & Substance Reference
*Scripts for scraping, downloading, and compiling drug reference databases.*

### `atc_ddd_downloader.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/atc_ddd_data`
- **Description**: WHO ATC/DDD Database Downloader and Parser Author: Antigravity AI Coding Assistant Description: Recursively crawls the official WHO Collaborating Centre for Drug Statistics Methodology              website (https://atcddd.fhi.no) to extract the complete therapeutic classification              hierarchy (Levels 1 to 4) and Defined Daily Doses (Level 5 substances).

**Usage and Parameters**:
```text
usage: atc_ddd_downloader.py [-h] [--output-dir OUTPUT_DIR] [--delay DELAY]
                             [--max-retries MAX_RETRIES]
                             [--limit-branch {A,B,C,D,G,H,J,L,M,N,P,R,S,V}]
                             [--verbose]

Scrape official WHO ATC/DDD database.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Directory to save the outputs (default: Drug &
                        Substance Reference/atc_ddd_data)
  --delay DELAY         Delay between requests in seconds (default: 0.2)
  --max-retries MAX_RETRIES
                        Maximum retries for failed requests (default: 5)
  --limit-branch {A,B,C,D,G,H,J,L,M,N,P,R,S,V}
                        Limit crawl to a single Level 1 branch (e.g. V) for
                        testing
  --verbose             Enable verbose logging
```

---

### `chembl_downloader.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/chembl_data`
- **Description**: chembl_downloader.py

**Usage and Parameters**:
```text
usage: chembl_downloader.py [-h] {molecule,target,activity,download-db} ...

Search, extract, and download drug, compound, target, and bioactivity data from ChEMBL.

positional arguments:
  {molecule,target,activity,download-db}
                        Subcommand to run
    molecule            Search and extract compound/substance data
    target              Search and extract biological targets
    activity            Retrieve bioactivity data
    download-db         Download the latest offline ChEMBL SQLite database
                        dump

options:
  -h, --help            show this help message and exit

Examples:
  # Search for Aspirin molecules and export to CSV
  python chembl_downloader.py molecule --name aspirin

  # Find molecules similar to a SMILES structure (minimum 85% Tanimoto similarity)
  python chembl_downloader.py molecule --smiles "CC(=O)Oc1ccccc1C(=O)O" --type similarity --cutoff 85

  # Search targets containing the term "HERG"
  python chembl_downloader.py target --name HERG

  # Retrieve all IC50 bioactivity measurements for the target CHEMBL240 (HERG)
  python chembl_downloader.py activity --target-id CHEMBL240 --type IC50

  # Download and extract the full offline ChEMBL SQLite database dump
  python chembl_downloader.py download-db
```

---

### `dailymed_downloader.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/dailymed_data`
- **Description**: dailymed_downloader.py

**Usage and Parameters**:
```text
usage: dailymed_downloader.py [-h] [--output-dir OUTPUT_DIR]
                              {download-mappings,search,api-fetch-spls,api-fetch-details}
                              ...

Authoritative data collector and compiler for DailyMed Structured Product
Labeling (SPL).

positional arguments:
  {download-mappings,search,api-fetch-spls,api-fetch-details}
                        Command to run
    download-mappings   Download NLM bulk mapping ZIP files and compile them
                        into a unified, indexed SQLite database.
    search              Search for drug labels by title, generic ingredient,
                        NDC, or Set ID.
    api-fetch-spls      Harvest active SPL catalog paginated from the DailyMed
                        REST API.
    api-fetch-details   Concurrently enrich a list of Set IDs with NDC,
                        packaging, and media details from the API.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Directory to save log files, database, and CSV outputs
                        (default: c:\Users\LeMonde\Desktop\Biolyt_Intern\Drug
                        & Substance Reference/dailymed_data)
```

---

### `drugbank_downloader.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/drugbank_data (or custom)`
- **Description**: drugbank_downloader.py

**Usage and Parameters**:
```text
usage: drugbank_downloader.py [-h] {scrape,parse-xml} ...

Professional DrugBank Data Downloader and Parser Script

positional arguments:
  {scrape,parse-xml}  Subcommands
    scrape            Politely scrape individual drugs from go.drugbank.com
    parse-xml         Memory-optimized parser for official DrugBank XML
                      database files

options:
  -h, --help          show this help message and exit

Examples:
  1. Scrape specific drugs by ID or query name politely:
     python drugbank_downloader.py scrape --drugs DB00316 DB00191 "Ibuprofen" --out-dir data_scraped

  2. Scrape from a file containing drug queries (one per line):
     python drugbank_downloader.py scrape --drugs-file drug_queries.txt --out-dir data_scraped

  3. Parse full official DrugBank XML database in a memory-optimized way:
     python drugbank_downloader.py parse-xml --xml-path drugbank_all.xml --out-dir data_parsed
```

---

### `gsrs_downloader.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/gsrs_data`
- **Description**: gsrs_downloader.py

**Usage and Parameters**:
```text
usage: gsrs_downloader.py [-h] [-o OUTPUT_DIR] [-p PAGE_SIZE] [-t THREADS]
                          [-d DELAY] [-l LIMIT] [--no-resume]

GSRS Substance Downloader: Scrapes and stores the full FDA UNII / GSRS
database.

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for data and logs. (default: Drug &
                        Substance Reference/gsrs_data)
  -p PAGE_SIZE, --page-size PAGE_SIZE
                        Number of records to fetch per page. (default: 500)
  -t THREADS, --threads THREADS
                        Number of concurrent download threads. (default: 2)
  -d DELAY, --delay DELAY
                        Delay in seconds between batch requests. (default:
                        0.5)
  -l LIMIT, --limit LIMIT
                        Maximum number of records to download (for testing).
                        (default: None)
  --no-resume           Do not resume; overwrite existing output files and
                        start fresh. (default: False)
```

---

### `pubchem_downloader.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/pubchem_data`
- **Description**: pubchem_downloader.py

**Usage and Parameters**:
```text
usage: pubchem_downloader.py [-h]
                             {property,search,download-bulk,extract-bulk} ...

PubChem Downloader - Fetch structures, identifiers, and bulk mappings from PubChem.

positional arguments:
  {property,search,download-bulk,extract-bulk}
                        Subcommands
    property            Retrieve chemical properties for CIDs or chemical
                        names.
    search              Perform structure similarity or substructure search.
    download-bulk       Download bulk whole-database mapping files from
                        PubChem FTP.
    extract-bulk        Extract and convert downloaded bulk mapping files to
                        CSV format, then delete source files.

options:
  -h, --help            show this help message and exit

Examples:
  1. Fetch properties for list of CIDs:
     python pubchem_downloader.py property --cids 2244,1983,3672
     
  2. Fetch properties for a list of chemical names:
     python pubchem_downloader.py property --names "Aspirin,Acetaminophen,Ibuprofen"
     
  3. Search similar compounds using SMILES:
     python pubchem_downloader.py search --smiles "CC(=O)OC1=CC=CC=C1C(=O)O" --type similarity --threshold 90
     
  4. Download a bulk mapping file from FTP (dry run, first 1MB):
     python pubchem_downloader.py download-bulk --file CID-Parent.gz --limit-bytes 1048576
```

---

### `rxnorm_scraper.py`
- **Data Storage Folder**: `[data]/Drug & Substance Reference/rxnorm_data`
- **Description**: rxnorm_scraper.py

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

## Regulatory & Approvals
*Scripts for downloading and processing regulatory approvals and drug databases.*

### `canada_dpd_downloader.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/canada_dpd_data`
- **Description**: canada_dpd_downloader.py

**Usage and Parameters**:
```text
usage: canada_dpd_downloader.py [-h] {download-bulk,api-enrich,search} ...

Resilient and multi-threaded data collector for the Health Canada Drug Product
Database (DPD).

positional arguments:
  {download-bulk,api-enrich,search}
                        Collector commands
    download-bulk       Download bulk ZIP extracts, compile SQLite database,
                        and export master datasets.
    api-enrich          Concurrently enrichment local drug records via DPD
                        REST API.
    search              Query compiled local database.

options:
  -h, --help            show this help message and exit
```

---

### `ema_downloader.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/ema_data`
- **Description**: ema_downloader.py

**Usage and Parameters**:
```text
No command-line arguments or failed to load help menu.
```

---

### `mhra_downloader.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/mhra_data`
- **Description**: mhra_downloader.py

**Usage and Parameters**:
```text
usage: mhra_downloader.py [-h] [--output-dir OUTPUT_DIR] [--threads THREADS]
                          [--max-retries MAX_RETRIES] [--timeout TIMEOUT]
                          [--dry-run] [--limit LIMIT] [--doc-types DOC_TYPES]

Resumable and multi-threaded MHRA UK approvals and regulatory documents
collector.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Directory to save downloaded files and metadata.
  --threads THREADS     Number of concurrent download threads.
  --max-retries MAX_RETRIES
                        Maximum retries for failed downloads.
  --timeout TIMEOUT     Timeout in seconds for HTTP requests.
  --dry-run             Scrape metadata index only, without downloading PDF
                        files.
  --limit LIMIT         Limit the number of products to download (for
                        testing).
  --doc-types DOC_TYPES
                        Comma-separated document types to download (e.g.,
                        'Par,Spc').
```

---

### `openfda_downloader.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/openfda_data`
- **Description**: openfda_downloader.py

**Usage and Parameters**:
```text
usage: openfda_downloader.py [-h] [-o OUTPUT_DIR] [-t THREADS] [-d DELAY]
                             [-l LIMIT] [--api-key API_KEY] [--query QUERY]
                             [--no-resume]
                             {download-bulk,api-harvest,search}

openFDA Drugs@FDA Downloader: Scrapes, downloads, and processes FDA-approved
drug metadata.

positional arguments:
  {download-bulk,api-harvest,search}
                        Data collection mode. 'download-bulk' is the
                        recommended full download. 'api-harvest' crawls the
                        live API. 'search' queries records.

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for data, progress, and logs.
                        (default: Regulatory & Approvals/openfda_data)
  -t THREADS, --threads THREADS
                        Number of threads for partition API harvesting.
                        (default: 4)
  -d DELAY, --delay DELAY
                        Polite delay between API requests. Default: 1.5s
                        (public) or 0.25s (with API key). (default: None)
  -l LIMIT, --limit LIMIT
                        Maximum records to harvest (for test runs). (default:
                        None)
  --api-key API_KEY     Optional openFDA API key for higher rate limits (240
                        requests/min). (default: None)
  --query QUERY         Query string for search mode (application number,
                        brand, ingredient, or sponsor). (default: None)
  --no-resume           Start download/harvest fresh, ignoring any progress
                        files. (default: False)
```

---

### `orangebook_downloader.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/orangebook_data`
- **Description**: orangebook_downloader.py

**Usage and Parameters**:
```text
usage: orangebook_downloader.py [-h] [--output-dir OUTPUT_DIR]
                                {download,parse,unified,search} ...

FDA Orange Book Data Collector and Analyst.

positional arguments:
  {download,parse,unified,search}
    download            Discover and download Orange Book ZIP, and scrape code
                        definitions.
    parse               Extract ZIP, parse tilde-delimited files, map code
                        definitions, and compile outputs.
    unified             Compile the unified analytical dataset from existing
                        parsed files.
    search              Search the local unified database.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Output directory path.
```

---

### `pmda_collector.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/pmda_data`
- **Description**: pmda_collector.py

**Usage and Parameters**:
```text
usage: pmda_collector.py [-h] [--output-dir OUTPUT_DIR] [--threads THREADS]
                         [--max-retries MAX_RETRIES] [--timeout TIMEOUT]
                         [--dry-run] [--limit LIMIT]

Resumable and multi-threaded PMDA Japan approvals and review reports
collector.

options:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Directory to save downloaded files and metadata.
  --threads THREADS     Number of concurrent download threads.
  --max-retries MAX_RETRIES
                        Maximum retries for failed downloads.
  --timeout TIMEOUT     Timeout in seconds for HTTP requests.
  --dry-run             Scrape metadata without downloading PDF files.
  --limit LIMIT         Limit the number of products to download (for
                        testing).
```

---

### `purplebook_downloader.py`
- **Data Storage Folder**: `[data]/Regulatory & Approvals/purplebook_data`
- **Description**: purplebook_downloader.py

**Usage and Parameters**:
```text
usage: purplebook_downloader.py [-h] [-o OUTPUT_DIR] [-t THREADS] [-d]
                                [-m MAX_PRODUCTS] [-f]

FDA Purple Book Resumable & Multi-Threaded Data Collector

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Directory to save collected datasets (default:
                        Regulatory & Approvals/purplebook_data)
  -t THREADS, --threads THREADS
                        Number of threads for deep crawler (default: 5)
  -d, --deep-crawl      Perform deep crawling of individual BLA details pages
  -m MAX_PRODUCTS, --max-products MAX_PRODUCTS
                        Limit the number of product pages crawled in deep
                        crawl mode (for testing)
  -f, --force           Force re-download of bulk files even if they already
                        exist
```

---

## Safety & Pharmacovigilance
*Scripts and tools for scraping and analyzing adverse event reports and pharmacovigilance databases.*

### `openfda_faers_downloader.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/openfda_faers_data`
- **Description**: openfda_faers_downloader.py

**Usage and Parameters**:
```text
usage: openfda_faers_downloader.py [-h] [-o OUTPUT_DIR] [-t THREADS]
                                   [-d DELAY] [-l LIMIT] [--api-key API_KEY]
                                   [--query QUERY] [--output-name OUTPUT_NAME]
                                   [--write-jsonl] [--clean-zips]
                                   [--no-resume]
                                   {download-bulk,api-harvest,consolidate,search,metadata-only}

openFDA FAERS Downloader: Resilient, multi-threaded collector for US adverse
event reports.

positional arguments:
  {download-bulk,api-harvest,consolidate,search,metadata-only}
                        Mode of operation. 'download-bulk' is the full
                        pipeline. 'api-harvest' fetches a live query.
                        'consolidate' merges partitions. 'search' queries
                        cases. 'metadata-only' checks available partitions.

options:
  -h, --help            show this help message and exit
  -o OUTPUT_DIR, --output-dir OUTPUT_DIR
                        Output directory for storing logs, checkpoints, and
                        data. (default: Safety &
                        Pharmacovigilance/openfda_faers_data)
  -t THREADS, --threads THREADS
                        Number of concurrent worker threads for bulk
                        downloads. (default: 4)
  -d DELAY, --delay DELAY
                        Polite delay between API requests. Default: 1.5s
                        (public) or 0.25s (with API key). (default: None)
  -l LIMIT, --limit LIMIT
                        Harvest limit (api-harvest) or partition limit
                        (download-bulk). (default: None)
  --api-key API_KEY     Optional openFDA API key for higher rate limits (240
                        requests/min). (default: None)
  --query QUERY         Search query term (for 'search' or 'api-harvest'
                        modes). (default: None)
  --output-name OUTPUT_NAME
                        Filename prefix for live harvested datasets. (default:
                        harvested_events)
  --write-jsonl         Write high-fidelity raw JSONL files in addition to
                        normalized CSVs. (default: False)
  --clean-zips          Delete raw ZIP files immediately after extraction to
                        save disk space. (default: False)
  --no-resume           Start bulk download fresh, ignoring the progress
                        checkpoint. (default: False)
```

---

### `explorer.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (VigiAccess explorer)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `find_obiee_selectors.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (OBIEE helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `find_run_button.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (OBIEE helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `find_tabs.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (OBIEE helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `get_obiee_html.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (OBIEE helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `inspect_dap_html.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (VigiAccess helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `inspect_run_button.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (OBIEE helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `inspect_search_elements.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (VigiAccess helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `parse_home.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (VigiAccess helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `substance_indexer.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (Writes to eudravigilance.db)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

### `verify_excel.py`
- **Data Storage Folder**: `[data]/Safety & Pharmacovigilance/ (Excel helper)`
- **Description**: No docstring available.

**Usage and Parameters**:
```text
No command-line arguments (executed directly or as a helper utility).
```

---

## Utility Scripts
*General purpose utility scripts for workspace management and deployment.*

### `upload_to_s3.py`
- **Data Storage Folder**: `[data]/N/A (S3 Upload Utility)`
- **Description**: AWS S3 Upload Utility

**Usage and Parameters**:
```text
usage: upload_to_s3.py [-h] (-f FILE | -d DIR) [-b BUCKET] [-k KEY]
                       [--key-prefix KEY_PREFIX] [--access-key ACCESS_KEY]
                       [--secret-key SECRET_KEY]
                       [--session-token SESSION_TOKEN] [--profile PROFILE]
                       [--region REGION] [--env ENV] [--overwrite]
                       [--only-csv]

Upload files or directories to AWS S3.

options:
  -h, --help            show this help message and exit
  -f FILE, --file FILE  Path to the local file to upload. (default: None)
  -d DIR, --dir DIR     Path to the local directory to upload. (default: None)
  -b BUCKET, --bucket BUCKET
                        Target S3 bucket name. (default: moine-data)
  -k KEY, --key KEY     S3 Key (destination path). For directory uploads, this
                        acts as a prefix. (default: None)
  --key-prefix KEY_PREFIX
                        Prefix to prepend to S3 keys (useful for directory
                        uploads). (default: None)
  --access-key ACCESS_KEY
                        AWS Access Key ID. (default: None)
  --secret-key SECRET_KEY
                        AWS Secret Access Key. (default: None)
  --session-token SESSION_TOKEN
                        AWS Session Token (if using temporary credentials).
                        (default: None)
  --profile PROFILE     AWS Profile name to use from ~/.aws/credentials.
                        (default: moine)
  --region REGION       AWS Region (e.g., us-east-1). (default: us-east-1)
  --env ENV             Path to a custom .env file to load credentials from.
                        (default: None)
  --overwrite           Force overwrite files even if they already exist on S3
                        with the same size. (default: False)
  --only-csv            Only upload CSV files, ignoring other file extensions.
                        (default: False)
```

---