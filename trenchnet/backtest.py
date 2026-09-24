"""Pass 5 copy-trade backtest + walk-forward (paper / analysis only).

Never invents prices: missing data => unpriceable. Every figure is tagged
with its price source (helius / birdeye / rpc / derived).
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

STABLE_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "So11111111111111111111111111111111111111112",
}


@dataclass
class PricePoint:
    t: int
    px: float  # price units (SOL/token derived, or USD close from birdeye)
    source: str  # birdeye | derived | helius | rpc


@dataclass
class CopyTradeResult:
    wallet: str
    token_mint: str
    buy_sig: str
    buy_time: int
    delay_s: int
    exit_mode: str
    entry_px: float | None
    exit_px: float | None
    entry_source: str
    exit_source: str
    position_sol: float
    gross_return: float | None
    net_return: float | None
    pnl_sol: float | None
    costs_sol: float | None
    unpriceable: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_backtest_config(root: Path) -> dict[str, Any]:
    p = root / "config" / "backtest.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def load_all_history_events(root: Path) -> list[dict[str, Any]]:
    hdir = root / "data" / "raw" / "history"
    out: list[dict[str, Any]] = []
    if not hdir.is_dir():
        return out
    for fp in sorted(hdir.glob("*.json")):
        try:
            st = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        primary = st.get("source_primary") or ""
        for e in st.get("events") or []:
            if not isinstance(e, dict):
                continue
            row = dict(e)
            if not row.get("source"):
                row["source"] = primary or "rpc"
            row.setdefault("wallet", st.get("wallet") or fp.stem)
            out.append(row)
    seen: set[tuple] = set()
    deduped: list[dict[str, Any]] = []
    for e in out:
        key = (e.get("wallet"), e.get("signature"), e.get("token_mint"), e.get("side"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return deduped


def build_derived_price_index(events: Iterable[dict[str, Any]]) -> dict[str, list[PricePoint]]:
    idx: dict[str, list[PricePoint]] = {}
    for e in events:
        mint = e.get("token_mint") or ""
        if not mint or mint in STABLE_MINTS:
            continue
        sol = _safe_float(e.get("amount_sol"))
        tok = _safe_float(e.get("amount_token"))
        t = e.get("block_time")
        if sol is None or tok is None or not t or tok <= 0 or sol <= 0:
            continue
        idx.setdefault(mint, []).append(PricePoint(int(t), sol / tok, "derived"))
    for mint, pts in idx.items():
        pts.sort(key=lambda p: p.t)
    return idx


def load_birdeye_ohlcv(root: Path) -> dict[str, list[PricePoint]]:
    """Birdeye OHLCV closes. Relative returns used (USD ratios ~= SOL ratios)."""
    bdir = root / "data" / "raw" / "birdeye"
    out: dict[str, list[PricePoint]] = {}
    if not bdir.is_dir():
        return out
    for fp in bdir.glob("*.birdeye.json"):
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        mint = doc.get("mint") or fp.name.split(".")[0]
        if mint in STABLE_MINTS:
            continue
        candles = ((doc.get("ohlcv") or {}).get("candles")) or []
        pts: list[PricePoint] = []
        for c in candles:
            if not isinstance(c, dict):
                continue
            t = c.get("unixTime") or c.get("t")
            px = _safe_float(c.get("c") if c.get("c") is not None else c.get("close"))
            if t is None or px is None or px <= 0:
                continue
            pts.append(PricePoint(int(t), float(px), "birdeye"))
        pts.sort(key=lambda p: p.t)
        if pts:
            out[mint] = pts
    return out


def merge_price_indexes(
    birdeye: dict[str, list[PricePoint]],
    derived: dict[str, list[PricePoint]],
) -> dict[str, list[PricePoint]]:
    """Per mint, use ONE unit system only.

    Birdeye OHLCV is USD; derived trade prices are SOL/token. Mixing them
    invents nonsense returns — never merge across sources on the same mint.
    Prefer derived when it has >=2 points (enough for entry+exit); else birdeye.
    """
    mints = set(birdeye) | set(derived)
    merged: dict[str, list[PricePoint]] = {}
    for m in mints:
        d = list(derived.get(m) or [])
        b = list(birdeye.get(m) or [])
        if len(d) >= 2:
            d.sort(key=lambda p: p.t)
            merged[m] = d
        elif len(b) >= 1:
            b.sort(key=lambda p: p.t)
            merged[m] = b
        elif d:
            d.sort(key=lambda p: p.t)
            merged[m] = d
    return merged


def price_at(
    series: list[PricePoint],
    t: int,
    *,
    max_gap_s: int = 60,
    allow_before: bool = False,
) -> tuple[float | None, str]:
    """Price lookup.

    Default (Pass 6): nearest trade at or AFTER t within max_gap_s (no lookahead).
    allow_before=True restores legacy nearest-before behavior for tests that need it.
    """
    if not series:
        return None, ""
    if allow_before:
        lo, hi = 0, len(series) - 1
        best_le: PricePoint | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if series[mid].t <= t:
                best_le = series[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        if best_le is not None and (t - best_le.t) <= max_gap_s:
            return best_le.px, best_le.source
        idx = lo
        if idx < len(series) and (series[idx].t - t) <= max_gap_s:
            return series[idx].px, series[idx].source
        return None, ""
    # at-or-after only
    lo, hi = 0, len(series) - 1
    best_ge: PricePoint | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid].t >= t:
            best_ge = series[mid]
            hi = mid - 1
        else:
            lo = mid + 1
    if best_ge is not None and (best_ge.t - t) <= max_gap_s:
        return best_ge.px, best_ge.source
    return None, ""


def liquidity_proxy(events: list[dict[str, Any]], mint: str, t: int, window_s: int = 1800) -> float | None:
    sols = []
    for e in events:
        if e.get("token_mint") != mint:
            continue
        bt = e.get("block_time")
        if bt is None or abs(int(bt) - t) > window_s:
            continue
        s = _safe_float(e.get("amount_sol"))
        if s is not None and s > 0:
            sols.append(s)
    if not sols:
        return None
    return float(statistics.median(sols))


def apply_costs(
    position_sol: float,
    gross_return: float,
    *,
    liq: float | None,
    cfg: dict[str, Any],
    slippage_mult: float = 1.0,
) -> tuple[float, float]:
    costs = cfg.get("costs") or {}
    fee_bps = float(costs.get("pumpfun_fee_bps", 100))
    prio = float(costs.get("priority_fee_sol", 0.00005))
    slip_base = float(costs.get("slippage_base_bps", 50))
    slip_max = float(costs.get("slippage_max_bps", 800))
    slip_ref = float(costs.get("slippage_liquidity_ref_sol", 1.0)) or 1.0
    if liq is None or liq <= 0:
        slip_bps = slip_max
    else:
        scale = max(0.25, min(8.0, slip_ref / liq))
        slip_bps = min(slip_max, slip_base * scale)
    slip_bps *= max(0.0, float(slippage_mult))
    fee_frac = fee_bps / 10_000.0
    slip_frac = slip_bps / 10_000.0
    entry_cost = position_sol * (fee_frac + slip_frac)
    exit_notional = position_sol * (1.0 + gross_return)
    exit_cost = abs(exit_notional) * (fee_frac + slip_frac)
    costs_sol = entry_cost + exit_cost + 2.0 * prio
    pnl_net = position_sol * gross_return - costs_sol
    net_return = pnl_net / position_sol if position_sol else 0.0
    return float(net_return), float(costs_sol)


def _pair_buys_sells(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_wm: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in events:
        mint = e.get("token_mint") or ""
        wallet = e.get("wallet") or ""
        if not mint or not wallet or mint in STABLE_MINTS:
            continue
        if e.get("side") not in ("buy", "sell"):
            continue
        if e.get("block_time") is None:
            continue
        by_wm.setdefault((wallet, mint), []).append(e)
    pairs: list[dict[str, Any]] = []
    for (wallet, mint), evs in by_wm.items():
        evs.sort(key=lambda x: int(x.get("block_time") or 0))
        open_buys: list[dict[str, Any]] = []
        for e in evs:
            if e.get("side") == "buy":
                open_buys.append(e)
            elif e.get("side") == "sell" and open_buys:
                b = open_buys.pop(0)
                pairs.append({"wallet": wallet, "token_mint": mint, "buy": b, "sell": e})
        for b in open_buys:
            pairs.append({"wallet": wallet, "token_mint": mint, "buy": b, "sell": None})
    return pairs


def simulate_copy_trade(
    pair: dict[str, Any],
    *,
    delay_s: int,
    exit_mode: str,
    prices: dict[str, list[PricePoint]],
    all_events: list[dict[str, Any]],
    cfg: dict[str, Any],
    position_sol: float | None = None,
    slippage_mult: float = 1.0,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    time_stop_seconds: int | None = None,
    families: dict[str, dict[str, list[PricePoint]]] | None = None,
) -> CopyTradeResult:
    buy = pair["buy"]
    sell = pair.get("sell")
    wallet = pair["wallet"]
    mint = pair["token_mint"]
    buy_t = int(buy["block_time"])
    pos = float(position_sol if position_sol is not None else (cfg.get("position") or {}).get("size_sol", 0.25))
    exits = cfg.get("exits") or {}
    tp = float(take_profit_pct if take_profit_pct is not None else exits.get("take_profit_pct", 0.50))
    sl = float(stop_loss_pct if stop_loss_pct is not None else exits.get("stop_loss_pct", 0.25))
    tstop = int(time_stop_seconds if time_stop_seconds is not None else exits.get("time_stop_seconds", 3600))

    entry_t = buy_t + int(delay_s)
    pricing_cfg = cfg.get("pricing") or {}
    max_staleness = int(pricing_cfg.get("max_staleness_seconds", 60))
    mode_out = exit_mode

    fams = families
    if fams is None:
        fams = {"derived": prices, "helius_pool": {}, "birdeye": {}}

    if exit_mode == "mirror":
        if not (sell and sell.get("block_time") is not None):
            return CopyTradeResult(
                wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                buy_time=buy_t, delay_s=delay_s, exit_mode=exit_mode,
                entry_px=None, exit_px=None, entry_source="", exit_source="",
                position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                costs_sol=None, unpriceable=True, reason="no_mirror_sell",
            )
        exit_t = int(sell["block_time"]) + int(delay_s)
        if exit_t <= entry_t:
            exit_t = entry_t + 1
        entry_px, exit_px, entry_src, exit_src = lookup_entry_exit(
            mint, entry_t, exit_t, fams, max_staleness_s=max_staleness,
        )
        if entry_px is None or exit_px is None:
            return CopyTradeResult(
                wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                buy_time=buy_t, delay_s=delay_s, exit_mode=exit_mode,
                entry_px=entry_px, exit_px=exit_px, entry_source=entry_src or "", exit_source=exit_src or "",
                position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                costs_sol=None, unpriceable=True,
                reason="no_entry_price" if entry_px is None else "no_exit_price_mirror",
            )
    else:
        entry_px = None
        entry_src = ""
        series: list[PricePoint] = []
        for fam in ("helius_pool", "derived", "birdeye"):
            series = (fams.get(fam) or {}).get(mint) or []
            entry_px, entry_src = price_at(series, entry_t, max_gap_s=max_staleness)
            if entry_px is not None:
                break
        if entry_px is None:
            return CopyTradeResult(
                wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                buy_time=buy_t, delay_s=delay_s, exit_mode=exit_mode,
                entry_px=None, exit_px=None, entry_source="", exit_source="",
                position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                costs_sol=None, unpriceable=True, reason="no_entry_price",
            )
        deadline = entry_t + tstop
        hit = None
        for pt in series:
            if pt.t < entry_t:
                continue
            if pt.t > deadline:
                break
            ret = (pt.px / entry_px) - 1.0
            if ret >= tp:
                hit = (pt, "take_profit")
                break
            if ret <= -sl:
                hit = (pt, "stop_loss")
                break
        if hit:
            exit_px, exit_src = hit[0].px, hit[0].source
            mode_out = f"fixed:{hit[1]}"
        else:
            exit_px, exit_src = price_at(series, deadline, max_gap_s=max_staleness)
            mode_out = "fixed:time_stop"
            if exit_px is None and entry_src != "birdeye":
                for fam in ("helius_pool", "derived"):
                    alt = (fams.get(fam) or {}).get(mint) or []
                    exit_px, exit_src = price_at(alt, deadline, max_gap_s=max_staleness)
                    if exit_px is not None:
                        break
            if exit_px is None:
                return CopyTradeResult(
                    wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                    buy_time=buy_t, delay_s=delay_s, exit_mode=mode_out,
                    entry_px=entry_px, exit_px=None, entry_source=entry_src, exit_source="",
                    position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                    costs_sol=None, unpriceable=True, reason="no_exit_price_fixed",
                )

    gross = (exit_px / entry_px) - 1.0
    # Data-quality gate: |return| > 10x is almost always a bad mark (dust tick), not alpha.
    if abs(gross) > 10.0:
        return CopyTradeResult(
            wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
            buy_time=buy_t, delay_s=delay_s, exit_mode=mode_out,
            entry_px=entry_px, exit_px=exit_px, entry_source=entry_src, exit_source=exit_src,
            position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
            costs_sol=None, unpriceable=True, reason="outlier_return",
        )
    liq = liquidity_proxy(all_events, mint, entry_t)
    net_ret, costs_sol = apply_costs(pos, gross, liq=liq, cfg=cfg, slippage_mult=slippage_mult)
    pnl = pos * net_ret
    return CopyTradeResult(
        wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
        buy_time=buy_t, delay_s=delay_s, exit_mode=mode_out,
        entry_px=entry_px, exit_px=exit_px, entry_source=entry_src, exit_source=exit_src,
        position_sol=pos, gross_return=gross, net_return=net_ret, pnl_sol=pnl,
        costs_sol=costs_sol, unpriceable=False,
    )


def _sharpe_like(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mu = statistics.mean(returns)
    sd = statistics.pstdev(returns)
    if sd <= 1e-12:
        return None
    return mu / sd * math.sqrt(len(returns))


def _max_drawdown(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    eq = 0.0
    peak = 0.0
    mdd = 0.0
    for x in pnls:
        eq += x
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    return float(mdd)


def summarize_wallet_results(results: list[CopyTradeResult]) -> dict[str, Any]:
    priced = [r for r in results if not r.unpriceable and r.net_return is not None]
    unp = [r for r in results if r.unpriceable]
    total = len(results)
    coverage = (len(priced) / total * 100.0) if total else 0.0
    rets = [float(r.net_return) for r in priced]
    pnls = [float(r.pnl_sol or 0.0) for r in priced]
    wins = sum(1 for r in rets if r > 0)
    priced_sorted = sorted(priced, key=lambda r: (r.buy_time, r.delay_s))
    pnl_path = [float(r.pnl_sol or 0.0) for r in priced_sorted]
    sources: dict[str, int] = {}
    for r in priced:
        sources[r.entry_source] = sources.get(r.entry_source, 0) + 1
    sh = _sharpe_like(rets)
    return {
        "n_copies": total,
        "n_priced": len(priced),
        "n_unpriceable": len(unp),
        "coverage_pct": round(coverage, 2),
        "win_rate": round(wins / len(rets), 4) if rets else None,
        "median_return": round(statistics.median(rets), 6) if rets else None,
        "mean_return": round(statistics.mean(rets), 6) if rets else None,
        "total_pnl_sol": round(sum(pnls), 6) if pnls else 0.0,
        "max_drawdown_sol": round(_max_drawdown(pnl_path), 6),
        "sharpe_like": round(sh, 4) if sh is not None else None,
        "price_sources": sources,
    }


def delay_decay_table(by_delay: dict[int, list[CopyTradeResult]]) -> list[dict[str, Any]]:
    rows = []
    for d in sorted(by_delay):
        s = summarize_wallet_results(by_delay[d])
        s["delay_s"] = d
        rows.append(s)
    return rows


def _wallet_labels(root: Path) -> dict[str, str]:
    try:
        from trenchnet.config_load import load_roster
        roster = load_roster()
        return {
            w["address"]: w.get("label") or w["address"][:8]
            for w in (roster.get("wallets") or [])
            if w.get("address")
        }
    except Exception:
        return {}



def load_helius_pool_pricepoints(root: Path) -> dict[str, list[PricePoint]]:
    """SOL/token series from Pass 6 pool reconstruction cache."""
    try:
        from trenchnet.pool_prices import load_pool_price_index
    except Exception:
        return {}
    raw = load_pool_price_index(root)
    out: dict[str, list[PricePoint]] = {}
    for mint, series in raw.items():
        out[mint] = [PricePoint(t=int(t), px=float(px), source="helius_pool") for t, px in series]
    return out


def lookup_entry_exit(
    mint: str,
    t_entry: int,
    t_exit: int,
    families: dict[str, dict[str, list[PricePoint]]],
    *,
    max_staleness_s: int,
) -> tuple[float | None, float | None, str, str]:
    """Lookup entry then exit without mixing USD and SOL families.

    Order: helius_pool → derived → birdeye. Cross-SOL (pool↔derived) allowed
    only if the preferred family misses one side. Birdeye (USD) only with itself.
    """
    order = ["helius_pool", "derived", "birdeye"]
    # same-family first
    for fam in order:
        series = (families.get(fam) or {}).get(mint) or []
        e_px, e_src = price_at(series, t_entry, max_gap_s=max_staleness_s)
        x_px, x_src = price_at(series, t_exit, max_gap_s=max_staleness_s)
        if e_px is not None and x_px is not None:
            return e_px, x_px, e_src or fam, x_src or fam
    # cross SOL only
    for ef in ("helius_pool", "derived"):
        for xf in ("helius_pool", "derived"):
            if ef == xf:
                continue
            es = (families.get(ef) or {}).get(mint) or []
            xs = (families.get(xf) or {}).get(mint) or []
            e_px, e_src = price_at(es, t_entry, max_gap_s=max_staleness_s)
            x_px, x_src = price_at(xs, t_exit, max_gap_s=max_staleness_s)
            if e_px is not None and x_px is not None:
                return e_px, x_px, e_src or ef, x_src or xf
    return None, None, "", ""


def run_walk_forward(
    pairs: list[dict[str, Any]],
    prices: dict[str, list[PricePoint]],
    events: list[dict[str, Any]],
    cfg: dict[str, Any],
    families: dict[str, dict[str, list[PricePoint]]] | None = None,
) -> dict[str, Any]:
    wf = cfg.get("walk_forward") or {}
    min_train = int(wf.get("min_train_trades", 30))
    min_test = int(wf.get("min_test_trades", 15))
    min_span_days = float(wf.get("min_span_days", 7))
    n_folds = int(wf.get("n_folds", 3))

    times = [int(p["buy"]["block_time"]) for p in pairs if p.get("buy") and p["buy"].get("block_time")]
    if len(times) < (min_train + min_test):
        return {
            "status": "insufficient_data",
            "reason": f"only {len(times)} paired buys; need >= {min_train + min_test}",
            "n_pairs": len(times),
        }
    tmin, tmax = min(times), max(times)
    span_days = (tmax - tmin) / 86400.0
    if span_days < min_span_days:
        return {
            "status": "insufficient_data",
            "reason": (
                f"time span {span_days:.2f} days < min_span_days {min_span_days}; "
                "cannot form honest train/test without lookahead"
            ),
            "span_days": round(span_days, 3),
            "t_min": tmin,
            "t_max": tmax,
            "n_pairs": len(times),
        }

    cuts = [tmin + (tmax - tmin) * i / (n_folds + 1) for i in range(1, n_folds + 1)]
    fold_reports = []
    flagged: dict[str, int] = {}

    for cut in cuts:
        train_pairs = [p for p in pairs if int(p["buy"]["block_time"]) < cut]
        test_pairs = [p for p in pairs if int(p["buy"]["block_time"]) >= cut]
        if len(train_pairs) < min_train or len(test_pairs) < min_test:
            continue

        def wallet_pnl(plist: list[dict[str, Any]]) -> dict[str, float]:
            acc: dict[str, float] = {}
            for p in plist:
                r = simulate_copy_trade(
                    p, delay_s=60, exit_mode="fixed", prices=prices, all_events=events, cfg=cfg,
                    families=families,
                )
                if r.unpriceable or r.pnl_sol is None:
                    continue
                acc[r.wallet] = acc.get(r.wallet, 0.0) + float(r.pnl_sol)
            return acc

        tr = wallet_pnl(train_pairs)
        te = wallet_pnl(test_pairs)
        common = sorted(set(tr) & set(te))
        if len(common) < 3:
            fold_reports.append({
                "cut": int(cut),
                "n_train": len(train_pairs),
                "n_test": len(test_pairs),
                "common_wallets": len(common),
                "status": "insufficient_overlap",
            })
            continue
        train_rank = {w: i for i, w in enumerate(sorted(common, key=lambda w: tr[w], reverse=True))}
        test_rank = {w: i for i, w in enumerate(sorted(common, key=lambda w: te[w], reverse=True))}
        n = len(common)
        d2 = sum((train_rank[w] - test_rank[w]) ** 2 for w in common)
        spearman = 1.0 - (6.0 * d2) / (n * (n * n - 1)) if n > 1 else None
        for w in common:
            if train_rank[w] < n / 2 and test_rank[w] >= n / 2:
                flagged[w] = flagged.get(w, 0) + 1
        fold_reports.append({
            "cut": int(cut),
            "cut_iso": datetime.fromtimestamp(cut, tz=timezone.utc).isoformat(),
            "n_train": len(train_pairs),
            "n_test": len(test_pairs),
            "common_wallets": n,
            "spearman_rank": round(spearman, 4) if spearman is not None else None,
            "train_top3": sorted(common, key=lambda w: tr[w], reverse=True)[:3],
            "test_top3": sorted(common, key=lambda w: te[w], reverse=True)[:3],
        })

    if not fold_reports or all(f.get("spearman_rank") is None for f in fold_reports):
        return {
            "status": "insufficient_data",
            "reason": "time span ok but priced wallet overlap across train/test cuts is <3 (coverage too thin for honest OOS rank correlation)",
            "span_days": round(span_days, 3),
            "folds_attempted": fold_reports,
            "n_pairs": len(times),
        }

    spearman_vals = [f["spearman_rank"] for f in fold_reports if f.get("spearman_rank") is not None]
    return {
        "status": "ok",
        "span_days": round(span_days, 3),
        "folds": fold_reports,
        "mean_spearman": round(statistics.mean(spearman_vals), 4) if spearman_vals else None,
        "edge_disappeared_wallets": sorted(
            [{"wallet": w, "folds_flagged": n} for w, n in flagged.items()],
            key=lambda x: -x["folds_flagged"],
        )[:20],
        "note": "Train ranks use only trades strictly before cut; test uses at/after cut (no lookahead).",
    }


def run_backtest(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_backtest_config(root)
    events = load_all_history_events(root)
    derived = build_derived_price_index(events)
    birdeye = load_birdeye_ohlcv(root)
    pool = load_helius_pool_pricepoints(root)
    prices: dict[str, list[PricePoint]] = {}
    for m in set(pool) | set(derived):
        if m in pool and len(pool[m]) >= 1:
            prices[m] = pool[m]
        elif m in derived:
            prices[m] = derived[m]
    for m, series in birdeye.items():
        if m not in prices:
            prices[m] = series
    families = {
        "helius_pool": pool,
        "derived": derived,
        "birdeye": birdeye,
    }
    pairs = _pair_buys_sells(events)
    delays = list(cfg.get("delays_seconds") or [0, 30, 60, 120])
    exits_cfg = cfg.get("exits") or {}
    modes = []
    if exits_cfg.get("mirror_sell", True):
        modes.append("mirror")
    modes.append("fixed")

    per_trade: list[dict[str, Any]] = []
    all_results: list[CopyTradeResult] = []
    by_wallet_delay: dict[str, dict[int, list[CopyTradeResult]]] = {}

    for pair in pairs:
        mint = pair["token_mint"]
        series = prices.get(mint) or []
        buy = pair["buy"]
        buy_t = int(buy["block_time"])
        path = []
        for d in range(0, 121, 10):
            px, src = price_at(series, buy_t + d)
            if px is not None:
                path.append({"t": buy_t + d, "delay": d, "px": px, "source": src})
        # denser forward path for TP/SL browser sim (up to 1h every 60s)
        for d in range(180, 3601, 60):
            px, src = price_at(series, buy_t + d, max_gap_s=1800)
            if px is not None:
                path.append({"t": buy_t + d, "delay": d, "px": px, "source": src, "kind": "fwd"})
        sell = pair.get("sell")
        sell_t = int(sell["block_time"]) if sell and sell.get("block_time") is not None else None
        if sell_t is not None:
            for d in delays:
                px, src = price_at(series, sell_t + d)
                if px is not None:
                    path.append({"t": sell_t + d, "delay": None, "px": px, "source": src, "kind": "sell"})
        liq = liquidity_proxy(events, mint, buy_t)
        per_trade.append({
            "wallet": pair["wallet"],
            "token_mint": mint,
            "buy_sig": buy.get("signature"),
            "buy_time": buy_t,
            "sell_time": sell_t,
            "path": path,
            "liq_proxy_sol": liq,
            "buy_source": buy.get("source") or "",
        })

        for delay in delays:
            for mode in modes:
                r = simulate_copy_trade(
                    pair, delay_s=delay, exit_mode=mode, prices=prices,
                    all_events=events, cfg=cfg, families=families,
                )
                all_results.append(r)
                by_wallet_delay.setdefault(r.wallet, {}).setdefault(delay, []).append(r)

    wallet_rows = []
    labels = _wallet_labels(root)
    for wallet, dmap in sorted(by_wallet_delay.items()):
        delay_rows = {}
        for d, res in dmap.items():
            mir = [r for r in res if r.exit_mode == "mirror"]
            fix = [r for r in res if str(r.exit_mode).startswith("fixed")]
            delay_rows[str(d)] = {
                "mirror": summarize_wallet_results(mir),
                "fixed": summarize_wallet_results(fix),
                "all": summarize_wallet_results(res),
            }
        primary = delay_rows.get("60", {}).get("all") or summarize_wallet_results([])
        wallet_rows.append({
            "wallet": wallet,
            "label": labels.get(wallet) or wallet[:8],
            "delays": delay_rows,
            "copy_pnl_60s": primary.get("total_pnl_sol"),
            "win_rate_60s": primary.get("win_rate"),
            "coverage_60s": primary.get("coverage_pct"),
            "n_copies_60s": primary.get("n_copies"),
        })

    overall = summarize_wallet_results(all_results)

    # Pass 6: coverage by wallet and by token (priced / copies)
    cov_w: dict[str, dict[str, int]] = {}
    cov_t: dict[str, dict[str, int]] = {}
    for r in all_results:
        if r.delay_s != 60:
            continue
        for key, bucket in ((r.wallet, cov_w), (r.token_mint, cov_t)):
            b = bucket.setdefault(key, {"n": 0, "priced": 0})
            b["n"] += 1
            if not r.unpriceable:
                b["priced"] += 1
    coverage_by = {
        "wallets": [
            {
                "wallet": w,
                "n_copies_60s": v["n"],
                "n_priced_60s": v["priced"],
                "coverage_pct": round(100.0 * v["priced"] / v["n"], 2) if v["n"] else 0.0,
            }
            for w, v in sorted(cov_w.items(), key=lambda kv: -kv[1]["n"])
        ],
        "tokens": [
            {
                "token_mint": m,
                "n_copies_60s": v["n"],
                "n_priced_60s": v["priced"],
                "coverage_pct": round(100.0 * v["priced"] / v["n"], 2) if v["n"] else 0.0,
                "has_pool_series": m in pool,
            }
            for m, v in sorted(cov_t.items(), key=lambda kv: -kv[1]["n"])[:80]
        ],
    }

    out = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paper_only": True,
        "disclaimer": "PAPER / BACKTEST only. Not a promise of live returns. Costs are estimated.",
        "config": {
            "delays_seconds": delays,
            "position_size_sol": (cfg.get("position") or {}).get("size_sol"),
            "costs": cfg.get("costs"),
            "exits": cfg.get("exits"),
        },
        "n_events": len(events),
        "n_pairs": len(pairs),
        "n_results": len(all_results),
        "price_index": {
            "helius_pool_mints": len(pool),
            "birdeye_mints": len(birdeye),
            "derived_mints": len(derived),
            "merged_mints": len(prices),
            "source_tags": ["helius_pool", "helius", "birdeye", "rpc", "derived"],
            "max_staleness_seconds": int((cfg.get("pricing") or {}).get("max_staleness_seconds", 60)),
        },
        "overall": overall,
        "delay_decay": delay_decay_table({d: [r for r in all_results if r.delay_s == d] for d in delays}),
        "wallets": wallet_rows,
        "per_trade": per_trade,
        "walk_forward": run_walk_forward(pairs, prices, events, cfg, families=families),
        "coverage_by": coverage_by,
    }
    return out


def write_backtest_outputs(root: Path, result: dict[str, Any] | None = None) -> dict[str, str]:
    result = result or run_backtest(root)
    out_dir = root / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    full = out_dir / "backtest.json"
    full.write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary = {k: result[k] for k in result if k != "per_trade"}
    summary["per_trade_count"] = len(result.get("per_trade") or [])
    (out_dir / "backtest_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"backtest": str(full), "summary": str(out_dir / "backtest_summary.json")}
