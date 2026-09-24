"""LIVE order path: gate → build → sign locally → simulate (default). send only if armed+confirmed.

Agent must NEVER call execute(..., confirm_phrase=...) with real confirm.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from trenchnet.config_load import ROOT
from trenchnet.live.gates import evaluate_live_order
from trenchnet.live import routes as live_routes
from trenchnet.live.state import disarm, load_state, save_state

LEDGER = ROOT / "data" / "live" / "ledger.jsonl"
WSOL = "So11111111111111111111111111111111111111112"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _append_ledger(row: dict[str, Any]) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    # scrub any accidental secret-like fields
    for bad in ("secret", "private_key", "secret_key", "seed", "keypair"):
        row.pop(bad, None)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def simulate_b64_tx(rpc_url: str, tx_b64: str) -> dict[str, Any]:
    """simulateTransaction only — never sendTransaction."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "simulateTransaction",
        "params": [tx_b64, {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True}],
    }
    r = httpx.post(rpc_url, json=payload, timeout=60.0)
    data = r.json()
    return {"ok": "error" not in data, "rpc": rpc_url, "result": data.get("result"), "error": data.get("error"), "method": "simulateTransaction"}


def build_order_preview(
    *,
    side: str,
    token_mint: str,
    sol_amount: float,
    slippage_pct: float,
    priority_fee_lamports: int,
    pubkey: str,
) -> dict[str, Any]:
    """Unsigned route preview for GUI confirm modal. No signing."""
    lamports = int(sol_amount * 1_000_000_000)
    slip_bps = int(slippage_pct * 100)
    if side == "buy":
        q = live_routes.jupiter_quote(input_mint=WSOL, output_mint=token_mint, amount_lamports=lamports, slippage_bps=slip_bps)
    else:
        # sell needs token amount — GUI should pass; here sol_amount treated as approx out desire
        q = live_routes.jupiter_quote(input_mint=token_mint, output_mint=WSOL, amount_lamports=lamports, slippage_bps=slip_bps)
    return {
        "side": side,
        "token_mint": token_mint,
        "sol_amount": sol_amount,
        "slippage_pct": slippage_pct,
        "priority_fee_lamports": priority_fee_lamports,
        "pubkey": pubkey,
        "route": "jupiter_lite",
        "fee_note": "No TRENCHNET/PumpPortal fee unless pumpportal_opt_in. Network fees apply.",
        "quote": q,
        "links": {
            "token_solscan": f"https://solscan.io/token/{token_mint}",
            "jupiter": "https://lite-api.jup.ag/",
        },
    }


def execute(
    *,
    side: str,
    token_mint: str,
    sol_amount: float,
    slippage_pct: float,
    priority_fee_lamports: int,
    confirm_phrase: str,
    mode: str = "simulate",  # simulate | send
    open_positions: int = 0,
    gate_veto: bool = False,
    hygiene_ok: bool = True,
) -> dict[str, Any]:
    """Execute LIVE path. `send` requires confirm_phrase == 'CONFIRM LIVE ORDER' and armed state.

    Default and agent-safe path is mode='simulate'.
    """
    from trenchnet.live.wallet import load_keypair_for_signing, public_address

    st = load_state()
    gate = evaluate_live_order(
        side=side,
        sol_amount=sol_amount,
        slippage_pct=slippage_pct,
        priority_fee_lamports=priority_fee_lamports,
        state=st,
        open_positions=open_positions,
        gate_veto=gate_veto,
        hygiene_ok=hygiene_ok,
    )
    if not gate["ok"]:
        row = {"ts": _now(), "ok": False, "reason": gate["reason"], "side": side, "token_mint": token_mint, "mode": mode}
        _append_ledger(row)
        return row

    if mode == "send" and confirm_phrase.strip() != "CONFIRM LIVE ORDER":
        return {"ok": False, "reason": "confirm_phrase_required"}
    if mode == "send" and not st.get("armed"):
        return {"ok": False, "reason": "disarmed"}
    # Auto mode check
    if mode == "send" and st.get("auto_armed") is False:
        # manual mode still allowed with confirm phrase
        pass

    pubkey = public_address()
    preview = build_order_preview(
        side=side, token_mint=token_mint, sol_amount=sol_amount,
        slippage_pct=slippage_pct, priority_fee_lamports=priority_fee_lamports, pubkey=pubkey or "",
    )
    quote = (preview.get("quote") or {}).get("data")
    if not (preview.get("quote") or {}).get("ok") or not quote:
        row = {"ts": _now(), "ok": False, "reason": "quote_failed", "preview": {k: preview[k] for k in preview if k != "quote"}, "quote_status": (preview.get("quote") or {}).get("status")}
        _append_ledger(row)
        return row

    swap = live_routes.jupiter_swap_tx(quote=quote, user_pubkey=pubkey or "")
    if not swap.get("ok"):
        row = {"ts": _now(), "ok": False, "reason": "swap_tx_build_failed", "status": swap.get("status")}
        _append_ledger(row)
        # streak
        st["rpc_error_streak"] = int(st.get("rpc_error_streak") or 0) + 1
        if st["rpc_error_streak"] >= 5:
            disarm("rpc_error_streak")
        else:
            save_state(st)
        return row

    tx_b64 = swap["swapTransaction"]
    # Sign locally — key never leaves this scope / never logged
    try:
        from solders.transaction import VersionedTransaction
        import base64

        kp = load_keypair_for_signing()
        raw = base64.b64decode(tx_b64)
        tx = VersionedTransaction.from_bytes(raw)
        # re-sign
        signed = VersionedTransaction(tx.message, [kp])
        signed_b64 = base64.b64encode(bytes(signed)).decode("ascii")
        del kp
    except Exception as exc:
        row = {"ts": _now(), "ok": False, "reason": f"sign_failed:{type(exc).__name__}"}
        _append_ledger(row)
        return row

    sim = simulate_b64_tx(st.get("rpc_url") or "https://api.mainnet-beta.solana.com", signed_b64)
    if mode != "send":
        row = {
            "ts": _now(), "ok": True, "mode": "simulate", "side": side, "token_mint": token_mint,
            "sol_amount": sol_amount, "simulate": {"ok": sim.get("ok"), "err": (sim.get("result") or {}).get("value", {}).get("err") if isinstance(sim.get("result"), dict) else sim.get("error")},
            "signature": None,
            "fee_note": swap.get("fee_note"),
            "route": "jupiter_lite",
        }
        _append_ledger(row)
        return row

    # REAL SEND — only with explicit confirm; agent must not reach here in automation
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
        "params": [signed_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}],
    }
    r = httpx.post(st.get("rpc_url") or "https://api.mainnet-beta.solana.com", json=payload, timeout=60.0)
    data = r.json()
    sig = data.get("result")
    row = {
        "ts": _now(), "ok": "error" not in data, "mode": "send", "side": side, "token_mint": token_mint,
        "sol_amount": sol_amount, "signature": sig,
        "solscan": f"https://solscan.io/tx/{sig}" if sig else None,
        "error": data.get("error"),
        "route": "jupiter_lite",
    }
    _append_ledger(row)
    if row["ok"]:
        st["day_trade_count"] = int(st.get("day_trade_count") or 0) + 1
        st["rpc_error_streak"] = 0
        save_state(st)
    else:
        st["rpc_error_streak"] = int(st.get("rpc_error_streak") or 0) + 1
        if st["rpc_error_streak"] >= 5:
            disarm("rpc_error_streak")
        else:
            save_state(st)
    return row
