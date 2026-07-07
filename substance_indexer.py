import os
import sys
import sqlite3
import requests
import re
import time
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = "Safety & Pharmacovigilance/eudravigilance.db"
BASE_INDEX_URL = "https://www.adrreports.eu/tables/substance"

# Build letters list: a to z, plus '0-9'
LETTERS = [chr(i) for i in range(ord('a'), ord('z') + 1)] + ['0-9']

def init_db():
    """Initializes the SQLite database schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS substances (
            substance_name TEXT PRIMARY KEY,
            substance_code TEXT,
            dap_url TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            last_attempt_at TEXT,
            downloaded_at TEXT
        );
    """)
    conn.commit()
    conn.close()
    print("Database initialized.")

def extract_substance_code(url: str) -> str:
    """Extracts the substance code (from P3 parameter) from the DAP URL."""
    # Example: P3=1+18853 or P3=1 18853
    match = re.search(r'P3=([^&]+)', url)
    if match:
        # Decode URL-encoded parts like + or %20
        code = match.group(1)
        code = code.replace('+', ' ').replace('%20', ' ')
        return code.strip()
    return None

def fetch_and_index_substances():
    """Fetches all A-Z substance lists and stores them in the database."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive"
    }
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    total_indexed = 0
    
    for letter in LETTERS:
        url = f"{BASE_INDEX_URL}/{letter}.html"
        print(f"Fetching substance list for '{letter}' from {url}...")
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                print(f"  Error: Received status code {response.status_code} for '{letter}'")
                continue
                
            soup = BeautifulSoup(response.text, "html.parser")
            links = soup.find_all("a")
            print(f"  Found {len(links)} links for '{letter}'")
            
            letter_indexed = 0
            for a in links:
                href = a.get("href")
                name = a.get_text(strip=True)
                
                if href and name:
                    # Validate that the link looks like a DAP link
                    if "dap.ema.europa.eu" in href or "saw.dll" in href:
                        substance_code = extract_substance_code(href)
                        
                        # Insert or ignore to handle duplicates
                        cursor.execute("""
                            INSERT OR IGNORE INTO substances (substance_name, substance_code, dap_url)
                            VALUES (?, ?, ?)
                        """, (name, substance_code, href))
                        
                        if cursor.rowcount > 0:
                            letter_indexed += 1
                            total_indexed += 1
            
            conn.commit()
            print(f"  Successfully indexed {letter_indexed} new substances for '{letter}'.")
            
            # Polite delay between requests
            time.sleep(1.0)
            
        except Exception as e:
            print(f"  Exception occurred for '{letter}': {e}")
            
    conn.close()
    print(f"\nIndexing complete! Total unique substances indexed: {total_indexed}")

def print_db_summary():
    """Prints a summary of the indexed database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM substances")
    total = cursor.fetchone()[0]
    
    print(f"\nDatabase Summary (from {DB_PATH}):")
    print(f"  Total Substances in DB: {total}")
    
    # Print a few samples
    cursor.execute("SELECT substance_name, substance_code, status FROM substances LIMIT 10")
    samples = cursor.fetchall()
    print("\nFirst 10 sample records:")
    for s in samples:
        print(f"  Name: {s[0]} | Code: {s[1]} | Status: {s[2]}")
        
    conn.close()

if __name__ == "__main__":
    init_db()
    fetch_and_index_substances()
    print_db_summary()
