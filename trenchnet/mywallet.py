"""Read-only view of MY_WALLET_ADDRESS from .env via Helius RPC.

Never logs the address or API key. API payload returns only a masked label.
No signing, no private keys, no send.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from trenchnet.secrets import get_secret

LAMPORTS_PER_SOL = 1_000_000_000

try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")
except Exception:
    CT = timezone(timedelta(hours=-5))


def mask_address(addr: str) -> str:
    a = (addr or "").strip()
    if len(a) < 8:
        return "—"
    return f"{a[:4]}…{a[-4:]}"


def configured_address() -> str | None:
    raw = get_secret("MY_WALLET_ADDRESS")
    if not raw:
        return None
    a = raw.strip()
    if len(a) < 32:
        return None
    return a


def _ct(ts: int | float | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(CT).strftime(
            "%Y-%m-%d %H:%M:%S CT"
        )
    except Exception:
        return None


def _rpc():
    from trenchnet.data_solana import SolanaRPC
    from trenchnet.helius_client import rpc_url_for_solana

    url = rpc_url_for_solana()
    if not url:
        raise RuntimeError("HELIUS_RPC_URL / HELIUS_API_KEY not configured")
    return SolanaRPC(url, sleep_ms=200)


def fetch_my_wallet(*, tx_limit: int = 5) -> dict[str, Any]:
    """Pull SOL balance, SPL token holdings, last N signatures. Read-only."""
    addr = configured_address()
    if not addr:
        return {
            "ok": False,
            "configured": False,
            "paper_only": True,
            "read_only": True,
            "masked_address": None,
            "note": "Set MY_WALLET_ADDRESS in local .env (gitignored) to enable.",
            "sol_balance": None,
            "tokens": [],
            "transactions": [],
            "refreshed_at_ct": datetime.now(CT).strftime("%Y-%m-%d %H:%M:%S CT"),
        }

    rpc = _rpc()
    # SOL balance
    bal_lamports = rpc.call("getBalance", [addr])
    if isinstance(bal_lamports, dict):
        lamports = int(bal_lamports.get("value") or 0)
    else:
        lamports = int(bal_lamports or 0)
    sol = lamports / LAMPORTS_PER_SOL

    # Token accounts (jsonParsed)
    tokens: list[dict[str, Any]] = []
    try:
        tok = rpc.call(
            "getTokenAccountsByOwner",
            [
                addr,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"},
            ],
        )
        value = (tok or {}).get("value") if isinstance(tok, dict) else None
        for row in value or []:
            try:
                info = (((row.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
                ta = info.get("tokenAmount") or {}
                ui = ta.get("uiAmount")
                if ui is None:
                    continue
                if float(ui) == 0:
                    continue
                mint = info.get("mint") or ""
                tokens.append({
                    "mint_masked": mask_address(mint),
                    "mint_suffix": mint[-4:] if len(mint) >= 4 else mint,
                    "amount": float(ui),
                    "decimals": ta.get("decimals"),
                })
            except Exception:
                continue
    except Exception as exc:
        tokens = []
        token_err = type(exc).__name__
    else:
        token_err = None

    # Recent signatures
    txs: list[dict[str, Any]] = []
    try:
        from trenchnet.data_solana import get_signatures
        sigs = get_signatures(rpc, addr, limit=tx_limit)
        for s in sigs[:tx_limit]:
            bt = s.get("blockTime")
            txs.append({
                "signature_masked": mask_address(s.get("signature") or ""),
                "signature_suffix": (s.get("signature") or "")[-4:],
                "block_time": bt,
                "time_ct": _ct(bt),
                "err": bool(s.get("err")),
                "status": "failed" if s.get("err") else "ok",
            })
    except Exception as exc:
        txs = []
        tx_err = type(exc).__name__
    else:
        tx_err = None

    return {
        "ok": True,
        "configured": True,
        "paper_only": True,
        "read_only": True,
        "no_signing": True,
        "masked_address": mask_address(addr),
        "sol_balance": round(sol, 9),
        "sol_lamports": lamports,
        "tokens": tokens,
        "token_count": len(tokens),
        "transactions": txs,
        "tx_count_shown": len(txs),
        "refreshed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refreshed_at_ct": datetime.now(CT).strftime("%Y-%m-%d %H:%M:%S CT"),
        "errors": {k: v for k, v in {"tokens": token_err, "transactions": tx_err}.items() if v},
        "note": "Read-only public balance via Helius RPC. No private key. No send.",
    }
