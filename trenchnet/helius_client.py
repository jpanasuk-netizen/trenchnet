"""Helius Enhanced Transactions + RPC helpers.

PRIMARY wallet-history feed for TRENCHNET Pass 4.
Keys via trenchnet.secrets.get_secret — NEVER log key values or api-key query params.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import httpx

from trenchnet.models import TradeEvent
from trenchnet.secrets import get_secret

WSOL = "So11111111111111111111111111111111111111112"
PUMP_SOURCES = {"PUMP_FUN", "PUMP_AMM", "PUMPFUN", "PUMP"}


def redact_url(url: str) -> str:
    """Strip api-key / authorization query values for safe logging."""
    try:
        parts = urlparse(url)
        q = parse_qs(parts.query, keep_blank_values=True)
        for k in list(q.keys()):
            if k.lower() in ("api-key", "apikey", "api_key", "key", "access_token", "token"):
                q[k] = ["REDACTED"]
        return urlunparse(parts._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    except Exception:
        return re.sub(r"(api-key=)[^&\\s]+", r"\\1REDACTED", url, flags=re.I)


def _api_key() -> str | None:
    return get_secret("HELIUS_API_KEY")


def _rpc_url() -> str | None:
    """Prefer HELIUS_RPC_URL; else build from key. Never log the result."""
    url = get_secret("HELIUS_RPC_URL")
    if url:
        return url.strip()
    key = _api_key()
    if not key:
        return None
    return f"https://mainnet.helius-rpc.com/?api-key={key}"


def helius_configured() -> bool:
    return bool(_api_key() or get_secret("HELIUS_RPC_URL"))


class HeliusLimitError(RuntimeError):
    """Raised when free-tier credits / hard rate limits require a graceful stop."""


class HeliusClient:
    """Enhanced Transactions API client with 429 backoff."""

    def __init__(self, sleep_ms: int = 250, max_retries: int = 4):
        self.sleep_ms = sleep_ms
        self.max_retries = max_retries
        self.last_error: str | None = None
        self.credits_exhausted = False
        key = _api_key()
        if not key:
            raise RuntimeError("HELIUS_API_KEY missing")
        self._key = key
        # Prefer api.helius.xyz for enhanced REST; also works via helius-rpc host
        self.base = "https://api.helius.xyz"

    def _tx_url(self, address: str) -> str:
        return f"{self.base}/v0/addresses/{address}/transactions"

    def fetch_enhanced_page(
        self,
        address: str,
        *,
        before: str | None = None,
        limit: int = 50,
        tx_type: str = "SWAP",
        source: str | None = "PUMP_FUN",
    ) -> list[dict[str, Any]]:
        """One page of enhanced txs. Filters type=SWAP and optional source=PUMP_FUN.

        Pagination via before=signature (newest-first). On type-filter search-window
        miss, follows the continuation signature from the error body.
        """
        params: dict[str, Any] = {
            "api-key": self._key,
            "limit": max(1, min(int(limit), 100)),
            "type": tx_type,
            "sort-order": "desc",
            "token-accounts": "balanceChanged",
        }
        if source:
            params["source"] = source
        if before:
            params["before"] = before
            # docs also use before-signature
            params["before-signature"] = before

        url = self._tx_url(address)
        safe = redact_url(f"{url}?type={tx_type}")
        for attempt in range(self.max_retries):
            try:
                r = httpx.get(url, params=params, timeout=60.0)
            except httpx.HTTPError as exc:
                self.last_error = f"http_error:{type(exc).__name__}"
                time.sleep(1.5 * (attempt + 1))
                continue

            if r.status_code == 429:
                self.last_error = f"429@{safe}"
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                self.credits_exhausted = True
                self.last_error = f"auth_or_plan_blocked status={r.status_code}"
                raise HeliusLimitError(self.last_error)
            if r.status_code >= 500:
                self.last_error = f"server_{r.status_code}@{safe}"
                time.sleep(1.5 * (attempt + 1))
                continue

            # Some plan limits return 402 / 4xx with credit messages
            body: Any
            try:
                body = r.json()
            except Exception:
                self.last_error = f"bad_json status={r.status_code}"
                return []

            if isinstance(body, dict) and body.get("error"):
                err = str(body.get("error"))
                # Continuation for type-filter search window
                m = re.search(r"parameter set to ([A-Za-z0-9]+)", err)
                if m and "Failed to find events" in err:
                    # Caller should retry with this before cursor; return sentinel page
                    return [{"_continue_before": m.group(1)}]
                low = err.lower()
                if "credit" in low or "limit" in low or "quota" in low:
                    self.credits_exhausted = True
                    self.last_error = "credits_or_quota"
                    raise HeliusLimitError(self.last_error)
                self.last_error = f"api_error:{err[:120]}"
                # Retry without source filter once if source rejected
                if source and attempt == 0:
                    source = None
                    params.pop("source", None)
                    continue
                return []

            if not isinstance(body, list):
                self.last_error = f"unexpected_shape status={r.status_code}"
                return []

            time.sleep(self.sleep_ms / 1000.0)
            return [x for x in body if isinstance(x, dict) and x.get("signature")]

        raise RuntimeError(f"Helius enhanced page failed after retries: {self.last_error}")

    def fetch_any_page(
        self,
        address: str,
        *,
        before: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Unfiltered enhanced history page (no type/source). Safer for thin wallets."""
        params: dict[str, Any] = {
            "api-key": self._key,
            "limit": max(1, min(int(limit), 100)),
            "sort-order": "desc",
            "token-accounts": "balanceChanged",
        }
        if before:
            params["before"] = before
            params["before-signature"] = before
        url = self._tx_url(address)
        safe = redact_url(url)
        for attempt in range(self.max_retries):
            try:
                r = httpx.get(url, params=params, timeout=60.0)
            except httpx.HTTPError:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                self.credits_exhausted = True
                raise HeliusLimitError(f"auth_or_plan_blocked status={r.status_code}")
            if r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            body = r.json()
            if not isinstance(body, list):
                return []
            time.sleep(self.sleep_ms / 1000.0)
            return [x for x in body if isinstance(x, dict) and x.get("signature")]
        raise RuntimeError(f"Helius any-page failed: {self.last_error} host={safe}")

    def iter_enhanced_swaps(
        self,
        address: str,
        *,
        max_pages: int = 20,
        page_limit: int = 50,
        prefer_pump: bool = True,
        before: str | None = None,
        log_fn=None,
    ):
        """Yield (page_idx, txs) newest-first until empty or max_pages."""
        log = log_fn or (lambda m: None)
        source = "PUMP_FUN" if prefer_pump else None
        pages = 0
        empty_streak = 0
        while pages < max_pages:
            try:
                batch = self.fetch_enhanced_page(
                    address, before=before, limit=page_limit, source=source
                )
            except HeliusLimitError:
                log(f"helius_limit stop pages={pages}")
                raise
            # Continuation sentinel
            if len(batch) == 1 and isinstance(batch[0], dict) and batch[0].get("_continue_before"):
                before = batch[0]["_continue_before"]
                empty_streak += 1
                if empty_streak > 2:
                    log("helius_continue_exhausted")
                    break
                continue
            if not batch:
                break
            empty_streak = 0
            pages += 1
            yield pages, batch
            last_sig = batch[-1].get("signature") if isinstance(batch[-1], dict) else None
            if not last_sig or last_sig == before:
                break
            before = last_sig


