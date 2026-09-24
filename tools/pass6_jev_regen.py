import json
from pathlib import Path
from trenchnet.config_load import load_roster, load_settings
from trenchnet.jev_gate import judge_snapshot
from trenchnet.scores import score_features_for_wallet, write_scores
from trenchnet.backtest import load_all_history_events

ROOT = Path(".")
write_scores(ROOT)
settings = load_settings()
out_dir = ROOT / "out"
routes_dir = out_dir / "routes"
routes_dir.mkdir(parents=True, exist_ok=True)

profiles = []
for p in sorted((out_dir / "profiles").glob("*.json")):
    if p.name == "roster_ordered.json":
        continue
    profiles.append(json.loads(p.read_text(encoding="utf-8")))

events = load_all_history_events(ROOT)
by_w = {}
for e in events:
    by_w.setdefault(e.get("wallet"), []).append(e)

routes = []
ok_n = 0
fail_n = 0
statuses = {}
for i, p in enumerate(profiles):
    waddr = p.get("wallet")
    metrics = p.get("metrics") or {}
    evs = by_w.get(waddr) or []
    buys = [e for e in evs if e.get("side") == "buy" and e.get("amount_sol") is not None]
    buys.sort(key=lambda e: e.get("block_time") or 0)
    last = buys[-1] if buys else None
    snap = {
        "wallet": waddr,
        "label": p.get("label"),
        "history_flag": metrics.get("history_flag") or "ok",
        "trade_count": metrics.get("trade_count") or len(evs),
        "typical_buy_size_sol": metrics.get("typical_buy_size_sol"),
        "current_buy_sol": (last or {}).get("amount_sol"),
        "attention_hint": "needs_update",
        "wallet_score": score_features_for_wallet(ROOT, waddr),
    }
    snap["numeric_features"] = snap["wallet_score"]
    routed = judge_snapshot(snap, model=settings.get("jev", {}).get("model", "jev-latest"))
    routed["wallet"] = waddr
    routed["label"] = p.get("label")
    routes.append(routed)
    (routes_dir / f"{waddr}.json").write_text(json.dumps(routed, indent=2), encoding="utf-8")
    if routed.get("jev_call_ok"):
        ok_n += 1
    else:
        fail_n += 1
    st = routed.get("jev_http_status")
    statuses[st] = statuses.get(st, 0) + 1
    print(i + 1, p.get("label"), routed.get("jev_mode"), "ok", routed.get("jev_call_ok"), "http", st, "route", routed.get("route"), flush=True)

(routes_dir / "all_routes.json").write_text(json.dumps(routes, indent=2), encoding="utf-8")
summary = {
    "jev_live_ok": ok_n,
    "jev_live_fail": fail_n,
    "http_statuses": {str(k): v for k, v in statuses.items()},
    "n": len(routes),
}
Path("out/pass6_jev_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print("SUMMARY", summary, flush=True)
