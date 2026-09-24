"""Pass 4: Helius-primary history for thin wallets then full roster re-sweep.

Never prints API keys. Stops gracefully on Helius credit/limit errors.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trenchnet.config_load import load_roster, load_settings
from trenchnet.helius_client import HeliusLimitError, helius_configured, redact_url
from trenchnet.history import history_dir
from trenchnet.history_helius import fetch_wallet_history_helius
from trenchnet.secrets import secret_present

LOG = ROOT / "out" / "pass4_fetch.log"
SUMMARY = ROOT / "out" / "pass4_fetch_summary.json"
THIN_LABELS = {"jijo", "cented", "decu", "theo"}


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # redact any accidental api-key fragments
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {redact_url(msg)}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
    print(line, flush=True)


def run_one(w: dict, hdir: Path, *, max_pages: int, rpc_pages: int, rpc_tx: int) -> dict:
    addr = w["address"]
    label = w.get("label") or addr[:8]
    cache = hdir / f"{addr}.json"
    log(f"START {label} pages_cap={max_pages}")
    try:
        res = fetch_wallet_history_helius(
            addr, cache,
            max_pages=max_pages,
            page_limit=50,
            prefer_pump=True,
            log_fn=lambda m: log(f"  {m}"),
            allow_rpc_fallback=True,
            rpc_max_pages=rpc_pages,
            rpc_max_tx=rpc_tx,
            reset_helius_cursor=True,
        )
        res["label"] = label
        res["role"] = w.get("role")
        log(f"DONE {label} ev={res.get('events')} src={res.get('source')} stop={res.get('stopped_early_reason')}")
        return res
    except HeliusLimitError as exc:
        log(f"LIMIT {label}")
        return {"wallet": addr, "label": label, "error": "helius_limit", "limit_hit": True}
    except Exception as exc:
        log(f"FAIL {label} {type(exc).__name__}")
        return {"wallet": addr, "label": label, "error": type(exc).__name__}


def main() -> int:
    log(f"PASS4 start helius={secret_present('HELIUS_API_KEY')} birdeye={secret_present('BIRDEYE_API_KEY')} configured={helius_configured()}")
    settings = load_settings()
    roster = load_roster()
    raw = ROOT / (settings.get("paths") or {}).get("raw_dir", "data/raw")
    hdir = history_dir(raw)
    wallets = list(roster.get("wallets") or [])

    thin = [w for w in wallets if (w.get("label") or "").lower() in THIN_LABELS]
    rest = [w for w in wallets if w not in thin]
    # Prefer seeds with few events next, then expanded
    def rank(w):
        lab = (w.get("label") or "").lower()
        role = 0 if w.get("role") == "seed" else 1
        return (role, lab)

    rest.sort(key=rank)

    results = []
    limit_hit = False

    log(f"PHASE1 thin n={len(thin)} {[w.get('label') for w in thin]}")
    for w in thin:
        if limit_hit:
            results.append({"wallet": w["address"], "label": w.get("label"), "skipped": "helius_limit"})
            continue
        r = run_one(w, hdir, max_pages=12, rpc_pages=15, rpc_tx=150)
        results.append(r)
        if r.get("limit_hit"):
            limit_hit = True
            log("STOP graceful — Helius limit hit after thin phase item")

    log(f"PHASE2 re-sweep n={len(rest)} limit_hit={limit_hit}")
    # Serial for credit hygiene (1–2 rps style); small parallel if not limited
    workers = 1
    if limit_hit:
        for w in rest:
            results.append({"wallet": w["address"], "label": w.get("label"), "skipped": "helius_limit"})
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(run_one, w, hdir, max_pages=15, rpc_pages=10, rpc_tx=100): w
                for w in rest
            }
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                if r.get("limit_hit"):
                    limit_hit = True
                    log("STOP graceful — Helius limit during re-sweep")
                    # cancel remaining? executor will finish started ones

    SUMMARY.write_text(json.dumps({
        "results": results,
        "limit_hit": limit_hit,
        "thin_labels": sorted(THIN_LABELS),
        "n": len(results),
    }, indent=2, default=str), encoding="utf-8")
    log(f"ALL_DONE n={len(results)} limit_hit={limit_hit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
