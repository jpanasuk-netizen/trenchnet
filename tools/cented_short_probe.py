"""Short Cented probe — errspam-safe, free RPC, tiny caps."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trenchnet.config_load import load_roster, load_settings
from trenchnet.history import fetch_wallet_history, history_dir
from trenchnet.data_solana import SolanaRPC

def main():
    roster = load_roster()
    settings = load_settings()
    raw = ROOT / (settings.get("paths") or {}).get("raw_dir", "data/raw")
    hdir = history_dir(raw)
    w = next(x for x in roster["wallets"] if (x.get("label") or "").lower() == "cented")
    addr = w["address"]
    cache = hdir / f"{addr}.json"
    rpc = SolanaRPC("https://api.mainnet.solana.com", sleep_ms=400)
    print("CENTED_PROBE start", flush=True)
    res = fetch_wallet_history(rpc, addr, cache, max_pages=3, max_tx=20, log_fn=print)
    print(json.dumps(res, indent=2))
    (ROOT / "out" / "cented_probe.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
