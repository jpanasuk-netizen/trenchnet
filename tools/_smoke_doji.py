from pathlib import Path
from trenchnet.config_load import load_roster, load_settings
from trenchnet.data_solana import SolanaRPC
from trenchnet.history import fetch_wallet_history, history_dir

s = load_settings()
r = load_roster()
doji = next(w for w in r["wallets"] if w["label"].lower() == "doji")
rpc = SolanaRPC(s["solana"]["rpc_url"], sleep_ms=400)
hdir = history_dir(Path("data/raw"))
print("Doji", doji["address"])
res = fetch_wallet_history(
    rpc, doji["address"], hdir / f"{doji['address']}.json",
    max_pages=1, max_tx=20, log_fn=print,
)
print("RES", res)
