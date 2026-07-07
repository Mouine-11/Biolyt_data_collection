import requests
import sys
from bs4 import BeautifulSoup

# Reconfigure stdout to use UTF-8
sys.stdout.reconfigure(encoding='utf-8')

url = "https://www.adrreports.eu/en/index.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

try:
    print(f"Requesting {url}...")
    response = requests.get(url, headers=headers, allow_redirects=True, timeout=15)
    print(f"Status Code: {response.status_code}")
    print(f"Final URL: {response.url}")
    
    soup = BeautifulSoup(response.text, "html.parser")
    print("\nAll links on the English homepage:")
    for a in soup.find_all("a"):
        href = a.get("href")
        text = a.get_text(strip=True)
        if href:
            print(f"  {text} -> {href}")
            
    with open("adr_en_index.html", "w", encoding="utf-8") as f:
        f.write(response.text)
        
except Exception as e:
    print(f"Error: {e}")
