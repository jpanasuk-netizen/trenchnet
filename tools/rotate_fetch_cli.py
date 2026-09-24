import json, subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
py = str(ROOT / ".venv" / "Scripts" / "python.exe")
sys.path.insert(0, str(ROOT))
from trenchnet.config_load import load_roster
wallets = list(load_roster()["wallets"])
def rank(w):
    lab = (w.get("label") or "").lower()
    if lab == "doji": return (0, 0)
    if lab == "cented": return (2, 99)
    return (1, w.get("kolscan_rank_monthly") or 50)
wallets.sort(key=rank)
max_pages, max_tx, rounds = 20, 250, 15
deadline = time.time() + 85 * 60
log = ROOT / "out" / "fetch_history_pass2.log"
def append(msg):
    with log.open("a", encoding="utf-8") as f:
        f.write(msg + "\n"); f.flush()
        print(msg, flush=True)
append(f"START {time.strftime('%Y-%m-%dT%H:%M:%S')} order={[w.get('label') for w in wallets]}")
for rnd in range(1, rounds+1):
    if time.time() > deadline:
        append("DEADLINE"); break
    append(f"=== ROUND {rnd} ===")
    for w in wallets:
        if time.time() > deadline: break
        append(f"wallet {w.get('label')} {w['address']}")
        cmd = [py, "-u", "-m", "trenchnet.cli", "fetch-history", "--wallet", w["address"], "--max-pages", str(max_pages), "--max-tx", str(max_tx)]
        with log.open("a", encoding="utf-8") as f:
            p = subprocess.run(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT, text=True)
        append(f"rc={p.returncode}")
    # quick status dump
    st = subprocess.run([py, "-u", "-m", "trenchnet.cli", "history-status"], cwd=str(ROOT), capture_output=True, text=True)
    append(st.stdout)
append("DONE")
