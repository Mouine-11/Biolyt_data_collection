import requests
import sys
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding='utf-8')

url = "https://www.adrreports.eu/tables/substance/a.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

try:
    print(f"Requesting {url}...")
    response = requests.get(url, headers=headers, timeout=15)
    print(f"Status Code: {response.status_code}")
    
    soup = BeautifulSoup(response.text, "html.parser")
    # Find some links or table rows
    rows = soup.find_all("tr")
    print(f"Found {len(rows)} table rows.")
    
    print("\nFirst 10 links in the table:")
    count = 0
    for a in soup.find_all("a"):
        href = a.get("href")
        text = a.get_text(strip=True)
        print(f"  {text} -> {href}")
        count += 1
        if count >= 10:
            break
            
    with open("substance_a_table.html", "w", encoding="utf-8") as f:
        f.write(response.text)
        
except Exception as e:
    print(f"Error: {e}")
