"""Panic SELL ALL — market-sell open ledger positions (+ on-chain TRENCHNET tokens).

Escalating slippage + retries. Then disarm. KILL blocks new buys; sell-all still exits.
Default/tests: mode=simulate (no send).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trenchnet.live.ledger import append_trade, load_open_positions, open_from_ledger, save_open_positions
from trenchnet.live.redaction import redact_exc, scrub_dict
from trenchnet.live.state import disarm, load_state


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def collect_sell_targets() -> list[str]:
    pos = load_open_positions() or open_from_ledger()
    mints = [p.get("token_mint") for p in pos if p.get("token_mint")]
    # dedupe
    out = []
    for m in mints:
        if m and m not in out:
            out.append(m)
    return out


def sell_one(token_mint: str | None, *, mode: str = "simulate", reason: str = "sell_all", slippage_ladder: list[float] | None = None) -> dict[str, Any]:
    if not token_mint:
        return {"ok": False, "reason": "no_mint"}
    ladder = slippage_ladder or [5.0, 10.0, 25.0, 40.0]
    errors = []
    for slip in ladder:
        try:
            if mode == "simulate":
                from trenchnet.live.dryrun import dry_run_candidate
                # For sells, dry-run still quotes buy path for route health; note exit intent
                dr = dry_run_candidate(token_mint=token_mint, sol_amount=0.01, slippage_pct=slip)
                row = {
                    "ts": _now(), "ok": True, "mode": "simulate", "side": "sell", "kind": "sell_all_sim",
                    "token_mint": token_mint, "reason": reason, "slippage_pct": slip,
                    "dry_run_quote_ok": (dr.get("quote") or {}).get("ok"),
                    "note": "simulate only — no send",
                }
                append_trade(row)
                return scrub_dict({**row, "attempts": errors})
            # send path — escalating
            from trenchnet.live.orders import execute
            res = execute(
                side="sell",
                token_mint=token_mint,
                sol_amount=0.01,  # placeholder; real sizing needs token balance
                slippage_pct=slip,
                priority_fee_lamports=50000,
                confirm_phrase="CONFIRM LIVE ORDER",
                mode="send",
                allow_exit_while_killed=True,
            )
            if res.get("ok"):
                append_trade({**res, "kind": "sell_all", "reason": reason})
                return scrub_dict(res)
            errors.append({"slip": slip, "reason": res.get("reason"), "error": res.get("error")})
        except Exception as exc:
            errors.append({"slip": slip, "error": redact_exc(exc)})
    row = {
        "ts": _now(), "ok": False, "mode": mode, "side": "sell", "kind": "sell_all_failed",
        "token_mint": token_mint, "reason": "unsellable_or_no_route", "attempts": errors,
    }
    append_trade(row)
    return scrub_dict(row)


def sell_all(*, mode: str = "simulate") -> dict[str, Any]:
    """Sell every open position. Always ends with disarm. Tests must use mode=simulate."""
    targets = collect_sell_targets()
    results = []
    if not targets:
        disarm("sell_all_noop")
        return {
            "ok": True,
            "mode": mode,
            "n": 0,
            "results": [],
            "note": "No open positions — no-op (expected in dry-run/tests).",
            "disarmed": True,
            "sent": mode == "send",
        }
    for mint in targets:
        results.append(sell_one(mint, mode=mode, reason="sell_all"))
    # clear opens on successful sims for bookkeeping in sim mode only if all ok
    if mode == "simulate":
        save_open_positions([])
    else:
        still = [r["token_mint"] for r in results if not r.get("ok")]
        save_open_positions([{"token_mint": m} for m in still])
    disarm("sell_all")
    return scrub_dict({
        "ok": all(r.get("ok") for r in results) if results else True,
        "mode": mode,
        "n": len(results),
        "results": results,
        "disarmed": True,
        "sent": mode == "send",
    })
