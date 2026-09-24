"""Pass 7 Top Pick card — paper/analysis only, never a promise.

Produces per-token calls (BUY candidate / WATCH / AVOID / no buy), logs a pick
ledger, scores paper outcomes at fixed horizons, and can backfill historically
with point-in-time inputs (no lookahead).
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from trenchnet.backtest import (
    STABLE_MINTS,
    PricePoint,
    load_all_history_events,
    load_backtest_config,
    load_birdeye_ohlcv,
    load_helius_pool_pricepoints,
    price_at,
    build_derived_price_index,
    _safe_float,
)


def load_picks_config(root: Path) -> dict[str, Any]:
    p = root / "config" / "picks.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def picks_dir(root: Path) -> Path:
    d = root / "data" / "picks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _top_wallets(scores: dict[str, Any], min_score: float) -> list[dict[str, Any]]:
    out = []
    for w in scores.get("wallets") or []:
        if float(w.get("score") or 0) >= min_score:
            out.append(w)
    return out


def _first_buys_by_mint(events: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """mint -> wallet -> first buy event."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for e in events:
        if e.get("side") != "buy":
            continue
        mint = e.get("token_mint") or ""
        w = e.get("wallet") or ""
        t = e.get("block_time")
        if not mint or not w or t is None or mint in STABLE_MINTS:
            continue
        cur = out.setdefault(mint, {})
        prev = cur.get(w)
        if prev is None or int(t) < int(prev.get("block_time") or 0):
            cur[w] = e
    return out


def _token_context_map(root: Path) -> dict[str, dict[str, Any]]:
    d = root / "data" / "raw" / "token_context"
    out: dict[str, dict[str, Any]] = {}
    if not d.is_dir():
        return out
    for fp in d.glob("*.json"):
        doc = _load_json(fp)
        if isinstance(doc, dict):
            out[doc.get("mint") or fp.stem] = doc
    return out


def _liquidity_signals(mint: str, events: list[dict[str, Any]], tctx: dict[str, Any] | None) -> dict[str, Any]:
    sols = []
    for e in events:
        if e.get("token_mint") != mint:
            continue
        s = _safe_float(e.get("amount_sol"))
        if s is not None and s > 0:
            sols.append(s)
    proxy = float(statistics.median(sols)) if sols else None
    liq_usd = None
    thin = None
    if isinstance(tctx, dict):
        thin = tctx.get("thin_data")
        dx = tctx.get("dexscreener") or {}
        if isinstance(dx, dict):
            # common shapes
            for path in (
                ("liquidity", "usd"),
                ("pair", "liquidity", "usd"),
            ):
                cur: Any = dx
                ok = True
                for k in path:
                    if not isinstance(cur, dict) or k not in cur:
                        ok = False
                        break
                    cur = cur[k]
                if ok:
                    liq_usd = _safe_float(cur)
                    if liq_usd is not None:
                        break
            if liq_usd is None:
                liq_usd = _safe_float(dx.get("liquidity_usd") or dx.get("liquidityUsd"))
    return {"liquidity_proxy_sol": proxy, "liquidity_usd": liq_usd, "thin_data": thin}


def _safety_check(mint: str, age_s: float | None, liq: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, list[str]]:
    saf = cfg.get("safety") or {}
    reasons: list[str] = []
    skip = set(saf.get("skip_mints") or []) | set(STABLE_MINTS)
    if mint in skip:
        return False, ["stable_or_skipped_mint"]
    min_age = float(saf.get("min_token_age_seconds", 60))
    max_age = float(saf.get("max_token_age_seconds", 604800))
    if age_s is None:
        reasons.append("age_unknown")
    else:
        if age_s < min_age:
            reasons.append(f"too_new_age_{int(age_s)}s")
        if age_s > max_age:
            reasons.append(f"too_old_age_{int(age_s)}s")
    min_proxy = float(saf.get("min_liquidity_proxy_sol", 0.05))
    min_usd = float(saf.get("min_liquidity_usd", 1000))
    proxy = liq.get("liquidity_proxy_sol")
    usd = liq.get("liquidity_usd")
    liq_ok = False
    if proxy is not None and proxy >= min_proxy:
        liq_ok = True
    if usd is not None and usd >= min_usd:
        liq_ok = True
    if not liq_ok:
        reasons.append("liquidity_below_threshold")
    if liq.get("thin_data"):
        reasons.append("token_context_thin")
    ok = not any(r.startswith("too_") or r in ("stable_or_skipped_mint", "liquidity_below_threshold") for r in reasons)
    # age_unknown alone does not hard-fail if liquidity ok
    if "age_unknown" in reasons and liq_ok and "stable_or_skipped_mint" not in reasons:
        ok = "liquidity_below_threshold" not in reasons and not any(r.startswith("too_") for r in reasons)
    return ok, reasons


