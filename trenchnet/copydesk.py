"""Pass 9 Copy Wallets command center — paper/analysis only."""

from __future__ import annotations

import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:  # Windows without tzdata
    from datetime import timedelta
    CT = timezone(timedelta(hours=-5))

STABLE = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "So11111111111111111111111111111111111111112",
}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _ct(ts: int | float | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(CT).strftime("%Y-%m-%d %H:%M:%S CT")
    except Exception:
        return None


def _ago(ts: int | float | None, now: float | None = None) -> str:
    if ts is None:
        return "—"
    now = now or time.time()
    d = max(0, int(now - float(ts)))
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"


def _delay60_fixed(bt: dict[str, Any]) -> dict[str, Any]:
    delays = bt.get("delays") or {}
    d60 = delays.get("60") or delays.get(60) or {}
    if isinstance(d60, dict):
        fixed = d60.get("fixed") or d60.get("all") or {}
        if isinstance(fixed, dict):
            return fixed
    return {}


def verdict_for(w: dict[str, Any], bt: dict[str, Any], n_trades: int, pnl: float | None, win: float | None) -> tuple[str, str]:
    min_n = 5
    score = float(w.get("score") or 0)
    oos = str(w.get("oos_flag") or "")
    if n_trades < min_n or pnl is None:
        return (
            "not enough trades",
            f"Need >={min_n} priced 60s fixed copy sims with P&L; have n={n_trades}, pnl={'missing' if pnl is None else 'ok'}.",
        )
    pnl_f = float(pnl)
    wr = float(win) if win is not None else None
    if score >= 0.6 and pnl_f > 0 and (wr is None or wr >= 0.45) and "insufficient" not in oos.lower():
        extra = f", win {wr:.0%}" if wr is not None else ""
        return "COPY-WORTHY", f"Score {score:.2f}, 60s copy P&L {pnl_f:+.4f} SOL after costs{extra}"
    if score >= 0.5 and pnl_f >= -0.05:
        return "WATCH", f"Borderline: score {score:.2f}, 60s copy P&L {pnl_f:+.4f} SOL — watch, do not size up."
    return "AVOID", f"Weak copy profile: score {score:.2f}, 60s copy P&L {pnl_f:+.4f} SOL after costs."


def build_copydesk(root: Path) -> dict[str, Any]:
    scores = _load(root / "out" / "scores.json") or {}
    backtest = _load(root / "out" / "backtest_summary.json") or {}
    bt_w = {w.get("wallet"): w for w in (backtest.get("wallets") or []) if w.get("wallet")}
    wallets_scored = list(scores.get("wallets") or [])

    from trenchnet.backtest import load_all_history_events

    events = load_all_history_events(root)
    last_by_w: dict[str, int] = {}
    for e in events:
        w = e.get("wallet")
        t = e.get("block_time")
        if w and t and (w not in last_by_w or int(t) > last_by_w[w]):
            last_by_w[w] = int(t)

    leaderboard = []
    for w in wallets_scored:
        addr = w.get("wallet")
        if not addr:
            continue
        bt = dict(bt_w.get(addr) or {})
        d60 = _delay60_fixed(bt)
        n = int(
            bt.get("n_copies_60s")
            or d60.get("n_priced")
            or d60.get("n_copies")
            or 0
        )
        pnl = bt.get("copy_pnl_60s")
        if pnl is None:
            pnl = d60.get("total_pnl_sol")
        win = bt.get("win_rate_60s")
        if win is None:
            win = d60.get("win_rate")
        med = d60.get("median_return")
        verd, reason = verdict_for(w, bt, n, float(pnl) if pnl is not None else None, float(win) if win is not None else None)
        last_t = last_by_w.get(addr)
        leaderboard.append({
            "wallet": addr,
            "label": w.get("label") or addr[:8],
            "score": w.get("score"),
            "oos_flag": w.get("oos_flag"),
            "copy_pnl_60s_sol": pnl,
            "win_rate_60s": win,
            "n_trades_60s": n,
            "median_return_60s": med,
            "coverage_60s": bt.get("coverage_60s") or d60.get("coverage_pct"),
            "last_trade_ct": _ct(last_t),
            "last_trade_unix": last_t,
            "verdict": verd,
            "verdict_reason": reason,
        })
    leaderboard.sort(key=lambda r: (-(float(r["score"]) if r["score"] is not None else -1), r["wallet"]))

    top_addrs = {r["wallet"] for r in leaderboard if (r.get("score") or 0) >= 0.55}
    timed = [
        e for e in events
        if e.get("block_time") and e.get("side") in ("buy", "sell") and e.get("token_mint") not in STABLE
    ]
    timed.sort(key=lambda e: int(e["block_time"]), reverse=True)

    mint_top: dict[str, set[str]] = {}
    for e in timed:
        if e.get("side") != "buy":
            continue
        m = e.get("token_mint")
        w = e.get("wallet")
        if m and w in top_addrs:
            mint_top.setdefault(m, set()).add(w)

    label_of = {r["wallet"]: r["label"] for r in leaderboard}
    feed = []
    for e in timed[:50]:
        mint = e.get("token_mint") or ""
        feed.append({
            "side": e.get("side"),
            "label": "BOUGHT" if e.get("side") == "buy" else "SOLD",
            "wallet": e.get("wallet"),
            "wallet_label": label_of.get(e.get("wallet") or "", (e.get("wallet") or "")[:8]),
            "token_mint": mint,
            "amount_sol": e.get("amount_sol"),
            "block_time": e.get("block_time"),
            "time_ct": _ct(e.get("block_time")),
            "time_ago": _ago(e.get("block_time")),
            "top_wallets_in_token": len(mint_top.get(mint) or []),
            "signature": e.get("signature"),
        })

    now = time.time()
    recent_cut = now - 7 * 86400
    hot = []
    for mint, ws in mint_top.items():
        if len(ws) < 2:
            continue
        buys = [
            e for e in timed
            if e.get("token_mint") == mint and e.get("side") == "buy" and int(e.get("block_time") or 0) >= recent_cut
        ]
        if len({e.get("wallet") for e in buys if e.get("wallet") in top_addrs}) < 2:
            continue
        sols = [float(e["amount_sol"]) for e in buys if e.get("amount_sol") is not None]
        med = statistics.median(sols) if sols else None
        safety = {
            "liquidity": {
                "ok": bool(med is not None and med >= 0.05),
                "detail": f"median_buy_sol={med:.4g}" if med is not None else "unavailable",
            },
            "age": {"ok": True, "detail": "recent_cluster_7d"},
        }
        hot.append({
            "token_mint": mint,
            "n_top_wallets": len(ws),
            "wallets": sorted(ws)[:8],
            "median_buy_sol": med,
            "safety": safety,
            "last_buy_ct": _ct(max(int(e["block_time"]) for e in buys)) if buys else None,
        })
    hot.sort(key=lambda h: (-h["n_top_wallets"], h["token_mint"]))

    # Equity curves: cumulative copy_pnl from delay-60 fixed summary stepped by last_trade time.
    # Full per-trade sim paths are price paths, not P&L series — use wallet summary totals as end points
    # and walk-forward folds when available for a coarse paper equity view.
    top5 = [r["wallet"] for r in leaderboard[:5]]
    curves: dict[str, list[dict[str, Any]]] = {w: [] for w in top5}
    curves["ALL_TOP5"] = []
    wf = backtest.get("walk_forward") or {}
    folds = wf.get("folds") if isinstance(wf, dict) else None
    if isinstance(folds, list) and folds:
        run = {w: 0.0 for w in top5}
        run_all = 0.0
        for fold in folds:
            ts = fold.get("end_unix") or fold.get("t1") or fold.get("end")
            by_w = fold.get("by_wallet") or fold.get("wallets") or {}
            if isinstance(by_w, list):
                by_w = {x.get("wallet"): x for x in by_w if isinstance(x, dict)}
            for w in top5:
                cell = by_w.get(w) if isinstance(by_w, dict) else None
                delta = 0.0
                if isinstance(cell, dict):
                    delta = float(cell.get("pnl_sol") or cell.get("copy_pnl_60s") or cell.get("total_pnl_sol") or 0)
                elif isinstance(cell, (int, float)):
                    delta = float(cell)
                run[w] += delta
                if ts:
                    curves[w].append({"t": int(ts), "t_ct": _ct(ts), "equity_sol": round(run[w], 6)})
                run_all += delta
            if ts:
                curves["ALL_TOP5"].append({"t": int(ts), "t_ct": _ct(ts), "equity_sol": round(run_all, 6)})
    else:
        # Fallback: single end-point per wallet from copy_pnl_60s (honest thin-data curve)
        now_ts = int(time.time())
        run_all = 0.0
        for r in leaderboard[:5]:
            w = r["wallet"]
            pnl = float(r["copy_pnl_60s_sol"] or 0)
            t0 = r.get("last_trade_unix") or now_ts
            curves[w] = [
                {"t": int(t0) - 86400, "t_ct": _ct(int(t0) - 86400), "equity_sol": 0.0},
                {"t": int(t0), "t_ct": _ct(t0), "equity_sol": round(pnl, 6)},
            ]
            run_all += pnl
        curves["ALL_TOP5"] = [
            {"t": now_ts - 86400, "t_ct": _ct(now_ts - 86400), "equity_sol": 0.0},
            {"t": now_ts, "t_ct": _ct(now_ts), "equity_sol": round(run_all, 6)},
        ]

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at_ct": datetime.now(CT).strftime("%Y-%m-%d %H:%M:%S CT"),
        "paper_only": True,
        "not_financial_advice": True,
        "copy_assumptions": {
            "delay_seconds": 60,
            "position_sol": 0.25,
            "slip_mult": 1,
            "take_profit": 0.5,
            "stop_loss": 0.25,
            "time_stop_s": 3600,
            "mode": "fixed",
            "note": "Paper copy-trade after fees/slippage from backtest — not live results.",
        },
        "leaderboard": leaderboard,
        "activity_feed": feed,
        "hot_tokens": hot[:20],
        "equity_curves": curves,
        "n_wallets": len(leaderboard),
        "n_tokens_watched": len({e.get("token_mint") for e in timed[:2000] if e.get("token_mint")}),
    }


def write_copydesk(root: Path) -> Path:
    doc = build_copydesk(root)
    outp = root / "out" / "copydesk.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return outp
