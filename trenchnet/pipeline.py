
"""End-to-end observe-only pipeline: poll + replay."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trenchnet.config_load import ROOT, load_roster, load_settings
from trenchnet.data_solana import (
    PUMPFUN_PROGRAM,
    SolanaRPC,
    events_from_raw,
    fetch_wallet_raw,
    load_raw_dir,
    save_raw,
)
from trenchnet.graph import graph_summary_dict
from trenchnet.history import dedupe_events, history_dir, history_events_for_wallet
from trenchnet.jev_gate import judge_snapshot
from trenchnet.llm_fcc import FCCWriter
from trenchnet.profiles import build_profiles
from trenchnet.reports import write_situation_report
from trenchnet.timeline import build_token_timelines


def _paths(settings: dict[str, Any]) -> tuple[Path, Path]:
    raw = ROOT / settings.get("paths", {}).get("raw_dir", "data/raw")
    out = ROOT / settings.get("paths", {}).get("out_dir", "out")
    return raw, out


def poll_fetch(settings: dict[str, Any] | None = None, roster: dict[str, Any] | None = None) -> list[Path]:
    settings = settings or load_settings()
    roster = roster or load_roster()
    raw_dir, _ = _paths(settings)
    raw_dir.mkdir(parents=True, exist_ok=True)
    sol = settings.get("solana", {})
    rpc = SolanaRPC(sol.get("rpc_url", "https://api.mainnet-beta.solana.com"), sleep_ms=int(sol.get("request_sleep_ms", 400)))
    program = sol.get("pumpfun_program", PUMPFUN_PROGRAM)
    written: list[Path] = []
    for w in roster.get("wallets") or []:
        addr = w["address"]
        doc = fetch_wallet_raw(
            rpc,
            addr,
            sig_limit=int(sol.get("signatures_per_wallet", 25)),
            max_tx=int(sol.get("max_tx_fetch", 20)),
            program_id=program,
        )
        path = raw_dir / f"{addr}.json"
        save_raw(doc, path)
        written.append(path)
    return written


def run_replay(settings: dict[str, Any] | None = None, roster: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    roster = roster or load_roster()
    raw_dir, out_dir = _paths(settings)
    program = settings.get("solana", {}).get("pumpfun_program", PUMPFUN_PROGRAM)
    raw_docs = load_raw_dir(raw_dir)
    events = events_from_raw(raw_docs, program_id=program)
    # Merge FULL history caches (data/raw/history/*.json) when present, without
    # double-counting txs that are also in the recent poll raw files.
    hdir = history_dir(raw_dir)
    if hdir.is_dir():
        merged = list(events)
        for p in sorted(hdir.glob("*.json")):
            merged.extend(history_events_for_wallet(hdir, p.stem))
        events = dedupe_events(merged)

    fcc_cfg = settings.get("fcc", {})
    writer = FCCWriter(
        base_url=fcc_cfg.get("base_url", "http://127.0.0.1:8082/v1"),
        model=fcc_cfg.get("model", "anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code"),
        timeout=float(fcc_cfg.get("timeout_seconds", 90)),
    )
    # probe FCC once
    fcc_ok = writer.available()

    wallets = roster.get("wallets") or []
    profiles = build_profiles(wallets, events, writer, out_dir / "profiles")

    window = int(settings.get("graph", {}).get("co_entry_window_minutes", 30))
    gsum = graph_summary_dict(events, window_minutes=window)
    (out_dir / "graph").mkdir(parents=True, exist_ok=True)
    (out_dir / "graph" / "summary.json").write_text(json.dumps(gsum, indent=2), encoding="utf-8")
    (out_dir / "graph" / "summary.md").write_text(
        "# Wallet-token graph summary\n\n"
        f"Edges: {gsum['edge_count']}\n\n"
        f"Co-entries: {len(gsum['co_entries'])}\n\n"
        f"Token summaries: {len(gsum['token_summaries'])}\n\n"
        f"{gsum['disclaimer']}\n",
        encoding="utf-8",
    )

    # Jev routes: one snapshot per profile with a latest buy if any
    routes_dir = out_dir / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    routes = []
    events_by_wallet: dict[str, list] = {}
    for e in events:
        events_by_wallet.setdefault(e.wallet, []).append(e)
    jev_model = settings.get("jev", {}).get("model", "jev-latest")
    for p in profiles:
        waddr = p["wallet"]
        m = p["metrics"]
        buys = [e for e in events_by_wallet.get(waddr, []) if e.side == "buy"]
        buys = sorted(buys, key=lambda e: e.block_time or 0)
        current = buys[-1] if buys else None
        snapshot = {
            "wallet": waddr,
            "label": p["label"],
            "trade_count": m.get("trade_count"),
            "history_flag": m.get("history_flag"),
            "typical_buy_size_sol": m.get("typical_buy_size_sol"),
            "median_hold_seconds": m.get("median_hold_seconds"),
            "current_buy_sol": (current.amount_sol if current else None),
            "current_buy_signature": (current.signature if current else None),
            "current_token": (current.token_mint if current else None),
            "attention_hint": "new_situation" if current else "still_valid",
            "note": "Code computed all counts; Jev must not do arithmetic.",
        }
        routed = judge_snapshot(snapshot, model=jev_model)
        routed["wallet"] = waddr
        routed["label"] = p["label"]
        routed["snapshot"] = snapshot
        routes.append(routed)
        (routes_dir / f"{waddr}.json").write_text(json.dumps(routed, indent=2), encoding="utf-8")
    (routes_dir / "all_routes.json").write_text(json.dumps(routes, indent=2), encoding="utf-8")

    # Situation report for the token with most roster activity
    label_map = {w["address"]: w.get("label") or w["address"][:8] for w in wallets}
    timelines = build_token_timelines(events, out_dir / "timelines", label_map=label_map)
    focus_token = timelines[0] if timelines else None
    facts = {
        "focus_token": focus_token,
        "event_count": len(events),
        "wallet_count": len(wallets),
        "sample_signatures": [e.signature for e in events[:10]],
        "graph_edge_count": gsum["edge_count"],
        "token_summary": next((t for t in gsum["token_summaries"] if t["token_mint"] == focus_token), None),
        "routes_preview": [{"wallet": r["wallet"], "route": r["route"], "jev_mode": r.get("jev_mode")} for r in routes[:8]],
        "fcc_available": fcc_ok,
        "fcc_model": writer.model,
        "fcc_last_error": writer.last_error,
    }
    report = write_situation_report(
        writer,
        facts=facts,
        out_dir=out_dir / "reports",
        event_id=("token_" + (focus_token[:12] if focus_token else "none")),
    )

    summary = {
        "events": len(events),
        "profiles": len(profiles),
        "routes": len(routes),
        "timelines": len(timelines),
        "fcc_mode": writer.mode,
        "fcc_available": fcc_ok,
        "fcc_model": writer.model,
        "focus_token": focus_token,
        "report_event_id": report.get("event_id"),
        "jev_modes": sorted({r.get("jev_mode") for r in routes}),
        "observe_only": True,
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
