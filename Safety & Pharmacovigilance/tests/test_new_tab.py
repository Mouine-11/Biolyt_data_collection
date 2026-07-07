import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting New Tab Discovery...")
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
        
        print("Clicking 'Line Listing' tab...")
        page.get_by_text("Line Listing", exact=True).click()
        
        print("Waiting 5 seconds for filtering conditions to render...")
        time.sleep(5)
        
        # Locate the 'Run Line Listing Report' link
        run_link = page.locator("a:has-text('Run Line Listing Report')").first
        
        if run_link.count() > 0:
            print("Found the Run link! Preparing to capture the new tab...")
            
            # Click and expect a new page (tab)
            try:
                with context.expect_page(timeout=60000) as new_page_info:
                    print("Clicking 'Run Line Listing Report'...")
                    run_link.click()
                
                # Capture the new page
                new_page = new_page_info.value
                print("Captured the new tab!")
                print(f"New Tab Initial URL: {new_page.url}")
                
                print("Waiting 20 seconds for the new tab to run the query and load the table...")
                time.sleep(20)
                
                # Check the new page's URL and title
                print(f"New Tab URL after wait: {new_page.url}")
                print(f"New Tab Title: {new_page.title()}")
                
                # Print the text content of the new tab
                new_body_text = new_page.locator("body").inner_text()
                print(f"\nNew Tab Body Text Length: {len(new_body_text)} chars")
                
                # Check for line listing headers in the new tab
                headers_to_check = ["Safety Report ID", "Report ID", "Local Report Number", "Reaction Seriousness", "Suspect Drug"]
                found_headers = [h for h in headers_to_check if h.lower() in new_body_text.lower()]
                print(f"Found Line Listing headers in new tab: {found_headers}")
                
                # If headers are found, or even if they aren't (maybe it is empty or different),
                # let's list the links on the new page to see if we have an Export option!
                links = new_page.query_selector_all("a")
                print(f"\nFound {len(links)} links on the new page.")
                export_current_page_el = None
                for i, link in enumerate(links):
                    text = link.inner_text().strip()
                    id_attr = link.get_attribute("id")
                    class_attr = link.get_attribute("class")
                    if text:
                        if any(k in text.lower() for k in ["export", "excel", "download", "summary"]):
                            print(f"  Link {i}: text='{text}', id='{id_attr}', class='{class_attr}'")
                            if text == "Export Current Page" or "export" in text.lower():
                                export_current_page_el = link
                                
                # Let's try to trigger export in the new tab!
                # In OBIEE, at the bottom of the page there is usually a link containing "Export" or an icon
                # Let's see: we can click Page Options or check if there is an Export button in the table footer
                # Let's try clicking the "Page Options" button in the new tab first, if it exists
                options_btn = new_page.locator("#uberBar_dashboardpageoptions_image")
                if options_btn.count() > 0:
                    print("\nFound Page Options in new tab! Clicking it...")
                    options_btn.click()
                    time.sleep(2)
                else:
                    # In a single report view (which is what Go opens), there might be a direct "Export" link at the bottom!
                    # Let's look for any link containing the text "Export"
                    print("\nPage Options button not found in new tab. Looking for direct 'Export' link...")
                    export_link = new_page.locator("a:has-text('Export')").last
                    if export_link.count() > 0:
                        print("Found direct 'Export' link! Clicking it...")
                        export_link.click()
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
                        // Fallback: look for link containing Excel
                        const excel_target = Array.from(document.querySelectorAll("a, td")).find(el => el.textContent.trim().toLowerCase().includes("excel"));
                        if (excel_target) {
                            excel_target.click();
                            return true;
                        }
                        return false;
                    }
                """
                print("Attempting to trigger export in new tab and capture download...")
                with new_page.expect_download(timeout=60000) as download_info:
                    success = new_page.evaluate(js_trigger_dl)
                    if success:
                        print("Download triggered successfully in new tab!")
                    else:
                        print("Failed to click export link via JS in new tab.")
                        raise Exception("Export click failed")
                        
                download = download_info.value
                save_path = "abacavir_line_listing_real.xlsx"
                download.save_as(save_path)
                print(f"File downloaded and saved successfully to {save_path}!")
                
            except Exception as click_err:
                print(f"Error during tab capture/download: {click_err}")
                # Print first 1000 chars of new body text if we captured the page
                try:
                    print("\nNew tab body text preview (to debug):")
                    print(new_body_text[:1200])
                except:
                    pass
        else:
            print("Run link NOT found.")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
