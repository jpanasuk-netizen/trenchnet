"""Pass 5 wallet composite scores (paper / analysis only).

Features (all computed from real history + backtest + graph):
  entry_earliness, win_rate, median_hold, lead_follow, trade_frequency,
  copyability_60s, oos_stability

Weights are documented in config/backtest.yaml under scores.weights.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trenchnet.backtest import (
    STABLE_MINTS,
    load_all_history_events,
    load_backtest_config,
    _safe_float,
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _norm_series(values: dict[str, float], *, higher_better: bool = True) -> dict[str, float]:
    if not values:
        return {}
    xs = list(values.values())
    lo, hi = min(xs), max(xs)
    out: dict[str, float] = {}
    for k, v in values.items():
        if hi - lo < 1e-12:
            out[k] = 0.5
        else:
            n = (v - lo) / (hi - lo)
            out[k] = n if higher_better else (1.0 - n)
    return out


def _lead_follow_ratios(root: Path) -> dict[str, float]:
    """lead_count / (lead_count + follow_count) from graph co_entries; 0.5 if unknown."""
    gpath = root / "out" / "graph" / "summary.json"
    scores: dict[str, list[int]] = {}  # wallet -> [leads, follows]
    if not gpath.exists():
        return {}
    try:
        g = json.loads(gpath.read_text(encoding="utf-8"))
    except Exception:
        return {}
    for row in g.get("co_entries") or []:
        a, b = row.get("wallet_a"), row.get("wallet_b")
        lead = row.get("lead")
        if not a or not b:
            continue
        scores.setdefault(a, [0, 0])
        scores.setdefault(b, [0, 0])
        if lead == a:
            scores[a][0] += 1
            scores[b][1] += 1
        elif lead == b:
            scores[b][0] += 1
            scores[a][1] += 1
    # also use a_first / b_first counts when lead null
    for row in g.get("co_entries") or []:
        a, b = row.get("wallet_a"), row.get("wallet_b")
        if not a or not b or row.get("lead"):
            continue
        af = int(row.get("a_first") or 0)
        bf = int(row.get("b_first") or 0)
        scores.setdefault(a, [0, 0])
        scores.setdefault(b, [0, 0])
        scores[a][0] += af
        scores[a][1] += bf
        scores[b][0] += bf
        scores[b][1] += af
    out: dict[str, float] = {}
    for w, (le, fo) in scores.items():
        tot = le + fo
        out[w] = (le / tot) if tot else 0.5
    return out


def _entry_earliness(events: list[dict[str, Any]]) -> dict[str, float]:
    """Seconds after first tracked buy on mint; lower is better -> invert later."""
    first_by_mint: dict[str, int] = {}
    for e in events:
        if e.get("side") != "buy":
            continue
        mint = e.get("token_mint") or ""
        if not mint or mint in STABLE_MINTS:
            continue
        t = e.get("block_time")
        if t is None:
            continue
        t = int(t)
        if mint not in first_by_mint or t < first_by_mint[mint]:
            first_by_mint[mint] = t
    delays: dict[str, list[float]] = {}
    for e in events:
        if e.get("side") != "buy":
            continue
        mint = e.get("token_mint") or ""
        w = e.get("wallet") or ""
        t = e.get("block_time")
        if not mint or not w or t is None or mint not in first_by_mint:
            continue
        delays.setdefault(w, []).append(max(0, int(t) - first_by_mint[mint]))
    return {w: float(statistics.median(xs)) for w, xs in delays.items() if xs}


def _win_rate_and_hold(events: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    """FIFO realized win rate + median hold seconds per wallet."""
    by_wm: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in events:
        mint = e.get("token_mint") or ""
        w = e.get("wallet") or ""
        if not mint or not w or mint in STABLE_MINTS:
            continue
        if e.get("side") not in ("buy", "sell") or e.get("block_time") is None:
            continue
        by_wm.setdefault((w, mint), []).append(e)
    wins: dict[str, list[int]] = {}
    holds: dict[str, list[float]] = {}
    for (w, mint), evs in by_wm.items():
        evs.sort(key=lambda x: int(x["block_time"]))
        opens: list[dict[str, Any]] = []
        for e in evs:
            if e["side"] == "buy":
                opens.append(e)
            elif e["side"] == "sell" and opens:
                b = opens.pop(0)
                hold = int(e["block_time"]) - int(b["block_time"])
                holds.setdefault(w, []).append(float(max(0, hold)))
                bs = _safe_float(b.get("amount_sol"))
                ss = _safe_float(e.get("amount_sol"))
                if bs is not None and ss is not None:
                    wins.setdefault(w, []).append(1 if ss > bs else 0)
                else:
                    # no SOL sizes — count completed round-trip as unresolved (skip)
                    pass
    win_rate = {w: (sum(v) / len(v) if v else 0.5) for w, v in wins.items()}
    # wallets with round-trips but no SOL: use neutral 0.5
    for w in holds:
        win_rate.setdefault(w, 0.5)
    med_hold = {w: float(statistics.median(v)) for w, v in holds.items() if v}
    return win_rate, med_hold


def _trade_frequency(events: list[dict[str, Any]]) -> dict[str, float]:
    by_w: dict[str, list[int]] = {}
    for e in events:
        w = e.get("wallet") or ""
        t = e.get("block_time")
        if not w or t is None:
            continue
        if (e.get("token_mint") or "") in STABLE_MINTS:
            continue
        by_w.setdefault(w, []).append(int(t))
    out: dict[str, float] = {}
    for w, ts in by_w.items():
        if len(ts) < 2:
            out[w] = float(len(ts))
            continue
        span_days = max(1.0 / 24.0, (max(ts) - min(ts)) / 86400.0)
        out[w] = len(ts) / span_days
    return out


def _hold_score(seconds: float, sweet_min: float, sweet_max: float) -> float:
    """1.0 inside sweet band; decays outside."""
    if sweet_min <= seconds <= sweet_max:
        return 1.0
    if seconds < sweet_min:
        return _clamp01(seconds / sweet_min) if sweet_min else 0.0
    # above max: decay
    return _clamp01(sweet_max / seconds) if seconds else 0.0


def compute_scores(
    root: Path,
    backtest: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or load_backtest_config(root)
    scfg = cfg.get("scores") or {}
    weights = dict(scfg.get("weights") or {})
    # defaults if missing
    defaults = {
        "entry_earliness": 0.15,
        "win_rate": 0.15,
        "median_hold": 0.10,
        "lead_follow": 0.15,
        "trade_frequency": 0.10,
        "copyability_60s": 0.20,
        "oos_stability": 0.15,
    }
    for k, v in defaults.items():
        weights.setdefault(k, v)
    wsum = sum(float(x) for x in weights.values()) or 1.0
    weights = {k: float(v) / wsum for k, v in weights.items()}

    if backtest is None:
        bpath = root / "out" / "backtest.json"
        if bpath.exists():
            backtest = json.loads(bpath.read_text(encoding="utf-8"))
        else:
            from trenchnet.backtest import run_backtest
            backtest = run_backtest(root, cfg)

    events = load_all_history_events(root)
    earliness = _entry_earliness(events)
    win_rate, med_hold = _win_rate_and_hold(events)
    lead_follow = _lead_follow_ratios(root)
    freq = _trade_frequency(events)

    copy_pnl: dict[str, float] = {}
    copy_cov: dict[str, float] = {}
    for row in backtest.get("wallets") or []:
        w = row.get("wallet")
        if not w:
            continue
        copy_pnl[w] = float(row.get("copy_pnl_60s") or 0.0)
        copy_cov[w] = float(row.get("coverage_60s") or 0.0)

    wf = backtest.get("walk_forward") or {}
    disappeared = {x["wallet"] for x in (wf.get("edge_disappeared_wallets") or []) if x.get("wallet")}
    oos_raw: dict[str, float] = {}
    for w in set(list(copy_pnl) + list(win_rate) + list(earliness)):
        if wf.get("status") != "ok":
            oos_raw[w] = 0.5  # neutral when insufficient OOS
        elif w in disappeared:
            oos_raw[w] = 0.15
        else:
            oos_raw[w] = 0.85

    sweet_min = float(scfg.get("hold_sweet_min", 60))
    sweet_max = float(scfg.get("hold_sweet_max", 3600))
    hold_feat = {w: _hold_score(s, sweet_min, sweet_max) for w, s in med_hold.items()}

    # normalize where needed
    n_early = _norm_series(earliness, higher_better=False)  # earlier = better
    n_win = {w: _clamp01(v) for w, v in win_rate.items()}
    n_hold = hold_feat
    n_lead = {w: _clamp01(v) for w, v in lead_follow.items()}
    n_freq = _norm_series(freq, higher_better=True)
    n_copy = _norm_series(copy_pnl, higher_better=True)
    n_oos = {w: _clamp01(v) for w, v in oos_raw.items()}

    wallets = sorted(
        set(n_early) | set(n_win) | set(n_hold) | set(n_lead) | set(n_freq) | set(n_copy) | set(n_oos)
    )
    labels = {}
    try:
        from trenchnet.config_load import load_roster
        for w in load_roster().get("wallets") or []:
            if w.get("address"):
                labels[w["address"]] = w.get("label") or w["address"][:8]
    except Exception:
        pass

    rows = []
    for w in wallets:
        feats = {
            "entry_earliness": n_early.get(w, 0.5),
            "win_rate": n_win.get(w, 0.5),
            "median_hold": n_hold.get(w, 0.5),
            "lead_follow": n_lead.get(w, 0.5),
            "trade_frequency": n_freq.get(w, 0.5),
            "copyability_60s": n_copy.get(w, 0.5),
            "oos_stability": n_oos.get(w, 0.5),
        }
        score = sum(feats[k] * weights[k] for k in weights)
        rows.append({
            "wallet": w,
            "label": labels.get(w) or w[:8],
            "score": round(score, 4),
            "features": {k: round(v, 4) for k, v in feats.items()},
            "raw": {
                "entry_earliness_sec_median": round(earliness[w], 1) if w in earliness else None,
                "win_rate": round(win_rate[w], 4) if w in win_rate else None,
                "median_hold_sec": round(med_hold[w], 1) if w in med_hold else None,
                "lead_follow_ratio": round(lead_follow[w], 4) if w in lead_follow else None,
                "trades_per_day": round(freq[w], 4) if w in freq else None,
                "copy_pnl_60s_sol": round(copy_pnl[w], 6) if w in copy_pnl else None,
                "copy_coverage_60s_pct": round(copy_cov[w], 2) if w in copy_cov else None,
            },
            "oos_flag": "edge_disappeared" if w in disappeared else (
                "insufficient_oos" if wf.get("status") != "ok" else "stable"
            ),
            "weights": weights,
        })
    rows.sort(key=lambda r: (-r["score"], r["wallet"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paper_only": True,
        "weights": weights,
        "walk_forward_status": wf.get("status"),
        "n_wallets": len(rows),
        "wallets": rows,
        "disclaimer": "Composite score is an observational ranking for paper analysis — not financial advice.",
    }


def write_scores(root: Path, backtest: dict[str, Any] | None = None) -> dict[str, str]:
    doc = compute_scores(root, backtest=backtest)
    out = root / "out" / "scores.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return {"scores": str(out)}


def score_features_for_wallet(root: Path, wallet: str) -> dict[str, Any]:
    """Helper for Jev gate: numeric features citation blob."""
    path = root / "out" / "scores.json"
    if not path.exists():
        return {"available": False}
    doc = json.loads(path.read_text(encoding="utf-8"))
    for row in doc.get("wallets") or []:
        if row.get("wallet") == wallet:
            return {
                "available": True,
                "score": row.get("score"),
                "rank": row.get("rank"),
                "features": row.get("features"),
                "raw": row.get("raw"),
                "oos_flag": row.get("oos_flag"),
                "weights": row.get("weights") or doc.get("weights"),
            }
    return {"available": False, "wallet": wallet}
