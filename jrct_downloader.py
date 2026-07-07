#!/usr/bin/env python3
"""
jrct_downloader.py
========================
Automates downloading of trial registration data from the Japan Registry of Clinical Trials (jRCT).
Specifically targeting:
  Search list: https://jrct.mhlw.go.jp/search?language=en&searched=1&page=1&dis_op=0&free_op=1
  Details page: https://jrct.mhlw.go.jp/en-latest-detail/jRCT1042260071

Features:
  1. Iterates through search results pages to collect all Trial IDs.
  2. Visits each detail page, parses the structured HTML tables (handling rowspan/colspan).
  3. Flattens data fields into a dictionary with proper section prefixes to avoid key collision.
  4. Saves all trials to a unified CSV file in the output directory.
  5. Includes error retries, exponential backoffs, and respectful request delays.

Requirements:
    pip install requests beautifulsoup4
"""

import os
import sys
import time
import argparse
import csv
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode
import requests
from bs4 import BeautifulSoup

# Reconfigure output encoding for UTF-8 compatibility on Windows terminal
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

class BlockedException(Exception):
    """
    Raised when the server blocks requests (e.g. returns HTTP 403 or 429).
    """
    pass


# A rotation pool of modern desktop browsers to bypass User-Agent fingerprinting
USER_AGENTS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
]


def get_random_headers(referer=None):
    """
    Generates realistic, browser-complete headers with a random User-Agent and Sec-Ch-Ua attributes.
    Optionally attaches a Referer header to simulate page navigation.
    """
    import random
    ua = random.choice(USER_AGENTS)
    
    # Determine Sec-Ch-Ua based on User-Agent
    if "Edg/" in ua:
        sec_ua = '"Edge";v="124", "Chromium";v="124", "Not-A.Brand";v="99"'
    elif "Chrome" in ua:
        sec_ua = '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"'
    else:
        sec_ua = None

    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin" if referer else "none",
        "Sec-Fetch-User": "?1",
        "DNT": "1"
    }
    
    if sec_ua:
        headers["Sec-Ch-Ua"] = sec_ua
        headers["Sec-Ch-Ua-Mobile"] = "?0"
        headers["Sec-Ch-Ua-Platform"] = '"Windows"' if "Windows" in ua else '"macOS"'
        
    if referer:
        headers["Referer"] = referer
        
    return headers


DEFAULT_SEARCH_URL = "https://jrct.mhlw.go.jp/search?language=en&searched=1&page=1&dis_op=0&free_op=1"


import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global synchronization lock for modifying proxy pool or executing VPN rotation
rotation_lock = threading.Lock()
last_vpn_rotation_time = 0.0


