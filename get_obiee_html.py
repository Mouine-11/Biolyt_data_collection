import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting OBIEE HTML Capture...")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        print("Waiting for any link or table to appear (up to 30s)...")
        try:
            # Wait for any anchor tag that might indicate OBIEE menu or content is loaded
            page.wait_for_selector("a", timeout=30000)
            print("Detected anchor tags! Content is loading...")
        except Exception as e:
            print(f"Timed out waiting for anchor tags: {e}")
            
        print("Sleeping an extra 10 seconds to ensure full rendering...")
        time.sleep(10)
        
        # Get the full HTML
        full_html = page.content()
        print(f"Rendered HTML Length: {len(full_html)} characters")
        
        with open("dap_fully_rendered.html", "w", encoding="utf-8") as f:
            f.write(full_html)
        print("Saved fully rendered HTML to dap_fully_rendered.html")
        
        # Check if body is present and print its text
        try:
            body_text = page.inner_text("body")
            print(f"Body Text Length: {len(body_text)} characters")
            print("\nBody Text Preview:")
            print(body_text[:1000])
        except Exception as e:
            print(f"Error getting body text: {e}")
            
        # Let's count some elements
        links = page.query_selector_all("a")
        divs = page.query_selector_all("div")
        tables = page.query_selector_all("table")
        print(f"\nElements count: Links={len(links)}, Divs={len(divs)}, Tables={len(tables)}")
        
        # Print some links with text
        print("\nSome links found on the page:")
        for i, link in enumerate(links[:30]):
            text = link.inner_text().strip()
            href = link.get_attribute("href")
            id_attr = link.get_attribute("id")
            class_attr = link.get_attribute("class")
            print(f"  Link {i}: '{text}' | href='{href}' | id='{id_attr}' | class='{class_attr}'")

        browser.close()
        print("\nCapture finished.")

except Exception as e:
    print(f"An error occurred: {e}")
