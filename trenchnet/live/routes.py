"""Build pump/Jupiter swap routes. Prefer fee-free public APIs. Never send here."""
from __future__ import annotations

from typing import Any

import httpx

JUPITER_LITE_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_LITE_SWAP = "https://lite-api.jup.ag/swap/v1/swap"
WSOL = "So11111111111111111111111111111111111111112"


def jupiter_quote(*, input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int) -> dict[str, Any]:
    """Free public Jupiter lite quote — no API key. May 4xx for some pump tokens."""
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": str(slippage_bps),
    }
    try:
        r = httpx.get(JUPITER_LITE_QUOTE, params=params, timeout=30.0, headers={"Accept": "application/json"})
        return {"ok": r.status_code == 200, "status": r.status_code, "source_url": str(r.url), "data": r.json() if r.content else None}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "source_url": JUPITER_LITE_QUOTE}


def jupiter_swap_tx(*, quote: dict, user_pubkey: str) -> dict[str, Any]:
    """Ask Jupiter for an unsigned swap transaction (base64). Caller signs locally."""
    body = {
        "quoteResponse": quote,
        "userPublicKey": user_pubkey,
        "wrapAndUnwrapSol": True,
        "dynamicComputeUnitLimit": True,
    }
    try:
        r = httpx.post(JUPITER_LITE_SWAP, json=body, timeout=45.0, headers={"Accept": "application/json", "Content-Type": "application/json"})
        data = r.json() if r.content else None
        return {
            "ok": r.status_code == 200 and bool((data or {}).get("swapTransaction")),
            "status": r.status_code,
            "source_url": JUPITER_LITE_SWAP,
            "swapTransaction": (data or {}).get("swapTransaction"),
            "data": data,
            "fee_note": "Jupiter lite public API — no per-trade platform fee from TRENCHNET; normal Solana network fees only.",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "source_url": JUPITER_LITE_SWAP}


def describe_routes() -> dict[str, Any]:
    return {
        "preferred": "jupiter_lite (lite-api.jup.ag) — free public, no API key, no TRENCHNET fee",
        "pre_graduation": "pump.fun bonding curve local ix (built unsigned; signed only when armed)",
        "pumpportal": {
            "opt_in": True,
            "fee_note": "PumpPortal local-transaction API may take a per-trade fee — OFF by default; enable only in GUI opt-in.",
        },
        "helius_quicknode": "Free-signup RPCs listed for Jeremy — NOT signed up by agent.",
    }
