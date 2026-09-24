from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(r"C:\Users\jpana\Documents\HermesTools\trenchnet\out")
BASE = "http://127.0.0.1:8791/live"
def shot(path, w=3440, h=1440):
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page(viewport={"width": w, "height": h})
        page.goto(BASE, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(4000)
        st = page.evaluate("""() => document.getElementById('armBadge')?.textContent || ''""")
        print("armBadge", st)
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=False)
        b.close()
        print("wrote", path, path.stat().st_size)
shot(OUT / "live_disarmed_3440.png")
print("LIVE_SHOT_OK")
