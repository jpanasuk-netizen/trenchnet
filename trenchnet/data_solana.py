
"""Fetch + parse Solana pump.fun trades via free public RPC. Observe-only."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from trenchnet.models import TradeEvent

PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
# Official pump.fun AMM (PumpSwap) for graduated tokens.
PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
PUMP_ECOSYSTEM_PROGRAMS = (PUMPFUN_PROGRAM, PUMPSWAP_PROGRAM)
WSOL = "So11111111111111111111111111111111111111112"
SYSTEM_PROGRAM = "11111111111111111111111111111111"


class SolanaRPC:
    def __init__(self, url: str, sleep_ms: int = 400):
        self.url = url
        self.sleep_ms = sleep_ms
        self._id = 0

    def call(self, method: str, params: list[Any]) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        for attempt in range(5):
            try:
                r = httpx.post(self.url, json=payload, timeout=60.0)
                if r.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    # rate limit style
                    msg = str(data["error"])
                    if "429" in msg or "rate" in msg.lower():
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise RuntimeError(msg)
                time.sleep(self.sleep_ms / 1000.0)
                return data.get("result")
            except httpx.HTTPError:
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"RPC failed after retries: {method}")


def get_signatures(rpc: SolanaRPC, address: str, limit: int = 25) -> list[dict[str, Any]]:
    res = rpc.call("getSignaturesForAddress", [address, {"limit": limit}])
    return res or []


def get_signatures_page(rpc: SolanaRPC, address: str, before: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """One page of signature history; `before` pages toward the oldest tx."""
    opts: dict[str, Any] = {"limit": max(1, min(int(limit), 1000))}
    if before:
        opts["before"] = before
    res = rpc.call("getSignaturesForAddress", [address, opts])
    return res or []


def rpc_get_transaction(rpc: SolanaRPC, signature: str) -> dict[str, Any] | None:
    """getTransaction (jsonParsed); missing/pruned txs return None."""
    try:
        return rpc.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}],
        )
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "not found" in msg or "missing" in msg or "-32020" in msg or "-32009" in msg:
            return None
        raise


def get_transaction(rpc: SolanaRPC, signature: str) -> dict[str, Any] | None:
    res = rpc.call(
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}],
    )
    return res


def _token_deltas(tx: dict[str, Any], wallet: str) -> list[dict[str, Any]]:
    """Parse token balance deltas for wallet from jsonParsed tx."""
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return []
    pre = meta.get("preTokenBalances") or []
    post = meta.get("postTokenBalances") or []
    # index by (accountIndex, mint) ? prefer owner match
    def idx(balances):
        out = {}
        for b in balances:
            owner = b.get("owner")
            mint = b.get("mint")
            if owner != wallet or not mint:
                continue
            ui = (b.get("uiTokenAmount") or {}).get("uiAmount")
            if ui is None:
                try:
                    ui = float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0)
                except Exception:
                    ui = 0.0
            out[mint] = float(ui or 0.0)
        return out

    pre_m = idx(pre)
    post_m = idx(post)
    mints = set(pre_m) | set(post_m)
    deltas = []
    for m in mints:
        d = post_m.get(m, 0.0) - pre_m.get(m, 0.0)
        if abs(d) < 1e-12:
            continue
        deltas.append({"mint": m, "delta": d})
    return deltas


def _sol_delta(tx: dict[str, Any], wallet: str) -> float | None:
    meta = tx.get("meta") or {}
    msg = (tx.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    # accountKeys may be list of str or list of {pubkey, ...}
    pubkeys = []
    for k in keys:
        if isinstance(k, str):
            pubkeys.append(k)
        elif isinstance(k, dict):
            pubkeys.append(k.get("pubkey") or "")
    try:
        i = pubkeys.index(wallet)
    except ValueError:
        return None
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if i >= len(pre) or i >= len(post):
        return None
    # lamports ? SOL; negative means wallet spent SOL
    return (post[i] - pre[i]) / 1_000_000_000


def _mentions_pumpfun(tx: dict[str, Any], program_id: str | None = None) -> bool:
    """True if tx references pump.fun bonding curve and/or PumpSwap AMM."""
    blob = json.dumps(tx)
    if program_id and program_id not in ("ECOSYSTEM", ""):
        return program_id in blob
    return any(prog in blob for prog in PUMP_ECOSYSTEM_PROGRAMS)


def parse_trades_from_tx(
    tx: dict[str, Any],
    signature: str,
    wallet: str,
    program_id: str | None = None,
) -> list[TradeEvent]:
    if not tx:
        return []
    meta = tx.get("meta") or {}
    if meta.get("err"):
        return []
    if not _mentions_pumpfun(tx, program_id):
        # still allow token delta events tagged unknown if present ? but prefer pump.fun only
        return []
    deltas = _token_deltas(tx, wallet)
    sol_d = _sol_delta(tx, wallet)
    slot = tx.get("slot")
    block_time = tx.get("blockTime")
    events: list[TradeEvent] = []
    for d in deltas:
        mint = d["mint"]
        if mint == WSOL:
            continue
        delta = d["delta"]
        if delta > 0:
            side = "buy"
            amount_sol = abs(sol_d) if sol_d is not None and sol_d < 0 else (abs(sol_d) if sol_d else None)
        else:
            side = "sell"
            amount_sol = abs(sol_d) if sol_d is not None and sol_d > 0 else (abs(sol_d) if sol_d else None)
        events.append(TradeEvent(
            signature=signature,
            wallet=wallet,
            token_mint=mint,
            side=side,
            amount_token=abs(delta),
            amount_sol=amount_sol,
            slot=slot,
            block_time=block_time,
            program_id=program_id,
            raw_note="parsed_from_token_balance_delta",
        ))
    return events


def fetch_wallet_raw(
    rpc: SolanaRPC,
    wallet: str,
    sig_limit: int,
    max_tx: int,
    program_id: str,
) -> dict[str, Any]:
    sigs = get_signatures(rpc, wallet, limit=sig_limit)
    txs = []
    for s in sigs[:max_tx]:
        sig = s.get("signature")
        if not sig:
            continue
        try:
            tx = get_transaction(rpc, sig)
        except Exception as exc:
            txs.append({"signature": sig, "error": str(exc)})
            continue
        txs.append({"signature": sig, "rpc_sig_meta": s, "transaction": tx})
    return {"wallet": wallet, "signatures": sigs, "transactions": txs, "program_id": program_id}


def save_raw(raw: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


def load_raw_dir(raw_dir: Path) -> list[dict[str, Any]]:
    out = []
    if not raw_dir.is_dir():
        return out
    for p in sorted(raw_dir.glob("*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def events_from_raw(raw_docs: list[dict[str, Any]], program_id: str | None = None) -> list[TradeEvent]:
    events: list[TradeEvent] = []
    for doc in raw_docs:
        wallet = doc.get("wallet") or ""
        for item in doc.get("transactions") or []:
            sig = item.get("signature") or ""
            tx = item.get("transaction")
            if not tx:
                continue
            events.extend(parse_trades_from_tx(tx, sig, wallet, program_id=program_id))
    return events

