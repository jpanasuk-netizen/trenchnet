"""Wallet history via Helius enhanced txs (PRIMARY) with public-RPC fallback.

Resumable under data/raw/history/<wallet>.json. Events tagged source=helius.
Never logs API keys.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trenchnet.data_solana import SolanaRPC
from trenchnet.helius_client import (
    HeliusClient,
    HeliusLimitError,
    helius_configured,
    parse_enhanced_swap,
    redact_url,
    rpc_url_for_solana,
)
from trenchnet.history import (
    _load_state,
    _save_state,
    fetch_wallet_history as fetch_wallet_history_rpc,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_wallet_history_helius(
    wallet: str,
    cache_path: Path,
    *,
    max_pages: int = 25,
    page_limit: int = 50,
    prefer_pump: bool = True,
    log_fn=None,
    allow_rpc_fallback: bool = True,
    rpc_fallback_url: str | None = None,
    rpc_max_pages: int = 8,
    rpc_max_tx: int = 80,
    reset_helius_cursor: bool = False,
) -> dict[str, Any]:
    """PRIMARY: Helius enhanced SWAP pages. FALLBACK: public/Helius RPC parse."""
    log = log_fn or (lambda m: None)
    st = _load_state(cache_path)
    if st.get("wallet") and st.get("wallet") != wallet:
        st = {}
    st.setdefault("wallet", wallet)
    st.setdefault("seen", [])
    st.setdefault("events", [])
    st.setdefault("pages_fetched", 0)
    st.setdefault("txs_fetched", 0)
    st.setdefault("errors", [])
    st.setdefault("sources_used", [])
    seen: set[str] = set(st["seen"])
    events: list[dict[str, Any]] = list(st["events"])
    existing_keys = {
        (e.get("signature"), e.get("token_mint"), e.get("side"))
        for e in events
    }
    pages = int(st.get("helius_pages") or 0)
    errors: list[str] = list(st["errors"])
    helius_ok = False
    stopped: str | None = None
    limit_hit = False

    def _persist(**extra: Any) -> None:
        st.update({
            "seen": sorted(seen)[-8000:],
            "events": events,
            "helius_pages": pages,
            "pages_fetched": max(int(st.get("pages_fetched") or 0), pages),
            "updated_at": _now(),
            "complete": False,
            "source_primary": "helius" if helius_ok else st.get("source_primary"),
            "sources_used": st["sources_used"],
            "errors": errors[-30:],
        })
        st.update(extra)
        _save_state(cache_path, st)

    def _ingest_batch(batch: list[dict[str, Any]]) -> int:
        added = 0
        for tx in batch:
            if not isinstance(tx, dict):
                continue
            sig = tx.get("signature") or ""
            for ev in parse_enhanced_swap(tx, wallet):
                key = (ev.signature, ev.token_mint, ev.side)
                if key in existing_keys:
                    continue
                events.append(ev.to_dict())
                existing_keys.add(key)
                added += 1
            if sig:
                seen.add(sig)
        return added

    if helius_configured():
        try:
            client = HeliusClient()
            before_cursor = None if reset_helius_cursor else st.get("helius_before")
            if len(events) == 0:
                before_cursor = None
            pages_this = 0
            empty_pump_pages = 0
            for page_idx, batch in client.iter_enhanced_swaps(
                wallet,
                max_pages=max_pages,
                page_limit=page_limit,
                prefer_pump=prefer_pump,
                before=before_cursor,
                log_fn=log,
            ):
                added = _ingest_batch(batch)
                pages_this += 1
                pages += 1
                helius_ok = True
                if "helius" not in st["sources_used"]:
                    st["sources_used"].append("helius")
                last_sig = batch[-1].get("signature") if batch else None
                _persist(helius_before=last_sig, stopped_early_reason=None,
                         txs_fetched=int(st.get("txs_fetched") or 0) + len(batch))
                log(f"helius {wallet[:8]}: page {page_idx} +{added} ev total={len(events)}")
                if added == 0:
                    empty_pump_pages += 1
                else:
                    empty_pump_pages = 0
                if empty_pump_pages >= 3:
                    log(f"helius_pump_empty_stop {wallet[:8]}")
                    break
                if pages_this >= max_pages:
                    stopped = "max_pages"
                    break

            # Broad unfiltered pass if still no helius-tagged events (skip on shallow runs)
            helius_event_n = sum(1 for e in events if e.get("source") == "helius")
            if helius_event_n == 0 and max_pages > 4:
                log(f"helius_broad {wallet[:8]}")
                before_b = None
                for bi in range(max(4, max_pages // 2)):
                    batch = client.fetch_any_page(wallet, before=before_b, limit=page_limit)
                    if not batch:
                        break
                    added = _ingest_batch(batch)
                    pages += 1
                    helius_ok = True
                    before_b = batch[-1].get("signature")
                    if "helius" not in st["sources_used"]:
                        st["sources_used"].append("helius")
                    _persist(helius_before=before_b)
                    log(f"helius_broad {wallet[:8]}: page {bi+1} +{added} ev total={len(events)}")
                    if added == 0 and bi >= 2:
                        break

            if helius_ok and not stopped:
                st["helius_complete"] = True
            if client.credits_exhausted:
                stopped = "helius_credits"
                limit_hit = True
        except HeliusLimitError:
            stopped = "helius_limit"
            limit_hit = True
            errors.append("helius_limit")
            log(f"helius_limit {wallet[:8]}")
            _persist(stopped_early_reason=stopped)
            return {
                "wallet": wallet,
                "complete": False,
                "events": len(events),
                "helius_pages": pages,
                "stopped_early_reason": stopped,
                "source": "helius",
                "limit_hit": True,
            }
        except Exception as exc:
            errors.append(f"helius_error:{type(exc).__name__}")
            log(f"helius_fail {wallet[:8]} {type(exc).__name__}")
            helius_ok = False
    else:
        log("helius_not_configured")

    if allow_rpc_fallback and (not helius_ok or len(events) == 0):
        pages_prior = int(st.get("pages_fetched") or 0)
        if st.get("skip_rpc_zerofill") or (pages_prior >= 40 and len(events) == 0):
            log(f"rpc_skip_zerofill {wallet[:8]} pages={pages_prior}")
            _persist(stopped_early_reason="zero_fill_skip")
            return {
                "wallet": wallet,
                "complete": False,
                "events": len(events),
                "helius_pages": pages,
                "stopped_early_reason": "zero_fill_skip",
                "source": "helius" if helius_ok else "none",
                "limit_hit": limit_hit,
            }
        url = rpc_fallback_url or rpc_url_for_solana() or "https://api.mainnet-beta.solana.com"
        log(f"rpc_fallback {wallet[:8]} via={redact_url(url).split('?')[0]}")
        rpc = SolanaRPC(url, sleep_ms=280)
        try:
            res = fetch_wallet_history_rpc(
                rpc, wallet, cache_path,
                max_pages=rpc_max_pages, max_tx=rpc_max_tx,
                log_fn=log,
            )
            st2 = _load_state(cache_path)
            for e in st2.get("events") or []:
                if not e.get("source"):
                    e["source"] = "rpc"
            if "rpc" not in (st2.get("sources_used") or []):
                st2.setdefault("sources_used", []).append("rpc")
            _save_state(cache_path, st2)
            return {
                "wallet": wallet,
                "complete": bool(res.get("complete")),
                "events": len(st2.get("events") or []),
                "helius_pages": pages,
                "stopped_early_reason": res.get("stopped_early_reason") or stopped,
                "source": "rpc_fallback",
                "limit_hit": limit_hit,
            }
        except Exception as exc:
            errors.append(f"rpc_fallback:{type(exc).__name__}")
            log(f"rpc_fallback_fail {wallet[:8]} {type(exc).__name__}")

    complete = bool(st.get("helius_complete")) and not stopped
    _persist(complete=complete, stopped_early_reason=stopped, helius_pages=pages)
    return {
        "wallet": wallet,
        "complete": complete,
        "events": len(events),
        "helius_pages": pages,
        "stopped_early_reason": stopped,
        "source": "helius" if helius_ok else "none",
        "limit_hit": limit_hit,
    }