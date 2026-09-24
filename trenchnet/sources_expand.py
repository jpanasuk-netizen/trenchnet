"""Expand roster from FREE public sources only. No signup, no paid keys, no X API."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from trenchnet.config_load import CONFIG_DIR, ROOT, load_roster, load_settings
from trenchnet.data_solana import SolanaRPC, get_signatures_page, parse_trades_from_tx, rpc_get_transaction
from trenchnet.history import history_dir, history_events_for_wallet
from trenchnet.rpc_pool import FREE_RPC_URLS, MultiEndpointRPC

KOLSCAN_RAW = (
    "https://raw.githubusercontent.com/yksanjo/kol-tracker/main/snapshots/2026-05-21_0320Z.json"
)
DEX_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
MAX_ROSTER = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_json(url: str, timeout: float = 30.0) -> Any | None:
    try:
        r = httpx.get(url, timeout=timeout, headers={"Accept": "application/json", "User-Agent": "TRENCHNET-observe/1.0"})
        if r.status_code != 200:
            return {"_blocked": True, "status": r.status_code, "url": url}
        return r.json()
    except Exception as exc:
        return {"_error": str(exc), "url": url}


def fetch_kolscan_snapshot(url: str = KOLSCAN_RAW) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Public GitHub mirror of Kolscan leaderboard — no auth."""
    data = _get_json(url)
    meta = {"source_url": url, "fetched_at": _now(), "ok": False}
    out: list[dict[str, Any]] = []
    if not isinstance(data, dict) or data.get("_blocked") or data.get("_error"):
        meta["detail"] = data
        return out, meta
    # yksanjo/kol-tracker snapshot: {daily,weekly,monthly: [{rank,wallet,name,...}]}
    rows = []
    if isinstance(data, list):
        rows = data
    else:
        for key in ("monthly", "weekly", "daily", "leaderboard", "wallets", "kols"):
            chunk = data.get(key)
            if isinstance(chunk, list) and chunk:
                rows = chunk
                meta["board"] = key
                break
        if not rows:
            nested = data.get("data")
            if isinstance(nested, list):
                rows = nested
            elif isinstance(nested, dict):
                rows = nested.get("items") or nested.get("results") or []
    for i, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict):
            continue
        addr = row.get("wallet") or row.get("address") or row.get("owner") or row.get("pubkey")
        if not addr or not isinstance(addr, str) or len(addr) < 32:
            continue
        out.append({
            "address": addr,
            "label": row.get("name") or row.get("label") or row.get("username") or f"kol_{i+1}",
            "role": "expanded",
            "kolscan_rank_monthly": row.get("rank") or row.get("monthly_rank") or (i + 1),
            "source_name": "Kolscan snapshot (GitHub mirror)",
            "source_url": url,
            "provenance": {"source_url": url, "fetched_at": meta["fetched_at"], "role": "expanded", "board": meta.get("board")},
            "notes": "Public KOL leaderboard entry; observe-only.",
        })
    meta["ok"] = True
    meta["count"] = len(out)
    return out, meta


def doji_token_mints(raw_dir: Path) -> list[str]:
    roster = load_roster()
    doji = None
    for w in roster.get("wallets") or []:
        if (w.get("label") or "").lower() == "doji":
            doji = w["address"]
            break
    if not doji:
        return []
    evs = history_events_for_wallet(history_dir(raw_dir), doji)
    mints = []
    seen = set()
    for e in evs:
        m = getattr(e, "token_mint", None)
        if m and m not in seen:
            seen.add(m)
            mints.append(m)
    return mints


def co_buyers_for_mint(rpc: SolanaRPC, mint: str, seed_addrs: set[str], max_pages: int = 3, max_tx: int = 40) -> list[dict[str, Any]]:
    """On-chain co-traders of a mint via free RPC (no signup)."""
    found: dict[str, int] = {}
    before = None
    pages = 0
    txs = 0
    while pages < max_pages and txs < max_tx:
        try:
            sigs = get_signatures_page(rpc, mint, before=before, limit=50)
        except Exception:
            break
        if not sigs:
            break
        pages += 1
        for s in sigs:
            if txs >= max_tx:
                break
            if s.get("err"):
                continue
            sig = s.get("signature")
            if not sig:
                continue
            try:
                tx = rpc_get_transaction(rpc, sig)
            except Exception:
                continue
            txs += 1
            if not tx:
                continue
            # Any wallet with token delta on this mint
            meta = tx.get("meta") or {}
            for bal in (meta.get("postTokenBalances") or []):
                if bal.get("mint") != mint:
                    continue
                owner = bal.get("owner")
                if not owner or owner in seed_addrs:
                    continue
                found[owner] = found.get(owner, 0) + 1
            time.sleep(0.25)
        before = (sigs[-1] or {}).get("signature")
        time.sleep(0.5)
    rows = []
    src = f"on-chain co-trade of mint {mint} via free Solana RPC"
    for addr, n in sorted(found.items(), key=lambda kv: -kv[1]):
        rows.append({
            "address": addr,
            "label": f"cobuy_{addr[:6]}",
            "role": "expanded",
            "overlap_hits": n,
            "source_name": "on-chain mint co-traders",
            "source_url": f"https://solscan.io/token/{mint}",
            "provenance": {
                "source_url": f"https://solscan.io/token/{mint}",
                "fetched_at": _now(),
                "role": "expanded",
                "method": "getSignaturesForAddress+getTransaction",
                "mint": mint,
                "hits": n,
            },
            "notes": src,
        })
    return rows


