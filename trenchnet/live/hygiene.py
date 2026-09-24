"""Token hygiene / rug checks (read-only RPC). Fail-closed on errors."""
from __future__ import annotations

from typing import Any

import httpx

from trenchnet.live.redaction import redact_exc


def _rpc_call(rpc_url: str, method: str, params: list) -> Any:
    r = httpx.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=30.0)
    data = r.json()
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    return data.get("result")


def check_mint_authorities(rpc_url: str, mint: str) -> dict[str, Any]:
    """mint + freeze authority must be null/revoked."""
    try:
        res = _rpc_call(rpc_url, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        val = (res or {}).get("value") or {}
        parsed = ((val.get("data") or {}).get("parsed") or {}).get("info") or {}
        mint_auth = parsed.get("mintAuthority")
        freeze_auth = parsed.get("freezeAuthority")
        return {
            "ok": mint_auth is None and freeze_auth is None,
            "mint_authority": mint_auth,
            "freeze_authority": freeze_auth,
            "mint_authority_revoked": mint_auth is None,
            "freeze_authority_revoked": freeze_auth is None,
        }
    except Exception as exc:
        return {"ok": False, "error": redact_exc(exc), "mint_authority_revoked": None, "freeze_authority_revoked": None}


def can_sell_simulation_note(*, quote_ok: bool, sim_ok: bool | None, detail: str | None = None) -> dict[str, Any]:
    return {
        "ok": bool(quote_ok and (sim_ok is not False)),
        "quote_ok": quote_ok,
        "sim_ok": sim_ok,
        "detail": detail,
    }