def parse_enhanced_swap(tx: dict[str, Any], wallet: str) -> list[TradeEvent]:
    """Convert one Helius enhanced tx into TradeEvent(s) for wallet."""
    if not isinstance(tx, dict):
        return []
    sig = tx.get("signature") or ""
    if not sig:
        return []
    src = str(tx.get("source") or "")
    slot = tx.get("slot")
    ts = tx.get("timestamp") or tx.get("blockTime")
    try:
        block_time = int(ts) if ts is not None else None
    except Exception:
        block_time = None
    events: list[TradeEvent] = []

    def _add(mint: str, side: str, amt: float, sol: float | None = None, note: str = "") -> None:
        if not mint or mint == WSOL:
            return
        events.append(TradeEvent(
            signature=sig,
            wallet=wallet,
            token_mint=str(mint),
            side=side,  # type: ignore[arg-type]
            amount_token=abs(float(amt or 0)),
            amount_sol=sol,
            slot=int(slot) if slot is not None else None,
            block_time=block_time,
            program_id=src or str(tx.get("type") or "HELIUS"),
            raw_note=note or f"helius type={tx.get('type')} source={src}",
            source="helius",
        ))

    swap = ((tx.get("events") or {}) if isinstance(tx.get("events"), dict) else {}).get("swap")
    if isinstance(swap, dict):
        for side_key, side in (("tokenInputs", "sell"), ("tokenOutputs", "buy")):
            for item in swap.get(side_key) or []:
                if not isinstance(item, dict):
                    continue
                mint = item.get("mint") or item.get("tokenMint")
                raw_amt = item.get("tokenAmount") or item.get("rawTokenAmount") or {}
                if isinstance(raw_amt, dict):
                    try:
                        amt = float(raw_amt.get("tokenAmount") or raw_amt.get("uiAmount") or 0)
                    except Exception:
                        amt = 0.0
                else:
                    try:
                        amt = float(raw_amt or 0)
                    except Exception:
                        amt = 0.0
                sol = None
                if side == "buy":
                    ni = swap.get("nativeInput") or {}
                    if isinstance(ni, dict):
                        try:
                            sol = abs(float(ni.get("amount") or 0)) / 1e9
                        except Exception:
                            sol = None
                else:
                    no = swap.get("nativeOutput") or {}
                    if isinstance(no, dict):
                        try:
                            sol = abs(float(no.get("amount") or 0)) / 1e9
                        except Exception:
                            sol = None
                _add(str(mint or ""), side, amt, sol, "helius_events.swap")
        if events:
            return events

    for tr in tx.get("tokenTransfers") or []:
        if not isinstance(tr, dict):
            continue
        mint = tr.get("mint")
        frm = tr.get("fromUserAccount")
        to = tr.get("toUserAccount")
        try:
            amt = float(tr.get("tokenAmount") or tr.get("amount") or 0)
        except Exception:
            amt = 0.0
        if to == wallet:
            _add(str(mint or ""), "buy", amt, None, "helius_tokenTransfer")
        elif frm == wallet:
            _add(str(mint or ""), "sell", amt, None, "helius_tokenTransfer")
    if events:
        return events

    for acc in tx.get("accountData") or []:
        if not isinstance(acc, dict):
            continue
        for tb in acc.get("tokenBalanceChanges") or []:
            if not isinstance(tb, dict):
                continue
            user = tb.get("userAccount")
            if user and user != wallet and acc.get("account") != wallet:
                continue
            if not user and acc.get("account") != wallet:
                continue
            mint = tb.get("mint")
            raw = tb.get("rawTokenAmount") or {}
            amt = 0.0
            try:
                if isinstance(raw, dict):
                    if raw.get("uiAmount") is not None:
                        amt = float(raw.get("uiAmount") or 0)
                    else:
                        token_amount = float(raw.get("tokenAmount") or 0)
                        dec = int(raw.get("decimals") or 0)
                        amt = token_amount / (10 ** dec) if dec else token_amount
            except Exception:
                amt = 0.0
            if abs(amt) < 1e-18:
                continue
            side = "buy" if amt > 0 else "sell"
            _add(str(mint or ""), side, abs(amt), None, "helius_accountData")
    return events


def rpc_url_for_solana() -> str | None:
    """Return Helius RPC URL for SolanaRPC fallback chain (caller must not log)."""
    return _rpc_url()
