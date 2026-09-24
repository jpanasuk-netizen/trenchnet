"""CLI: python -m trenchnet.cli replay|poll|fetch-and-replay|fetch-history|history-status|paper-*"""

from __future__ import annotations

import argparse
import json
import sys

from trenchnet.config_load import ROOT, load_roster, load_settings
from trenchnet.data_solana import SolanaRPC


def _paths(settings: dict):
    from pathlib import Path
    raw = ROOT / settings.get("paths", {}).get("raw_dir", "data/raw")
    out = ROOT / settings.get("paths", {}).get("out_dir", "out")
    return raw, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TRENCHNET observe-only Solana pump.fun wallet watcher (NO trading)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("replay", help="Run pipeline from data/raw/*.json (offline-capable)")
    sub.add_parser("poll", help="Fetch latest signatures/txs into data/raw/ then stop")
    sub.add_parser("fetch-and-replay", help="Poll free RPC then run replay")
    p_fh = sub.add_parser("fetch-history", help="Resumable FULL signature history per roster wallet (free RPC)")
    p_fh.add_argument("--wallet", help="Limit to one wallet address", default=None)
    p_fh.add_argument("--max-pages", type=int, default=None, help="Max signature pages this run (resume later)")
    p_fh.add_argument("--max-tx", type=int, default=None, help="Max getTransaction calls this run")
    sub.add_parser("history-status", help="Show per-wallet full-history progress")
    sub.add_parser("ui", help="Start local desk UI (WATCH-ONLY / PAPER) on 127.0.0.1")
    p_ui = sub.choices["ui"]
    p_ui.add_argument("--port", type=int, default=8791)
    p_ui.add_argument("--no-browser", action="store_true")
    p_pb = sub.add_parser("paper-buy", help="PAPER buy a token (simulated fill at last real price)")
    p_pb.add_argument("wallet")
    p_pb.add_argument("token_mint")
    p_ps = sub.add_parser("paper-sell", help="PAPER sell a token (partial or all)")
    p_ps.add_argument("wallet")
    p_ps.add_argument("token_mint")
    p_ps.add_argument("--amount-token", type=float, default=None)
    p_pc = sub.add_parser("paper-close", help="PAPER close full position in a token")
    p_pc.add_argument("wallet")
    p_pc.add_argument("token_mint")
    p_pk = sub.add_parser("paper-kill", help="Set/unset paper kill switch (blocks new paper fills)")
    p_pk.add_argument("state", choices=["on", "off"])
    sub.add_parser("paper-status", help="Show paper portfolio state from ledger")

    sub.add_parser("expand-roster", help="Expand roster from FREE public sources (cap ~40; seed tagged)")
    p_tc = sub.add_parser("fetch-token-context", help="Dexscreener+GeckoTerminal context for graph tokens (free)")
    p_tc.add_argument("--max", type=int, default=12)
    p_fh = sub.choices.get("fetch-history")
    if p_fh is not None and not any(a.dest=="rpc" for a in getattr(p_fh, "_actions", [])):
        p_fh.add_argument("--rpc", default=None, help="Override free RPC URL for this run")

        sub.add_parser("pool-prices", help="Pass 6: fetch Helius pool-wide swaps into data/prices/")
    sub.add_parser("backtest", help="Pass 5 copy-trade backtest + walk-forward (paper only)")
    sub.add_parser("scores", help="Pass 5 wallet composite scores (paper only)")

    args = parser.parse_args(argv)

    print("=" * 60)
    print("TRENCHNET - OBSERVE / ANALYSIS ONLY - PAPER TRADING ONLY")
    print("No keys, no signing, no buy/sell/swap/order code.")
    print("LIVE is off until Jeremy names a ticket. No implementation exists.")
    print("=" * 60)

    from trenchnet.pipeline import poll_fetch, run_replay

    if args.cmd == "poll":
        paths = poll_fetch()
        print(json.dumps({"fetched": [str(p) for p in paths]}, indent=2))
        return 0
    if args.cmd == "fetch-and-replay":
        paths = poll_fetch()
        print(f"Fetched {len(paths)} wallet raw files")
        summary = run_replay()
        try:
            from trenchnet.dashboard import regenerate
            reg = regenerate(ROOT)
            print(f"Dashboard regenerated: {reg.get('dashboard')}")
        except Exception as exc:
            print(f"Dashboard regen skipped: {exc}")
        print(json.dumps(summary, indent=2))
        return 0
    if args.cmd == "replay":
        summary = run_replay()
        try:
            from trenchnet.dashboard import regenerate
            reg = regenerate(ROOT)
            print(f"Dashboard regenerated: {reg.get('dashboard')}")
        except Exception as exc:
            print(f"Dashboard regen skipped: {exc}")
        print(json.dumps(summary, indent=2))
        return 0
    if args.cmd == "ui":
        from trenchnet.webui import serve
        serve(ROOT, port=args.port, open_browser=not args.no_browser)
        return 0
    if args.cmd == "fetch-history":
        settings = load_settings()
        roster = load_roster()
        raw_dir, _ = _paths(settings)
        sol = settings.get("solana", {})
        rpc_url = getattr(args, "rpc", None) or sol.get("rpc_url", "https://api.mainnet-beta.solana.com")
        rpc = SolanaRPC(
            rpc_url,
            sleep_ms=int(sol.get("request_sleep_ms", 500)),
        )
        from trenchnet.history import fetch_wallet_history, history_dir
        hdir = history_dir(raw_dir)
        wallets = roster.get("wallets") or []
        if args.wallet:
            wallets = [w for w in wallets if w.get("address") == args.wallet]
        if not wallets:
            print("No roster wallets matched.", file=sys.stderr)
            return 1
        results = []
        for w in wallets:
            addr = w["address"]
            print(f"Fetching history: {w.get('label') or addr[:8]} ({addr[:12]}...)", flush=True)
            res = fetch_wallet_history(
                rpc, addr, hdir / f"{addr}.json",
                max_pages=args.max_pages, max_tx=args.max_tx,
                log_fn=lambda m: print("  " + m, flush=True),
            )
            results.append(res)
            print(json.dumps(res))
        return 0
    if args.cmd == "history-status":
        settings = load_settings()
        raw_dir, _ = _paths(settings)
        from trenchnet.history import all_progress, history_dir, oldest_iso
        prog = all_progress(history_dir(raw_dir))
        rows = []
        for addr, st in sorted(prog.items()):
            rows.append({
                "wallet": addr,
                "complete": st.get("complete"),
                "sigs_scanned": len(st.get("seen") or []),
                "pages": st.get("pages_fetched"),
                "txs_fetched": st.get("txs_fetched"),
                "events": len(st.get("events") or []),
                "oldest": oldest_iso(st.get("oldest_block_time")),
                "stopped_early": st.get("stopped_early_reason"),
            })
        print(json.dumps({"wallets": rows, "note": "complete=false means history fetch not finished; never invented"}, indent=2))
        return 0


    if args.cmd == "expand-roster":
        from trenchnet.sources_expand import expand_roster
        rep = expand_roster()
        print(json.dumps(rep, indent=2, default=str))
        return 0
    if args.cmd == "fetch-token-context":
        from trenchnet.history import all_progress, history_dir
        from trenchnet.token_context import fetch_for_mints
        settings = load_settings()
        raw_dir, _ = _paths(settings)
        mints = []
        seen = set()
        for st in all_progress(history_dir(raw_dir)).values():
            for e in st.get("events") or []:
                m = e.get("token_mint")
                if m and m not in seen:
                    seen.add(m); mints.append(m)
        mints = mints[: max(1, int(args.max))]
        print(json.dumps({"fetching": mints}, indent=2))
        res = fetch_for_mints(mints, raw_dir)
        print(json.dumps({"ok": True, "n": len(res), "mints": list(res)}, indent=2))
        return 0

    
    if args.cmd == "pool-prices":
        from trenchnet.pool_prices import build_pool_prices_for_roster
        from trenchnet.backtest import load_backtest_config
        cfg = load_backtest_config(ROOT)
        pf = cfg.get("pool_fetch") or {}
        rep = build_pool_prices_for_roster(
            ROOT,
            max_mints=int(pf.get("max_mints", 80)),
            max_pages_per_mint=int(pf.get("max_pages_per_mint", 20)),
            min_pairs=int(pf.get("min_pairs", 1)),
            log=lambda m: print(m, flush=True),
        )
        # build_pool uses log= not log_fn — fix below if needed
        print(json.dumps({k: (v if k not in ("ok","failed","skipped") else len(v)) for k,v in rep.items()}, indent=2, default=str))
        print(json.dumps({"ok_mints": [x.get("mint") for x in (rep.get("ok") or [])][:20], "failed_sample": (rep.get("failed") or [])[:10]}, indent=2))
        return 0

    if args.cmd == "backtest":
        from trenchnet.backtest import run_backtest, write_backtest_outputs
        from trenchnet.scores import write_scores
        from trenchnet.dashboard import regenerate
        result = run_backtest(ROOT)
        paths = write_backtest_outputs(ROOT, result)
        sp = write_scores(ROOT, backtest=result)
        try:
            reg = regenerate(ROOT)
        except Exception as exc:
            reg = {"error": str(exc)}
        summary = {k: result[k] for k in result if k != "per_trade"}
        summary["per_trade_count"] = len(result.get("per_trade") or [])
        summary["outputs"] = {**paths, **sp, **(reg if isinstance(reg, dict) else {})}
        print(json.dumps(summary, indent=2, default=str))
        return 0
    if args.cmd == "scores":
        from trenchnet.scores import write_scores, compute_scores
        from trenchnet.backtest import run_backtest, write_backtest_outputs
        bt = run_backtest(ROOT)
        write_backtest_outputs(ROOT, bt)
        doc = compute_scores(ROOT, backtest=bt)
        write_scores(ROOT, backtest=bt)
        print(json.dumps({k: doc[k] for k in doc if k != "wallets"} | {"top5": doc.get("wallets", [])[:5]}, indent=2))
        return 0


    # ---- paper commands ----
    from trenchnet.paper import (
        _utc_day,
        iter_records,
        paper_fill,
        paper_settings_from,
        paper_state,
        set_kill_switch,
        kill_switch_on,
    )
    from trenchnet.data_solana import events_from_raw, load_raw_dir
    from trenchnet.history import history_events_for_wallet, history_dir

    settings = load_settings()
    raw_dir, out_dir = _paths(settings)
    data_dir = ROOT / "data"
    ledger = data_dir / "paper" / "ledger.jsonl"
    cfg = paper_settings_from(settings)

    if args.cmd == "paper-kill":
        on = set_kill_switch(data_dir, args.state == "on")
        print(json.dumps({"kill_switch": "on" if on else "off", "mode": "PAPER"}))
        return 0

    if args.cmd == "paper-status":
        state = paper_state(ledger, cfg)
        print(json.dumps({
            "mode": "PAPER",
            "live_toggle": cfg.get("live_toggle"),
            "live_note": cfg.get("live_toggle_note"),
            "balance_sol": state["balance_sol"],
            "realized_pnl_sol": state["realized_pnl_sol"],
            "open_positions": state["open_positions"],
            "fills": len(state["fills"]),
            "refusals": len(state["refusals"]),
            "kill_switch": kill_switch_on(data_dir),
        }, indent=2, default=str))
        return 0

    # paper-buy / paper-sell / paper-close need events for real pricing
    events = events_from_raw(load_raw_dir(raw_dir))
    events += history_events_for_wallet(history_dir(raw_dir), args.wallet)
    res = paper_fill(
        {"paper-buy": "buy", "paper-sell": "sell", "paper-close": "close"}[args.cmd],
        args.wallet,
        args.token_mint,
        events=events,
        ledger_path=ledger,
        data_dir=data_dir,
        settings=cfg,
        amount_token=getattr(args, "amount_token", None),
        note=f"CLI {args.cmd}",
    )
    print(json.dumps(res, indent=2, default=str))
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
