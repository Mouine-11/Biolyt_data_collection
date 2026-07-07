from bs4 import BeautifulSoup
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open("Safety & Pharmacovigilance/adr_search.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")

# Find the A-Z elements
# Let's search for links with text 'A', 'B', 'C', etc.
print("A-Z links and their attributes:")
for a in soup.find_all("a"):
    text = a.get_text(strip=True)
    if len(text) == 1 and text.isupper() and a.get("href") == "#":
        print(f"Link: {text}, ID: {a.get('id')}, Class: {a.get('class')}, Onclick: {a.get('onclick')}, Title: {a.get('title')}, Parent: {a.parent.name}, Attributes: {a.attrs}")
    elif text == "0-9" and a.get("href") == "#":
        print(f"Link: {text}, ID: {a.get('id')}, Class: {a.get('class')}, Onclick: {a.get('onclick')}, Title: {a.get('title')}, Parent: {a.parent.name}, Attributes: {a.attrs}")

# Also let's find script tags to see what JS files are loaded
print("\nScript tags:")
for s in soup.find_all("script"):
    src = s.get("src")
    if src:
        print(f"  External Script: {src}")
    else:
        print(f"  Inline Script (first 200 chars): {s.get_text()[:200].strip()}")