def fetch_with_retry(session, url, proxies_list=None, vpn_rotate_cmd=None, retries=3, backoff=5, timeout=60, referer=None):
    """
    Fetches a URL with a retry mechanism, exponential backoff, optional proxy rotation, or VPN rotation.
    When a proxy pool is active, dynamically retries across as many proxies as needed.
    This function is thread-safe and can be called concurrently.
    Mimics a real browser by generating realistic dynamic headers and introducing jitter to avoid WAF blocks.
    """
    import random
    global last_vpn_rotation_time
    
    # Introduce a small random jitter before initiating request to spread out concurrent threads
    # This prevents the WAF from seeing multiple requests hitting the server at the exact same millisecond.
    time.sleep(random.uniform(0.1, 2.5))
    
    # When a proxy pool is active, try every proxy in the pool before giving up
    effective_retries = len(proxies_list) if proxies_list else retries

    for attempt in range(1, effective_retries + 1):
        current_proxy = None
        if proxies_list:
            # We select a random proxy but do not modify the session.proxies attribute.
            # Instead, we pass it directly to the get() request to keep it thread-safe.
            with rotation_lock:
                if proxies_list:
                    current_proxy = random.choice(proxies_list)
            
            if not current_proxy:
                effective_retries = attempt - 1
                break
                
            # Shorter per-proxy timeout so dead proxies fail fast
            effective_timeout = min(timeout, 15)
            # Small random jitter so successive proxy attempts look less robotic to the WAF
            if attempt > 1:
                time.sleep(random.uniform(0.5, 2.0))
            print(f"  [Proxy {attempt}/{effective_retries}] Using proxy: {current_proxy}")
        else:
            effective_timeout = timeout
            
        try:
            # Generate a fresh set of realistic headers for this request, mimicking a real browser
            headers = get_random_headers(referer=referer)
            
            # Pass proxy at the request level to ensure thread safety
            proxies_dict = {"http": current_proxy, "https": current_proxy} if current_proxy else None
            resp = session.get(url, headers=headers, timeout=effective_timeout, proxies=proxies_dict)
            if resp.status_code == 200:
                return resp
            print(f"  [!] HTTP {resp.status_code} on attempt {attempt}/{effective_retries} for {url}")
            
            # WAF/Rate limit block
            if resp.status_code in [403, 429]:
                if proxies_list:
                    print("      Access denied (403/429). Rotating proxy...")
                    with rotation_lock:
                        try:
                            proxies_list.remove(current_proxy)
                            print(f"      Removed blocked proxy. {len(proxies_list)} remaining.")
                        except ValueError:
                            pass
                elif vpn_rotate_cmd:
                    print(f"      Access denied (403/429). Executing VPN rotation...")
                    import subprocess
                    with rotation_lock:
                        current_time = time.time()
                        if current_time - last_vpn_rotation_time > 30:
                            try:
                                subprocess.run(vpn_rotate_cmd, shell=True, check=True)
                                print("      VPN command executed. Waiting 15s for connection to stabilize...")
                                time.sleep(15)
                                last_vpn_rotation_time = time.time()
                            except Exception as ve:
                                print(f"      [VPN Error] Rotation command failed: {ve}")
                        else:
                            print("      VPN was recently rotated by another thread. Skipping duplicate rotation.")
                else:
                    raise BlockedException("The server has blocked your IP address (HTTP 403/429).")
                
        except BlockedException:
            raise
        except Exception as e:
            if proxies_list:
                with rotation_lock:
                    try:
                        proxies_list.remove(current_proxy)
                        print(f"      Dead proxy removed. {len(proxies_list)} remaining. Rotating...")
                    except ValueError:
                        pass
            elif vpn_rotate_cmd:
                print(f"      Connection failure. Executing VPN rotation...")
                import subprocess
                with rotation_lock:
                    current_time = time.time()
                    if current_time - last_vpn_rotation_time > 30:
                        try:
                            subprocess.run(vpn_rotate_cmd, shell=True, check=True)
                            print("      VPN command executed. Waiting 15s for connection to stabilize...")
                            time.sleep(15)
                            last_vpn_rotation_time = time.time()
                        except Exception as ve:
                            print(f"      [VPN Error] Rotation command failed: {ve}")
                    else:
                        print("      VPN was recently rotated by another thread. Skipping duplicate rotation.")
            else:
                print(f"  [!] Connection error on attempt {attempt}/{effective_retries}: {e}")
                if attempt < effective_retries:
                    sleep_time = backoff * attempt
                    print(f"      Waiting {sleep_time}s before retrying...")
                    time.sleep(sleep_time)
            continue

    raise BlockedException("Exhausted all proxies/retries without a successful response.")


def parse_html_table(table):
    """
    Parses an HTML table into a 2D grid of strings, correctly
    accounting for 'rowspan' and 'colspan' attributes.
    """
    rows = table.find_all('tr')
    num_rows = len(rows)
    grid = [[] for _ in range(num_rows)]
    
    for r_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        c_idx = 0
        for cell in cells:
            rowspan = int(cell.get('rowspan', 1))
            colspan = int(cell.get('colspan', 1))
            text = cell.get_text(" ", strip=True)
            
            # Find the next empty slot in the row grid
            while c_idx < len(grid[r_idx]) and grid[r_idx][c_idx] is not None:
                c_idx += 1
                
            # Fill the grid cells spanned by rowspan/colspan
            for r in range(rowspan):
                for c in range(colspan):
                    target_row = r_idx + r
                    target_col = c_idx + c
                    if target_row < num_rows:
                        while len(grid[target_row]) <= target_col:
                            grid[target_row].append(None)
                        grid[target_row][target_col] = text
            c_idx += colspan
            
    # Convert any remaining None values to empty strings
    return [[cell or '' for cell in row] for row in grid]


