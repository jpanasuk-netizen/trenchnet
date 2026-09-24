"""Pass 8 Hot Takes — paper opportunity tracker (not financial advice).

Looser than Top Pick BUY: strong wallet co-buy / fast-follow signals fire even
when safety checks fail (flags recorded). Outcomes use helius_pool/derived
prices + backtest cost model. Never invents prices.
"""

from __future__ import annotations

import json
import statistics
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from trenchnet.backtest import (
    STABLE_MINTS,
    PricePoint,
    apply_costs,
    build_derived_price_index,
    load_all_history_events,
    load_backtest_config,
    load_birdeye_ohlcv,
    load_helius_pool_pricepoints,
    price_at,
    _safe_float,
)


def _now_ts() -> float:
    return time.time()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def load_hottakes_config(root: Path) -> dict[str, Any]:
    p = root / "config" / "hottakes.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def hottakes_dir(root: Path) -> Path:
    d = root / "data" / "hottakes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path(root: Path) -> Path:
    return hottakes_dir(root) / "hottakes.jsonl"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _top_wallet_addrs(scores: dict[str, Any], min_score: float) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for w in scores.get("wallets") or []:
        if float(w.get("score") or 0) >= min_score:
            out[w["wallet"]] = w
    return out


def _liquidity_proxy(mint: str, events: list[dict[str, Any]]) -> float | None:
    sols = []
    for e in events:
        if e.get("token_mint") != mint:
            continue
        s = _safe_float(e.get("amount_sol"))
        if s is not None and s > 0:
            sols.append(s)
    return float(statistics.median(sols)) if sols else None


