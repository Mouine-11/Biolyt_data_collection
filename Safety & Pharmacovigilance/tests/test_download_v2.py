import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Playwright Download Test v2...")
try:
    with sync_playwright() as p:
        print("Launching browser (headless)...")
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        print("Creating context and page...")
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        print("Waiting 15 seconds for OBIEE dynamic content to load...")
        time.sleep(15)
        
        print(f"Current URL: {page.url}")
        print(f"Page Title: {page.title()}")
        
        export_selector = "#idPageExportToExcel"
        export_el = page.query_selector(export_selector)
        if export_el:
            print("Found Export to Excel element in the DOM!")
            
            # Set up the download listener
            print("Attempting to click via JS evaluate and capture download...")
            try:
                with page.expect_download(timeout=60000) as download_info:
                    # Execute JavaScript click
                    page.evaluate('document.getElementById("idPageExportToExcel").click()')
                
                download = download_info.value
                print(f"Download triggered successfully!")
                print(f"Suggested filename: {download.suggested_filename}")
                
                save_path = "abacavir_test.xlsx"
                download.save_as(save_path)
                print(f"File downloaded and saved to {save_path}")
                
            except Exception as click_err:
                print(f"Error during click/download: {click_err}")
        else:
            print("Export to Excel element NOT found in the DOM.")
                
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
