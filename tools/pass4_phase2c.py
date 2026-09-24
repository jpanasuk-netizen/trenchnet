"""Shallow Helius re-sweep for remaining expanded wallets. No key logging."""
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
DONE_SEED = {"Joji", "tech", "clukz", "Doji", "Cented", "theo", "Jijo", "decu"}

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
    # Skip wallets already DONE in phase2b seeds + thin + first few cobuy
    already = set(DONE_SEED)
    # parse log for DONE cobuy labels
    for line in LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "DONE cobuy_" in line:
            # DONE cobuy_XXX
            try:
                part = line.split("DONE ", 1)[1]
                lab = part.split(" ", 1)[0]
                already.add(lab)
            except Exception:
                pass
    remaining = [w for w in (roster.get("wallets") or []) if (w.get("label") or "") not in already]
    log(f"PHASE2C remaining={len(remaining)} already={len(already)}")
    results = []
    limit_hit = False
    for w in remaining:
        addr = w["address"]; label = w.get("label") or addr[:8]
        if limit_hit:
            results.append({"wallet": addr, "label": label, "skipped": "limit"})
            continue
        log(f"START {label} shallow")
        try:
            # monkeypatch: skip broad by setting prefer_pump and max_pages low; disable rpc
            res = fetch_wallet_history_helius(
                addr, hdir / f"{addr}.json",
                max_pages=4, page_limit=40, prefer_pump=True,
                log_fn=lambda m: log(f"  {m}"),
                allow_rpc_fallback=False,
                reset_helius_cursor=True,
            )
            # if still 0 helius events, that's ok for shallow
            res["label"] = label
            results.append(res)
            log(f"DONE {label} ev={res.get('events')} src={res.get('source')}")
            if res.get("limit_hit"):
                limit_hit = True
        except HeliusLimitError:
            limit_hit = True
            results.append({"wallet": addr, "label": label, "limit_hit": True})
        except Exception as exc:
            log(f"FAIL {label} {type(exc).__name__}")
            results.append({"wallet": addr, "label": label, "error": type(exc).__name__})
    # merge summary
    out = {"phase2c": results, "limit_hit": limit_hit, "n": len(results)}
    (ROOT / "out" / "pass4_phase2c_summary.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    # update combined
    combined = {"thin": ["Cented","theo","Jijo","decu"], "seeds_done": ["Joji","tech","clukz","Doji"], "phase2c": results, "limit_hit": limit_hit}
    (ROOT / "out" / "pass4_fetch_summary.json").write_text(json.dumps(combined, indent=2, default=str), encoding="utf-8")
    log(f"ALL_DONE phase2c n={len(results)} limit_hit={limit_hit}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())