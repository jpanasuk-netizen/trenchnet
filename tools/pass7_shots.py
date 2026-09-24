"""Pass 7 screenshots via Playwright."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "out"
BASE = "http://127.0.0.1:8791"

def shot(path, out, w, h, full=True, wait_ms=4500, click=None, after=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(BASE + path, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(wait_ms)
        if click:
            try:
                page.locator(click).first.click(timeout=8000)
                page.wait_for_timeout(2500)
            except Exception as e:
                print("click_skip", click, e)
        if after:
            after(page)
        out.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out), full_page=full)
        browser.close()
        print("wrote", out.name, out.stat().st_size)

def main():
    # full-page dashboard at three widths
    for w, name in [(1280, "pass7_dashboard_1280.png"), (1920, "pass7_dashboard_1920.png"), (3440, "pass7_dashboard_3440.png")]:
        h = 1440 if w >= 1920 else 900
        shot("/", OUT / name, w, h, full=True, wait_ms=5000)
    # Top Pick focused (viewport of card area)
    shot("/", OUT / "pass7_toppick_3440.png", 3440, 1440, full=False, wait_ms=5000,
         after=lambda page: page.locator("#topPickCard").first.scroll_into_view_if_needed())
    # Coin Desk tab
    shot("/", OUT / "pass7_coindesk_3440.png", 3440, 1440, full=True, wait_ms=4000,
         click='button.tabBtn[data-tab="coindesk"]')
    # also 1920/1280 full pages already cover; extra coindesk at those widths
    for w, name in [(1920, "pass7_coindesk_1920.png"), (1280, "pass7_coindesk_1280.png")]:
        h = 1440 if w >= 1920 else 900
        shot("/", OUT / name, w, h, full=True, wait_ms=3500, click='button.tabBtn[data-tab="coindesk"]')
    for w, name in [(1920, "pass7_toppick_1920.png"), (1280, "pass7_toppick_1280.png")]:
        h = 1440 if w >= 1920 else 900
        shot("/", OUT / name, w, h, full=False, wait_ms=3500,
             after=lambda page: page.locator("#topPickCard").first.scroll_into_view_if_needed())

if __name__ == "__main__":
    main()
