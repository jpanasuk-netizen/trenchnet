"""LIVE order path: gate → build → (optional sign) → simulate by default.

Agent/automation must NEVER call execute(..., mode='send') with a real confirm.
Dry-run uses trenchnet.live.dryrun (public wallet, no signing).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from trenchnet.live.gates import pre_trade_gate
from trenchnet.live import routes as live_routes
from trenchnet.live.ledger import append_trade
from trenchnet.live.redaction import redact_exc, scrub_dict
from trenchnet.live.state import disarm, kill_file_present, load_state, save_state

WSOL = "So11111111111111111111111111111111111111112"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
    return {
        "ok": "error" not in data,
        "rpc": rpc_url.split("?")[0],  # strip api-key query if present
        "result": data.get("result"),
        "error": data.get("error"),
        "method": "simulateTransaction",
    }


def build_order_preview(
    *,
    side: str,
    token_mint: str,
    sol_amount: float,
    slippage_pct: float,
    priority_fee_lamports: int,
    pubkey: str,
) -> dict[str, Any]:
    lamports = int(sol_amount * 1_000_000_000)
    slip_bps = int(slippage_pct * 100)
    if side == "buy":
        q = live_routes.jupiter_quote(input_mint=WSOL, output_mint=token_mint, amount_lamports=lamports, slippage_bps=slip_bps)
    else:
        q = live_routes.jupiter_quote(input_mint=token_mint, output_mint=WSOL, amount_lamports=lamports, slippage_bps=slip_bps)
    return scrub_dict({
        "side": side,
        "token_mint": token_mint,
        "sol_amount": sol_amount,
        "slippage_pct": slippage_pct,
        "priority_fee_lamports": priority_fee_lamports,
        "pubkey_masked": (pubkey[:4] + "…" + pubkey[-4:]) if pubkey and len(pubkey) > 8 else None,
        "route": "jupiter_lite",
        "quote": q,
    })


def execute(
    *,
    side: str,
    token_mint: str,
    sol_amount: float,
    slippage_pct: float,
    priority_fee_lamports: int,
    confirm_phrase: str,
    mode: str = "simulate",
    open_positions: int = 0,
    buys_this_token: int = 0,
    wallet_sol: float | None = None,
    allow_exit_while_killed: bool = False,
) -> dict[str, Any]:
    """Default mode=simulate. mode=send requires CONFIRM LIVE ORDER + armed — agents must not use send."""
    st = load_state()
    if allow_exit_while_killed and side == "sell":
        # sell-all / position manager may sell under kill (no new buys)
        gate_state = {**st, "armed": True, "kill_switch": False}
        kill_for_gate = False
    else:
        gate_state = st
        kill_for_gate = kill_file_present()

    gate = pre_trade_gate(
        side=side,
        sol_amount=sol_amount,
        token_mint=token_mint,
        state=gate_state,
        open_positions=open_positions,
        buys_this_token=buys_this_token,
        wallet_sol=wallet_sol,
        kill_file_present=kill_for_gate,
    )
    if not gate["ok"]:
        row = {"ts": _now(), "ok": False, "reason": gate["reason"], "side": side, "token_mint": token_mint, "mode": mode, "kind": "refusal"}
        append_trade(row)
        return row

    if mode == "send" and (confirm_phrase or "").strip() != "CONFIRM LIVE ORDER":
        return {"ok": False, "reason": "confirm_phrase_required"}
    if mode == "send" and not st.get("armed") and not allow_exit_while_killed:
        return {"ok": False, "reason": "disarmed"}

    # Simulate path does not load private key when dry — but legacy simulate still signs if wallet present.
    # For agent safety: if mode != send, prefer unsigned simulate via dryrun for public wallet.
    if mode != "send":
        from trenchnet.live.dryrun import dry_run_candidate
        dr = dry_run_candidate(token_mint=token_mint, sol_amount=sol_amount, slippage_pct=slippage_pct)
        row = {
            "ts": _now(), "ok": True, "mode": "simulate", "side": side, "token_mint": token_mint,
            "sol_amount": sol_amount, "dry_run": dr, "signature": None, "kind": "simulate",
        }
        append_trade(row)
        return scrub_dict(row)

    # REAL SEND path — requires key. Agents must not reach here.
    from trenchnet.live.wallet import load_keypair_for_signing, public_address
    pubkey = public_address()
    preview = build_order_preview(
        side=side, token_mint=token_mint, sol_amount=sol_amount,
        slippage_pct=slippage_pct, priority_fee_lamports=priority_fee_lamports, pubkey=pubkey or "",
    )
    quote = (preview.get("quote") or {}).get("data")
    if not (preview.get("quote") or {}).get("ok") or not quote:
        row = {"ts": _now(), "ok": False, "reason": "quote_failed", "mode": "send", "side": side, "token_mint": token_mint}
        append_trade(row)
        return row
    swap = live_routes.jupiter_swap_tx(quote=quote, user_pubkey=pubkey or "")
    if not swap.get("ok"):
        row = {"ts": _now(), "ok": False, "reason": "swap_tx_build_failed", "mode": "send"}
        append_trade(row)
        return row
    try:
        from solders.transaction import VersionedTransaction
        import base64
        kp = load_keypair_for_signing()
        raw = base64.b64decode(swap["swapTransaction"])
        tx = VersionedTransaction.from_bytes(raw)
        signed = VersionedTransaction(tx.message, [kp])
        signed_b64 = base64.b64encode(bytes(signed)).decode("ascii")
        del kp
    except Exception as exc:
        row = {"ts": _now(), "ok": False, "reason": f"sign_failed:{redact_exc(exc)}"}
        append_trade(row)
        return row

    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
        "params": [signed_b64, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}],
    }
    r = httpx.post(st.get("rpc_url") or "https://api.mainnet-beta.solana.com", json=payload, timeout=60.0)
    data = r.json()
    sig = data.get("result")
    row = {
        "ts": _now(), "ok": "error" not in data, "mode": "send", "side": side, "token_mint": token_mint,
        "sol_amount": sol_amount, "sol_in": sol_amount if side == "buy" else None,
        "signature": sig, "solscan": f"https://solscan.io/tx/{sig}" if sig else None,
        "error": data.get("error"), "route": "jupiter_lite", "kind": "fill",
    }
    append_trade(row)
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
    return scrub_dict(row)
