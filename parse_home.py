import sys
from bs4 import BeautifulSoup

# Reconfigure stdout to use UTF-8
sys.stdout.reconfigure(encoding='utf-8')

with open("Safety & Pharmacovigilance/adr_homepage.html", "r", encoding="utf-8") as f:
    html = f.read()

soup = BeautifulSoup(html, "html.parser")
print("All links in homepage:")
for a in soup.find_all("a"):
    href = a.get("href")
    text = a.get_text(strip=True)
    if href:
        print(f"  {text} -> {href}")
