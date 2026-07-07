import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Tab Navigation Test...")
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
        
        # Find the div containing "Line Listing"
        div = page.locator("div:has-text('Line Listing')").first
        if div.count() > 0:
            print("Found 'Line Listing' div!")
            
            # Let's inspect the hierarchy of this div
            js_inspect = """
                (el) => {
                    let info = [];
                    let curr = el;
                    for (let i = 0; i < 4; i++) {
                        if (!curr) break;
                        info.push({
                            depth: i,
                            tagName: curr.tagName,
                            id: curr.id,
                            className: curr.className,
                            onClick: curr.getAttribute('onclick'),
                            href: curr.getAttribute('href')
                        });
                        curr = curr.parentElement;
                    }
                    return info;
                }
            """
            hierarchy = div.evaluate(js_inspect)
            print("\nElement Hierarchy:")
            for item in hierarchy:
                print(f"  Depth {item['depth']}: <{item['tagName']}> id='{item['id']}', class='{item['className']}', onclick='{item['onClick']}', href='{item['href']}'")
                
            # Let's attempt to click the elements in the hierarchy to see which one triggers the tab switch.
            # In OBIEE, the actual clickable element is usually the anchor <a> or cell <td> that wraps the div.
            # Let's find if there is an <a> or <td> at depth 1 or 2.
            # Let's try clicking the div first, but let's do it via JS click on the element that has an onclick or is an <a>.
            print("\nClicking the parent elements to trigger tab switch...")
            
            # Let's evaluate a script that clicks the <a> or <td> wrapper in the page
            js_click_tab = """
                (el) => {
                    // Traverse up to find a link or a table cell that acts as the tab trigger
                    let curr = el;
                    while (curr && curr.tagName !== 'BODY') {
                        if (curr.tagName === 'A' || curr.tagName === 'TD' && curr.className.includes('Tab')) {
                            curr.click();
                            return curr.tagName + " clicked";
                        }
                        curr = curr.parentElement;
                    }
                    // Fallback: click the element itself
                    el.click();
                    return "self clicked";
                }
            """
            result = div.evaluate(js_click_tab)
            print(f"Tab click action: {result}")
            
            print("Waiting 20 seconds for the Line Listing tab content to load...")
            time.sleep(20)
            
            # Verify if we are on the Line Listing tab
            body_text = page.locator("body").inner_text()
            print(f"\nBody text length after tab click: {len(body_text)} chars")
            
            # Check for line listing headers
            headers_to_check = ["Safety Report ID", "Report ID", "Local Report Number", "Reaction Seriousness", "Suspect Drug"]
            found_headers = [h for h in headers_to_check if h.lower() in body_text.lower()]
            print(f"Found Line Listing headers: {found_headers}")
            
            if len(found_headers) > 0:
                print("SUCCESS: Successfully switched to the Line Listing tab!")
                
                # Let's trigger the export menu and see if it changes
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
                with page.expect_download(timeout=60000) as download_info:
                    success = page.evaluate(js_trigger_dl)
                    if success:
                        print("Download triggered!")
                    else:
                        print("Could not trigger download.")
                        
                download = download_info.value
                save_path = "abacavir_line_listing_real.xlsx"
                download.save_as(save_path)
                print(f"Saved real line listing to {save_path}")
                
            else:
                print("FAILURE: Did not switch to the Line Listing tab. Body text preview:")
                print(body_text[:1000])
                
        else:
            print("Line Listing tab div not found.")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
