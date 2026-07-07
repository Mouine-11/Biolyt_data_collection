import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Playwright v3...")
try:
    with sync_playwright() as p:
        print("Launching browser (headless)...")
        browser = p.chromium.launch(headless=True)
        
        print("Creating context and page...")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        print("Waiting 15 seconds for OBIEE dynamic content and frames...")
        time.sleep(15)
        
        print(f"Current URL: {page.url}")
        print(f"Page Title: {page.title()}")
        
        # Save the body HTML for detailed inspection
        html_content = page.content()
        with open("dap_rendered.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("Saved rendered page HTML to dap_rendered.html")
        
        # Extract text content
        body_text = page.inner_text("body")
        with open("dap_text.txt", "w", encoding="utf-8") as f:
            f.write(body_text)
        print("Saved body text to dap_text.txt")
        
        print(f"Total text length: {len(body_text)} chars")
        print("\nFirst 1000 characters of body text:")
        print(body_text[:1000])
        
        # Let's inspect links/tabs
        print("\nSearching for links or elements with 'Line Listing' or 'Export'...")
        links = page.query_selector_all("a")
        found_count = 0
        for i, link in enumerate(links):
            text = link.inner_text().strip()
            id_attr = link.get_attribute("id")
            class_attr = link.get_attribute("class")
            if text:
                if any(k in text.lower() for k in ["line", "listing", "export", "download", "summary", "reaction"]):
                    print(f"  Link {i}: text='{text}', id='{id_attr}', class='{class_attr}'")
                    found_count += 1
                    
        print(f"Found {found_count} relevant links.")
        
        # Let's check for frames
        frames = page.frames
        print(f"\nTotal frames found: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"  Frame {i}: name='{frame.name}', url='{frame.url}'")
            # Try to get frame content or links
            try:
                frame_title = frame.title()
                print(f"    Title: '{frame_title}'")
            except Exception as e:
                print(f"    Could not query title: {e}")

        browser.close()
        print("\nFinished v3 test successfully.")

except Exception as e:
    print(f"An error occurred: {e}")
