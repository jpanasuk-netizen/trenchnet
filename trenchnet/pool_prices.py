"""Pass 6: reconstruct SOL/token prices from Helius pool-wide swaps.

Fetches enhanced transactions for each mint (all traders, not just roster),
builds tick series tagged helius_pool, resamples to compact bars, caches under
data/prices/. Never logs API keys. Stops gracefully on HeliusLimitError.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trenchnet.backtest import STABLE_MINTS, _safe_float, load_all_history_events, _pair_buys_sells
from trenchnet.helius_client import HeliusClient, HeliusLimitError, helius_configured

WSOL = "So11111111111111111111111111111111111111112"


@dataclass
class Tick:
    t: int
    px: float  # SOL per token
    sol: float
    token: float
    signature: str = ""
    source_tag: str = "helius_pool"


def prices_dir(root: Path) -> Path:
    d = root / "data" / "prices"
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_pool_ticks_from_tx(tx: dict[str, Any], mint: str) -> list[Tick]:
    """Derive SOL/token ticks from one enhanced tx involving mint.

    Amount math:
      - Prefer events.swap native SOL + token I/O for this mint.
      - Else match tokenTransfers for mint with the largest |nativeBalanceChange|.
    Decimals: Helius tokenAmount is already UI amount when present; rawTokenAmount
    uses decimals field.
    """
    if not isinstance(tx, dict) or not mint:
        return []
    sig = str(tx.get("signature") or "")
    ts = tx.get("timestamp") or tx.get("blockTime")
    try:
        t = int(ts) if ts is not None else None
    except Exception:
        t = None
    if t is None:
        return []

    # --- path A: structured swap event ---
    events = tx.get("events") if isinstance(tx.get("events"), dict) else {}
    swap = events.get("swap") if isinstance(events, dict) else None
    if isinstance(swap, dict):
        sol = None
        tok = None
        # buy token => nativeInput SOL, tokenOutputs mint
        for item in swap.get("tokenOutputs") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("mint") or item.get("tokenMint") or "") != mint:
                continue
            tok = _ui_amount(item)
            ni = swap.get("nativeInput") or {}
            if isinstance(ni, dict):
                sol = abs(_safe_float(ni.get("amount")) or 0) / 1e9
        # sell token => nativeOutput SOL, tokenInputs mint
        if tok is None:
            for item in swap.get("tokenInputs") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("mint") or item.get("tokenMint") or "") != mint:
                    continue
                tok = _ui_amount(item)
                no = swap.get("nativeOutput") or {}
                if isinstance(no, dict):
                    sol = abs(_safe_float(no.get("amount")) or 0) / 1e9
        if sol and tok and tok > 0 and sol >= 0.001:
            return [Tick(t=t, px=sol / tok, sol=sol, token=tok, signature=sig)]

    # --- path B: tokenTransfers + nativeBalanceChange ---
    token_amts: list[float] = []
    for tr in tx.get("tokenTransfers") or []:
        if not isinstance(tr, dict):
            continue
        if str(tr.get("mint") or "") != mint:
            continue
        amt = _safe_float(tr.get("tokenAmount") if tr.get("tokenAmount") is not None else tr.get("amount"))
        if amt is None:
            raw = tr.get("rawTokenAmount") or {}
            if isinstance(raw, dict):
                amt = _ui_from_raw(raw)
        if amt is not None and abs(amt) > 0:
            token_amts.append(abs(amt))
    if not token_amts:
        return []

    # largest absolute SOL movement in accountData (lamports)
    best_sol = 0.0
    for acc in tx.get("accountData") or []:
        if not isinstance(acc, dict):
            continue
        nc = _safe_float(acc.get("nativeBalanceChange"))
        if nc is None:
            continue
        sol = abs(nc) / 1e9
        if sol > best_sol:
            best_sol = sol
    # also consider nativeTransfers
    for n in tx.get("nativeTransfers") or []:
        if not isinstance(n, dict):
            continue
        amt = _safe_float(n.get("amount"))
        if amt is None:
            continue
        sol = abs(amt) / 1e9
        if sol > best_sol:
            best_sol = sol

    tok = max(token_amts)
    # Require meaningful SOL (filter dust/fee-only / rent)
    if best_sol < 0.001 or tok <= 0:
        return []
    return [Tick(t=t, px=best_sol / tok, sol=best_sol, token=tok, signature=sig)]


def _ui_amount(item: dict[str, Any]) -> float | None:
    raw = item.get("tokenAmount") or item.get("rawTokenAmount") or item.get("uiTokenAmount")
    if isinstance(raw, dict):
        return _ui_from_raw(raw)
    return _safe_float(raw)


def _ui_from_raw(raw: dict[str, Any]) -> float | None:
    if raw.get("uiAmount") is not None:
        return _safe_float(raw.get("uiAmount"))
    amt = _safe_float(raw.get("tokenAmount") or raw.get("amount"))
    if amt is None:
        return None
    try:
        dec = int(raw.get("decimals") or 0)
    except Exception:
        dec = 0
    return amt / (10 ** dec) if dec else amt


def resample_bars(ticks: list[Tick], interval_s: int) -> list[dict[str, Any]]:
    """OHLC-ish compact bars from ticks (open=first, high, low, close=last, vwapat)."""
    if not ticks or interval_s <= 0:
        return []
    buckets: dict[int, list[Tick]] = {}
    for tk in ticks:
        b = (tk.t // interval_s) * interval_s
        buckets.setdefault(b, []).append(tk)
    bars = []
    for b in sorted(buckets):
        xs = sorted(buckets[b], key=lambda z: z.t)
        px = [z.px for z in xs]
        vol_sol = sum(z.sol for z in xs)
        bars.append({
            "t": b,
            "o": px[0],
            "h": max(px),
            "l": min(px),
            "c": px[-1],
            "n": len(xs),
            "vol_sol": round(vol_sol, 9),
            "source": "helius_pool",
        })
    return bars


def mint_time_window(
    pairs: list[dict[str, Any]],
    mint: str,
    *,
    pre_s: int = 300,
    post_s: int = 3720,
    max_span_s: int = 172800,
) -> tuple[int, int] | None:
    """Window around tracked trades; clamp span so free-tier pages stay useful."""
    ts: list[int] = []
    for p in pairs:
        if p.get("token_mint") != mint:
            continue
        b = p.get("buy") or {}
        if b.get("block_time") is not None:
            ts.append(int(b["block_time"]))
        s = p.get("sell") or {}
        if s.get("block_time") is not None:
            ts.append(int(s["block_time"]))
    if not ts:
        return None
    t0, t1 = min(ts) - pre_s, max(ts) + post_s
    if (t1 - t0) > max_span_s:
        # keep the most recent max_span_s ending at t1
        t0 = t1 - max_span_s
    return t0, t1


def fetch_mint_pool_ticks(
    client: HeliusClient,
    mint: str,
    t_start: int,
    t_end: int,
    *,
    max_pages: int = 25,
    log: Callable[[str], None] | None = None,
) -> tuple[list[Tick], dict[str, Any]]:
    """Paginate enhanced SWAP txs for mint address; keep those in [t_start, t_end]."""
    log = log or (lambda m: None)
    ticks: list[Tick] = []
    before: str | None = None
    pages = 0
    empty_streak = 0
    meta: dict[str, Any] = {
        "mint": mint,
        "pages": 0,
        "txs": 0,
        "ticks": 0,
        "stopped": None,
        "t_start": t_start,
        "t_end": t_end,
    }
    seen_sig: set[str] = set()

    while pages < max_pages:
        try:
            # Prefer SWAP without source filter (Pump + Raydium/PumpSwap/OKX etc.)
            page = client.fetch_enhanced_page(
                mint, before=before, limit=100, tx_type="SWAP", source=None,
            )
        except HeliusLimitError as exc:
            meta["stopped"] = f"limit:{exc}"
            log(f"  limit stop mint={mint[:8]}…")
            raise
        pages += 1
        meta["pages"] = pages
        if not page:
            empty_streak += 1
            if empty_streak >= 2:
                meta["stopped"] = "empty_pages"
                break
            continue
        if len(page) == 1 and page[0].get("_continue_before"):
            before = page[0]["_continue_before"]
            continue
        empty_streak = 0
        oldest_on_page: int | None = None
        last_sig = None
        for tx in page:
            if not isinstance(tx, dict) or tx.get("_continue_before"):
                if isinstance(tx, dict) and tx.get("_continue_before"):
                    before = tx["_continue_before"]
                continue
            sig = tx.get("signature")
            if not sig or sig in seen_sig:
                continue
            seen_sig.add(sig)
            last_sig = sig
            meta["txs"] += 1
            ts = tx.get("timestamp") or tx.get("blockTime")
            try:
                t = int(ts) if ts is not None else None
            except Exception:
                t = None
            if t is not None:
                oldest_on_page = t if oldest_on_page is None else min(oldest_on_page, t)
            if t is not None and t > t_end:
                continue
            if t is not None and t < t_start:
                # past window — can stop after this page
                continue
            for tk in extract_pool_ticks_from_tx(tx, mint):
                ticks.append(tk)
        if last_sig:
            before = last_sig
        else:
            meta["stopped"] = "no_signature"
            break
        if oldest_on_page is not None and oldest_on_page < t_start:
            meta["stopped"] = "past_window"
            break
        if len(page) < 5:
            meta["stopped"] = "short_page"
            break

    ticks.sort(key=lambda z: z.t)
    # dedupe same second keep median-ish (last)
    by_t: dict[int, Tick] = {}
    for tk in ticks:
        by_t[tk.t] = tk
    ticks = [by_t[k] for k in sorted(by_t)]
    meta["ticks"] = len(ticks)
    return ticks, meta


def save_mint_cache(root: Path, mint: str, ticks: list[Tick], meta: dict[str, Any]) -> Path:
    d = prices_dir(root) / "helius_pool"
    d.mkdir(parents=True, exist_ok=True)
    bars_1s = resample_bars(ticks, 1)
    bars_5s = resample_bars(ticks, 5)
    bars_1m = resample_bars(ticks, 60)
    # Compact: keep 1s only if small; always keep 5s + 1m
    doc = {
        "mint": mint,
        "unit": "SOL_per_token",
        "source": "helius_pool",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "meta": meta,
        "n_ticks": len(ticks),
        # ticks truncated for cache size — bars are the commit-friendly form
        "ticks_sample": [asdict(t) for t in ticks[:20]],
        "bars_1s": bars_1s if len(bars_1s) <= 5000 else bars_1s[:: max(1, len(bars_1s)//4000)],
        "bars_5s": bars_5s,
        "bars_1m": bars_1m,
        # full tick timeseries compact: [t, px]
        "ticks_compact": [[t.t, round(t.px, 12)] for t in ticks],
    }
    path = d / f"{mint}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _clean_px_series(series: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Drop dust/outlier marks vs robust median (keeps SOL/token series coherent)."""
    if len(series) < 5:
        return series
    xs = sorted(p for _, p in series if p > 0)
    if not xs:
        return []
    med = xs[len(xs) // 2]
    if med <= 0:
        return series
    lo, hi = med / 50.0, med * 50.0
    cleaned = [(t, px) for t, px in series if lo <= px <= hi]
    return cleaned if len(cleaned) >= 3 else series


def load_pool_price_index(root: Path) -> dict[str, list[tuple[int, float]]]:
    """Load cached helius_pool ticks as (t, px) lists sorted by t."""
    d = prices_dir(root) / "helius_pool"
    out: dict[str, list[tuple[int, float]]] = {}
    if not d.is_dir():
        return out
    for fp in d.glob("*.json"):
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        mint = doc.get("mint") or fp.stem
        compact = doc.get("ticks_compact") or []
        series: list[tuple[int, float]] = []
        for row in compact:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                try:
                    series.append((int(row[0]), float(row[1])))
                except Exception:
                    continue
        if not series and doc.get("bars_1s"):
            for b in doc["bars_1s"]:
                try:
                    series.append((int(b["t"]), float(b["c"])))
                except Exception:
                    continue
        series.sort(key=lambda x: x[0])
        series = _clean_px_series(series)
        if series:
            out[mint] = series
    return out


def build_pool_prices_for_roster(
    root: Path,
    *,
    max_mints: int | None = None,
    max_pages_per_mint: int = 20,
    min_pairs: int = 1,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fetch pool prices for pair mints (priority by pair count)."""
    log = log or print
    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": [],
        "failed": [],
        "skipped": [],
        "stopped_early": None,
        "helius_configured": helius_configured(),
        "credits_note": None,
    }
    if not helius_configured():
        report["stopped_early"] = "HELIUS_API_KEY missing"
        return report

    events = load_all_history_events(root)
    pairs = _pair_buys_sells(events)
    from collections import Counter
    counts = Counter(p["token_mint"] for p in pairs if p.get("token_mint") and p["token_mint"] not in STABLE_MINTS)
    ranked = [m for m, n in counts.most_common() if n >= min_pairs]
    if max_mints is not None:
        ranked = ranked[: max_mints]
    report["mints_targeted"] = len(ranked)
    report["pair_mints_total"] = len(counts)

    client = HeliusClient(sleep_ms=350, max_retries=4)
    for i, mint in enumerate(ranked, 1):
        cache_fp = prices_dir(root) / "helius_pool" / f"{mint}.json"
        if cache_fp.exists():
            try:
                prev = json.loads(cache_fp.read_text(encoding="utf-8"))
                if int(prev.get("n_ticks") or 0) > 0:
                    report["ok"].append({"mint": mint, "ticks": prev.get("n_ticks"), "pages": (prev.get("meta") or {}).get("pages"), "stopped": "cached"})
                    log(f"[{i}/{len(ranked)}] skip cached {mint[:12]}… ticks={prev.get('n_ticks')}")
                    continue
            except Exception:
                pass
        win = mint_time_window(pairs, mint)
        if not win:
            report["skipped"].append({"mint": mint, "reason": "no_time_window"})
            continue
        t0, t1 = win
        log(f"[{i}/{len(ranked)}] pool fetch {mint[:12]}… pairs={counts[mint]} window={t1-t0}s")
        try:
            ticks, meta = fetch_mint_pool_ticks(
                client, mint, t0, t1, max_pages=max_pages_per_mint, log=log,
            )
            meta["pair_count"] = counts[mint]
            if ticks:
                save_mint_cache(root, mint, ticks, meta)
                report["ok"].append({"mint": mint, "ticks": len(ticks), "pages": meta.get("pages"), "stopped": meta.get("stopped")})
            else:
                report["failed"].append({"mint": mint, "reason": "no_ticks", "meta": meta})
        except HeliusLimitError as exc:
            report["stopped_early"] = f"HeliusLimitError:{exc}"
            report["credits_note"] = "graceful stop — free-tier/plan limit hit; partial cache kept"
            report["failed"].append({"mint": mint, "reason": "helius_limit"})
            break
        except Exception as exc:
            report["failed"].append({"mint": mint, "reason": type(exc).__name__, "detail": str(exc)[:160]})
    # summary file
    summary_path = prices_dir(root) / "pool_fetch_summary.json"
    summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["summary_path"] = str(summary_path)
    return report
