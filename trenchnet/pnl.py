
"""PnL and position metrics from parsed trades. Code-only math."""

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Iterable

from trenchnet.models import TradeEvent, WalletMetrics


def compute_wallet_metrics(
    wallet: str,
    label: str,
    events: Iterable[TradeEvent],
) -> WalletMetrics:
    evs = sorted(
        [e for e in events if e.wallet == wallet],
        key=lambda e: (e.block_time or 0, e.signature),
    )
    buys: dict[str, list[TradeEvent]] = defaultdict(list)
    realized = 0.0
    profit_by_token: dict[str, float] = defaultdict(float)
    hold_times: list[float] = []
    buy_sizes: list[float] = []
    cited: list[str] = []
    buy_count = sell_count = 0
    open_cost: dict[str, float] = defaultdict(float)
    open_qty: dict[str, float] = defaultdict(float)

    for e in evs:
        cited.append(e.signature)
        if e.side == "buy":
            buy_count += 1
            buys[e.token_mint].append(e)
            sol = float(e.amount_sol or 0.0)
            buy_sizes.append(sol)
            open_cost[e.token_mint] += sol
            open_qty[e.token_mint] += float(e.amount_token or 0.0)
        elif e.side == "sell":
            sell_count += 1
            sol_in = float(e.amount_sol or 0.0)
            qty = float(e.amount_token or 0.0)
            # FIFO-ish cost basis from open inventory
            if open_qty[e.token_mint] > 0 and qty > 0:
                frac = min(1.0, qty / open_qty[e.token_mint])
                cost = open_cost[e.token_mint] * frac
                pnl = sol_in - cost
                realized += pnl
                profit_by_token[e.token_mint] += pnl
                open_cost[e.token_mint] -= cost
                open_qty[e.token_mint] -= qty * frac
                # hold time vs earliest unmatched buy if available
                if buys[e.token_mint] and e.block_time and buys[e.token_mint][0].block_time:
                    hold_times.append(max(0, e.block_time - buys[e.token_mint][0].block_time))
            else:
                # no cost basis ? count proceeds as unresolved; do not invent PnL
                pass

    open_positions = sum(1 for m, q in open_qty.items() if q > 1e-9)
    positives = {k: v for k, v in profit_by_token.items() if v > 0}
    if positives:
        top = max(positives.values())
        total_pos = sum(positives.values())
        concentration = (top / total_pos) if total_pos > 0 else None
    else:
        concentration = None

    if len(evs) == 0:
        flag = "missing_history"
    elif len(evs) < 3:
        flag = "sparse"
    else:
        flag = "ok"

    # unique cite list preserving order
    uniq_cited: list[str] = []
    seen = set()
    for s in cited:
        if s not in seen:
            seen.add(s)
            uniq_cited.append(s)

    return WalletMetrics(
        wallet=wallet,
        label=label,
        trade_count=len(evs),
        buy_count=buy_count,
        sell_count=sell_count,
        realized_pnl_sol=round(realized, 6),
        open_positions=open_positions,
        typical_buy_size_sol=(round(median(buy_sizes), 6) if buy_sizes else None),
        median_hold_seconds=(round(median(hold_times), 1) if hold_times else None),
        profit_concentration=(round(concentration, 4) if concentration is not None else None),
        cited_signatures=uniq_cited[:20],
        history_flag=flag,
    )
