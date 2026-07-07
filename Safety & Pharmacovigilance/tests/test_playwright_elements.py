import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Playwright Elements Inspector...")
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
        
        print("Waiting 20 seconds for full rendering...")
        time.sleep(20)
        
        # Print page frames
        print("\n--- FRAMES ---")
        for i, f in enumerate(page.frames):
            print(f"Frame {i}: name='{f.name}', url='{f.url}'")
            
        # Check if there are any iframe tags in the HTML
        iframes = page.query_selector_all("iframe")
        print(f"\nFound {len(iframes)} iframe elements via selector:")
        for i, iframe in enumerate(iframes):
            print(f"  iframe {i}: id={iframe.get_attribute('id')}, name={iframe.get_attribute('name')}, src={iframe.get_attribute('src')}")
            
        # Print all divs on the page to see where the content goes
        divs = page.query_selector_all("div")
        print(f"\nTotal div elements: {len(divs)}")
        print("Sample divs (first 20):")
        for i, div in enumerate(divs[:20]):
            text = div.inner_text().strip()
            # clean text
            text = " ".join(text.split())[:80]
            print(f"  div {i}: id={div.get_attribute('id')}, class={div.get_attribute('class')}, text='{text}'")
            
        # Let's print all text content on the page
        all_text = page.locator("body").inner_text()
        print(f"\nBody inner text length: {len(all_text)}")
        print("Body inner text:")
        print(all_text[:1500])
        
        # Check if there are any tables
        tables = page.query_selector_all("table")
        print(f"\nFound {len(tables)} table elements on the page.")
        
        browser.close()
        print("\nInspector finished.")

except Exception as e:
    print(f"An error occurred: {e}")
