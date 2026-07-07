import requests

url = "https://www.adrreports.eu"
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
    print("Response Headers:")
    for k, v in response.headers.items():
        print(f"  {k}: {v}")
    
    print(f"\nFinal URL after redirects: {response.url}")
    
    # Print the first 1000 characters of the response text
    print("\nContent Preview (first 1000 chars):")
    print(response.text[:1000])
    
    with open("adr_homepage.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("\nSaved homepage to adr_homepage.html")

except Exception as e:
    print(f"Error requesting site: {e}")
