import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

# Abacavir dashboard link
url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting Tab Element Discovery...")
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
        
        # We will run a script inside the browser to find all elements containing 'Line Listing'
        js_find_all = """
            () => {
                let results = [];
                let walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, null, false);
                let node;
                while (node = walker.nextNode()) {
                    // Check if this node has direct text child containing 'Line Listing'
                    let hasDirectText = false;
                    for (let child of node.childNodes) {
                        if (child.nodeType === Node.TEXT_NODE && child.nodeValue.trim() === 'Line Listing') {
                            hasDirectText = true;
                            break;
                        }
                    }
                    if (hasDirectText) {
                        // Get parent chain
                        let parentChain = [];
                        let p = node;
                        for (let i = 0; i < 4; i++) {
                            if (!p) break;
                            parentChain.push({
                                tagName: p.tagName,
                                id: p.id,
                                className: p.className
                            });
                            p = p.parentElement;
                        }
                        results.push({
                            tagName: node.tagName,
                            id: node.id,
                            className: node.className,
                            parentChain: parentChain
                        });
                    }
                }
                return results;
            }
        """
        
        matches = page.evaluate(js_find_all)
        print(f"\nFound {len(matches)} elements containing 'Line Listing' as direct text:")
        for idx, m in enumerate(matches):
            print(f"\nMatch {idx}: <{m['tagName']}> id='{m['id']}', class='{m['className']}'")
            print("  Parent Chain:")
            for depth, p in enumerate(m['parentChain']):
                print(f"    Depth {depth}: <{p['tagName']}> id='{p['id']}', class='{p['className']}'")
                
        browser.close()
        print("\nDiscovery finished.")

except Exception as e:
    print(f"An error occurred: {e}")