def scrape_search_page(session, base_url, page_num, proxies_list=None, vpn_rotate_cmd=None, timeout=60):
    """
    Scrapes a search result listing page and extracts Trial IDs.
    Simulates organic referer navigation.
    """
    parsed = urlparse(base_url)
    query_params = parse_qs(parsed.query)
    query_params["page"] = [str(page_num)]
    
    # Reconstruct URL with the target page number
    new_query = urlencode(query_params, doseq=True)
    page_url = parsed._replace(query=new_query).geturl()
    
    # Simulate realistic referer: page 1 came from home, page 2+ came from the previous page
    referer = "https://jrct.mhlw.go.jp/" if page_num == 1 else f"https://jrct.mhlw.go.jp/search?language=en&searched=1&page={page_num-1}&dis_op=0&free_op=1"
    
    print(f"\n[Search Page {page_num}] Fetching list: {page_url}")
    resp = fetch_with_retry(session, page_url, proxies_list=proxies_list, vpn_rotate_cmd=vpn_rotate_cmd, timeout=timeout, referer=referer)
    if not resp:
        print(f"  [Error] Failed to load search page {page_num}")
        return []
        
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        print(f"  [Warning] No table found on search page {page_num}. Ending pagination.")
        return []
        
    trial_ids = []
    rows = table.find_all("tr")
    for row in rows:
        tds = row.find_all("td")
        if not tds:
            continue
        
        # Trial ID is located in the first cell (index 0)
        trial_id = tds[0].get_text(strip=True)
        if trial_id.startswith("jRCT"):
            trial_ids.append(trial_id)
            
    return trial_ids


def scrape_detail_page(session, trial_id, proxies_list=None, vpn_rotate_cmd=None, timeout=60, referer="https://jrct.mhlw.go.jp/search?language=en&searched=1&page=1&dis_op=0&free_op=1"):
    """
    Downloads and parses a trial's detail page, converting structured
    tables into flat key-value pairs.
    Simulates organic referer navigation from the search listings page.
    """
    detail_url = f"https://jrct.mhlw.go.jp/en-latest-detail/{trial_id}"
    resp = fetch_with_retry(session, detail_url, proxies_list=proxies_list, vpn_rotate_cmd=vpn_rotate_cmd, timeout=timeout, referer=referer)
    if not resp:
        print(f"  [Error] Failed to fetch details for {trial_id}")
        return None
        
    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    
    data_dict = {
        "Trial ID": trial_id,
        "Detail URL": detail_url
    }
    
    for table in tables:
        grid = parse_html_table(table)
        if not grid or len(grid) == 0:
            continue
            
        # Skip the revision history table which is table-meta of the registry itself
        if len(grid[0]) >= 2 and grid[0][0].strip() == 'No' and grid[0][1].strip() == 'Publication date':
            continue
            
        section_prefix = None
        for row in grid:
            if len(row) == 2:
                key = row[0].strip()
                val = row[1].strip()
                if not key:
                    continue
                
                # Context-aware prefix mapping to avoid key collision
                if key == 'Name of Certified Review Board':
                    section_prefix = 'Certified Review Board'
                    data_dict['Certified Review Board - Name'] = val
                elif section_prefix and key in ['Address', 'Telephone', 'E-Mail', 'Approval Status', 'Date of approval']:
                    data_dict[f"{section_prefix} - {key}"] = val
                else:
                    if key in data_dict and data_dict[key] != val:
                        suffix = 2
                        while f"{key} ({suffix})" in data_dict:
                            suffix += 1
                        data_dict[f"{key} ({suffix})"] = val
                    else:
                        data_dict[key] = val
                        
            elif len(row) == 3:
                key1 = row[0].strip()
                key2 = row[1].strip()
                val = row[2].strip()
                if key1 == key2:
                    data_dict[key1] = val
                else:
                    data_dict[f"{key1} - {key2}"] = val
                    
            elif len(row) >= 4:
                key1 = row[0].strip()
                key2 = row[1].strip()
                key3 = row[2].strip()
                val = " ".join(row[3:]).strip()
                data_dict[f"{key1} - {key2} - {key3}"] = val
                
    return data_dict


