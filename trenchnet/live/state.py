"""LIVE arming + kill + caps. Default: fully disarmed (all caps 0)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trenchnet.config_load import ROOT

STATE_PATH = ROOT / "data" / "live" / "state.json"
DEFAULTS = {
    "armed": False,
    "auto_armed": False,
    "armed_at": None,
    "disarm_reason": "default",
    "kill_switch": False,
    "limits": {
        "max_sol_per_trade": 0.0,
        "daily_loss_cap_sol": 0.0,
        "max_trades_per_day": 0,
        "max_open_positions": 0,
        "max_slippage_pct": 0.0,
        "max_priority_fee_lamports": 0,
    },
    "rpc_url": "https://api.mainnet-beta.solana.com",
    "route_preference": "jupiter_lite_then_pump_local",  # fee-free preferred
    "pumpportal_opt_in": False,  # fee-taking route — off by default
    "day_utc": None,
    "day_realized_pnl_sol": 0.0,
    "day_trade_count": 0,
    "rpc_error_streak": 0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_state() -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.is_file():
        st = json.loads(json.dumps(DEFAULTS))
        st["day_utc"] = _utc_day()
        save_state(st)
        return st
    st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    # roll day
    if st.get("day_utc") != _utc_day():
        st["day_utc"] = _utc_day()
        st["day_realized_pnl_sol"] = 0.0
        st["day_trade_count"] = 0
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
    save_state(st)
    return {"ok": True, "kill_switch": st["kill_switch"], "armed": st["armed"]}


def set_limits(limits: dict[str, Any]) -> dict[str, Any]:
    st = load_state()
    cur = dict(st.get("limits") or {})
    for k, v in limits.items():
        if k in DEFAULTS["limits"]:
            cur[k] = v
    st["limits"] = cur
    # caps at 0 keep disarmed semantics
    save_state(st)
    return {"ok": True, "limits": cur}


def try_arm(phrase: str, *, auto: bool = False) -> dict[str, Any]:
    """Arm only if phrase exact and prerequisites met. Never logs secrets."""
    from trenchnet.live.wallet import public_address, wallet_exists

    need = "ARM AUTO" if auto else "ARM LIVE"
    if (phrase or "").strip() != need:
        return {"ok": False, "error": f"type exactly `{need}` to confirm"}
    st = load_state()
    if st.get("kill_switch"):
        return {"ok": False, "error": "kill_switch on"}
    if not wallet_exists():
        return {"ok": False, "error": "no LIVE wallet — generate or import first"}
    if not public_address():
        return {"ok": False, "error": "wallet pubkey missing"}
    lim = st.get("limits") or {}
    required = ["max_sol_per_trade", "daily_loss_cap_sol", "max_trades_per_day", "max_open_positions", "max_slippage_pct", "max_priority_fee_lamports"]
    for k in required:
        if not lim.get(k):
            return {"ok": False, "error": f"limit {k} must be > 0 (currently disarmed-default 0)"}
    # balance check is done by caller/GUI (needs RPC) — soft note
    st["armed"] = True
    st["auto_armed"] = bool(auto)
    st["armed_at"] = _now()
    st["disarm_reason"] = None
    save_state(st)
    return {"ok": True, "armed": True, "auto_armed": bool(auto), "pubkey": public_address()}


def public_state() -> dict[str, Any]:
    """Safe for GUI/API — no secrets."""
    from trenchnet.live.wallet import public_info

    st = load_state()
    return {
        "armed": bool(st.get("armed")),
        "auto_armed": bool(st.get("auto_armed")),
        "kill_switch": bool(st.get("kill_switch")),
        "disarm_reason": st.get("disarm_reason"),
        "limits": st.get("limits"),
        "rpc_url": st.get("rpc_url"),
        "route_preference": st.get("route_preference"),
        "pumpportal_opt_in": bool(st.get("pumpportal_opt_in")),
        "day_utc": st.get("day_utc"),
        "day_trade_count": st.get("day_trade_count"),
        "day_realized_pnl_sol": st.get("day_realized_pnl_sol"),
        "wallet": public_info(),
        "note": "LIVE disarmed by default. Money never moves until Jeremy arms and confirms.",
    }
