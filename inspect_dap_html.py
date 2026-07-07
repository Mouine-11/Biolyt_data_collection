from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open("Safety & Pharmacovigilance/dap_rendered.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

print(f"HTML Length: {len(html)} chars")

print("\n--- Searching for 'Line Listing' in HTML text ---")
text_nodes = soup.find_all(text=True)
count = 0
for node in text_nodes:
    t = node.strip()
    if t and "line" in t.lower() and "list" in t.lower():
        print(f"Found match: '{t}' | parent tag: {node.parent.name} | parent class: {node.parent.get('class')}")
        count += 1
if count == 0:
    print("No direct 'Line Listing' text matches found.")

print("\n--- Printing first 50 links (a tags) in the rendered page ---")
links = soup.find_all("a")
print(f"Total links found: {len(links)}")
for i, a in enumerate(links[:50]):
    print(f"  Link {i}: text='{a.get_text(strip=True)}', href='{a.get('href')}', id='{a.get('id')}', class={a.get('class')}, onclick={a.get('onclick')}")

print("\n--- Searching for tabs or navigation elements ---")
# Dashboards typically use tabs. Let's search for class containing 'tab' or 'nav'
tab_elements = soup.find_all(class_=lambda c: c and any(k in str(c).lower() for k in ["tab", "nav", "menu"]))
print(f"Found {len(tab_elements)} elements with class containing 'tab', 'nav', or 'menu'.")
for i, el in enumerate(tab_elements[:20]):
    print(f"  El {i}: tag={el.name}, class={el.get('class')}, text='{el.get_text(strip=True)[:100]}'")
