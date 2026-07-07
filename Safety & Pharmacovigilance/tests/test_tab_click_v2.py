import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Tab Navigation Test v2 (Exact Match)...")
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        
        print(f"Navigating to {url}...")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        print("Waiting 15 seconds for initial render...")
        time.sleep(15)
        
        # Click the actual tab using exact match
        print("Locating tab with exact text 'Line Listing'...")
        tab = page.get_by_text("Line Listing", exact=True)
        
        if tab.count() > 0:
            print("Found exact 'Line Listing' tab element! Clicking it...")
            tab.click()
            print("Clicked tab. Waiting 25 seconds for the large Line Listing table to load...")
            time.sleep(25)
            
            # Verify if we are on the Line Listing tab by checking text
            body_text = page.locator("body").inner_text()
            print(f"\nBody text length after click: {len(body_text)} chars")
            
            # Check for line listing headers
            headers_to_check = ["Safety Report ID", "Report ID", "Local Report Number", "Reaction Seriousness", "Suspect Drug"]
            found_headers = [h for h in headers_to_check if h.lower() in body_text.lower()]
            print(f"Found Line Listing headers: {found_headers}")
            
            if len(found_headers) > 0:
                print("SUCCESS: Successfully switched to the Line Listing tab!")
                
                # Let's trigger the export
                print("Clicking Page Options button...")
                page.locator("#uberBar_dashboardpageoptions_image").click()
                time.sleep(2)
                
                # Trigger the Excel download
                js_trigger_dl = """
                    () => {
                        const cells = Array.from(document.querySelectorAll("td"));
                        const target = cells.find(el => el.textContent.trim() === "Export Current Page");
                        if (target) {
                            target.click();
                            return true;
                        }
                        return false;
                    }
                """
                print("Attempting to trigger export and capture download...")
                with page.expect_download(timeout=60000) as download_info:
                    success = page.evaluate(js_trigger_dl)
                    if success:
                        print("Download triggered successfully!")
                    else:
                        print("Failed to click 'Export Current Page' via JS.")
                        raise Exception("Export click failed")
                        
                download = download_info.value
                save_path = "abacavir_line_listing_real.xlsx"
                download.save_as(save_path)
                print(f"File downloaded and saved successfully to {save_path}")
                
            else:
                print("FAILURE: Did not switch to the Line Listing tab. Body text preview:")
                print(body_text[:1200])
        else:
            print("Exact 'Line Listing' tab NOT found.")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