def safety_flags_for(
    mint: str,
    *,
    age_s: float | None,
    liq_proxy: float | None,
    liq_usd: float | None,
    jev_ok: bool,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Return visible pass/fail flags — do NOT block Hot Takes."""
    saf = cfg.get("safety_flags") or {}
    flags: dict[str, Any] = {}
    min_age = float(saf.get("min_token_age_seconds", 60))
    max_age = float(saf.get("max_token_age_seconds", 604800))
    if age_s is None:
        flags["age"] = {"ok": False, "detail": "unknown"}
    elif age_s < min_age:
        flags["age"] = {"ok": False, "detail": f"too_new_{int(age_s)}s"}
    elif age_s > max_age:
        flags["age"] = {"ok": False, "detail": f"too_old_{int(age_s)}s"}
    else:
        flags["age"] = {"ok": True, "detail": f"{int(age_s)}s"}

    min_proxy = float(saf.get("min_liquidity_proxy_sol", 0.05))
    min_usd = float(saf.get("min_liquidity_usd", 1000))
    liq_ok = False
    detail_parts = []
    if liq_proxy is not None:
        detail_parts.append(f"proxy_sol={liq_proxy:.4g}")
        if liq_proxy >= min_proxy:
            liq_ok = True
    if liq_usd is not None:
        detail_parts.append(f"usd={liq_usd:.4g}")
        if liq_usd >= min_usd:
            liq_ok = True
    if not detail_parts:
        detail_parts.append("unavailable")
    flags["liquidity"] = {"ok": liq_ok, "detail": ",".join(detail_parts)}
    # Holder concentration: only if we ever have free data; otherwise unknown (not fail)
    flags["holder_concentration"] = {"ok": None, "detail": "not_available_free"}
    flags["jev"] = {"ok": bool(jev_ok), "detail": "constructive" if jev_ok else "missing_or_weak"}
    return flags


def evaluate_hot_take_signals(
    root: Path,
    events: list[dict[str, Any]] | None = None,
    *,
    cfg: dict[str, Any] | None = None,
    as_of: int | None = None,
) -> list[dict[str, Any]]:
    """Point-in-time Hot Take candidates.

    If as_of is set, only events with block_time <= as_of are used (no lookahead).
    """
    cfg = cfg or load_hottakes_config(root)
    rule = cfg.get("rule") or {}
    min_score = float(rule.get("min_wallet_score", 0.55))
    min_tops = int(rule.get("min_top_wallets", 2))
    max_span = int(rule.get("max_cobuy_span_seconds", 900))
    min_follow = int(rule.get("min_follow_buys", 2))
    follow_win = int(rule.get("follow_window_seconds", 180))
    jev_ok_routes = set(rule.get("jev_ok_routes") or ["send_for_analysis", "keep_observing"])

    scores = _load_json(root / "out" / "scores.json") or {}
    routes = _load_json(root / "out" / "routes" / "all_routes.json") or []
    route_by = {r.get("wallet"): r for r in routes if isinstance(r, dict)}
    top = _top_wallet_addrs(scores, min_score)
    if not top:
        return []

    if events is None:
        events = load_all_history_events(root)
    if as_of is not None:
        events = [e for e in events if (e.get("block_time") or 0) <= int(as_of)]

    # first buy per (mint, wallet) and all buys per mint
    first_by_mint_w: dict[str, dict[str, dict[str, Any]]] = {}
    buys_by_mint: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e.get("side") != "buy":
            continue
        mint = e.get("token_mint") or ""
        w = e.get("wallet") or ""
        t = e.get("block_time")
        if not mint or not w or t is None or mint in STABLE_MINTS:
            continue
        buys_by_mint.setdefault(mint, []).append(e)
        cur = first_by_mint_w.setdefault(mint, {})
        prev = cur.get(w)
        if prev is None or int(t) < int(prev.get("block_time") or 0):
            cur[w] = e

    # price families for entry mark
    pool = load_helius_pool_pricepoints(root)
    derived = build_derived_price_index(events)

    out: list[dict[str, Any]] = []
    for mint, by_w in first_by_mint_w.items():
        top_entries = []
        for w, ev in by_w.items():
            if w not in top:
                continue
            top_entries.append((int(ev["block_time"]), w, ev))
        top_entries.sort(key=lambda x: x[0])
        if not top_entries:
            continue

        path = None
        trigger_wallets: list[str] = []
        flag_t = None
        reason = ""

        # Path A: >= min_tops within max_span
        if len(top_entries) >= min_tops:
            cluster = top_entries[:min_tops]
            span = cluster[-1][0] - cluster[0][0]
            if span <= max_span:
                path = "A_cobuy_top_wallets"
                trigger_wallets = [w for _, w, _ in cluster]
                flag_t = cluster[-1][0]
                reason = (
                    f"{min_tops}+ top-scored wallets co-bought within {span}s "
                    f"(max {max_span}s); scores>={min_score}"
                )

        # Path B: 1 top + fast follow-ons (any wallets) if Path A missed
        if path is None and top_entries:
            t0, w0, _ = top_entries[0]
            follows = [
                e for e in buys_by_mint.get(mint, [])
                if int(e.get("block_time") or 0) > t0
                and int(e.get("block_time") or 0) <= t0 + follow_win
                and e.get("wallet") != w0
            ]
            # unique follow wallets
            follow_ws = sorted({e.get("wallet") for e in follows if e.get("wallet")})
            if len(follows) >= min_follow:
                path = "B_top_plus_fast_follow"
                trigger_wallets = [w0] + follow_ws[:6]
                flag_t = max(int(e["block_time"]) for e in follows)
                reason = (
                    f"1 top wallet ({w0[:8]}…) then {len(follows)} follow-on buys "
                    f"from {len(follow_ws)} wallet(s) within {follow_win}s"
                )

        if path is None or flag_t is None:
            continue

        age = float(flag_t - top_entries[0][0])
        liq = _liquidity_proxy(mint, [e for e in events if e.get("token_mint") == mint])
        jev_ok = any(
            (route_by.get(w) or {}).get("route") in jev_ok_routes
            for w in trigger_wallets if w in top
        )
        flags = safety_flags_for(
            mint, age_s=age if age > 0 else 1.0, liq_proxy=liq, liq_usd=None, jev_ok=jev_ok, cfg=cfg
        )

        entry_px = None
        entry_src = ""
        for fam, series_map in (("helius_pool", pool), ("derived", derived)):
            series = series_map.get(mint) or []
            entry_px, entry_src = price_at(series, int(flag_t), max_gap_s=int((cfg.get("max_staleness_seconds") or 300)))
            if entry_px is not None:
                entry_src = entry_src or fam
                break

        out.append({
            "kind": "hot_take",
            "token_mint": mint,
            "path": path,
            "reason": reason,
            "flagged_at": int(flag_t),
            "flagged_at_iso": _iso(flag_t),
            "entry_price": entry_px,
            "entry_price_source": entry_src,
            "entry_unit": "SOL_per_token",
            "trigger_wallets": trigger_wallets,
            "flags": flags,
            "n_top_in_cluster": sum(1 for w in trigger_wallets if w in top),
            "status": "open",
            "paper_only": True,
            "chain": "Solana",
            "venue": "pump.fun",
        })
    return out


def load_ledger(root: Path) -> list[dict[str, Any]]:
    p = ledger_path(root)
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def append_ledger(root: Path, row: dict[str, Any]) -> None:
    p = ledger_path(root)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def rewrite_ledger(root: Path, rows: list[dict[str, Any]]) -> None:
    """Rewrite full ledger (used when updating outcomes). Atomic-ish via tmp."""
    p = ledger_path(root)
    tmp = p.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    tmp.replace(p)


def recent_take_for_mint(rows: list[dict[str, Any]], mint: str, *, dedup_hours: float) -> dict[str, Any] | None:
    cutoff = _now_ts() - dedup_hours * 3600
    best = None
    for r in rows:
        if r.get("token_mint") != mint:
            continue
        if r.get("kind") == "backtested":
            continue
        t = r.get("flagged_at") or 0
        if float(t) >= cutoff:
            if best is None or float(t) > float(best.get("flagged_at") or 0):
                best = r
    return best


def dedupe_new_takes(
    candidates: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    *,
    dedup_hours: float,
) -> list[dict[str, Any]]:
    out = []
    for c in candidates:
        mint = c.get("token_mint")
        if not mint:
            continue
        if recent_take_for_mint(existing, mint, dedup_hours=dedup_hours):
            continue
        out.append(c)
    return out


def _price_families(root: Path, events: list[dict[str, Any]] | None = None) -> dict[str, dict[str, list[PricePoint]]]:
    if events is None:
        events = load_all_history_events(root)
    return {
        "helius_pool": load_helius_pool_pricepoints(root),
        "derived": build_derived_price_index(events),
        "birdeye": load_birdeye_ohlcv(root),
    }


def mark_horizon_outcome(
    take: dict[str, Any],
    horizon_s: int,
    families: dict[str, dict[str, list[PricePoint]]],
    *,
    cfg: dict[str, Any],
    bt_cfg: dict[str, Any],
    now_ts: float | None = None,
) -> dict[str, Any] | None:
    """Mark one horizon if due. Returns outcome cell or None if not yet due."""
    flag_t = int(take.get("flagged_at") or 0)
    entry_px = take.get("entry_price")
    if not flag_t or not entry_px:
        return {
            "horizon_s": horizon_s,
            "result": "UNPRICED",
            "reason": "no_entry_price",
            "net_return": None,
            "gross_return": None,
        }
    due = flag_t + int(horizon_s)
    now = now_ts if now_ts is not None else _now_ts()
    if now < due:
        return None  # not yet

    mint = take.get("token_mint") or ""
    max_stale = int(cfg.get("max_staleness_seconds") or 300)
    px = None
    src = ""
    # Prefer SOL families; avoid mixing with birdeye unless entry was birdeye
    for fam in ("helius_pool", "derived"):
        series = (families.get(fam) or {}).get(mint) or []
        px, src = price_at(series, due, max_gap_s=max_stale)
        if px is not None:
            break
    if px is None:
        return {
            "horizon_s": horizon_s,
            "result": "UNPRICED",
            "reason": "no_trade_within_staleness",
            "due_at": due,
            "net_return": None,
            "gross_return": None,
        }
    gross = float(px) / float(entry_px) - 1.0
    if abs(gross) > 10:
        return {
            "horizon_s": horizon_s,
            "result": "UNPRICED",
            "reason": "outlier_return",
            "gross_return": gross,
            "net_return": None,
            "px": px,
            "source": src,
        }
    pos = float(cfg.get("position_size_sol") or 0.25)
    # liquidity proxy for slippage scale: use median from take flags detail if any
    liq = None
    try:
        detail = ((take.get("flags") or {}).get("liquidity") or {}).get("detail") or ""
        if "proxy_sol=" in detail:
            liq = float(detail.split("proxy_sol=")[1].split(",")[0])
    except Exception:
        liq = None
    net, costs_sol = apply_costs(pos, gross, liq=liq, cfg=bt_cfg)
    result = "WIN" if net > 0 else "LOSS"
    return {
        "horizon_s": horizon_s,
        "result": result,
        "gross_return": round(gross, 6),
        "net_return": round(net, 6),
        "costs_sol": round(costs_sol, 8),
        "px": px,
        "source": src,
        "due_at": due,
        "marked_at_iso": _now_iso(),
    }


def update_take_outcomes(
    take: dict[str, Any],
    families: dict[str, dict[str, list[PricePoint]]],
    *,
    cfg: dict[str, Any],
    bt_cfg: dict[str, Any],
    now_ts: float | None = None,
) -> dict[str, Any]:
    horizons = list(cfg.get("horizons_seconds") or [900, 3600, 14400, 86400])
    outcomes = dict(take.get("outcomes") or {})
    samples = list(take.get("price_samples") or [])
    now = now_ts if now_ts is not None else _now_ts()
    mint = take.get("token_mint") or ""
    entry_px = take.get("entry_price")
    max_stale = int(cfg.get("max_staleness_seconds") or 300)

    # live sample
    cur_px = None
    cur_src = ""
    for fam in ("helius_pool", "derived"):
        series = (families.get(fam) or {}).get(mint) or []
        # newest at-or-before now via allow_before for "current"
        cur_px, cur_src = price_at(series, int(now), max_gap_s=max_stale, allow_before=True)
        if cur_px is None:
            cur_px, cur_src = price_at(series, int(now), max_gap_s=max_stale)
        if cur_px is not None:
            break
    if cur_px is not None and entry_px:
        live_gross = float(cur_px) / float(entry_px) - 1.0
        samples.append({"t": int(now), "px": cur_px, "source": cur_src, "gross": round(live_gross, 6)})
        # keep last 200
        samples = samples[-200:]
        runups = [s["gross"] for s in samples if s.get("gross") is not None]
        take["live_px"] = cur_px
        take["live_source"] = cur_src
        take["live_gross"] = round(live_gross, 6)
        take["max_runup"] = round(max(runups), 6) if runups else None
        take["max_drawdown"] = round(min(runups), 6) if runups else None
    take["price_samples"] = samples

    for h in horizons:
        key = str(h)
        prev = outcomes.get(key)
        if prev and prev.get("result") in ("WIN", "LOSS", "UNPRICED"):
            continue
        cell = mark_horizon_outcome(take, int(h), families, cfg=cfg, bt_cfg=bt_cfg, now_ts=now)
        if cell is not None:
            outcomes[key] = cell
    take["outcomes"] = outcomes

    close_after = int(cfg.get("close_after_seconds") or 86400)
    flag_t = int(take.get("flagged_at") or 0)
    if flag_t and now >= flag_t + close_after:
        take["status"] = "closed"
        take["closed_at_iso"] = _now_iso()
    elif take.get("status") != "closed":
        take["status"] = "open"
    return take


def scoreboard(rows: list[dict[str, Any]], *, kind: str | None = None) -> dict[str, Any]:
    """Aggregate Hot Take outcomes. UNPRICED counted separately from WIN/LOSS."""
    filtered = [r for r in rows if (kind is None or r.get("kind") == kind or (kind == "live" and r.get("kind") != "backtested"))]
    if kind == "live":
        filtered = [r for r in rows if r.get("kind") != "backtested"]
    elif kind == "backtested":
        filtered = [r for r in rows if r.get("kind") == "backtested"]

    open_n = sum(1 for r in filtered if r.get("status") == "open")
    closed_n = sum(1 for r in filtered if r.get("status") == "closed")
    horizons = ["900", "3600", "14400", "86400"]
    by_h: dict[str, Any] = {}
    for h in horizons:
        wins = losses = unpriced = 0
        nets: list[float] = []
        best = worst = None
        for r in filtered:
            cell = (r.get("outcomes") or {}).get(h)
            if not cell:
                continue
            res = cell.get("result")
            if res == "WIN":
                wins += 1
                nr = cell.get("net_return")
                if nr is not None:
                    nets.append(float(nr))
            elif res == "LOSS":
                losses += 1
                nr = cell.get("net_return")
                if nr is not None:
                    nets.append(float(nr))
            elif res == "UNPRICED":
                unpriced += 1
        decided = wins + losses
        by_h[h] = {
            "wins": wins,
            "losses": losses,
            "unpriced": unpriced,
            "win_rate": round(wins / decided, 4) if decided else None,
            "mean_net": round(statistics.mean(nets), 6) if nets else None,
            "median_net": round(statistics.median(nets), 6) if nets else None,
            "best": round(max(nets), 6) if nets else None,
            "worst": round(min(nets), 6) if nets else None,
            "n_priced": decided,
        }
    return {
        "total": len(filtered),
        "open": open_n,
        "closed": closed_n,
        "by_horizon": by_h,
        "paper_only": True,
        "not_financial_advice": True,
    }


def backfill_hottakes(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replay Hot Take rule point-in-time; label as backtested (separate from live)."""
    cfg = cfg or load_hottakes_config(root)
    if not (cfg.get("backfill") or {}).get("enabled", True):
        return {"status": "disabled", "n": 0}
    bt_cfg = load_backtest_config(root)
    events = load_all_history_events(root)
    families = _price_families(root, events)
    # Candidate flag times = evaluate on full history then re-check with as_of=flag_t
    # Efficient approach: evaluate once; for each candidate, verify trigger wallets'
    # buys are all <= flag_t (already true by construction).
    cands = evaluate_hot_take_signals(root, events, cfg=cfg)
    takes = []
    now_fake = max((int(e.get("block_time") or 0) for e in events), default=int(_now_ts())) + 86400 * 2
    for c in cands:
        if c.get("entry_price") is None:
            continue
        row = dict(c)
        row["kind"] = "backtested"
        row["label"] = (cfg.get("backfill") or {}).get("label") or "backtested Hot Takes"
        row["logged_at_iso"] = _now_iso()
        update_take_outcomes(row, families, cfg=cfg, bt_cfg=bt_cfg, now_ts=float(now_fake))
        row["status"] = "closed"
        takes.append(row)

    summary = scoreboard(takes, kind="backtested")
    doc = {
        "generated_at_utc": _now_iso(),
        "kind": "backtested_hottakes",
        "n": len(takes),
        "scoreboard": summary,
        "takes": takes[:200],
        "disclaimer": "Backtested Hot Takes — point-in-time wallet arrivals; paper only.",
    }
    (hottakes_dir(root) / "backtested_summary.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (root / "out" / "hottakes_backtested.json").write_text(json.dumps({
        "n": len(takes), "scoreboard": summary, "generated_at_utc": _now_iso(),
    }, indent=2), encoding="utf-8")
    return doc


