"""Build Jupiter / PumpPortal swap routes. Never send here."""
from __future__ import annotations

from typing import Any

import httpx

from trenchnet.live.redaction import redact_exc

JUPITER_LITE_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_LITE_SWAP = "https://lite-api.jup.ag/swap/v1/swap"
PUMPPORTAL_LOCAL = "https://pumpportal.fun/api/trade-local"
WSOL = "So11111111111111111111111111111111111111112"


def jupiter_quote(*, input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int) -> dict[str, Any]:
    params = {
        "inputMint": input_mint,
        "outputMint": output_mint,
        "amount": str(amount_lamports),
        "slippageBps": str(slippage_bps),
    }
    try:
        r = httpx.get(JUPITER_LITE_QUOTE, params=params, timeout=30.0, headers={"Accept": "application/json"})
        data = r.json() if r.content else None
        return {"ok": r.status_code == 200, "status": r.status_code, "source_url": JUPITER_LITE_QUOTE, "data": data}
    except Exception as exc:
        return {"ok": False, "error": redact_exc(exc), "source_url": JUPITER_LITE_QUOTE}


def jupiter_swap_tx(*, quote: dict, user_pubkey: str) -> dict[str, Any]:
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
            "fee_note": "Jupiter lite — network fees only from TRENCHNET's perspective.",
        }
    except Exception as exc:
        return {"ok": False, "error": redact_exc(exc), "source_url": JUPITER_LITE_SWAP}


def pumpportal_local_tx_hint(*, token_mint: str, sol_amount: float, user_pubkey: str, side: str = "buy", slippage: int = 10) -> dict[str, Any]:
    """Request unsigned local tx from PumpPortal (bonding-curve). May fail; never send here."""
    body = {
        "publicKey": user_pubkey,
        "action": side,
        "mint": token_mint,
        "denominatedInSol": "true",
        "amount": sol_amount,
        "slippage": slippage,
        "priorityFee": 0.0001,
        "pool": "pump",
    }
    try:
        r = httpx.post(PUMPPORTAL_LOCAL, json=body, timeout=45.0)
        # response may be raw bytes (tx) or json error
        if r.status_code == 200 and r.content and not r.text.lstrip().startswith("{"):
            import base64
            return {
                "ok": True,
                "status": r.status_code,
                "source_url": PUMPPORTAL_LOCAL,
                "swapTransaction": base64.b64encode(r.content).decode("ascii"),
                "note": "PumpPortal local unsigned tx (bonding curve).",
            }
        return {
            "ok": False,
            "status": r.status_code,
            "source_url": PUMPPORTAL_LOCAL,
            "error": (r.text or "")[:300],
            "note": "PumpPortal local trade build failed or returned JSON error.",
        }
    except Exception as exc:
        return {"ok": False, "error": redact_exc(exc), "source_url": PUMPPORTAL_LOCAL}


def describe_routes() -> dict[str, Any]:
    return {
        "graduated": "Jupiter lite-api.jup.ag (quote + swap tx)",
        "bonding_curve": "PumpPortal /api/trade-local",
        "priority_fee_slippage": "configurable in config/settings.yaml live section + /live limits",
        "send": "Never in this module",
    }
