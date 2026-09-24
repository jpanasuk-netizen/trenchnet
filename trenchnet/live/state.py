"""LIVE arming + kill + caps. Default: fully disarmed. Persists across restarts as disarmed unless armed file says otherwise — but we force safe defaults."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from trenchnet.config_load import ROOT

STATE_PATH = ROOT / "data" / "live" / "state.json"
KILL_FILE = ROOT / "TRENCHNET_KILL"  # gitignored flag file
HEARTBEAT_FILE = ROOT / "data" / "live" / "position_manager_heartbeat.json"
ARM_PHRASE = "ARM TRENCHNET LIVE"

try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = timezone(timedelta(hours=-5))

DEFAULT_LIMITS = {
    "max_sol_per_trade": 0.0,          # 0 = disarmed-default; Jeremy sets to 0.25 when ready
    "daily_loss_cap_sol": 0.0,         # set to 2.0 when arming
    "total_loss_kill_sol": 0.0,        # set to 4.0 when arming
    "max_trades_per_day": 0,
    "max_open_positions": 0,           # set to 4
    "max_slippage_pct": 0.0,
    "max_priority_fee_lamports": 0,
    "fee_reserve_sol": 0.05,
    "max_buys_per_token": 1,
    "min_liquidity_sol": 5.0,
    "min_token_age_seconds": 300,
    "take_profit_pct": 0.50,
    "stop_loss_pct": 0.25,
    "time_stop_seconds": 3600,
}

DEFAULTS = {
    "armed": False,
    "auto_armed": False,
    "armed_at": None,
    "disarm_reason": "default",
    "kill_switch": False,
    "limits": dict(DEFAULT_LIMITS),
    "rpc_url": "https://api.mainnet-beta.solana.com",
    "route_preference": "jupiter_then_pumpportal",
    "pumpportal_opt_in": True,
    "day_ct": None,
    "day_realized_pnl_sol": 0.0,
    "day_trade_count": 0,
    "total_realized_pnl_sol": 0.0,
    "rpc_error_streak": 0,
    "armed_pubkey_masked": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ct_day() -> str:
    return datetime.now(CT).strftime("%Y-%m-%d")


def kill_file_present() -> bool:
    return KILL_FILE.is_file()


def write_kill_file() -> None:
    KILL_FILE.write_text("KILL\n", encoding="utf-8")


def clear_kill_file() -> None:
    try:
        KILL_FILE.unlink()
    except FileNotFoundError:
        pass


def load_state() -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        st = json.loads(json.dumps(DEFAULTS))
        st["day_ct"] = _ct_day()
        save_state(st)
        return st
    st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    # merge missing limit keys
    lim = dict(DEFAULT_LIMITS)
    lim.update(st.get("limits") or {})
    st["limits"] = lim
    # roll CT calendar day
    if st.get("day_ct") != _ct_day():
        st["day_ct"] = _ct_day()
        st["day_realized_pnl_sol"] = 0.0
        st["day_trade_count"] = 0
        save_state(st)
    # kill file forces kill+disarm
    if kill_file_present():
        if not st.get("kill_switch") or st.get("armed"):
            st["kill_switch"] = True
            st["armed"] = False
            st["auto_armed"] = False
            st["disarm_reason"] = "kill_file"
            save_state(st)
    return st


def save_state(st: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def disarm(reason: str = "manual") -> dict[str, Any]:
    st = load_state()
    st["armed"] = False
    st["auto_armed"] = False
    st["disarm_reason"] = reason
    st["armed_at"] = None
    save_state(st)
    return {"ok": True, "armed": False, "reason": reason}


def set_kill(on: bool) -> dict[str, Any]:
    st = load_state()
    st["kill_switch"] = bool(on)
    if on:
        st["armed"] = False
        st["auto_armed"] = False
        st["disarm_reason"] = "kill_switch"
        write_kill_file()
    else:
        clear_kill_file()
    save_state(st)
    return {"ok": True, "kill_switch": st["kill_switch"], "armed": st["armed"]}


def set_limits(limits: dict[str, Any]) -> dict[str, Any]:
    st = load_state()
    cur = dict(st.get("limits") or {})
    for k, v in limits.items():
        if k in DEFAULT_LIMITS:
            cur[k] = v
    st["limits"] = cur
    save_state(st)
    return {"ok": True, "limits": cur}


def apply_spec_caps() -> dict[str, Any]:
    """Convenience: set Jeremy's spec caps (still requires arm phrase)."""
    return set_limits({
        "max_sol_per_trade": 0.25,
        "daily_loss_cap_sol": 2.0,
        "total_loss_kill_sol": 4.0,
        "max_trades_per_day": 40,
        "max_open_positions": 4,
        "max_slippage_pct": 5.0,
        "max_priority_fee_lamports": 100000,
        "fee_reserve_sol": 0.05,
        "max_buys_per_token": 1,
        "min_liquidity_sol": 5.0,
        "min_token_age_seconds": 300,
        "take_profit_pct": 0.50,
        "stop_loss_pct": 0.25,
        "time_stop_seconds": 3600,
    })


