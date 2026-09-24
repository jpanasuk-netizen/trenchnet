"""Pull free public token price/mcap/liq/volume context. No paid keys. No X."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from trenchnet.config_load import ROOT, load_settings

DEX_TOKEN = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
GECKO_TOKEN = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}"
GECKO_OHLCV = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/ohlcv/hour?limit=48"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get(url: str) -> tuple[Any | None, dict[str, Any]]:
    meta = {"source_url": url, "fetched_at": _now()}
    try:
        r = httpx.get(
            url,
            timeout=30.0,
            headers={"Accept": "application/json", "User-Agent": "TRENCHNET-observe/1.0"},
        )
        meta["status"] = r.status_code
        if r.status_code != 200:
            meta["ok"] = False
            return None, meta
        meta["ok"] = True
        return r.json(), meta
    except Exception as exc:
        meta["ok"] = False
        meta["error"] = str(exc)
        return None, meta


def context_dir(raw_dir: Path) -> Path:
    return raw_dir / "token_context"


def fetch_token_context(mint: str, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dex, dex_meta = _get(DEX_TOKEN.format(mint=mint))
    time.sleep(0.35)
    gecko, gecko_meta = _get(GECKO_TOKEN.format(mint=mint))
    time.sleep(0.35)
    ohlcv, ohlcv_meta = _get(GECKO_OHLCV.format(mint=mint))

    pair = None
    mentions: list[dict[str, Any]] = []
    if isinstance(dex, dict):
        pairs = [p for p in (dex.get("pairs") or []) if (p.get("chainId") == "solana")]
        pairs.sort(key=lambda p: float(((p.get("liquidity") or {}).get("usd") or 0)), reverse=True)
        if pairs:
            pair = pairs[0]
            info = pair.get("info") or {}
            for s in info.get("socials") or []:
                mentions.append({
                    "kind": "dexscreener_social",
                    "type": s.get("type"),
                    "url": s.get("url"),
                    "source_url": pair.get("url") or dex_meta["source_url"],
                })
            for w in info.get("websites") or []:
                mentions.append({
                    "kind": "dexscreener_website",
                    "label": w.get("label"),
                    "url": w.get("url"),
                    "source_url": pair.get("url") or dex_meta["source_url"],
                })

    snap = {
        "mint": mint,
        "fetched_at": _now(),
        "dexscreener": {
            "meta": dex_meta,
            "pair": {
                "url": (pair or {}).get("url"),
                "pairAddress": (pair or {}).get("pairAddress"),
                "dexId": (pair or {}).get("dexId"),
                "priceUsd": (pair or {}).get("priceUsd"),
                "priceNative": (pair or {}).get("priceNative"),
                "liquidity_usd": ((pair or {}).get("liquidity") or {}).get("usd"),
                "volume_h24": ((pair or {}).get("volume") or {}).get("h24"),
                "fdv": (pair or {}).get("fdv"),
                "marketCap": (pair or {}).get("marketCap"),
                "priceChange_h24": ((pair or {}).get("priceChange") or {}).get("h24"),
                "base_symbol": ((pair or {}).get("baseToken") or {}).get("symbol"),
                "quote_symbol": ((pair or {}).get("quoteToken") or {}).get("symbol"),
            } if pair else None,
        },
        "geckoterminal": {"meta": gecko_meta, "token": gecko},
        "ohlcv_hour": {"meta": ohlcv_meta, "data": ohlcv},
        "mentions": mentions,
        "links": {
            "solscan": f"https://solscan.io/token/{mint}",
            "dexscreener": (pair or {}).get("url") or f"https://dexscreener.com/solana/{mint}",
            "geckoterminal": f"https://www.geckoterminal.com/solana/tokens/{mint}",
        },
        "thin_data": pair is None,
        "note": None if pair else "No Dexscreener solana pair found (honest thin)",
    }
    path = out_dir / f"{mint}.json"
    path.write_text(json.dumps(snap, indent=2), encoding="utf-8")
    return snap


def load_all_contexts(raw_dir: Path) -> dict[str, Any]:
    d = context_dir(raw_dir)
    out: dict[str, Any] = {}
    if not d.is_dir():
        return out
    for p in d.glob("*.json"):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    return out


def fetch_for_mints(mints: list[str], raw_dir: Path | None = None) -> dict[str, Any]:
    settings = load_settings()
    raw = raw_dir or (ROOT / settings.get("paths", {}).get("raw_dir", "data/raw"))
    out_dir = context_dir(raw)
    results = {}
    for m in mints:
        if not m:
            continue
        results[m] = fetch_token_context(m, out_dir)
        time.sleep(0.4)
    return results
