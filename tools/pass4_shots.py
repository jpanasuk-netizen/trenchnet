"""Pass4 full-page screenshots via Playwright."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "out"
BASE = "http://127.0.0.1:8791"

def shot(path, out, w, h, full=True, wait_ms=3500, click=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(BASE + path, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(wait_ms)
        if click:
            try:
                page.locator(click).first.click(timeout=8000)
                page.wait_for_timeout(2000)
            except Exception as e:
                print("click_skip", e)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=full)
        browser.close()
        print("wrote", out.name, out.stat().st_size)

def main():
    for w, name in [(1280, "pass4_dashboard_1280.png"), (1920, "pass4_dashboard_1920.png"), (3440, "pass4_dashboard_3440.png")]:
        h = 1440 if w >= 1920 else 900
        shot("/", OUT / name, w, h, full=True, wait_ms=4000)
    shot("/", OUT / "pass4_graph_3440.png", 3440, 1440, full=False, wait_ms=4500, click="text=Graph")

if __name__ == "__main__":
    main()