def try_arm(phrase: str, *, wallet_sol: float | None = None, auto: bool = False) -> dict[str, Any]:
    """Arm only with exact phrase + caps + real balance check. Never logs secrets."""
    from trenchnet.live.gates import arm_balance_ok
    from trenchnet.live.wallet import env_key_configured, public_address_masked, public_address_from_env_or_store

    if (phrase or "").strip() != ARM_PHRASE:
        return {"ok": False, "error": f'type exactly `{ARM_PHRASE}` to confirm', "armed": False}
    st = load_state()
    if st.get("kill_switch") or kill_file_present():
        return {"ok": False, "error": "kill_switch on — clear KILL before arming", "armed": False}
    if not env_key_configured() and not public_address_from_env_or_store():
        return {"ok": False, "error": "no wallet — paste TRENCHNET_WALLET_KEY in .env (or generate/import)", "armed": False}
    lim = st.get("limits") or {}
    for k in ("max_sol_per_trade", "daily_loss_cap_sol", "max_open_positions", "max_slippage_pct"):
        if not float(lim.get(k) or 0):
            return {"ok": False, "error": f"limit {k} must be > 0 (use Apply spec caps)", "armed": False}
    if wallet_sol is None:
        return {"ok": False, "error": "arm requires live on-chain balance (wallet_sol) — never assume", "armed": False}
    bal = arm_balance_ok(float(wallet_sol))
    if not bal["ok"]:
        return {
            "ok": False,
            "error": f"balance {bal['wallet_sol']:.6f} SOL < required {bal['required_sol']} SOL (0.25 trade + 0.05 fees)",
            "armed": False,
            "balance_check": bal,
        }
    # total loss already hit?
    if float(st.get("total_realized_pnl_sol") or 0) <= -abs(float(lim.get("total_loss_kill_sol") or 4)):
        return {"ok": False, "error": "total_loss_kill already tripped — reset ledger/PnL only intentionally", "armed": False}

    masked = public_address_masked()
    st["armed"] = True
    st["auto_armed"] = bool(auto)
    st["armed_at"] = _now()
    st["disarm_reason"] = None
    st["armed_pubkey_masked"] = masked
    save_state(st)
    return {
        "ok": True,
        "armed": True,
        "auto_armed": bool(auto),
        "pubkey_masked": masked,
        "balance_check": bal,
        "note": "Confirm masked address matches the wallet you funded.",
    }


def read_heartbeat() -> dict[str, Any]:
    try:
        if HEARTBEAT_FILE.is_file():
            return json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"alive": False, "last_beat_ct": None, "note": "no heartbeat yet"}


def write_heartbeat(extra: dict[str, Any] | None = None) -> None:
    from datetime import datetime
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "alive": True,
        "last_beat_utc": _now(),
        "last_beat_ct": datetime.now(CT).strftime("%Y-%m-%d %H:%M:%S CT"),
        "pid": __import__("os").getpid(),
        "role": "position_manager_exits_only",
    }
    if extra:
        doc.update(extra)
    HEARTBEAT_FILE.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def public_state() -> dict[str, Any]:
    """Safe for GUI/API — no secrets."""
    from trenchnet.live.wallet import public_info

    st = load_state()
    hb = read_heartbeat()
    # stale heartbeat?
    alive = False
    try:
        from datetime import datetime
        ts = hb.get("last_beat_utc")
        if ts:
            beat = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            alive = (datetime.now(timezone.utc) - beat).total_seconds() < 120
    except Exception:
        alive = False
    return {
        "armed": bool(st.get("armed")),
        "auto_armed": bool(st.get("auto_armed")),
        "kill_switch": bool(st.get("kill_switch") or kill_file_present()),
        "kill_file": kill_file_present(),
        "disarm_reason": st.get("disarm_reason"),
        "limits": st.get("limits"),
        "rpc_url": st.get("rpc_url"),
        "route_preference": st.get("route_preference"),
        "pumpportal_opt_in": bool(st.get("pumpportal_opt_in")),
        "day_ct": st.get("day_ct"),
        "day_trade_count": st.get("day_trade_count"),
        "day_realized_pnl_sol": st.get("day_realized_pnl_sol"),
        "total_realized_pnl_sol": st.get("total_realized_pnl_sol"),
        "armed_pubkey_masked": st.get("armed_pubkey_masked"),
        "arm_phrase_hint": ARM_PHRASE,
        "wallet": public_info(),
        "position_manager": {
            "alive": alive,
            "last_beat_ct": hb.get("last_beat_ct"),
            "detail": hb,
        },
        "note": "LIVE disarmed by default. No measured edge yet (simulated only). Money never moves until Jeremy arms.",
        "no_edge_disclaimer": "No measured edge yet — paper/simulated signals only. LIVE is optional and dangerous.",
    }
