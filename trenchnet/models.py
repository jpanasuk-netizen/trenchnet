
"""Shared dataclasses for observe-only trade events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Side = Literal["buy", "sell", "transfer_in", "transfer_out", "unknown"]


@dataclass
class TradeEvent:
    signature: str
    wallet: str
    token_mint: str
    side: Side
    amount_token: float
    amount_sol: float | None
    slot: int | None
    block_time: int | None  # unix seconds
    program_id: str | None = None
    raw_note: str = ""
    source: str = ""  # helius | birdeye | rpc | cobuy | etc.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WalletMetrics:
    wallet: str
    label: str
    trade_count: int
    buy_count: int
    sell_count: int
    realized_pnl_sol: float
    open_positions: int
    typical_buy_size_sol: float | None
    median_hold_seconds: float | None
    profit_concentration: float | None  # share of profit from top winner
    cited_signatures: list[str] = field(default_factory=list)
    history_flag: str = "ok"  # ok | missing_history | sparse

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
