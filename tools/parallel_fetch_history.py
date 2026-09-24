"""PASS3 parallel history fetch — resume incomplete seeds across free RPCs."""
from __future__ import annotations
import json, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trenchnet.config_load import load_roster, load_settings
from trenchnet.history import fetch_wallet_history, history_dir, load_progress
from trenchnet.data_solana import SolanaRPC

LOG = ROOT / "out" / "fetch_history_pass3.log"
RPCS = [
    "https://solana-rpc.publicnode.com",
    "https://api.mainnet-beta.solana.com",
    "https://api.mainnet.solana.com",
]
MAX_WORKERS = 4
MAX_PAGES = 10
MAX_TX = 60

def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n"); f.flush()
    print(line, flush=True)

def run_one(wallet: dict, idx: int, hdir: Path) -> dict:
    url = RPCS[idx % len(RPCS)]
    rpc = SolanaRPC(url, sleep_ms=200)
    addr = wallet["address"]
    label = wallet.get("label") or addr[:8]
    cache = hdir / f"{addr}.json"
    st = load_progress(hdir, addr) or {}
    if st.get("complete"):
        log(f"SKIP_COMPLETE {label}")
        return {"wallet": addr, "label": label, "skipped": "complete"}
    pages = int(st.get("pages_fetched") or 0)
    ev = len(st.get("events") or [])
    lab = (label or "").lower()
    if lab == "theo" and pages >= 40 and ev == 0:
        log(f"SKIP_ZEROFILL {label} pages={pages}")
        return {"wallet": addr, "label": label, "skipped": "zero_fill"}
    if lab == "cented":
        log(f"SKIP_CENTED_MAIN {label} (use short probe)")
        return {"wallet": addr, "label": label, "skipped": "cented_deferred"}
    max_pages, max_tx = MAX_PAGES, MAX_TX
    if lab == "doji" and ev >= 30:
        max_pages, max_tx = 6, 40
    if lab == "decu" and pages >= 12 and ev == 0:
        log(f"SKIP_ZEROFILL {label} pages={pages}")
        return {"wallet": addr, "label": label, "skipped": "zero_fill"}
    if lab == "jijo" and pages >= 12 and ev == 0:
        # one more short push then stop
        max_pages, max_tx = 4, 30
    log(f"START {label} {addr[:12]}... rpc={url} resume_pages={pages} events={ev} caps={max_pages}/{max_tx}")
    try:
        res = fetch_wallet_history(
            rpc, addr, cache, max_pages=max_pages, max_tx=max_tx,
            log_fn=lambda m: log(f"  {m}"),
        )
        res["label"] = label
        res["rpc"] = url
        log(f"DONE {label} {json.dumps(res)}")
        return res
    except Exception as exc:
        log(f"FAIL {label}: {exc}\n{traceback.format_exc()}")
        return {"wallet": addr, "label": label, "error": str(exc)}

def main() -> int:
    settings = load_settings()
    roster = load_roster()
    raw = ROOT / (settings.get("paths") or {}).get("raw_dir", "data/raw")
    hdir = history_dir(raw)
    seeds = [w for w in (roster.get("wallets") or []) if (w.get("role") or "seed") == "seed"]
    def rank(w):
        lab = (w.get("label") or "").lower()
        addr = w["address"]
        st = load_progress(hdir, addr) or {}
        ev = len(st.get("events") or [])
        pages = int(st.get("pages_fetched") or 0)
        if lab == "cented": return (9, 99)
        if lab == "theo": return (8, 50)
        if not (hdir / f"{addr}.json").is_file(): return (0, lab)
        if ev == 0 and pages < 8: return (1, lab)
        if ev == 0: return (2, lab)
        if lab == "doji": return (4, 0)
        return (3, lab)
    seeds.sort(key=rank)
    log(f"PASS3E parallel fetch n={len(seeds)} workers={MAX_WORKERS} order={[w.get('label') for w in seeds]}")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(run_one, w, i, hdir): w for i, w in enumerate(seeds)}
        for fut in as_completed(futs):
            results.append(fut.result())
    log(f"ALL_DONE count={len(results)}")
    (ROOT / "out" / "fetch_history_pass3_summary.json").write_text(
        json.dumps(results, indent=2, default=str), encoding="utf-8"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
