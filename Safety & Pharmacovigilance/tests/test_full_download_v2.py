import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Full Playwright Line Listing Download v2...")
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
        
        print("Waiting 15 seconds for initial render...")
        time.sleep(15)
        
        # 1. Click the Line Listing Tab
        print("Looking for 'Line Listing' tab...")
        tab_locator = page.locator("div:has-text('Line Listing')").first
        if tab_locator.count() > 0:
            print("Found Line Listing tab! Clicking it...")
            tab_locator.click()
            print("Clicked Line Listing tab. Waiting 20 seconds for the large table to load...")
            time.sleep(20)
        else:
            print("Line Listing tab NOT found. Exiting...")
            browser.close()
            sys.exit(1)
            
        # 2. Click Page Options Button
        print("Looking for Page Options button (#uberBar_dashboardpageoptions_image)...")
        options_btn = page.locator("#uberBar_dashboardpageoptions_image")
        if options_btn.count() > 0:
            print("Found Page Options button! Clicking it to activate the menu...")
            options_btn.click()
            time.sleep(2)
        else:
            print("Page Options button NOT found. Exiting...")
            browser.close()
            sys.exit(1)
            
        # 3. Trigger JS click on 'Export Current Page'
        print("Attempting to trigger JS click on 'Export Current Page' and capture download...")
        js_trigger = """
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
        
        try:
            with page.expect_download(timeout=60000) as download_info:
                success = page.evaluate(js_trigger)
                if success:
                    print("JS click executed successfully on 'Export Current Page'!")
                else:
                    print("Could not find 'Export Current Page' td element via JS.")
                    raise Exception("Element not found")
                
            download = download_info.value
            print("Download triggered successfully!")
            print(f"Suggested filename: {download.suggested_filename}")
            
            save_path = "abacavir_line_listing.xlsx"
            download.save_as(save_path)
            print(f"File downloaded and saved successfully to {save_path}")
            
        except Exception as dl_err:
            print(f"Error during download trigger: {dl_err}")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