def dexscreener_token_meta(mint: str) -> dict[str, Any]:
    url = DEX_TOKEN.format(mint=mint)
    data = _get_json(url)
    return {"source_url": url, "fetched_at": _now(), "data": data}


def expand_roster(*, max_total: int = MAX_ROSTER, do_cobuy: bool = True) -> dict[str, Any]:
    settings = load_settings()
    raw_dir = ROOT / settings.get("paths", {}).get("raw_dir", "data/raw")
    roster_path = CONFIG_DIR / "roster.yaml"
    doc = yaml.safe_load(roster_path.read_text(encoding="utf-8")) or {}
    seeds = list(doc.get("wallets") or [])
    for w in seeds:
        w["role"] = w.get("role") or "seed"
    seed_addrs = {w["address"] for w in seeds}
    blocked: list[dict[str, Any]] = []
    used: list[dict[str, Any]] = []

    # pump.fun frontend — expect blocked without JWT; record honestly
    pf = _get_json("https://frontend-api-v3.pump.fun/coins/latest")
    if isinstance(pf, dict) and (pf.get("_blocked") or pf.get("_error") or not isinstance(pf, list)):
        blocked.append({
            "source": "pump.fun frontend-api-v3",
            "why": "Not readable without login/JWT (404/auth). Needs free signup for Jeremy — NOT signed up.",
            "detail": pf if isinstance(pf, dict) else type(pf).__name__,
        })

    kols, kol_meta = fetch_kolscan_snapshot()
    used.append({"source": "kolscan_github", **kol_meta})

    candidates: list[dict[str, Any]] = []
    seen = set(seed_addrs)
    for k in kols:
        if k["address"] in seen:
            continue
        seen.add(k["address"])
        candidates.append(k)

    cobuy_added = 0
    if do_cobuy:
        pool = MultiEndpointRPC()
        mints = doji_token_mints(raw_dir)[:6]
        for i, mint in enumerate(mints):
            rpc = pool.bind_wallet(i)
            rows = co_buyers_for_mint(rpc, mint, seed_addrs, max_pages=2, max_tx=30)
            used.append({"source": "cobuy", "mint": mint, "found": len(rows), "rpc": rpc.url})
            for r in rows:
                if r["address"] in seen:
                    # bump overlap
                    for c in candidates:
                        if c["address"] == r["address"]:
                            c["overlap_hits"] = c.get("overlap_hits", 0) + r.get("overlap_hits", 0)
                    continue
                seen.add(r["address"])
                candidates.append(r)
                cobuy_added += 1

    # Rank: co-buy overlap first, then kolscan rank
    def crank(c):
        return (-int(c.get("overlap_hits") or 0), int(c.get("kolscan_rank_monthly") or 9999))

    candidates.sort(key=crank)
    room = max(0, max_total - len(seeds))
    chosen = candidates[:room]
    new_wallets = seeds + chosen
    doc["wallets"] = new_wallets
    doc["roster_meta"] = {
        "seed_count": len(seeds),
        "expanded_count": len(chosen),
        "total": len(new_wallets),
        "max_wallets": max_total,
        "updated_at": _now(),
        "sources_used": used,
        "sources_blocked": blocked,
        "needs_free_signup": [
            {"service": "pump.fun frontend API", "why": "JWT/auth required for trades/holders endpoints"},
            {"service": "Birdeye / GMGN APIs", "why": "Typically require free API key signup — not used this pass"},
        ],
        "x_api": "NOT used (balance ~$0 / policy)",
    }
    roster_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    report = {
        "seed": len(seeds),
        "expanded": len(chosen),
        "total": len(new_wallets),
        "cobuy_candidates": cobuy_added,
        "blocked": blocked,
        "used": used,
    }
    (ROOT / "out" / "expand_roster_pass3.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report
