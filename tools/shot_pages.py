from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / 'out'
BASE = 'http://127.0.0.1:8791'

def shot(url_path, out, width, height, full=True, wait_ms=3500, selector=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': width, 'height': height})
        page.goto(BASE + url_path, wait_until='networkidle', timeout=90000)
        page.wait_for_timeout(wait_ms)
        if selector:
            try:
                page.locator(selector).first.click(timeout=8000)
                page.wait_for_timeout(2000)
            except Exception as e:
                print('click skip', selector, e)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=full)
        browser.close()
        print('wrote', out.name, out.stat().st_size)

def main():
    for w, name in [(1280, 'dashboard_full_1280.png'), (1920, 'dashboard_full_1920.png'), (3440, 'dashboard_full_3440.png')]:
        h = 1440 if w >= 1920 else 900
        shot('/', OUT / name, w, h, full=True, wait_ms=4000)
    shot('/', OUT / 'graph_3440.png', 3440, 1440, full=False, wait_ms=4500, selector='text=Graph')
    shot('/live', OUT / 'live_page.png', 1440, 1100, full=True, wait_ms=3000)

if __name__ == '__main__':
    main()
