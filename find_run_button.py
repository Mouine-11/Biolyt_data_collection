import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Run Button Discovery...")
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
        
        # Search for buttons, links, and inputs that could be the "Run" button
        print("\n--- Searching for 'Run' or 'Report' or 'Submit' elements ---")
        
        # Let's search inside the page via JS
        js_find_buttons = """
            () => {
                let results = [];
                // Find all clickable elements: buttons, inputs, links, cells
                let clickables = document.querySelectorAll("button, input[type='button'], input[type='submit'], a, td, div");
                for (let el of clickables) {
                    let text = el.textContent.trim();
                    let val = el.value || "";
                    let id = el.id || "";
                    let cls = el.className || "";
                    let title = el.getAttribute("title") || "";
                    
                    let combined = (text + " " + val + " " + id + " " + cls + " " + title).toLowerCase();
                    if (combined.includes("run") || combined.includes("submit") || combined.includes("report") || combined.includes("query") || combined.includes("listing")) {
                        // Avoid very long parent texts
                        if (text.length < 100) {
                            results.push({
                                tagName: el.tagName,
                                id: id,
                                className: cls,
                                text: text,
                                value: val,
                                title: title
                            });
                        }
                    }
                }
                return results;
            }
        """
        
        buttons = page.evaluate(js_find_buttons)
        print(f"Found {len(buttons)} potential clickable elements:")
        for idx, btn in enumerate(buttons):
            print(f"  Element {idx}: <{btn['tagName']}> id='{btn['id']}', class='{btn['className']}', text='{btn['text']}', value='{btn['value']}', title='{btn['title']}'")
            
        # Let's try to find a button with text "Run Line Listing Report" or similar
        # In Playwright, we can click it directly if it exists
        print("\nLooking for 'Run Line Listing Report' button specifically...")
        # Let's search for a button/link/input with text 'Run Line Listing Report'
        run_btn = None
        for text in ["Run Line Listing Report", "Run Report", "Run", "Submit", "Line Listing"]:
            loc = page.get_by_text(text, exact=True).first
            if loc.count() > 0:
                print(f"Found exact match for '{text}'! TagName: {loc.evaluate('el => el.tagName')}")
                run_btn = loc
                break
                
        if not run_btn:
            # Try containing text
            for text in ["Run Line Listing Report", "Run Report", "Run", "Submit"]:
                loc = page.locator(f"text={text}").first
                if loc.count() > 0:
                    print(f"Found partial match for '{text}'! Text: '{loc.inner_text()}', Tag: {loc.evaluate('el => el.tagName')}")
                    run_btn = loc
                    break
                    
        if run_btn:
            print("\nClicking the Run button...")
            run_btn.click()
            print("Clicked! Waiting 20 seconds for the query to run and table to load...")
            time.sleep(20)
            
            # Verify body text
            body_text = page.locator("body").inner_text()
            print(f"Body text length after click: {len(body_text)} chars")
            headers_to_check = ["Safety Report ID", "Report ID", "Local Report Number", "Reaction Seriousness", "Suspect Drug"]
            found_headers = [h for h in headers_to_check if h.lower() in body_text.lower()]
            print(f"Found Line Listing headers: {found_headers}")
            
            if len(found_headers) > 0:
                print("SUCCESS: Line Listing table successfully loaded!")
                # Let's take a screenshot or print first 1000 chars of body
                print("Body text preview (first 1000 chars):")
                print(body_text[:1000])
            else:
                print("FAILURE: Did not load the table. Body text preview:")
                print(body_text[:1000])
        else:
            print("Could not find any Run button.")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