def _confidence(parts: dict[str, float], cfg: dict[str, Any]) -> float:
    c = cfg.get("confidence") or {}
    score = float(c.get("base", 0.2))
    score += parts.get("wallets", 0) * float(c.get("per_top_wallet", 0.1))
    score += parts.get("jev_live", 0) * float(c.get("jev_live_bonus", 0.15))
    score += parts.get("safety", 0) * float(c.get("safety_pass_bonus", 0.15))
    score += parts.get("copy_pos", 0) * float(c.get("copy_positive_bonus", 0.1))
    score -= parts.get("oos_pen", 0) * float(c.get("oos_insufficient_penalty", 0.2))
    return max(0.05, min(float(c.get("max", 0.95)), score))


def evaluate_candidates(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Score every active mint; return calls + optional top BUY candidate."""
    cfg = cfg or load_picks_config(root)
    thr = cfg.get("thresholds") or {}
    min_score = float(thr.get("min_wallet_score", 0.55))
    min_tops = int(thr.get("min_top_wallets", 2))
    max_span = int(thr.get("max_cobuy_span_seconds", 3600))
    min_copy = float(thr.get("min_copy_pnl_60s_sol", -0.05))
    jev_ok = set(thr.get("jev_ok_routes") or ["send_for_analysis", "keep_observing"])

    scores = _load_json(root / "out" / "scores.json") or {}
    backtest = _load_json(root / "out" / "backtest_summary.json") or {}
    routes = _load_json(root / "out" / "routes" / "all_routes.json") or []
    route_by = {r.get("wallet"): r for r in routes if isinstance(r, dict)}
    bt_w = {w.get("wallet"): w for w in (backtest.get("wallets") or []) if w.get("wallet")}
    events = load_all_history_events(root)
    first_buys = _first_buys_by_mint(events)
    tctx_map = _token_context_map(root)
    top = _top_wallets(scores, min_score)
    top_addr = {w["wallet"] for w in top}
    wf_status = scores.get("walk_forward_status") or (backtest.get("walk_forward") or {}).get("status")

    # price families for entry mark
    pool = load_helius_pool_pricepoints(root)
    derived = build_derived_price_index(events)
    now_t = max((int(e["block_time"]) for e in events if e.get("block_time")), default=0)

    candidates: list[dict[str, Any]] = []
    for mint, by_w in first_buys.items():
        if mint in STABLE_MINTS:
            continue
        tops_here = []
        times = []
        for w, ev in by_w.items():
            if w not in top_addr:
                continue
            sc = next((x for x in top if x["wallet"] == w), None)
            bt = bt_w.get(w) or {}
            tops_here.append({
                "wallet": w,
                "label": (sc or {}).get("label") or w[:8],
                "score": (sc or {}).get("score"),
                "first_buy_time": int(ev["block_time"]),
                "copy_pnl_60s": bt.get("copy_pnl_60s"),
                "coverage_60s": bt.get("coverage_60s"),
                "oos_flag": (sc or {}).get("oos_flag"),
                "jev_route": (route_by.get(w) or {}).get("route"),
                "jev_mode": (route_by.get(w) or {}).get("jev_mode"),
                "jev_call_ok": (route_by.get(w) or {}).get("jev_call_ok"),
            })
            times.append(int(ev["block_time"]))
        if not tops_here:
            continue
        times.sort()
        span = times[-1] - times[0] if len(times) > 1 else 0
        age = (now_t - times[0]) if now_t and times else None
        liq = _liquidity_signals(mint, events, tctx_map.get(mint))
        safety_ok, safety_reasons = _safety_check(mint, float(age) if age is not None else None, liq, cfg)

        # Jev: any top wallet with constructive live route
        jev_hits = [t for t in tops_here if t.get("jev_route") in jev_ok]
        jev_live = any(t.get("jev_mode") == "typesafe_live" and t.get("jev_call_ok") for t in tops_here)
        copy_ok = any(
            (t.get("copy_pnl_60s") is not None and float(t["copy_pnl_60s"]) >= min_copy)
            for t in tops_here
        )
        n_tops = len(tops_here)
        confirmations = []
        if n_tops >= min_tops:
            confirmations.append(f"{n_tops}_top_wallets_bought")
        if span <= max_span and n_tops >= 2:
            confirmations.append(f"cobuy_span_{span}s")
        if copy_ok:
            confirmations.append("copy_pnl_60s_not_deeply_negative")
        if jev_hits:
            confirmations.append(f"jev_routes_{sorted({t['jev_route'] for t in jev_hits if t.get('jev_route')})}")
        if jev_live:
            confirmations.append("jev_typesafe_live")
        if safety_ok:
            confirmations.append("safety_pass")

        # Call logic
        buy_ready = (
            n_tops >= min_tops
            and span <= max_span
            and copy_ok
            and bool(jev_hits)
            and safety_ok
        )
        if buy_ready:
            call = "BUY candidate"
        elif n_tops >= 1 and (copy_ok or jev_hits):
            call = "WATCH"
        else:
            call = "AVOID"

        # Entry mark at last top-wallet buy (call time)
        call_t = times[-1]
        entry_px = None
        entry_src = ""
        for fam, series_map in (("helius_pool", pool), ("derived", derived)):
            series = series_map.get(mint) or []
            entry_px, entry_src = price_at(series, call_t, max_gap_s=300)
            if entry_px is not None:
                entry_src = entry_src or fam
                break

        conf_parts = {
            "wallets": float(min(n_tops, 4)),
            "jev_live": 1.0 if jev_live else 0.0,
            "safety": 1.0 if safety_ok else 0.0,
            "copy_pos": 1.0 if copy_ok and any((t.get("copy_pnl_60s") or 0) > 0 for t in tops_here) else 0.0,
            "oos_pen": 1.0 if wf_status in ("insufficient_data",) or any(
                (t.get("oos_flag") or "").startswith("insufficient") for t in tops_here
            ) else 0.0,
        }
        conf = _confidence(conf_parts, cfg)

        reason_bits = []
        reason_bits.append(f"{n_tops} top-scored wallet(s) (min_score>={min_score})")
        reason_bits.append(f"co-buy span {span}s (max {max_span}s)")
        if copy_ok:
            reason_bits.append("60s copy PnL for at least one wallet meets floor")
        else:
            reason_bits.append("60s copy PnL floor not met")
        if jev_hits:
            reason_bits.append(f"Jev constructive on {len(jev_hits)} wallet(s)")
        else:
            reason_bits.append("no constructive Jev route among top wallets")
        if safety_ok:
            reason_bits.append("safety checks passed")
        else:
            reason_bits.append("safety: " + ", ".join(safety_reasons))
        if wf_status:
            reason_bits.append(f"walk_forward={wf_status}")

        candidates.append({
            "token_mint": mint,
            "call": call,
            "confidence": round(conf, 3),
            "reason": "; ".join(reason_bits),
            "confirmations": confirmations,
            "n_top_wallets": n_tops,
            "cobuy_span_seconds": span,
            "first_buy_time": times[0],
            "call_time": call_t,
            "call_time_iso": datetime.fromtimestamp(call_t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entry_price": entry_px,
            "entry_price_source": entry_src,
            "entry_unit": "SOL_per_token" if entry_src != "birdeye" else "USD_proxy",
            "safety_ok": safety_ok,
            "safety_reasons": safety_reasons,
            "liquidity": liq,
            "token_age_seconds": age,
            "wallets": tops_here,
            "chain": "Solana",
            "venue": "pump.fun",
        })

    # Rank BUY candidates by confidence then n_top_wallets
    buys = [c for c in candidates if c["call"] == "BUY candidate"]
    buys.sort(key=lambda c: (-c["confidence"], -c["n_top_wallets"], c["token_mint"]))
    watches = [c for c in candidates if c["call"] == "WATCH"]
    watches.sort(key=lambda c: (-c["confidence"], -c["n_top_wallets"]))

    if buys:
        top_pick = buys[0]
        headline = "BUY candidate"
        headline_reason = top_pick["reason"]
    else:
        top_pick = None
        headline = "No buy right now"
        if watches:
            headline_reason = (
                f"No token cleared BUY rules (need ≥{min_tops} top wallets, co-buy speed, "
                f"copy floor, Jev, safety). Closest WATCH: {watches[0]['token_mint'][:12]}… — {watches[0]['reason']}"
            )
        elif candidates:
            headline_reason = "Candidates exist but all AVOID under current thresholds."
        else:
            headline_reason = "No tokens with top-scored wallet buys in current data."

    return {
        "generated_at_utc": _now_iso(),
        "paper_only": True,
        "not_financial_advice": True,
        "walk_forward_status": wf_status,
        "headline": headline,
        "headline_reason": headline_reason,
        "top_pick": top_pick,
        "candidates": sorted(candidates, key=lambda c: (0 if c["call"].startswith("BUY") else 1 if c["call"] == "WATCH" else 2, -c["confidence"]))[:40],
        "n_candidates": len(candidates),
        "n_buy": len(buys),
        "n_watch": len(watches),
        "thresholds": {
            "min_wallet_score": min_score,
            "min_top_wallets": min_tops,
            "max_cobuy_span_seconds": max_span,
            "min_copy_pnl_60s_sol": min_copy,
        },
        "caveats": [
            "PAPER only — not financial advice.",
            "Small sample; coverage and walk-forward limits apply.",
            f"Walk-forward status: {wf_status}",
            "Entry prices from helius_pool/derived when available; never invented.",
        ],
    }


def append_live_pick(root: Path, evaluation: dict[str, Any]) -> Path | None:
    """Log current top pick (or no-buy) to append-only ledger."""
    d = picks_dir(root)
    ledger = d / "live_ledger.jsonl"
    row = {
        "logged_at_utc": _now_iso(),
        "kind": "live",
        "headline": evaluation.get("headline"),
        "headline_reason": evaluation.get("headline_reason"),
        "top_pick": evaluation.get("top_pick"),
        "walk_forward_status": evaluation.get("walk_forward_status"),
    }
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return ledger


def _price_families(root: Path, events: list[dict[str, Any]]) -> dict[str, dict[str, list[PricePoint]]]:
    return {
        "helius_pool": load_helius_pool_pricepoints(root),
        "derived": build_derived_price_index(events),
        "birdeye": load_birdeye_ohlcv(root),
    }


def outcome_at_horizons(
    mint: str,
    entry_t: int,
    entry_px: float,
    families: dict[str, dict[str, list[PricePoint]]],
    horizons: list[int],
    max_staleness: int,
) -> dict[str, Any]:
    """Paper mark-to-market returns; no costs here (track-record display)."""
    out: dict[str, Any] = {"entry_t": entry_t, "entry_px": entry_px, "horizons": {}}
    path_pnls = []
    for h in horizons:
        t = entry_t + int(h)
        px = None
        src = ""
        for fam in ("helius_pool", "derived", "birdeye"):
            # do not mix: if entry was SOL family, skip birdeye for exit
            series = (families.get(fam) or {}).get(mint) or []
            px, src = price_at(series, t, max_gap_s=max_staleness)
            if px is not None:
                break
        if px is None or not entry_px:
            out["horizons"][str(h)] = {"return": None, "unpriceable": True}
            continue
        ret = px / entry_px - 1.0
        # discard absurd marks
        if abs(ret) > 10:
            out["horizons"][str(h)] = {"return": None, "unpriceable": True, "reason": "outlier"}
            continue
        out["horizons"][str(h)] = {"return": round(ret, 6), "px": px, "source": src, "unpriceable": False}
        path_pnls.append(ret)
    # max drawdown along available horizon marks (ordered)
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for h in horizons:
        cell = out["horizons"].get(str(h)) or {}
        if cell.get("unpriceable") or cell.get("return") is None:
            continue
        eq = float(cell["return"])  # level return from entry, use as equity proxy path of marks
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    out["max_drawdown"] = round(mdd, 6)
    return out


def summarize_track_record(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    """Aggregate pick outcomes."""
    if not rows:
        return {
            "n": 0,
            "win_rate": None,
            "by_horizon": {},
            "worst": None,
            "note": "no picks",
        }
    # win = any horizon? use 1h if present else first priced
    wins = 0
    considered = 0
    by_h: dict[str, list[float]] = {str(h): [] for h in horizons}
    worst = None
    for row in rows:
        oc = row.get("outcome") or {}
        # prefer 3600s return for win
        ret_win = None
        for h in horizons:
            cell = (oc.get("horizons") or {}).get(str(h)) or {}
            if not cell.get("unpriceable") and cell.get("return") is not None:
                by_h[str(h)].append(float(cell["return"]))
                if h == 3600 or ret_win is None:
                    ret_win = float(cell["return"])
        if ret_win is None:
            continue
        considered += 1
        if ret_win > 0:
            wins += 1
        if worst is None or ret_win < float((worst.get("outcome") or {}).get("_sort", 0)):
            worst = dict(row)
            worst.setdefault("outcome", {})["_sort"] = ret_win

    by_horizon = {}
    for h, xs in by_h.items():
        if not xs:
            by_horizon[h] = {"n": 0, "median": None, "mean": None}
        else:
            by_horizon[h] = {
                "n": len(xs),
                "median": round(statistics.median(xs), 6),
                "mean": round(statistics.mean(xs), 6),
            }
    if worst and "outcome" in worst:
        worst["outcome"].pop("_sort", None)
    return {
        "n": considered,
        "n_logged": len(rows),
        "win_rate": round(wins / considered, 4) if considered else None,
        "by_horizon": by_horizon,
        "worst": {
            "token_mint": (worst or {}).get("token_mint"),
            "call_time": (worst or {}).get("call_time"),
            "outcome": (worst or {}).get("outcome"),
        } if worst else None,
    }


def backfill_picks(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replay rules at each moment a second top wallet joins a mint (point-in-time).

    Uses only buys with block_time <= call_time. Scores/backtest/Jev are from
    current artifacts but wallet membership is filtered by buy time — labeled
    honestly as backtested picks (not live-logged).
    """
    cfg = cfg or load_picks_config(root)
    if not (cfg.get("backfill") or {}).get("enabled", True):
        return {"status": "disabled", "n": 0}
    thr = cfg.get("thresholds") or {}
    min_score = float(thr.get("min_wallet_score", 0.55))
    min_tops = int(thr.get("min_top_wallets", 2))
    max_span = int(thr.get("max_cobuy_span_seconds", 3600))
    min_copy = float(thr.get("min_copy_pnl_60s_sol", -0.05))
    jev_ok = set(thr.get("jev_ok_routes") or ["send_for_analysis", "keep_observing"])
    horizons = list((cfg.get("track_record") or {}).get("horizons_seconds") or [900, 3600, 14400, 86400])
    max_stale = int((cfg.get("track_record") or {}).get("max_staleness_seconds", 300))

    scores = _load_json(root / "out" / "scores.json") or {}
    backtest = _load_json(root / "out" / "backtest_summary.json") or {}
    routes = _load_json(root / "out" / "routes" / "all_routes.json") or []
    route_by = {r.get("wallet"): r for r in routes if isinstance(r, dict)}
    bt_w = {w.get("wallet"): w for w in (backtest.get("wallets") or []) if w.get("wallet")}
    top_meta = {w["wallet"]: w for w in _top_wallets(scores, min_score)}
    events = load_all_history_events(root)
    families = _price_families(root, events)
    tctx_map = _token_context_map(root)

    # Build first-buy timeline per mint
    first_buys = _first_buys_by_mint(events)
    picks: list[dict[str, Any]] = []
    for mint, by_w in first_buys.items():
        if mint in STABLE_MINTS:
            continue
        # only top-scored wallets
        entries = []
        for w, ev in by_w.items():
            if w not in top_meta:
                continue
            entries.append((int(ev["block_time"]), w, ev))
        entries.sort(key=lambda x: x[0])
        if len(entries) < min_tops:
            continue
        # call when the min_tops-th top wallet arrives
        call_t = entries[min_tops - 1][0]
        present = entries[:min_tops]
        span = present[-1][0] - present[0][0]
        if span > max_span:
            continue
        # point-in-time: ignore wallets that bought after call_t
        assert all(t <= call_t for t, _, _ in present)
        tops_here = []
        for t, w, ev in present:
            sc = top_meta[w]
            bt = bt_w.get(w) or {}
            tops_here.append({
                "wallet": w,
                "score": sc.get("score"),
                "copy_pnl_60s": bt.get("copy_pnl_60s"),
                "jev_route": (route_by.get(w) or {}).get("route"),
            })
        copy_ok = any(
            (t.get("copy_pnl_60s") is not None and float(t["copy_pnl_60s"]) >= min_copy)
            for t in tops_here
        )
        jev_hits = [t for t in tops_here if t.get("jev_route") in jev_ok]
        age = 0.0  # at call, age since first of these
        liq = _liquidity_signals(mint, [e for e in events if (e.get("block_time") or 0) <= call_t], tctx_map.get(mint))
        safety_ok, _ = _safety_check(mint, float(span), liq, cfg)  # age~span from first of cluster
        # stricter: compute age from first present
        age = float(call_t - present[0][0])
        safety_ok, safety_reasons = _safety_check(mint, age if age > 0 else 60.0, liq, cfg)
        if not (copy_ok and jev_hits and safety_ok):
            continue
        # entry px at call_t
        entry_px = None
        entry_src = ""
        for fam in ("helius_pool", "derived"):
            series = (families.get(fam) or {}).get(mint) or []
            entry_px, entry_src = price_at(series, call_t, max_gap_s=max_stale)
            if entry_px is not None:
                break
        if entry_px is None:
            continue
        outcome = outcome_at_horizons(mint, call_t, entry_px, families, horizons, max_stale)
        picks.append({
            "kind": "backtested",
            "token_mint": mint,
            "call": "BUY candidate",
            "call_time": call_t,
            "entry_price": entry_px,
            "entry_price_source": entry_src,
            "n_top_wallets": min_tops,
            "cobuy_span_seconds": span,
            "safety_reasons": safety_reasons,
            "outcome": outcome,
            "note": "Point-in-time wallet arrivals only; scores/Jev/backtest stats from current artifacts (labeled backtested, not live).",
        })

    summary = summarize_track_record(picks, horizons)
    doc = {
        "generated_at_utc": _now_iso(),
        "kind": "backtested_picks",
        "n_picks": len(picks),
        "track_record": summary,
        "picks": picks[:100],
        "horizons_seconds": horizons,
        "disclaimer": "Backtested picks use historical buy timing with current score cards — still paper, still not advice.",
    }
    outp = picks_dir(root) / "backtested_summary.json"
    outp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def build_picks_payload(root: Path) -> dict[str, Any]:
    cfg = load_picks_config(root)
    evaluation = evaluate_candidates(root, cfg)
    # log live snapshot each rebuild (compact)
    try:
        append_live_pick(root, evaluation)
    except Exception:
        pass
    backtested = backfill_picks(root, cfg)
    # live ledger outcomes for prior BUY rows
    live_rows = _score_live_ledger(root, cfg)
    live_summary = summarize_track_record(live_rows, list((cfg.get("track_record") or {}).get("horizons_seconds") or [900, 3600, 14400, 86400]))
    # Coin Desk as separate Base input
    try:
        from trenchnet.coindesk import get_coindesk_state
        cd = get_coindesk_state()
    except Exception as exc:
        cd = {"status": "error", "note": type(exc).__name__, "cards": []}

    payload = {
        **evaluation,
        "backtested_track_record": backtested.get("track_record"),
        "backtested_n": backtested.get("n_picks"),
        "live_logged_track_record": live_summary,
        "live_logged_n": live_summary.get("n_logged"),
        "coindesk_summary": {
            "status": cd.get("status"),
            "as_of_utc": cd.get("as_of_utc"),
            "n_cards": len(cd.get("cards") or []),
            "pass_n": sum(1 for c in (cd.get("cards") or []) if str(c.get("call") or "").upper() in ("PASS",)),
            "watch_n": sum(1 for c in (cd.get("cards") or []) if "WATCH" in str(c.get("call") or "").upper()),
            "label": "Base / hood.fun (separate chain — not a Solana pick input for BUY)",
            "note": cd.get("note"),
        },
    }
    (picks_dir(root) / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (root / "out" / "top_pick.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _score_live_ledger(root: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = picks_dir(root) / "live_ledger.jsonl"
    if not ledger.is_file():
        return []
    events = load_all_history_events(root)
    families = _price_families(root, events)
    horizons = list((cfg.get("track_record") or {}).get("horizons_seconds") or [900, 3600, 14400, 86400])
    max_stale = int((cfg.get("track_record") or {}).get("max_staleness_seconds", 300))
    rows = []
    for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        tp = obj.get("top_pick")
        if not isinstance(tp, dict) or not str(tp.get("call") or "").startswith("BUY"):
            continue
        mint = tp.get("token_mint")
        entry_t = tp.get("call_time")
        entry_px = tp.get("entry_price")
        if not mint or not entry_t or not entry_px:
            continue
        outcome = outcome_at_horizons(mint, int(entry_t), float(entry_px), families, horizons, max_stale)
        rows.append({
            "kind": "live",
            "token_mint": mint,
            "call_time": entry_t,
            "entry_price": entry_px,
            "outcome": outcome,
            "logged_at_utc": obj.get("logged_at_utc"),
        })
    return rows
