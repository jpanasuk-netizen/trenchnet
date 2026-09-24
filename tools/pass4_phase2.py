"""Pass4 phase2: deepen seeds via Helius; shallow re-sweep expanded. No key logging."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trenchnet.config_load import load_roster, load_settings
from trenchnet.helius_client import HeliusLimitError, redact_url
from trenchnet.history import history_dir
from trenchnet.history_helius import fetch_wallet_history_helius

LOG = ROOT / "out" / "pass4_fetch.log"
SUMMARY = ROOT / "out" / "pass4_phase2_summary.json"
THIN = {"Cented", "theo", "Jijo", "decu"}  # already done in phase1

def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {redact_url(msg)}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n"); f.flush()
    print(line, flush=True)

def main() -> int:
    settings = load_settings()
    roster = load_roster()
    raw = ROOT / (settings.get("paths") or {}).get("raw_dir", "data/raw")
    hdir = history_dir(raw)
    wallets = [w for w in (roster.get("wallets") or []) if (w.get("label") or "") not in THIN]
    seeds = [w for w in wallets if w.get("role") == "seed"]
    expanded = [w for w in wallets if w.get("role") != "seed"]
    results = []
    limit_hit = False
    log(f"PHASE2B seeds={len(seeds)} expanded={len(expanded)}")

    def run(w, max_pages, rpc_pages, rpc_tx, allow_rpc):
        nonlocal limit_hit
        addr = w["address"]; label = w.get("label") or addr[:8]
        if limit_hit:
            return {"wallet": addr, "label": label, "skipped": "helius_limit"}
        cache = hdir / f"{addr}.json"
        if cache.is_file():
            st = json.loads(cache.read_text(encoding="utf-8"))
            if st.get("skip_rpc_zerofill") or st.get("stopped_early_reason") == "zero_fill_skip":
                log(f"SKIP_ZEROFILL {label}")
                return {"wallet": addr, "label": label, "skipped": "zero_fill", "events": len(st.get("events") or [])}
        log(f"START {label} role={w.get('role')} cap={max_pages} rpc={allow_rpc}")
        try:
            res = fetch_wallet_history_helius(
                addr, cache,
                max_pages=max_pages, page_limit=40, prefer_pump=True,
                log_fn=lambda m: log(f"  {m}"),
                allow_rpc_fallback=allow_rpc,
                rpc_max_pages=rpc_pages, rpc_max_tx=rpc_tx,
                reset_helius_cursor=True,
            )
            res["label"] = label
            res["role"] = w.get("role")
            log(f"DONE {label} ev={res.get('events')} src={res.get('source')}")
            if res.get("limit_hit"):
                limit_hit = True
                log("LIMIT stop")
            return res
        except HeliusLimitError:
            limit_hit = True
            return {"wallet": addr, "label": label, "limit_hit": True}
        except Exception as exc:
            log(f"FAIL {label} {type(exc).__name__}")
            return {"wallet": addr, "label": label, "error": type(exc).__name__}

    for w in seeds:
        results.append(run(w, max_pages=15, rpc_pages=8, rpc_tx=80, allow_rpc=True))
    for w in expanded:
        # shallow helius; rpc only if no events yet
        cache = hdir / f"{w['address']}.json"
        has_ev = False
        if cache.is_file():
            has_ev = bool((json.loads(cache.read_text(encoding="utf-8")).get("events") or []))
        results.append(run(w, max_pages=6, rpc_pages=4, rpc_tx=40, allow_rpc=not has_ev))

    SUMMARY.write_text(json.dumps({"results": results, "limit_hit": limit_hit, "n": len(results)}, indent=2, default=str), encoding="utf-8")
    # merge into pass4_fetch_summary
    thin_note = {"phase1_thin": ["Cented", "theo", "Jijo", "decu"], "phase2": results, "limit_hit": limit_hit}
    (ROOT / "out" / "pass4_fetch_summary.json").write_text(json.dumps(thin_note, indent=2, default=str), encoding="utf-8")
    log(f"ALL_DONE phase2 n={len(results)} limit_hit={limit_hit}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())