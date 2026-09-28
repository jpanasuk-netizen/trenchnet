"""Runner detection from real roster history + wallet scores.

A runner is 3+ wallets with score >= 0.40 buying the same mint inside 90s.
Jev entry bar is 0.50 on a runner and 0.68 otherwise.
"""
from __future__ import annotations

from typing import Any, Iterable

TOP_MIN_SCORE = 0.40
RUNNER_MIN_TOP = 3
RUNNER_WINDOW_S = 90.0
DEFAULT_JEV_THRESHOLD = 0.68
RUNNER_JEV_THRESHOLD = 0.50


def top_wallets_from_scores(scores: dict[str, Any], *, min_score: float = TOP_MIN_SCORE) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in scores.get("wallets") or []:
        addr = str(row.get("wallet") or "")
        if not addr:
            continue
        try:
            sc = float(row.get("score") or 0)
        except (TypeError, ValueError):
            continue
        if sc >= min_score:
            out[addr] = sc
    return out


def detect_runners(
    events: Iterable[dict[str, Any]],
    top_wallets: Iterable[str],
    *,
    window_s: float = RUNNER_WINDOW_S,
    min_top: int = RUNNER_MIN_TOP,
) -> list[dict[str, Any]]:
    allowed = {str(w) for w in top_wallets if w}
    by_mint: dict[str, list[tuple[float, str]]] = {}
    for ev in events:
        if str(ev.get("side") or "").lower() != "buy":
            continue
        mint = str(ev.get("token_mint") or "")
        wallet = str(ev.get("wallet") or "")
        try:
            ts = float(ev.get("block_time") or 0)
        except (TypeError, ValueError):
            ts = 0.0
        if not mint or not wallet or ts <= 0 or wallet not in allowed:
            continue
        by_mint.setdefault(mint, []).append((ts, wallet))

    found: list[dict[str, Any]] = []
    for mint, buys in by_mint.items():
        buys.sort()
        best_n = 0
        best_span = 0.0
        best_wallets: list[str] = []
        for i, (t0, _) in enumerate(buys):
            seen: set[str] = set()
            t_end = t0
            for ts, wallet in buys[i:]:
                if ts - t0 > window_s:
                    break
                seen.add(wallet)
                t_end = ts
            if len(seen) > best_n:
                best_n = len(seen)
                best_span = t_end - t0
                best_wallets = sorted(seen)
        if best_n >= min_top:
            tightness = 0.25 if best_span < 30 else 0.10
            score = min(0.95, 0.55 + 0.10 * (best_n - min_top) + tightness)
            found.append({
                "mint": mint,
                "n_top": best_n,
                "wallets": best_wallets[:8],
                "span_s": round(best_span, 1),
                "score": round(score, 3),
                "flagged_at": buys[-1][0],
                "kind": "runner",
            })
    found.sort(key=lambda r: (-float(r["score"]), -int(r["n_top"])))
    return found


def jev_threshold_for(mint: str, runners: Iterable[dict[str, Any]]) -> float:
    want = str(mint or "")
    for row in runners:
        if str(row.get("mint") or "") == want:
            return RUNNER_JEV_THRESHOLD
    return DEFAULT_JEV_THRESHOLD
