"""Pass 9 screenshots: default Overview (no hash, cleared localStorage)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(r"C:\Users\jpana\Documents\HermesTools\trenchnet\out")
BASE = "http://127.0.0.1:8791/"

def shot(path: Path, w: int, h: int, full: bool = False, wait_ms: int = 7000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": w, "height": h})
        page = context.new_page()
        # Clear storage before first navigation
        page.goto(BASE, wait_until="domcontentloaded", timeout=120000)
        page.evaluate("""() => {
          try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}
          if (location.hash) history.replaceState(null, '', location.pathname + location.search);
        }""")
        page.goto(BASE, wait_until="networkidle", timeout=120000)
        page.wait_for_timeout(wait_ms)
        # Assert default state
        st = page.evaluate("""() => {
          const T = window.TrenchInteractive || {};
          const s = T.state || {};
          return {
            hash: location.hash || '',
            layout: s.layout,
            tab: s.tab,
            delay: (s.backtest||{}).delay,
            sizeSol: (s.backtest||{}).sizeSol,
            slipMult: (s.backtest||{}).slipMult,
            tp: (s.backtest||{}).tp,
            sl: (s.backtest||{}).sl,
            tstop: (s.backtest||{}).tstop,
            mode: (s.backtest||{}).mode,
            hasCopydesk: !!document.getElementById('copydeskPanel'),
            copydeskDisplay: (document.getElementById('copydeskPanel')||{}).style?.display,
            hasNowStrip: !!document.getElementById('nowStrip'),
            hasReset: !!document.getElementById('btnResetView'),
            ls: (()=>{ try { return localStorage.getItem('trenchnet_view_v1'); } catch(e){ return null; } })(),
          };
        }""")
        print("STATE", st)
        assert st["layout"] == "columns", st
        assert st["tab"] == "overview", st
        assert st["delay"] == 60, st
        assert st["sizeSol"] == 0.25, st
        assert st["hasCopydesk"], st
        assert st["hasReset"], st
        assert not st["hash"] or "overview" in st["hash"], st
        try:
            page.locator("#copydeskPanel").first.wait_for(timeout=10000)
            page.locator("#cdeskLead").first.wait_for(timeout=10000)
        except Exception as e:
            print("copydesk_wait", e)
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=full)
        browser.close()
        print("wrote", path.name, path.stat().st_size)

shot(OUT / "pass9_default_overview_3440.png", 3440, 1440, full=False, wait_ms=8000)
shot(OUT / "pass9_default_overview_1920.png", 1920, 1080, full=False, wait_ms=7000)
shot(OUT / "pass9_default_overview_full.png", 1920, 1080, full=True, wait_ms=7000)
print("PASS9_SHOTS_OK")
