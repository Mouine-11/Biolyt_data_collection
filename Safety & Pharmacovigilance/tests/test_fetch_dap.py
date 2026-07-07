import requests
import sys

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://www.adrreports.eu/en/search_subst.html"
}

try:
    print(f"Requesting DAP URL: {url}...")
    response = requests.get(url, headers=headers, allow_redirects=True, timeout=20)
    print(f"Status Code: {response.status_code}")
    print(f"Final URL: {response.url}")
    
    print("\nResponse Headers:")
    for k, v in response.headers.items():
        print(f"  {k}: {v}")
        
    print("\nContent Preview (first 1000 chars):")
    print(response.text[:1000])
    
    with open("dap_abacavir.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("\nSaved content to dap_abacavir.html")
    
except Exception as e:
    print(f"Error: {e}")
