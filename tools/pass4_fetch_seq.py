"""Pass 4 sequential Helius-primary fetch. Never prints API keys."""
from __future__ import annotations
import json, sys, time
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
THIN = ["Cented", "theo", "Jijo", "decu"]

def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {redact_url(msg)}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n"); f.flush()
    print(line, flush=True)

def main() -> int:
    log(f"PASS4SEQ helius={secret_present('HELIUS_API_KEY')} birdeye={secret_present('BIRDEYE_API_KEY')} cfg={helius_configured()}")
    settings = load_settings()
    roster = load_roster()
    raw = ROOT / (settings.get("paths") or {}).get("raw_dir", "data/raw")
    hdir = history_dir(raw)
    by_label = {(w.get("label") or ""): w for w in roster.get("wallets") or []}
    thin = [by_label[l] for l in THIN if l in by_label]
    rest = [w for w in roster.get("wallets") or [] if (w.get("label") or "") not in THIN]
    results = []
    limit_hit = False

    def run(w, max_pages, rpc_pages, rpc_tx):
        nonlocal limit_hit
        addr = w["address"]; label = w.get("label") or addr[:8]
        if limit_hit:
            return {"wallet": addr, "label": label, "skipped": "helius_limit"}
        cache = hdir / f"{addr}.json"
        if cache.is_file():
            import json as _json
            _st = _json.loads(cache.read_text(encoding="utf-8"))
            if _st.get("skip_rpc_zerofill") or _st.get("stopped_early_reason") == "zero_fill_skip":
                log(f"SKIP_ZEROFILL {label}")
                return {"wallet": addr, "label": label, "skipped": "zero_fill", "events": len(_st.get("events") or [])}
        log(f"START {label} cap={max_pages}")
        try:
            res = fetch_wallet_history_helius(
                addr, hdir / f"{addr}.json",
                max_pages=max_pages, page_limit=40, prefer_pump=True,
                log_fn=lambda m: log(f"  {m}"),
                allow_rpc_fallback=True, rpc_max_pages=rpc_pages, rpc_max_tx=rpc_tx,
                reset_helius_cursor=True,
            )
            res["label"] = label
            res["role"] = w.get("role")
            log(f"DONE {label} ev={res.get('events')} src={res.get('source')} stop={res.get('stopped_early_reason')}")
            if res.get("limit_hit"):
                limit_hit = True
                log("LIMIT graceful stop")
            return res
        except HeliusLimitError:
            limit_hit = True
            log(f"LIMIT {label}")
            return {"wallet": addr, "label": label, "limit_hit": True, "error": "helius_limit"}
        except Exception as exc:
            log(f"FAIL {label} {type(exc).__name__}")
            return {"wallet": addr, "label": label, "error": type(exc).__name__}

    log(f"PHASE1 thin {[w.get('label') for w in thin]}")
    for w in thin:
        results.append(run(w, 10, 12, 120))

    log(f"PHASE2 rest n={len(rest)} limit_hit={limit_hit}")
    for w in rest:
        results.append(run(w, 12, 8, 80))

    SUMMARY.write_text(json.dumps({"results": results, "limit_hit": limit_hit, "n": len(results)}, indent=2, default=str), encoding="utf-8")
    log(f"ALL_DONE n={len(results)} limit_hit={limit_hit}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())