import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Playwright...")
try:
    with sync_playwright() as p:
        print("Launching browser (headless)...")
        # Try to launch chromium, if it fails, try to install it
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as launch_err:
            print(f"Error launching chromium: {launch_err}")
            print("Attempting to run 'playwright install chromium' might be needed.")
            sys.exit(1)
            
        print("Creating context and page...")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="networkidle", timeout=60000)
        
        print("Page loaded. Waiting 10 seconds for OBIEE dynamic content...")
        time.sleep(10)
        
        print("Title:", page.title())
        
        # Take screenshot to verify what got rendered
        screenshot_path = "dap_abacavir_screenshot.png"
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        # Print some info about elements on the page to see if we can find the tabs
        # OBIEE tabs are usually links or divs
        links = page.query_selector_all("a")
        print(f"Found {len(links)} links on the rendered page.")
        for i, link in enumerate(links[:20]):
            text = link.inner_text()
            href = link.get_attribute("href")
            print(f"  Link {i}: '{text}' -> {href}")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
