from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(r"C:\Users\jpana\Documents\HermesTools\trenchnet\out")
BASE = "http://127.0.0.1:8791"
def shot(out, w, h, full=True, wait_ms=5000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(BASE + "/", wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(wait_ms)
        # ensure panel visible
        try:
            page.locator("#hotTakesPanel").first.wait_for(timeout=8000)
            page.evaluate("document.getElementById('hotTakesPanel')?.classList.remove('collapsed')")
            page.wait_for_timeout(800)
        except Exception as e:
            print("panel_wait", e)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=full)
        browser.close()
        print("wrote", out.name, out.stat().st_size)
shot(OUT / "pass8_hottakes_3440.png", 3440, 1440, full=False, wait_ms=6000)
shot(OUT / "pass8_hottakes_1920.png", 1920, 1080, full=False, wait_ms=5000)
