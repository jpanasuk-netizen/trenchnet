"""Read-only Coin Desk (hood.fun / Base) observer for TRENCHNET.

Never starts/stops Coin Desk. Tries live :3010/api/state, else falls back to
%LOCALAPPDATA%\\token-desk\\data\\decisions.jsonl.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

COINDESK_URL = os.environ.get("COIN_DESK_SOURCE", "http://127.0.0.1:3010/api/state")
DEFAULT_TIMEOUT_S = 1.5


def decisions_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or ""
    return Path(local) / "token-desk" / "data" / "decisions.jsonl"


def ready_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or ""
    return Path(local) / "token-desk" / "data" / "ready.txt"


def _iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def read_decisions_jsonl(path: Path | None = None, *, limit: int = 80) -> list[dict[str, Any]]:
    path = path or decisions_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    for line in lines[-limit:]:
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def fetch_live_state(*, url: str = COINDESK_URL, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any] | None:
    try:
        r = httpx.get(url, timeout=timeout_s)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def normalize_card(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Map Coin Desk / JSONL row into a uniform card for the UI."""
    verdict = str(row.get("verdict") or row.get("call") or "").upper()
    gate = row.get("gate") if isinstance(row.get("gate"), dict) else {}
    stage = str(gate.get("stage") or row.get("stage") or "")
    # PASS/WATCH from judge; gate stage WATCH/STOP
    call = verdict if verdict in ("PASS", "SKIP", "WATCH") else (stage or "UNKNOWN")
    if call == "SKIP":
        call = "WATCH"  # show softer label; still note original
    addr = row.get("address") or row.get("token") or ""
    return {
        "chain": "Base",
        "venue": "hood.fun",
        "call": call,
        "verdict_raw": verdict or None,
        "gate_stage": stage or None,
        "name": row.get("name"),
        "symbol": row.get("symbol"),
        "address": addr,
        "creator": row.get("creator"),
        "age_sec": row.get("age_sec"),
        "real_eth": row.get("real_eth"),
        "graduated": row.get("graduated"),
        "fee_bps": row.get("fee_bps"),
        "reason": row.get("reason") or (gate.get("reasons") if gate else None),
        "logged_at": row.get("logged_at") or row.get("ts"),
        "logged_at_iso": _iso(row.get("logged_at") or row.get("ts")),
        "link_hood": f"https://hood.fun/" if not addr else f"https://hood.fun/",  # board; address deep-links vary
        "link_basescan": f"https://basescan.org/token/{addr}" if addr else None,
        "source": source,
        "execute": False,
        "paper_only": True,
    }


def get_coindesk_state(
    *,
    url: str = COINDESK_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    decisions_file: Path | None = None,
) -> dict[str, Any]:
    """Live-first, JSONL fallback. Never mutates Coin Desk."""
    live = fetch_live_state(url=url, timeout_s=timeout_s)
    if live is not None:
        fresh = live.get("fresh") or live.get("cards") or live.get("inside_hour") or []
        newest = live.get("newest") or []
        cards = []
        if isinstance(fresh, list):
            cards.extend(normalize_card(x, source="live:/api/state") for x in fresh if isinstance(x, dict))
        if isinstance(newest, list):
            for x in newest:
                if isinstance(x, dict):
                    cards.append(normalize_card(x, source="live:/api/state:newest"))
        return {
            "ok": True,
            "status": "live",
            "paper_only": True,
            "chain": "Base",
            "venue": "hood.fun",
            "label": "Base / hood.fun — PAPER watch (not Solana)",
            "source_url": url,
            "as_of_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "board": {k: live.get(k) for k in ("token_count", "board_up", "newest_age", "status") if k in live},
            "cards": cards,
            "raw_keys": sorted(live.keys()),
            "note": "Coin Desk process responded on :3010. TRENCHNET does not start/stop it.",
        }

    path = decisions_file or decisions_path()
    rows = read_decisions_jsonl(path)
    mtime = None
    if path.is_file():
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
    cards = [normalize_card(r, source="fallback:decisions.jsonl") for r in rows]
    # Prefer PASS/WATCH-looking rows first for display
    cards_sorted = sorted(cards, key=lambda c: float(c.get("logged_at") or 0), reverse=True)
    return {
        "ok": True,
        "status": "offline",
        "paper_only": True,
        "chain": "Base",
        "venue": "hood.fun",
        "label": "Base / hood.fun — PAPER watch (not Solana)",
        "source_url": url,
        "as_of_utc": _iso(mtime),
        "as_of_mtime": mtime,
        "decisions_path_hint": "%LOCALAPPDATA%\\token-desk\\data\\decisions.jsonl",
        "cards": cards_sorted,
        "n_cards": len(cards_sorted),
        "note": (
            f"offline, data as of {_iso(mtime) or 'unknown'} — "
            "start Coin Desk.exe separately if you want a live board. "
            "TRENCHNET will not start it."
        ),
    }
