import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Run Button Inspection...")
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
            print("Found the link!")
            # Get attributes
            js_inspect = """
                (el) => {
                    return {
                        tagName: el.tagName,
                        id: el.id,
                        className: el.className,
                        href: el.getAttribute('href'),
                        onclick: el.getAttribute('onclick'),
                        parentTagName: el.parentElement ? el.parentElement.tagName : '',
                        parentClassName: el.parentElement ? el.parentElement.className : '',
                        grandParentTagName: el.parentElement && el.parentElement.parentElement ? el.parentElement.parentElement.tagName : ''
                    };
                }
            """
            attrs = run_link.evaluate(js_inspect)
            print(f"Link Attributes: {attrs}")
            
            # Let's try multiple click methods and see if the page changes!
            # Method 1: JS Click
            print("\nMethod 1: Triggering JS click...")
            run_link.evaluate("el => el.click()")
            
            print("Waiting 5 seconds...")
            time.sleep(5)
            
            body_text = page.locator("body").inner_text()
            print(f"Body text length after JS click: {len(body_text)} chars")
            if "retrieving" in body_text.lower() or "loading" in body_text.lower() or "safety report id" in body_text.lower():
                print("JS Click succeeded in triggering the query!")
            else:
                print("JS Click did not trigger query. Let's try Method 2...")
                
                # Method 2: Dispatched click event
                print("\nMethod 2: Dispatching custom click event...")
                run_link.evaluate("""el => {
                    el.dispatchEvent(new MouseEvent('click', {
                        bubbles: true,
                        cancelable: true,
                        view: window
                    }));
                }""")
                
                print("Waiting 5 seconds...")
                time.sleep(5)
                
                body_text = page.locator("body").inner_text()
                print(f"Body text length after custom dispatch: {len(body_text)} chars")
                if "retrieving" in body_text.lower() or "loading" in body_text.lower() or "safety report id" in body_text.lower():
                    print("Custom dispatch click succeeded!")
                else:
                    print("Custom dispatch failed. Let's check if there is an onclick handler we can call directly.")
                    if attrs['onclick']:
                        print(f"Found onclick handler: {attrs['onclick']}")
                        # We can evaluate the onclick script directly!
                        # Often in OBIEE it is something like 'return false;' or calling a JS function.
                        # If it is 'return false;', the actual handler is bound via jQuery or event listener.
                    
                    # Let's write the HTML of the parent element for review
                    parent_html = run_link.evaluate("el => el.parentElement.outerHTML")
                    print("\nParent Element HTML:")
                    print(parent_html[:1000])
        else:
            print("Link NOT found.")
            
        browser.close()
        print("Done!")

except Exception as e:
    print(f"An error occurred: {e}")
