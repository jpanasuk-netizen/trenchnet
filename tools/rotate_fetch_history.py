"""Rotate roster wallets for fetch-history with per-wallet budgets (free RPC)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trenchnet.config_load import load_roster, load_settings
from trenchnet.data_solana import SolanaRPC
from trenchnet.history import all_progress, fetch_wallet_history, history_dir, oldest_iso

def main():
    settings = load_settings()
    roster = load_roster()
    sol = settings.get("solana", {})
    raw_dir = ROOT / settings.get("paths", {}).get("raw_dir", "data/raw")
    hdir = history_dir(raw_dir)
    rpc = SolanaRPC(sol.get("rpc_url", "https://api.mainnet-beta.solana.com"), sleep_ms=int(sol.get("request_sleep_ms", 500)))
    wallets = list(roster.get("wallets") or [])
    # Doji first (known activity), Cented last (failed-tx spam tip)
    def rank(w):
        lab = (w.get("label") or "").lower()
        if lab == "doji":
            return (0, 0)
        if lab == "cented":
            return (2, 99)
        return (1, w.get("kolscan_rank_monthly") or 50)
    wallets.sort(key=rank)
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    max_tx = int(sys.argv[2]) if len(sys.argv) > 2 else 350
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    deadline = time.time() + 85 * 60
    print(f"ROTATING fetch raw={raw_dir} hdir={hdir} wallets={[w.get('label') for w in wallets]} pages={max_pages} tx={max_tx} rounds={rounds}", flush=True)
    for rnd in range(1, rounds + 1):
        if time.time() > deadline:
            print("DEADLINE reached", flush=True)
            break
        print(f"\n=== ROUND {rnd}/{rounds} ===", flush=True)
        all_done = True
        for w in wallets:
            if time.time() > deadline:
                break
            addr = w["address"]
            prev = (all_progress(hdir).get(addr)) or {}
            if prev.get("complete"):
                print(f"SKIP complete {w.get('label')} events={len(prev.get('events') or [])}", flush=True)
                continue
            all_done = False
            print(f"Fetching {w.get('label')} ({addr[:10]}...) pages<={max_pages} tx<={max_tx}", flush=True)
            res = fetch_wallet_history(
                rpc, addr, hdir / f"{addr}.json",
                max_pages=max_pages, max_tx=max_tx,
                log_fn=lambda m: print("  " + m, flush=True),
            )
            print("RESULT", json.dumps(res), flush=True)
        if all_done:
            print("All wallets complete.", flush=True)
            break
    print("\n=== STATUS ===", flush=True)
    prog = all_progress(hdir)
    for w in wallets:
        addr = w["address"]
        st = prog.get(addr) or {}
        print(json.dumps({
            "label": w.get("label"),
            "wallet": addr,
            "complete": st.get("complete"),
            "sigs_scanned": len(st.get("seen") or []),
            "pages": st.get("pages_fetched"),
            "txs_fetched": st.get("txs_fetched"),
            "events": len(st.get("events") or []),
            "oldest": oldest_iso(st.get("oldest_block_time")),
        }), flush=True)

if __name__ == "__main__":
    main()