def test_proxy(proxy, test_url="https://jrct.mhlw.go.jp/", timeout=5):
    """
    Tests a single proxy with a fast timeout. Returns the proxy string if it works, else None.
    """
    try:
        resp = requests.get(
            test_url,
            proxies={"http": proxy, "https": proxy},
            headers=HEADERS,
            timeout=timeout
        )
        # Only accept genuine success/redirect — 403/429 means proxy IP is already blocked by jRCT
        if resp.status_code in [200, 301, 302]:
            return proxy
    except Exception:
        pass
    return None


def fetch_free_proxies(validate=True, max_workers=50):
    """
    Automatically fetches a list of free public HTTP/HTTPS proxies from public APIs,
    then concurrently validates them to keep only the live ones.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    print("\n>>> Fetching free public proxies for rotation...")
    urls = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
        "https://www.proxy-list.download/api/v1/get?type=https",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    raw_proxies = []
    for url in urls:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                for line in resp.text.splitlines():
                    line = line.strip()
                    if line and ":" in line and not line.startswith("#"):
                        raw_proxies.append(f"http://{line}")
        except Exception:
            pass

    raw_proxies = list(set(raw_proxies))
    print(f"    Collected {len(raw_proxies)} raw proxies. Validating concurrently (this may take ~30s)...")

    if not validate:
        return raw_proxies

    live_proxies = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(test_proxy, p): p for p in raw_proxies}
        done = 0
        for future in as_completed(futures):
            done += 1
            result = future.result()
            if result:
                live_proxies.append(result)
            # Print progress every 100 tested
            if done % 100 == 0:
                print(f"    Tested {done}/{len(raw_proxies)}... {len(live_proxies)} live proxies so far.")

    print(f"    Validation complete: {len(live_proxies)} live proxies out of {len(raw_proxies)} tested.")
    return live_proxies


def main():
    parser = argparse.ArgumentParser(
        description="Scrape and extract trial records from the Japan Registry of Clinical Trials (jRCT).",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_SEARCH_URL,
        help="Initial jRCT search result listing page URL containing query filters."
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum search result pages to crawl (50 trials per page)."
    )
    parser.add_argument(
        "--output-dir",
        default="Clinical Trials & Pipeline Intelligence/jrct_trials",
        help="Target folder to save output CSV. Defaults to 'Clinical Trials & Pipeline Intelligence/jrct_trials'."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Polite wait delay in seconds between details page requests (default: 1.0s)."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Connection and read timeout in seconds (default: 60s)."
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="Maximum number of trial detail pages to fetch and parse."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        help="Number of detail pages to scrape concurrently in each batch (default: 5)."
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="Proxy URL (e.g. 'http://user:pass@ip:port' or SOCKS5 'socks5h://127.0.0.1:9050')."
    )
    parser.add_argument(
        "--proxy-file",
        default=None,
        help="File path containing a list of proxies (one proxy per line) to rotate."
    )
    parser.add_argument(
        "--auto-proxy",
        action="store_true",
        help="Automatically fetch a list of free public proxies to use for rotation."
    )
    parser.add_argument(
        "--vpn-rotate",
        default=None,
        help="Shell command to run to rotate your VPN IP address when blocked (e.g. 'nordvpn connect')."
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "jrct_list.csv"

    # Load existing records for resume functionality
    existing_records = []
    scraped_ids = set()
    if csv_path.exists():
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for row in reader:
                        clean_row = {k: (v or "").strip() for k, v in row.items() if k}
                        trial_id = clean_row.get("Trial ID")
                        if trial_id:
                            existing_records.append(clean_row)
                            scraped_ids.add(trial_id)
            print(f"Loaded {len(existing_records)} existing records from {csv_path}. Resume mode active.")
        except Exception as e:
            print(f"[Warning] Failed to read existing CSV {csv_path} ({e}). Starting fresh.")

    print("=" * 70)
    print("  Japan Registry of Clinical Trials (jRCT) Downloader")
    print(f"  Initial Search URL : {args.url}")
    print(f"  Output CSV         : {csv_path}")
    print(f"  Polite Delay       : {args.delay}s")
    print(f"  Timeout            : {args.timeout}s")
    if args.max_pages:
        print(f"  Max Search Pages   : {args.max_pages} (~{args.max_pages * 50} trials)")
    if args.max_trials:
        print(f"  Max Trials to Fetch: {args.max_trials}")
    print("=" * 70)

    # Load and configure proxies
    proxies_list = []
    if args.proxy:
        proxies_list.append(args.proxy)
    if args.proxy_file:
        p_path = Path(args.proxy_file)
        if p_path.exists():
            with open(p_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        proxies_list.append(line)
            print(f"Loaded {len(proxies_list)} proxies from {args.proxy_file}")
        else:
            print(f"[Warning] Proxy file {args.proxy_file} not found.")

    if args.auto_proxy:
        free_proxies = fetch_free_proxies()
        proxies_list.extend(free_proxies)

    # Remove duplicates from list keeping order
    seen = set()
    proxies_list = [p for p in proxies_list if not (p in seen or seen.add(p))]

    session = requests.Session()
    static_proxy = None
    
    # If using a single static proxy, store it to apply to subsequent fresh sessions
    if len(proxies_list) == 1:
        static_proxy = proxies_list[0]
        session.proxies = {
            "http": static_proxy,
            "https": static_proxy
        }
        print(f"Configured static proxy: {static_proxy}")
        proxies_list = []  # Empty it to disable rotation logic

    all_trial_ids = []
    ids_cache_path = output_dir / "jrct_ids.txt"  # Persisted ID list for resume
    ids_collection_complete = False

    # Resume search ID collection from saved cache if it exists
    if ids_cache_path.exists():
        try:
            with open(ids_cache_path, "r", encoding="utf-8") as f:
                cached_lines = [l.strip() for l in f if l.strip()]
            # Last line is a sentinel when collection finished cleanly
            if cached_lines and cached_lines[-1] == "__COMPLETE__":
                all_trial_ids = cached_lines[:-1]
                ids_collection_complete = True
                print(f"Loaded {len(all_trial_ids)} Trial IDs from cache (collection was complete).")
            else:
                all_trial_ids = cached_lines
                print(f"Loaded {len(all_trial_ids)} Trial IDs from partial cache. Resuming search page collection...")
        except Exception as e:
            print(f"[Warning] Could not read ID cache ({e}). Starting fresh.")

    # Convert scraped_ids to a set for fast lookup
    all_scraped_records = list(existing_records)
    scraped_ids = {row.get("Trial ID") for row in all_scraped_records if row.get("Trial ID")}

    # Calculate starting search page based on already cached IDs
    # (Since each search page yields exactly 50 IDs, page is len(all_trial_ids) // 50 + 1)
    search_page = (len(all_trial_ids) // 50) + 1

    print("=" * 70)
    print(">>> PIPELINED CONCURRENT SCRAPING STARTED")
    print(f"    Already scraped in CSV: {len(scraped_ids)}")
    print(f"    Already discovered IDs : {len(all_trial_ids)}")
    print("=" * 70)

    # Helper function to save the CSV file dynamically
    def save_csv():
        if not all_scraped_records:
            return
        # Dynamically compile fieldnames
        all_keys = set()
        for trial in all_scraped_records:
            all_keys.update(trial.keys())
            
        first_cols = [
            "Trial ID",
            "Scientific Title",
            "Public Title",
            "Recruitment status",
            "Date of registration",
            "Last modified on",
            "Study Type",
            "Detail URL"
        ]
        first_cols = [c for c in first_cols if c in all_keys]
        other_cols = sorted(list(all_keys - set(first_cols)))
        fieldnames = first_cols + other_cols
        
        try:
            # Write to a temp file first, then rename to prevent corruption
            temp_path = csv_path.with_suffix(".tmp")
            with open(temp_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for trial in all_scraped_records:
                    row_data = {k: trial.get(k, "") for k in fieldnames}
                    writer.writerow(row_data)
            
            # Atomic rename
            if csv_path.exists():
                csv_path.unlink()
            temp_path.rename(csv_path)
            print(f"    [Save] CSV successfully updated. Total records: {len(all_scraped_records)}")
        except Exception as csv_err:
            print(f"    [Save Error] Failed to write CSV file: {csv_err}")

    # Special initialization if starting completely fresh
    # The user said: "After collecting the first page unique identifier, then, waiting, of course, we wait for 5 seconds, then we will do those requests."
    if not ids_collection_complete and len(all_trial_ids) == 0:
        print("\n>>> Fresh Start: Fetching Search Page 1 to discover initial Trial IDs...")
        try:
            page_ids = scrape_search_page(session, args.url, 1, proxies_list=proxies_list, vpn_rotate_cmd=args.vpn_rotate, timeout=args.timeout)
            if page_ids:
                all_trial_ids.extend(page_ids)
                print(f"    Collected {len(page_ids)} initial Trial IDs from Page 1.")
                with open(ids_cache_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(all_trial_ids))
                search_page = 2
                
                # Wait 5 seconds after collecting page 1
                print(f"    Waiting 5 seconds before entering pipelined concurrency...")
                time.sleep(5.0)
            else:
                print("    [Warning] No Trial IDs found on Search Page 1.")
                ids_collection_complete = True
        except BlockedException as e:
            print(f"\n[!] Block Detected during initial Page 1 fetch: {e}")
            print("    Exiting. Please change your VPN/IP before restarting.")
            return

    try:
        batch_index = 1
        while True:
            # Recreate session for each batch to avoid WAF session-tracking fingerprints
            session = requests.Session()
            if static_proxy:
                session.proxies = {
                    "http": static_proxy,
                    "https": static_proxy
                }
            # Determine which trials need to be fetched in this batch
            unscraped_ids = [tid for tid in all_trial_ids if tid not in scraped_ids]
            
            # Apply max_trials limit if specified
            if args.max_trials:
                # Calculate how many more we are allowed to fetch
                already_fetched_new = len(all_scraped_records) - len(existing_records)
                remaining_quota = args.max_trials - already_fetched_new
                if remaining_quota <= 0:
                    print(f"\n[Limit] Reached specified max trials quota of {args.max_trials}. Stopping.")
                    break
                # Truncate unscraped_ids to stay within remaining quota
                unscraped_ids = unscraped_ids[:remaining_quota]
                
            batch_to_fetch = unscraped_ids[:args.batch_size]
            
            # Determine if we should also request the next search page
            # We fetch next search page if:
            # 1. We haven't finished search pagination, AND
            # 2. (We are not limited by max_pages, OR the next search page is within max_pages limit)
            fetch_search = False
            if not ids_collection_complete:
                if not args.max_pages or search_page <= args.max_pages:
                    fetch_search = True
                else:
                    print(f"\n[Limit] Reached search page limit of {args.max_pages}. Stopping search collection.")
                    ids_collection_complete = True
                    with open(ids_cache_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(all_trial_ids) + "\n__COMPLETE__")

            # Check termination condition:
            # - No more un-scraped detail pages in the queue, AND
            # - No more search pages to fetch
            if not batch_to_fetch and not fetch_search:
                print("\n>>> All trials have been successfully scraped and search collection is complete.")
                break

            print(f"\n>>> [Batch {batch_index}] Processing concurrent requests...")
            if fetch_search:
                print(f"    - Concurrently requesting Search Page {search_page}")
            if batch_to_fetch:
                print(f"    - Concurrently requesting {len(batch_to_fetch)} trial details: {', '.join(batch_to_fetch)}")

            # Execute requests concurrently using a ThreadPoolExecutor
            # Workers is up to 11 (1 search + 10 details)
            max_workers = (1 if fetch_search else 0) + len(batch_to_fetch)
            
            new_page_ids = None
            scraped_details_batch = []
            search_blocked = False
            detail_blocked = False

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures_detail = {}
                future_search = None
                
                # Submit search page task
                if fetch_search:
                    future_search = executor.submit(
                        scrape_search_page,
                        session,
                        args.url,
                        search_page,
                        proxies_list=proxies_list,
                        vpn_rotate_cmd=args.vpn_rotate,
                        timeout=args.timeout
                    )
                
                # Submit detail page tasks
                for trial_id in batch_to_fetch:
                    future = executor.submit(
                        scrape_detail_page,
                        session,
                        trial_id,
                        proxies_list=proxies_list,
                        vpn_rotate_cmd=args.vpn_rotate,
                        timeout=args.timeout
                    )
                    futures_detail[future] = trial_id

                # Wait for search page task to complete if submitted
                if future_search:
                    try:
                        new_page_ids = future_search.result()
                    except BlockedException as e:
                        search_blocked = True
                        print(f"    [Block] Search page {search_page} hit a block exception.")
                    except Exception as e:
                        print(f"    [Error] Search page {search_page} failed: {e}")

                # Wait for detail page tasks to complete
                for future in as_completed(futures_detail):
                    trial_id = futures_detail[future]
                    try:
                        trial_data = future.result()
                        if trial_data:
                            scraped_details_batch.append(trial_data)
                        else:
                            print(f"    [Warning] Failed to scrape details for {trial_id}.")
                    except BlockedException as e:
                        detail_blocked = True
                        print(f"    [Block] Trial {trial_id} detail page hit a block exception.")
                    except Exception as e:
                        print(f"    [Error] Trial {trial_id} detail page failed: {e}")

            # Process search page results
            if fetch_search and not search_blocked:
                if new_page_ids:
                    # Filter out any duplicate IDs
                    unique_new_ids = [tid for tid in new_page_ids if tid not in all_trial_ids]
                    all_trial_ids.extend(unique_new_ids)
                    print(f"    [Search Page {search_page}] Collected {len(unique_new_ids)} new Trial IDs (Total discovered: {len(all_trial_ids)})")
                    
                    # Update ID cache file immediately
                    with open(ids_cache_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(all_trial_ids))
                        
                    search_page += 1
                elif new_page_ids is not None:
                    # Returned empty list, meaning end of search pagination
                    print(f"    [Search Page {search_page}] No more Trial IDs found. Search collection complete.")
                    ids_collection_complete = True
                    with open(ids_cache_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(all_trial_ids) + "\n__COMPLETE__")

            # Process detail page results & save
            if scraped_details_batch:
                all_scraped_records.extend(scraped_details_batch)
                scraped_ids.update({trial.get("Trial ID") for trial in scraped_details_batch if trial.get("Trial ID")})
                # Save immediately to CSV (10 by 10)
                save_csv()

            # Handle blocks with a smart, resilient failover strategy
            if detail_blocked:
                print(f"\n[!] Block Detected on detail pages: Detail scraping is blocked by the server's firewall.")
                print("    Current progress successfully saved. Please change your VPN/IP before restarting.")
                break
                
            if search_blocked:
                # Calculate how many un-scraped IDs we have left in memory (excluding the current batch)
                remaining_cached = len(unscraped_ids) - len(batch_to_fetch)
                if remaining_cached > 0:
                    print(f"\n[!] Block Detected on Search Page {search_page}. jRCT WAF is blocking search queries.")
                    print(f"    [Resilience] Skipping search page collection for this run and continuing with {remaining_cached} already cached Trial IDs...")
                    # Temporarily stop requesting search pages for this run so we can consume the cached queue
                    ids_collection_complete = True
                else:
                    print(f"\n[!] Block Detected on Search Page {search_page} and no cached Trial IDs remain.")
                    print("    Current progress successfully saved. Please change your VPN/IP before restarting.")
                    break

            # Polite wait delay after the batch completes
            wait_time = max(args.delay, 5.0)
            print(f"    Waiting {wait_time} seconds before repeating...")
            time.sleep(wait_time)
            batch_index += 1

    except KeyboardInterrupt:
        print("\n[!] Execution interrupted by user. Saving current progress...")
        save_csv()
        return

    print("\n" + "=" * 70)
    print("  *  SCRAPING PROCESS FINISHED")
    print(f"  Total records saved : {len(all_scraped_records)}")
    print(f"  CSV file path       : {csv_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