def build_hottakes_payload(root: Path) -> dict[str, Any]:
    cfg = load_hottakes_config(root)
    rows = load_ledger(root)
    live_rows = [r for r in rows if r.get("kind") != "backtested"]
    bt_path = hottakes_dir(root) / "backtested_summary.json"
    bt = _load_json(bt_path) or {}
    if not bt:
        try:
            bt = backfill_hottakes(root, cfg)
        except Exception as exc:
            bt = {"n": 0, "error": type(exc).__name__}
    tracker_st = _load_json(hottakes_dir(root) / "tracker_state.json") or {}
    payload = {
        "generated_at_utc": _now_iso(),
        "paper_only": True,
        "not_financial_advice": True,
        "caption": "Paper tracking only. Not financial advice.",
        "thresholds": cfg.get("rule"),
        "dedup_hours": cfg.get("dedup_hours"),
        "live_scoreboard": scoreboard(live_rows, kind="live"),
        "backtested_scoreboard": bt.get("scoreboard") or scoreboard([], kind="backtested"),
        "backtested_n": bt.get("n"),
        "takes": sorted(live_rows, key=lambda r: float(r.get("flagged_at") or 0), reverse=True)[:100],
        "tracker": tracker_st,
        "horizons_seconds": cfg.get("horizons_seconds"),
    }
    (hottakes_dir(root) / "latest_public.json").write_text(json.dumps({
        "generated_at_utc": payload["generated_at_utc"],
        "live_scoreboard": payload["live_scoreboard"],
        "backtested_scoreboard": payload["backtested_scoreboard"],
        "backtested_n": payload["backtested_n"],
        "n_live": len(live_rows),
        "thresholds": payload["thresholds"],
        "caption": payload["caption"],
    }, indent=2), encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- Tracker


class HotTakeTracker:
    """Background poller — never blocks the UI thread beyond starting."""

    def __init__(self, root: Path):
        self.root = root
        self.cfg = load_hottakes_config(root)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state: dict[str, Any] = {
            "running": False,
            "started_at_iso": None,
            "last_poll_iso": None,
            "last_error": None,
            "poll_interval_seconds": int((self.cfg.get("tracker") or {}).get("poll_interval_seconds") or 300),
            "helius_pages_this_hour": 0,
            "helius_hour_bucket": None,
            "credits_estimate_this_hour": 0,
            "credits_exhausted": False,
            "n_logged_session": 0,
            "wallet_cursor": 0,
            "next_poll_at": None,
            "next_poll_iso": None,
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.state["running"] = True
        self.state["started_at_iso"] = _now_iso()
        self._thread = threading.Thread(target=self._loop, name="hottake-tracker", daemon=True)
        self._thread.start()
        self._persist_state()

    def stop(self) -> None:
        self._stop.set()
        self.state["running"] = False
        self._persist_state()

    def _persist_state(self) -> None:
        try:
            (hottakes_dir(self.root) / "tracker_state.json").write_text(
                json.dumps(self.state, indent=2, default=str), encoding="utf-8"
            )
        except Exception:
            pass

    def _budget_tick(self, pages: int) -> None:
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        if self.state.get("helius_hour_bucket") != hour:
            self.state["helius_hour_bucket"] = hour
            self.state["helius_pages_this_hour"] = 0
            self.state["credits_estimate_this_hour"] = 0
        self.state["helius_pages_this_hour"] = int(self.state.get("helius_pages_this_hour") or 0) + pages
        per = int((self.cfg.get("helius") or {}).get("estimated_credits_per_page") or 100)
        self.state["credits_estimate_this_hour"] = int(self.state["helius_pages_this_hour"]) * per

    def _fetch_fresh_events(self) -> list[dict[str, Any]]:
        """Pull a small rotating set of enhanced SWAP pages for top wallets."""
        from trenchnet.helius_client import HeliusClient, HeliusLimitError, parse_enhanced_swap, helius_configured

        if not helius_configured():
            return []
        if self.state.get("credits_exhausted"):
            return []
        hcfg = self.cfg.get("helius") or {}
        max_w = int(hcfg.get("max_wallets_per_poll") or 5)
        max_pages = int(hcfg.get("max_pages_per_wallet") or 1)
        scores = _load_json(self.root / "out" / "scores.json") or {}
        min_score = float((self.cfg.get("rule") or {}).get("min_wallet_score") or 0.55)
        addrs = list(_top_wallet_addrs(scores, min_score).keys())
        if not addrs:
            # fall back to roster
            try:
                from trenchnet.config_load import load_roster
                addrs = [w["address"] for w in (load_roster().get("wallets") or []) if w.get("address")]
            except Exception:
                addrs = []
        if not addrs:
            return []
        cur = int(self.state.get("wallet_cursor") or 0) % len(addrs)
        batch = []
        for i in range(max_w):
            batch.append(addrs[(cur + i) % len(addrs)])
        self.state["wallet_cursor"] = (cur + max_w) % len(addrs)

        events: list[dict[str, Any]] = []
        pages = 0
        try:
            client = HeliusClient(sleep_ms=int(hcfg.get("sleep_ms") or 350))
        except Exception as exc:
            self.state["last_error"] = f"helius_init:{type(exc).__name__}"
            return []
        try:
            for addr in batch:
                if self._stop.is_set():
                    break
                before = None
                for _ in range(max_pages):
                    try:
                        page = client.fetch_enhanced_page(addr, before=before, limit=50, source="PUMP_FUN")
                    except HeliusLimitError:
                        self.state["credits_exhausted"] = True
                        self.state["last_error"] = "helius_credits_exhausted"
                        break
                    except Exception as exc:
                        self.state["last_error"] = f"fetch:{type(exc).__name__}"
                        break
                    pages += 1
                    if not page:
                        break
                    for tx in page:
                        for ev in parse_enhanced_swap(tx, addr):
                            events.append(ev.to_dict() if hasattr(ev, "to_dict") else dict(ev.__dict__))
                    before = page[-1].get("signature")
                    if not before:
                        break
                if self.state.get("credits_exhausted"):
                    break
        finally:
            self._budget_tick(pages)
        return events

    def _merge_events(self, fresh: list[dict[str, Any]]) -> list[dict[str, Any]]:
        base = load_all_history_events(self.root)
        seen = {(e.get("wallet"), e.get("signature"), e.get("token_mint"), e.get("side")) for e in base}
        for e in fresh:
            key = (e.get("wallet"), e.get("signature"), e.get("token_mint"), e.get("side"))
            if key in seen:
                continue
            seen.add(key)
            base.append(e)
        # also persist a small fresh cache (gitignored under data/hottakes)
        if fresh:
            cache = hottakes_dir(self.root) / "fresh_events.jsonl"
            with cache.open("a", encoding="utf-8") as f:
                for e in fresh:
                    f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
        return base

    def poll_once(self) -> dict[str, Any]:
        cfg = load_hottakes_config(self.root)
        self.cfg = cfg
        bt_cfg = load_backtest_config(self.root)
        dedup_h = float(cfg.get("dedup_hours") or 6)

        fresh = []
        try:
            fresh = self._fetch_fresh_events()
        except Exception as exc:
            self.state["last_error"] = f"fresh:{type(exc).__name__}"

        try:
            events = self._merge_events(fresh)
        except Exception:
            events = load_all_history_events(self.root)

        existing = load_ledger(self.root)
        # Resume/update open takes
        families = _price_families(self.root, events)
        changed = False
        for i, row in enumerate(existing):
            if row.get("kind") == "backtested":
                continue
            if row.get("status") == "closed" and all(
                (row.get("outcomes") or {}).get(str(h), {}).get("result")
                for h in (cfg.get("horizons_seconds") or [900, 3600, 14400, 86400])
            ):
                continue
            existing[i] = update_take_outcomes(row, families, cfg=cfg, bt_cfg=bt_cfg)
            changed = True

        # New signals
        cands = evaluate_hot_take_signals(self.root, events, cfg=cfg)
        new_ones = dedupe_new_takes(cands, existing, dedup_hours=dedup_h)
        # Live-only: ignore stale historical clusters (backfill covers those)
        max_age = float((cfg.get("tracker") or {}).get("max_flag_age_seconds") or 21600)  # 6h
        now = _now_ts()
        new_ones = [c for c in new_ones if (now - float(c.get("flagged_at") or 0)) <= max_age]
        logged = 0
        for c in new_ones:
            if c.get("entry_price") is None:
                # still log but mark entry missing — outcomes will be UNPRICED
                pass
            row = dict(c)
            row["kind"] = "live"
            row["logged_at_iso"] = _now_iso()
            row["id"] = f"{row.get('token_mint')}:{row.get('flagged_at')}"
            existing.append(row)
            logged += 1
            self.state["n_logged_session"] = int(self.state.get("n_logged_session") or 0) + 1

        if changed or logged:
            rewrite_ledger(self.root, existing)

        self.state["last_poll_iso"] = _now_iso()
        interval = int((cfg.get("tracker") or {}).get("poll_interval_seconds") or 300)
        self.state["poll_interval_seconds"] = interval
        self.state["next_poll_at"] = _now_ts() + interval
        self.state["next_poll_iso"] = _iso(self.state["next_poll_at"])
        self.state["last_fresh_events"] = len(fresh)
        self.state["last_new_takes"] = logged
        self._persist_state()
        return {"fresh": len(fresh), "new_takes": logged, "open": sum(1 for r in existing if r.get("status") == "open" and r.get("kind") != "backtested")}

    def _loop(self) -> None:
        # Ensure backfill exists once
        try:
            bp = hottakes_dir(self.root) / "backtested_summary.json"
            if not bp.exists():
                backfill_hottakes(self.root, self.cfg)
        except Exception as exc:
            self.state["last_error"] = f"backfill:{type(exc).__name__}"
        # Initial poll
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                self.state["last_error"] = f"poll:{type(exc).__name__}:{exc}"
                self.state["last_traceback"] = traceback.format_exc()[-500:]
                self._persist_state()
            interval = int((self.cfg.get("tracker") or {}).get("poll_interval_seconds") or 300)
            self.state["poll_interval_seconds"] = interval
            # sleep in chunks so stop is responsive
            for _ in range(max(1, interval)):
                if self._stop.is_set():
                    break
                time.sleep(1)
        self.state["running"] = False
        self._persist_state()


_TRACKER: HotTakeTracker | None = None
_TRACKER_LOCK = threading.Lock()


def ensure_tracker(root: Path) -> HotTakeTracker:
    global _TRACKER
    with _TRACKER_LOCK:
        if _TRACKER is None:
            _TRACKER = HotTakeTracker(root)
        cfg = load_hottakes_config(root)
        if (cfg.get("tracker") or {}).get("enabled", True):
            _TRACKER.start()
        return _TRACKER


def get_tracker() -> HotTakeTracker | None:
    return _TRACKER
