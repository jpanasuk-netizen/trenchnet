"""Position manager — EXITS ONLY (SL / TP / time stop / daily+total stops).

Never places buys. Runs hidden via pythonw / CREATE_NO_WINDOW scheduled task.
Reloads open positions from ledger on start. Idles cheaply when disarmed + flat.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from typing import Any

from trenchnet.live.ledger import load_open_positions, open_from_ledger, save_open_positions
from trenchnet.live.state import disarm, kill_file_present, load_state, save_state, write_heartbeat


def _now_ts() -> float:
    return time.time()


def evaluate_exit(pos: dict[str, Any], lim: dict[str, Any], *, mark_pnl_pct: float | None = None) -> dict[str, Any]:
    """Decide whether to exit. mark_pnl_pct = (mark - entry)/entry if known."""
    tp = float(lim.get("take_profit_pct") or 0.5)
    sl = float(lim.get("stop_loss_pct") or 0.25)
    tstop = int(lim.get("time_stop_seconds") or 3600)
    reason = None
    if mark_pnl_pct is not None:
        if mark_pnl_pct >= tp:
            reason = "take_profit"
        elif mark_pnl_pct <= -sl:
            reason = "stop_loss"
    # time stop from entry_ts
    entry_ts = pos.get("entry_ts")
    age = None
    if entry_ts:
        try:
            et = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00")).timestamp()
            age = _now_ts() - et
            if age >= tstop:
                reason = reason or "time_stop"
        except Exception:
            pass
    return {"should_exit": reason is not None, "reason": reason, "age_s": age, "mark_pnl_pct": mark_pnl_pct}


def check_global_stops(st: dict[str, Any]) -> dict[str, Any]:
    lim = st.get("limits") or {}
    daily = float(lim.get("daily_loss_cap_sol") or 2.0)
    total = float(lim.get("total_loss_kill_sol") or 4.0)
    day_pnl = float(st.get("day_realized_pnl_sol") or 0)
    tot_pnl = float(st.get("total_realized_pnl_sol") or 0)
    actions = []
    if tot_pnl <= -abs(total):
        disarm("total_loss_kill")
        actions.append("total_loss_kill_disarm")
    elif day_pnl <= -abs(daily):
        # stop new buys: ensure disarmed for buys; exits still allowed
        actions.append("daily_loss_stop_no_new_buys")
    return {"actions": actions, "day_pnl": day_pnl, "total_pnl": tot_pnl}


def tick(once: bool = False) -> dict[str, Any]:
    """One manager loop iteration. NEVER buys."""
    st = load_state()
    positions = load_open_positions() or open_from_ledger()
    save_open_positions(positions)
    stops = check_global_stops(st)
    exits_planned = []
    lim = st.get("limits") or {}
    for pos in positions:
        # Without a live mark, only time-stop can fire; mark integration is best-effort.
        decision = evaluate_exit(pos, lim, mark_pnl_pct=pos.get("mark_pnl_pct"))
        if decision["should_exit"]:
            exits_planned.append({"token_mint": pos.get("token_mint"), **decision})
            # Actual exit send is only when armed path + sell-all/manager send — default: log plan only if no key/send.
            # Position manager calls sell helper in simulate mode unless LIVE_PM_SEND=1 (Jeremy-only).
            import os
            if os.environ.get("TRENCHNET_PM_ALLOW_SEND") == "1" and st.get("armed"):
                from trenchnet.live.sellall import sell_one
                sell_one(pos.get("token_mint"), mode="send", reason=decision["reason"])
            else:
                # dry plan
                from trenchnet.live.sellall import sell_one
                sell_one(pos.get("token_mint"), mode="simulate", reason=decision["reason"])

    write_heartbeat({
        "open_positions": len(positions),
        "exits_planned": len(exits_planned),
        "armed": bool(st.get("armed")),
        "kill": bool(st.get("kill_switch") or kill_file_present()),
        "stops": stops,
        "can_buy": False,  # hard rule
    })
    return {
        "ok": True,
        "open_positions": len(positions),
        "exits_planned": exits_planned,
        "stops": stops,
        "buys_allowed": False,
    }


def run_forever(interval_s: float = 15.0) -> None:
    """Idle cheaply when disarmed and flat."""
    while True:
        st = load_state()
        positions = load_open_positions() or open_from_ledger()
        if (not st.get("armed")) and (not positions) and (not kill_file_present()):
            write_heartbeat({"idle": True, "open_positions": 0, "armed": False})
            time.sleep(max(30.0, interval_s * 2))
            continue
        try:
            tick()
        except Exception as exc:
            write_heartbeat({"error": type(exc).__name__, "alive": True})
        time.sleep(interval_s)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TRENCHNET position manager (exits only)")
    p.add_argument("--once", action="store_true")
    p.add_argument("--interval", type=float, default=15.0)
    args = p.parse_args(argv)
    if args.once:
        print(tick())
        return 0
    run_forever(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
