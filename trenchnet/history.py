"""Resumable FULL HISTORY fetch for roster wallets via free public RPC.

Pages getSignaturesForAddress with `before` until an EMPTY page comes back
(oldest reached). Progress + parsed events checkpoint incrementally under
data/raw/history/<wallet>.json so a run interrupted by 429s resumes where it
left off. Never invents trades.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trenchnet.data_solana import (
    PUMPSWAP_PROGRAM,
    SolanaRPC,
    get_signatures_page,
    parse_trades_from_tx,
    rpc_get_transaction,
)

PAGE_LIMIT = 100          # small, polite batches
SLEEP_BETWEEN_TX = 0.35   # seconds between getTransaction calls
SLEEP_BETWEEN_PAGES = 1.0


def history_dir(raw_dir: Path) -> Path:
    return raw_dir / "history"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_state(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_progress(history_root: Path, wallet: str) -> dict[str, Any] | None:
    return _load_state(history_root / f"{wallet}.json")


def all_progress(history_root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not history_root.is_dir():
        return out
    for p in sorted(history_root.glob("*.json")):
        st = _load_state(p)
        if st:
            out[st.get("wallet") or p.stem] = st
    return out


def history_events_for_wallet(history_root: Path, wallet: str) -> list:
    """Parsed TradeEvents for one wallet from its cached state file (if any)."""
    from trenchnet.models import TradeEvent

    st = _load_state(history_root / f"{wallet}.json")
    out: list[TradeEvent] = []
    for e in st.get("events") or []:
        try:
            out.append(TradeEvent(**e))
        except TypeError:
            continue
    return out


def fetch_wallet_history(
    rpc: SolanaRPC,
    wallet: str,
    cache_path: Path,
    *,
    program_id: str | None = None,
    max_pages: int | None = None,
    max_tx: int | None = None,
    log_fn=None,
) -> dict[str, Any]:
    """Page signatures oldest-ward until an empty page; parse every ecosystem tx.

    Resumable: state file keeps the seen-signature set + parsed events; on
    restart, already-seen signatures are skipped without re-fetching txs. If
    max_tx stops us mid-page, the page cursor is NOT advanced so the same page
    is re-listed on resume (sig listing is cheap; txs are skipped by seen-set).
    """
    program_id = program_id or PUMPSWAP_PROGRAM  # sentinel meaning "ecosystem"
    log = log_fn or (lambda msg: None)
    st = _load_state(cache_path)
    if st.get("wallet") and st.get("wallet") != wallet:
        st = {}
    st.setdefault("wallet", wallet)
    st.setdefault("seen", [])
    st.setdefault("events", [])
    st.setdefault("pages_fetched", 0)
    st.setdefault("txs_fetched", 0)
    st.setdefault("errors", [])
    seen: set[str] = set(st["seen"])
    events: list[dict[str, Any]] = list(st["events"])
    pages = int(st["pages_fetched"])
    txs = int(st["txs_fetched"])
    errors: list[str] = list(st["errors"])
    oldest_sig: str | None = st.get("oldest_signature")
    oldest_time = st.get("oldest_block_time")

    # Resume paging from last cursor so error-spam wallets don't re-walk the tip every run.
    before: str | None = st.get("before_cursor")
    exhausted = False
    pages_this_run = 0
    txs_this_run = 0
    stopped_early_reason: str | None = None

    while not exhausted and stopped_early_reason is None:
        if max_pages is not None and pages_this_run >= max_pages:
            stopped_early_reason = "max_pages"
            break
        try:
            sigs = get_signatures_page(rpc, wallet, before=before, limit=PAGE_LIMIT)
        except Exception as exc:
            msg = str(exc)
            # Bad/pruned cursor: drop before and retry from tip once (seen-set skips)
            if before and ("not found" in msg.lower() or "-32020" in msg):
                errors.append(f"page_cursor_reset@{before[:16]}:{exc}")
                before = None
                st["before_cursor"] = None
                log(f"{wallet[:8]}: reset before_cursor after page error")
                continue
            errors.append(f"page_error@{before or 'latest'}:{exc}")
            stopped_early_reason = f"page_error:{exc}"
            break
        if not sigs:
            exhausted = True
            break
        prev_before = before
        hit_tx_cap = False
        for s in sigs:
            sig = s.get("signature") or ""
            if not sig or sig in seen:
                continue
            if s.get("err"):
                seen.add(sig)
                continue
            if max_tx is not None and txs_this_run >= max_tx:
                hit_tx_cap = True
                break
            try:
                tx = rpc_get_transaction(rpc, sig)
            except Exception as exc:
                errors.append(f"tx_error:{sig[:16]}:{exc}")
                continue
            txs += 1
            txs_this_run += 1
            seen.add(sig)
            if not tx:
                continue
            parsed = parse_trades_from_tx(tx, sig, wallet, program_id=program_id)
            for ev in parsed:
                events.append(ev.to_dict())
                bt = ev.block_time
                if bt and (oldest_time is None or bt < oldest_time):
                    oldest_time = bt
                    oldest_sig = ev.signature
            time.sleep(SLEEP_BETWEEN_TX)
        pages += 1
        pages_this_run += 1
        if hit_tx_cap:
            # do not advance cursor: re-list this page on resume, unseen sigs retry
            before = prev_before
            stopped_early_reason = "max_tx"
        else:
            last_sig = (sigs[-1] or {}).get("signature")
            if not last_sig:
                exhausted = True
                break
            before = last_sig
        # incremental checkpoint after every page
        st.update({
            "seen": sorted(seen),
            "events": events,
            "pages_fetched": pages,
            "txs_fetched": txs,
            "errors": errors[-20:],
            "oldest_signature": oldest_sig,
            "oldest_block_time": oldest_time,
            "complete": False,
            "updated_at": _now_iso(),
            "stopped_early_reason": stopped_early_reason,
            "before_cursor": before,
        })
        _save_state(cache_path, st)
        log(f"{wallet[:8]}: page {pages} ok (+{txs_this_run} txs, {len(events)} events)")
        if not stopped_early_reason:
            time.sleep(SLEEP_BETWEEN_PAGES)

    complete = exhausted and stopped_early_reason is None
    st.update({
        "seen": sorted(seen),
        "events": events,
        "pages_fetched": pages,
        "txs_fetched": txs,
        "errors": errors[-20:],
        "oldest_signature": oldest_sig,
        "oldest_block_time": oldest_time,
        "complete": bool(complete),
        "updated_at": _now_iso(),
        "stopped_early_reason": stopped_early_reason,
        "observe_only": True,
        "before_cursor": before,
    })
    _save_state(cache_path, st)
    return {
        "wallet": wallet,
        "complete": bool(complete),
        "pages_fetched": pages,
        "txs_fetched": txs,
        "events": len(events),
        "oldest_block_time": oldest_time,
        "stopped_early_reason": stopped_early_reason,
    }


def oldest_iso(ts: int | float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _event_key(e) -> tuple:
    """Identity of a parsed trade: (wallet, signature, token_mint)."""
    if isinstance(e, dict):
        return (e.get("wallet"), e.get("signature"), e.get("token_mint"))
    return (getattr(e, "wallet", None), getattr(e, "signature", None), getattr(e, "token_mint", None))


def dedupe_events(events):
    """Merge poll-raw + full-history event lists without double-counting.

    The same tx can appear in both data/raw/<wallet>.json (recent poll) and
    data/raw/history/<wallet>.json (full fetch). Multiple token mints in one tx
    are legitimately distinct events and are kept.
    """
    seen: set[tuple] = set()
    out = []
    for e in events:
        key = _event_key(e)
        if key in seen or not all(key):
            if all(key):
                continue
            # malformed (missing signature/mint) — keep only if entirely unknown
            out.append(e)
            continue
        seen.add(key)
        out.append(e)
    return out
