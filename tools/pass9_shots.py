"""Pass 9 screenshots: default Overview; blur My Wallet card (address privacy)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(r"C:\Users\jpana\Documents\HermesTools\trenchnet\out")
BASE = "http://127.0.0.1:8791/"

def shot(path: Path, w: int, h: int, full: bool = False, wait_ms: int = 7000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": w, "height": h})
        page = context.new_page()
        page.goto(BASE, wait_until="domcontentloaded", timeout=120000)
        page.evaluate("""() => {
          try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}
          if (location.hash) history.replaceState(null, '', location.pathname + location.search);
        }""")
        page.goto(BASE, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(wait_ms)
        # Wait for wallet card, then blur/mask for screenshot privacy
        try:
            page.locator("#myWalletCard").first.wait_for(timeout=15000)
            page.evaluate("""() => {
              const el = document.getElementById('myWalletCard');
              if (el) {
                el.classList.add('blurForShot');
                el.style.filter = 'blur(10px)';
                el.style.opacity = '0.5';
                // also scrub any text nodes that might contain long base58
                el.querySelectorAll('.v').forEach(n => {
                  if ((n.textContent||'').length > 20) n.textContent = 'E8xo…xa77';
                });
              }
            }""")
            page.wait_for_timeout(400)
        except Exception as e:
            print("wallet_card_wait", e)
        st = page.evaluate("""() => {
          const T = window.TrenchInteractive || {};
          const s = T.state || {};
          return {
            layout: s.layout, tab: s.tab,
            delay: (s.backtest||{}).delay, sizeSol: (s.backtest||{}).sizeSol,
            hasCopydesk: !!document.getElementById('copydeskPanel'),
            hasReset: !!document.getElementById('btnResetView'),
            hasWallet: !!document.getElementById('myWalletCard'),
            hasNowStrip: !!document.getElementById('nowStrip'),
          };
        }""")
        print("STATE", st)
        assert st["layout"] == "columns" and st["tab"] == "overview"
        assert st["delay"] == 60 and st["sizeSol"] == 0.25
        assert st["hasCopydesk"] and st["hasReset"] and st["hasWallet"]
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=full)
        browser.close()
        print("wrote", path.name, path.stat().st_size)

shot(OUT / "pass9_default_overview_3440.png", 3440, 1440, full=False, wait_ms=9000)
shot(OUT / "pass9_default_overview_1920.png", 1920, 1080, full=False, wait_ms=7000)
shot(OUT / "pass9_wallet_blurred_3440.png", 3440, 1440, full=False, wait_ms=8000)
print("PASS9_SHOTS_OK")
