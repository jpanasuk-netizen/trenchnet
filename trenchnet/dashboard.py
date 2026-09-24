"""Static dashboard generator: out/dashboard.html + out/assets/data.js.

file://-friendly: all data is baked into data.js as window.TRENCHNET_DATA.
Never invents numbers — everything comes from out/ + data/ artifacts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THEME = {
    "bg": "#05060f",
    "panel": "rgba(10, 18, 38, 0.55)",
    "blue": "#00B4FF",
    "purple": "#B026FF",
    "text": "#dfe9ff",
}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_data(root: Path) -> dict[str, Any]:
    """Collect REAL data only; missing files become labeled empty states."""
    out_dir = root / "out"
    data_dir = root / "data"
    summary = _read_json(out_dir / "run_summary.json") or {}
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    profiles = []
    pdir = out_dir / "profiles"
    if pdir.is_dir():
        for p in sorted(pdir.glob("*.json")):
            if p.name == "roster_ordered.json":
                continue
            doc = _read_json(p) or {}
            profiles.append({
                "wallet": doc.get("wallet"),
                "label": doc.get("label"),
                "writer_mode": doc.get("writer_mode"),
                "profile_text": (doc.get("profile_text") or "")[:2200],
                "metrics": doc.get("metrics") or {},
            })

    graph = _read_json(out_dir / "graph" / "summary.json") or {}
    routes = (_read_json(out_dir / "routes" / "all_routes.json") or [])
    route_by_wallet = {r.get("wallet"): r for r in routes if isinstance(r, dict)}

    timelines = []
    tdir = out_dir / "timelines"
    if tdir.is_dir():
        for p in sorted(tdir.glob("*.json")):
            evs = _read_json(p)
            if isinstance(evs, list) and evs:
                timelines.append({"token": p.stem, "events": evs[:60]})

    # history progress (resumable full-history fetch)
    history = []
    hdir = data_dir / "raw" / "history"
    if hdir.is_dir():
        for p in sorted(hdir.glob("*.json")):
            st = _read_json(p) or {}
            history.append({
                "wallet": st.get("wallet") or p.stem,
                "complete": bool(st.get("complete")),
                "sigs_scanned": len(st.get("seen") or []),
                "events": len(st.get("events") or []),
                "oldest_block_time": st.get("oldest_block_time"),
                "stopped_early": st.get("stopped_early_reason"),
            })

    # paper state (from ledger only)
    from trenchnet.paper import default_paper_settings, iter_records, paper_state
    ledger = data_dir / "paper" / "ledger.jsonl"
    cfg = default_paper_settings()
    pstate = paper_state(ledger, cfg)
    paper = {
        "balance_sol": pstate["balance_sol"],
        "realized_pnl_sol": pstate["realized_pnl_sol"],
        "open_positions": pstate["open_positions"],
        "fills": pstate["fills"][-50:],
        "refusals": pstate["refusals"][-20:],
        "fill_count": len(pstate["fills"]),
        "refusal_count": len(pstate["refusals"]),
        "live_toggle": cfg.get("live_toggle"),
        "live_note": cfg.get("live_toggle_note"),
    }

    # ---- PASS 2 lower-half panels: derived ONLY from real parsed events ----
    all_events: list[dict[str, Any]] = []
    try:
        from trenchnet.data_solana import events_from_raw as _efr, load_raw_dir as _lrd
        docs = _lrd(data_dir / "raw")
        all_events.extend(e.to_dict() for e in _efr(docs))
    except Exception:
        pass
    if hdir.is_dir():
        try:
            from trenchnet.history import history_events_for_wallet as _hefw
            for p in sorted(hdir.glob("*.json")):
                all_events.extend(e.to_dict() for e in _hefw(hdir, p.stem))
        except Exception:
            pass
    try:
        from trenchnet.history import dedupe_events as _dde
        all_events = list(_dde(all_events))  # works on dicts; (wallet, sig, mint) identity
    except Exception:
        pass
    # token context (Dexscreener/Gecko) — real files only
    token_ctx = {}
    try:
        from trenchnet.token_context import load_all_contexts
        token_ctx = load_all_contexts(data_dir / "raw")
    except Exception:
        token_ctx = {}
    panels = derive_panels(all_events, profiles, route_by_wallet, graph, paper, token_ctx=token_ctx)

    return {
        "generated_at_utc": generated_at,
        "observe_only": True,
        "mode": "PAPER",
        "run_summary": summary,
        "profiles": profiles,
        "graph": {
            "edges_sample": (graph.get("edges_sample") or [])[:120],
            "co_entries": (graph.get("co_entries") or [])[:60],
            "token_summaries": (graph.get("token_summaries") or [])[:40],
        },
        "routes": routes,
        "route_by_wallet": route_by_wallet,
        "timelines": timelines,
        "history_progress": history,
        "paper": paper,
        "panels": panels,
        "token_context": token_ctx,
        "honesty": {
            "fcc_mode": summary.get("fcc_mode"),
            "jev_modes": summary.get("jev_modes"),
            "live": "LIVE is off until Jeremy names a ticket. No implementation exists.",
        },
        "empty_states": {
            "profiles": not profiles,
            "timelines": not timelines,
            "routes": not routes,
        },
    }


def bake_data_js(root: Path) -> Path:
    data = collect_data(root)
    assets = root / "out" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    p = assets / "data.js"
    p.write_text(
        "// Baked by trenchnet.dashboard — real out/ data only, no invented numbers.\n"
        "window.TRENCHNET_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    return p


def write_dashboard(root: Path) -> Path:
    bake_data_js(root)
    src = Path(__file__).resolve().parents[1] / "docs" / "dashboard_template.html"
    dst = root / "out" / "dashboard.html"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


# ------------------------------------------------------------------ panels

def _hour_dot(ts: int | None) -> tuple[int, int] | None:
    """UTC hour-of-day + day-of-week (0=Mon..6=Sun) from a block_time."""
    if not ts:
        return None
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return dt.weekday(), dt.hour


def derive_heatmap(events: list[dict[str, Any]]) -> dict[str, Any]:
    """7x24 activity matrix (UTC) from real trade block_times."""
    grid = [[0] * 24 for _ in range(7)]
    total = 0
    for e in events:
        hd = _hour_dot(e.get("block_time"))
        if not hd:
            continue
        grid[hd[0]][hd[1]] += 1
        total += 1
    return {"grid": grid, "total": total, "tz": "UTC", "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


def derive_token_flows(events: list[dict[str, Any]], max_tokens: int = 6) -> list[dict[str, Any]]:
    """Per-token buy/sell flow series with REAL per-tx points (for smooth curves)."""
    by_tok: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        tok = e.get("token_mint")
        if not tok or e.get("side") not in ("buy", "sell") or not e.get("block_time"):
            continue
        by_tok.setdefault(tok, []).append(e)
    out = []
    for tok, evs in sorted(by_tok.items(), key=lambda kv: -len(kv[1]))[:max_tokens]:
        evs_sorted = sorted(evs, key=lambda e: (e.get("block_time") or 0, e.get("signature") or ""))
        running = 0.0
        pts = []
        for e in evs_sorted:
            sol = float(e.get("amount_sol") or 0.0)
            running += sol if e.get("side") == "buy" else -sol
            pts.append({
                "t": e.get("block_time"),
                "side": e.get("side"),
                "cum_sol": round(running, 9),
                "sig": e.get("signature"),
                "wallet": e.get("wallet"),
            })
        out.append({"token": tok, "points": pts, "tx_count": len(pts)})
    return out


def derive_coentry_matrix(graph: dict[str, Any]) -> dict[str, Any]:
    """Pairwise co-entry strength matrix from graph summary (real co_entries only)."""
    co = graph.get("co_entries") or []
    wallets: list[str] = []
    cells: list[dict[str, Any]] = []
    idx: dict[str, int] = {}
    for c in co:
        for w in (c.get("wallet_a"), c.get("wallet_b")):
            if w and w not in idx:
                idx[w] = len(wallets)
                wallets.append(w)
        cells.append({
            "a": idx[c.get("wallet_a")], "b": idx[c.get("wallet_b")],
            "shared": c.get("shared_tokens", 0), "jaccard": c.get("jaccard", 0),
        })
    return {"wallets": wallets, "cells": cells}


def derive_paper_table(paper: dict[str, Any]) -> list[dict[str, Any]]:
    """Recent ledger rows (fills + refusals) for the desk table."""
    rows: list[dict[str, Any]] = []
    for f in (paper.get("fills") or [])[-15:]:
        rows.append({
            "kind": "fill", "side": f.get("side"), "wallet": f.get("wallet"),
            "token_mint": f.get("token_mint"), "amount_sol": f.get("amount_sol"),
            "amount_token": f.get("amount_token"), "sig": f.get("price_source_signature"),
            "delta_sol": f.get("realized_delta_sol"), "ts": f.get("recorded_at"),
        })
    for r in (paper.get("refusals") or [])[-15:]:
        rows.append({
            "kind": "refusal", "reason": r.get("reason"), "wallet": r.get("wallet"),
            "token_mint": r.get("token_mint"), "ts": r.get("recorded_at"),
        })
    rows.sort(key=lambda x: x.get("ts") or "")
    return rows


def derive_panels(
    events: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    route_by_wallet: dict[str, Any],
    graph: dict[str, Any],
    paper: dict[str, Any],
    token_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label_map = {p.get("wallet"): (p.get("label") or (p.get("wallet") or "")[:8]) for p in profiles}
    return {
        "heatmap": derive_heatmap(events),
        "token_flows": derive_token_flows(events),
        "coentry_matrix": derive_coentry_matrix(graph or {}),
        "paper_table": derive_paper_table(paper or {}),
        "token_context": token_ctx or {},
        "labels": label_map,
        "thin_data": {
            "events": len(events),
            "note": ("thin data — recent poll sample only" if len(events) < 20 else "ok"),
        },
    }


def regenerate(root: Path) -> dict[str, str]:
    d = write_dashboard(root)
    return {"dashboard": str(d), "data_js": str(root / "out" / "assets" / "data.js")}
