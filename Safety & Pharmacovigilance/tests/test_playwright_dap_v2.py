import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Playwright v2...")
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
        
        print(f"Navigating to {url} with domcontentloaded...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        print(f"Navigation complete. Current URL: {page.url}")
        print("Waiting 10 seconds for dynamic content to render...")
        time.sleep(10)
        
        print(f"URL after 10s wait: {page.url}")
        print(f"Page Title: {page.title()}")
        
        # Take a screenshot to see what's on the page
        screenshot_path = "dap_v2_screenshot.png"
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        # Let's print some of the HTML or text to see if there's a disclaimer
        body_text = page.inner_text("body")
        print("\nBody text preview (first 500 chars):")
        print(body_text[:500])
        
        # Check for common disclaimer words
        if "disclaimer" in body_text.lower() or "agree" in body_text.lower() or "understand" in body_text.lower():
            print("\nWARNING: Disclaimer or terms page detected!")
            # Let's find all buttons and checkboxes
            inputs = page.query_selector_all("input")
            print(f"Found {len(inputs)} input elements:")
            for i, inp in enumerate(inputs):
                print(f"  Input {i}: type={inp.get_attribute('type')}, id={inp.get_attribute('id')}, name={inp.get_attribute('name')}, value={inp.get_attribute('value')}")
            buttons = page.query_selector_all("button")
            print(f"Found {len(buttons)} button elements:")
            for i, btn in enumerate(buttons):
                print(f"  Button {i}: text='{btn.inner_text()}', id={btn.get_attribute('id')}, class={btn.get_attribute('class')}")
        
        # Let's check if there are frames
        frames = page.frames
        print(f"\nFound {len(frames)} frames/iframes on the page:")
        for i, frame in enumerate(frames):
            print(f"  Frame {i}: name='{frame.name}', url='{frame.url}'")

        browser.close()
        print("\nFinished v2 test successfully.")

except Exception as e:
    print(f"An error occurred: {e}")
