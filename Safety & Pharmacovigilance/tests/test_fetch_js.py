import requests

url = "https://www.adrreports.eu/Scripts/dashboard-api.js"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive"
}

try:
    print(f"Requesting {url}...")
    response = requests.get(url, headers=headers, timeout=15)
    print(f"Status Code: {response.status_code}")
    
    with open("dashboard-api.js", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("Saved script to dashboard-api.js")
    
    print("\nFirst 1000 chars of dashboard-api.js:")
    print(response.text[:1000])

except Exception as e:
    print(f"Error: {e}")
