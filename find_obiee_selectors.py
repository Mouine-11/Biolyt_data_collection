import sys
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

url = "https://dap.ema.europa.eu/analyticsSOAP/saw.dll?PortalPages&PortalPath=%2Fshared%2FPHV%20DAP%2F_portal%2FDAP&Action=Navigate&P0=1&P1=eq&P2=%22Line%20Listing%20Objects%22.%22Substance%20High%20Level%20Code%22&P3=1+18853"

print("Starting OBIEE Selector Discovery...")
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
        
        print("Waiting 15 seconds for dashboard to fully render...")
        time.sleep(15)
        
        print(f"Title: {page.title()}")
        print(f"URL: {page.url}")
        
        # 1. Search for Tabs
        print("\n--- 1. SEARCHING FOR DASHBOARD TABS ---")
        # In OBIEE, tabs are usually table cells or links at the top of the dashboard
        # Let's find elements that contain text like "Line Listing", "Summary", "Reaction"
        potential_tabs = []
        for text in ["Line Listing", "Summary", "Reactions", "Seriousness", "Cases"]:
            locators = page.locator(f"text={text}").all()
            for loc in locators:
                try:
                    tag_name = loc.evaluate("el => el.tagName")
                    id_attr = loc.evaluate("el => el.id")
                    class_attr = loc.evaluate("el => el.className")
                    inner_text = loc.inner_text().strip()
                    print(f"Match for '{text}': <{tag_name}> text='{inner_text}', id='{id_attr}', class='{class_attr}'")
                    potential_tabs.append(loc)
                except Exception as e:
                    pass
                    
        # 2. Search for Page Options / Gear menu
        print("\n--- 2. SEARCHING FOR PAGE OPTIONS / MENU BUTTONS ---")
        # Let's search for elements with title "Page Options" or containing options/menu
        all_links = page.query_selector_all("a")
        all_buttons = page.query_selector_all("button")
        all_imgs = page.query_selector_all("img")
        
        print(f"Total: Links={len(all_links)}, Buttons={len(all_buttons)}, Images={len(all_imgs)}")
        
        for l in all_links:
            title = l.get_attribute("title") or ""
            text = l.inner_text().strip()
            id_attr = l.get_attribute("id") or ""
            class_attr = l.get_attribute("class") or ""
            if "option" in title.lower() or "menu" in title.lower() or "option" in text.lower() or "menu" in text.lower() or "page options" in title.lower() or "page options" in text.lower():
                print(f"Link Option: text='{text}', title='{title}', id='{id_attr}', class='{class_attr}'")
                
        for img in all_imgs:
            title = img.get_attribute("title") or ""
            alt = img.get_attribute("alt") or ""
            id_attr = img.get_attribute("id") or ""
            class_attr = img.get_attribute("class") or ""
            if "option" in title.lower() or "menu" in title.lower() or "option" in alt.lower() or "menu" in alt.lower() or "page options" in title.lower():
                print(f"Image Option: title='{title}', alt='{alt}', id='{id_attr}', class='{class_attr}'")

        # 3. Search for Export elements
        print("\n--- 3. SEARCHING FOR EXPORT / DOWNLOAD ELEMENTS ---")
        # Let's search for any element containing 'Export' or 'Download'
        for text in ["Export", "Download"]:
            locators = page.locator(f"text={text}").all()
            for loc in locators:
                try:
                    tag_name = loc.evaluate("el => el.tagName")
                    id_attr = loc.evaluate("el => el.id")
                    class_attr = loc.evaluate("el => el.className")
                    inner_text = loc.inner_text().strip()
                    print(f"Match for '{text}': <{tag_name}> text='{inner_text}', id='{id_attr}', class='{class_attr}'")
                except Exception as e:
                    pass

        browser.close()
        print("\nDiscovery finished.")

except Exception as e:
    print(f"An error occurred: {e}")
