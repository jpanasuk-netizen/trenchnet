"""Single pre-trade gate for LIVE. Fail-closed. Unit-tested. No network here."""
from __future__ import annotations

from typing import Any

# Spec defaults (config may override; 0 in state.limits still means "not configured / block")
SPEC = {
    "max_sol_per_trade": 0.25,
    "max_open_positions": 4,
    "daily_loss_stop_sol": 2.0,
    "total_loss_kill_sol": 4.0,
    "fee_reserve_sol": 0.05,
    "max_buys_per_token": 1,
    "min_liquidity_sol": 5.0,
    "min_token_age_seconds": 300,
    "arm_min_balance_sol": 0.30,  # 0.25 + 0.05
}


def pre_trade_gate(
    *,
    side: str,
    sol_amount: float,
    token_mint: str | None = None,
    state: dict[str, Any],
    open_positions: int = 0,
    buys_this_token: int = 0,
    wallet_sol: float | None = None,
    token_liquidity_sol: float | None = None,
    token_age_seconds: float | None = None,
    mint_authority_revoked: bool | None = None,
    freeze_authority_revoked: bool | None = None,
    can_sell_ok: bool | None = None,
    kill_file_present: bool = False,
    hygiene_ok: bool = True,
    gate_veto: bool = False,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ONE gate before every order. Returns {ok, reason, checks}.

    Buys and sells both respect kill/disarm. Sell-all path uses a separate allow flag.
    """
    cfg = {**SPEC, **(cfg or {})}
    checks: dict[str, Any] = {}
    side = (side or "").lower()

    if kill_file_present or state.get("kill_switch"):
        return {"ok": False, "reason": "kill_switch", "checks": {"kill": True}}
    if gate_veto or not hygiene_ok:
        return {"ok": False, "reason": "hygiene_veto", "checks": {"hygiene_ok": hygiene_ok, "gate_veto": gate_veto}}
    if not state.get("armed"):
        return {"ok": False, "reason": "disarmed", "checks": {"armed": False}}

    lim = state.get("limits") or {}
    max_sol = float(lim.get("max_sol_per_trade") or 0) or float(cfg["max_sol_per_trade"])
    # If limits explicitly 0 → hard block (disarmed-default semantics)
    if float(lim.get("max_sol_per_trade") or 0) <= 0:
        return {"ok": False, "reason": "caps_zero_disarmed", "checks": {"max_sol_per_trade": 0}}

    max_open = int(lim.get("max_open_positions") or 0) or int(cfg["max_open_positions"])
    if int(lim.get("max_open_positions") or 0) <= 0:
        return {"ok": False, "reason": "caps_zero_disarmed", "checks": {"max_open_positions": 0}}

    daily_stop = float(lim.get("daily_loss_cap_sol") or lim.get("daily_loss_stop_sol") or 0) or float(cfg["daily_loss_stop_sol"])
    total_kill = float(lim.get("total_loss_kill_sol") or 0) or float(cfg["total_loss_kill_sol"])
    fee_reserve = float(lim.get("fee_reserve_sol") or 0) or float(cfg["fee_reserve_sol"])
    max_buys = int(lim.get("max_buys_per_token") or 0) or int(cfg["max_buys_per_token"])
    min_liq = float(lim.get("min_liquidity_sol") or 0) or float(cfg["min_liquidity_sol"])
    min_age = float(lim.get("min_token_age_seconds") or 0) or float(cfg["min_token_age_seconds"])

    # Total loss kill
    total_pnl = float(state.get("total_realized_pnl_sol") or 0)
    checks["total_realized_pnl_sol"] = total_pnl
    if total_pnl <= -abs(total_kill):
        return {"ok": False, "reason": "total_loss_kill", "checks": checks}

    # Daily loss stop (no new buys)
    day_pnl = float(state.get("day_realized_pnl_sol") or 0)
    checks["day_realized_pnl_sol"] = day_pnl
    if side == "buy" and day_pnl <= -abs(daily_stop):
        return {"ok": False, "reason": "daily_loss_stop", "checks": checks}

    if sol_amount is None or float(sol_amount) <= 0:
        return {"ok": False, "reason": "amount_zero", "checks": checks}
    sol_amount = float(sol_amount)
    checks["sol_amount"] = sol_amount
    checks["max_sol_per_trade"] = max_sol
    if sol_amount > max_sol + 1e-12:
        return {"ok": False, "reason": "over_max_sol_per_trade", "checks": checks}

    if side == "buy":
        checks["open_positions"] = open_positions
        checks["max_open"] = max_open
        if open_positions >= max_open:
            return {"ok": False, "reason": "max_open_positions", "checks": checks}
        checks["buys_this_token"] = buys_this_token
        if buys_this_token >= max_buys:
            return {"ok": False, "reason": "max_buys_per_token", "checks": checks}

        if wallet_sol is not None:
            checks["wallet_sol"] = wallet_sol
            checks["fee_reserve_sol"] = fee_reserve
            if wallet_sol - sol_amount < fee_reserve - 1e-12:
                return {"ok": False, "reason": "fee_reserve", "checks": checks}

        if token_liquidity_sol is not None:
            checks["token_liquidity_sol"] = token_liquidity_sol
            checks["min_liquidity_sol"] = min_liq
            if token_liquidity_sol < min_liq:
                return {"ok": False, "reason": "min_liquidity", "checks": checks}

        if token_age_seconds is not None:
            checks["token_age_seconds"] = token_age_seconds
            checks["min_token_age_seconds"] = min_age
            if token_age_seconds < min_age:
                return {"ok": False, "reason": "min_token_age", "checks": checks}

        if mint_authority_revoked is False:
            return {"ok": False, "reason": "mint_authority_active", "checks": {**checks, "mint_authority_revoked": False}}
        if freeze_authority_revoked is False:
            return {"ok": False, "reason": "freeze_authority_active", "checks": {**checks, "freeze_authority_revoked": False}}
        if can_sell_ok is False:
            return {"ok": False, "reason": "can_sell_failed", "checks": {**checks, "can_sell_ok": False}}
        if mint_authority_revoked is not None:
            checks["mint_authority_revoked"] = mint_authority_revoked
        if freeze_authority_revoked is not None:
            checks["freeze_authority_revoked"] = freeze_authority_revoked
        if can_sell_ok is not None:
            checks["can_sell_ok"] = can_sell_ok

    return {"ok": True, "reason": "passed", "checks": checks}


# Back-compat alias used by older callers
def evaluate_live_order(**kwargs) -> dict[str, Any]:
    state = kwargs.get("state") or {}
    return pre_trade_gate(
        side=kwargs.get("side") or "buy",
        sol_amount=float(kwargs.get("sol_amount") or 0),
        token_mint=kwargs.get("token_mint"),
        state=state,
        open_positions=int(kwargs.get("open_positions") or 0),
        buys_this_token=int(kwargs.get("buys_this_token") or 0),
        wallet_sol=kwargs.get("wallet_sol"),
        token_liquidity_sol=kwargs.get("token_liquidity_sol"),
        token_age_seconds=kwargs.get("token_age_seconds"),
        mint_authority_revoked=kwargs.get("mint_authority_revoked"),
        freeze_authority_revoked=kwargs.get("freeze_authority_revoked"),
        can_sell_ok=kwargs.get("can_sell_ok"),
        kill_file_present=bool(kwargs.get("kill_file_present") or False),
        hygiene_ok=bool(kwargs.get("hygiene_ok", True)),
        gate_veto=bool(kwargs.get("gate_veto") or False),
        cfg=kwargs.get("cfg"),
    )


def arm_balance_ok(wallet_sol: float, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refuse to arm if on-chain balance < 0.25 + 0.05 SOL."""
    cfg = {**SPEC, **(cfg or {})}
    need = float(cfg["arm_min_balance_sol"])
    ok = float(wallet_sol) >= need
    return {
        "ok": ok,
        "wallet_sol": float(wallet_sol),
        "required_sol": need,
        "reason": "ok" if ok else "balance_below_arm_minimum",
    }
