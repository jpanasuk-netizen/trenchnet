"""Pre-trade gates for LIVE — same spirit as paper hygiene. Fail-closed."""
from __future__ import annotations

from typing import Any


def evaluate_live_order(
    *,
    side: str,
    sol_amount: float,
    slippage_pct: float,
    priority_fee_lamports: int,
    state: dict[str, Any],
    open_positions: int = 0,
    gate_veto: bool = False,
    hygiene_ok: bool = True,
) -> dict[str, Any]:
    """Return {ok, reason}. Never sends. Caps default 0 = block."""
    if state.get("kill_switch"):
        return {"ok": False, "reason": "kill_switch"}
    if not state.get("armed"):
        return {"ok": False, "reason": "disarmed"}
    lim = state.get("limits") or {}
    max_sol = float(lim.get("max_sol_per_trade") or 0)
    daily_cap = float(lim.get("daily_loss_cap_sol") or 0)
    max_trades = int(lim.get("max_trades_per_day") or 0)
    max_open = int(lim.get("max_open_positions") or 0)
    max_slip = float(lim.get("max_slippage_pct") or 0)
    max_prio = int(lim.get("max_priority_fee_lamports") or 0)

    if max_sol <= 0 or daily_cap <= 0 or max_trades <= 0 or max_open <= 0 or max_slip <= 0 or max_prio <= 0:
        return {"ok": False, "reason": "caps_zero_disarmed"}
    if sol_amount <= 0:
        return {"ok": False, "reason": "amount_zero"}
    if sol_amount > max_sol:
        return {"ok": False, "reason": "over_max_sol_per_trade"}
    if slippage_pct > max_slip:
        return {"ok": False, "reason": "over_max_slippage"}
    if priority_fee_lamports > max_prio:
        return {"ok": False, "reason": "over_max_priority_fee"}
    if int(state.get("day_trade_count") or 0) >= max_trades:
        return {"ok": False, "reason": "max_trades_per_day"}
    if float(state.get("day_realized_pnl_sol") or 0) <= -abs(daily_cap):
        return {"ok": False, "reason": "daily_loss_cap"}
    if open_positions >= max_open and side == "buy":
        return {"ok": False, "reason": "max_open_positions"}
    if gate_veto or not hygiene_ok:
        return {"ok": False, "reason": "hygiene_veto"}
    return {"ok": True, "reason": "passed"}
