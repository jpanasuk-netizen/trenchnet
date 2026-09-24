"""Birdeye free-tier client: price, OHLCV, wallet PnL / top traders.

Keys via trenchnet.secrets — NEVER log key values.
Records which endpoints were blocked on free tier.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from trenchnet.secrets import get_secret

BASE = "https://public-api.birdeye.so"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def birdeye_configured() -> bool:
    return bool(get_secret("BIRDEYE_API_KEY"))


class BirdeyeClient:
    def __init__(self, sleep_ms: int = 1100, max_retries: int = 4):
        # Free Standard tier ~1 rps
        key = get_secret("BIRDEYE_API_KEY")
        if not key:
            raise RuntimeError("BIRDEYE_API_KEY missing")
        self._key = key
        self.sleep_ms = sleep_ms
        self.max_retries = max_retries
        self.blocked: list[dict[str, Any]] = []
        self.last_error: str | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-API-KEY": self._key,
            "x-chain": "solana",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any | None, dict[str, Any]]:
        meta: dict[str, Any] = {
            "endpoint": path,
            "source": "birdeye",
            "fetched_at": _now(),
            "params_keys": sorted((params or {}).keys()),
        }
        url = BASE + path
        for attempt in range(self.max_retries):
            try:
                r = httpx.get(url, params=params or {}, headers=self._headers(), timeout=45.0)
            except httpx.HTTPError as exc:
                self.last_error = type(exc).__name__
                time.sleep(1.5 * (attempt + 1))
                continue
            meta["status"] = r.status_code
            if r.status_code == 429:
                self.last_error = "429"
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code in (401, 403):
                meta["ok"] = False
                meta["blocked"] = True
                meta["reason"] = f"http_{r.status_code}"
                self.blocked.append({"endpoint": path, "status": r.status_code, "at": _now()})
                self.last_error = f"blocked_{r.status_code}"
                return None, meta
            if r.status_code == 404:
                meta["ok"] = False
                meta["blocked"] = True
                meta["reason"] = "not_found_or_unsupported"
                self.blocked.append({"endpoint": path, "status": 404, "at": _now()})
                return None, meta
            if r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            try:
                body = r.json()
            except Exception as exc:
                meta["ok"] = False
                meta["error"] = str(exc)
                return None, meta
            # Birdeye often wraps {success, data}
            if isinstance(body, dict) and body.get("success") is False:
                msg = str(body.get("message") or body.get("error") or "success_false")
                meta["ok"] = False
                low = msg.lower()
                if any(x in low for x in ("plan", "upgrade", "permission", "not available", "standard")):
                    meta["blocked"] = True
                    self.blocked.append({"endpoint": path, "status": r.status_code, "message": msg[:160], "at": _now()})
                meta["reason"] = msg[:160]
                self.last_error = msg[:120]
                time.sleep(self.sleep_ms / 1000.0)
                return None, meta
            meta["ok"] = True
            time.sleep(self.sleep_ms / 1000.0)
            return body, meta
        meta["ok"] = False
        meta["error"] = self.last_error or "retries_exhausted"
        return None, meta

    def token_price(self, mint: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        body, meta = self._get("/defi/price", {"address": mint})
        if not body:
            return None, meta
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return None, {**meta, "ok": False, "reason": "no_data"}
        out = {
            "mint": mint,
            "price_usd": data.get("value"),
            "price_change_24h": data.get("priceChange24h") or data.get("priceChange24hPercent"),
            "liquidity": data.get("liquidity"),
            "source": "birdeye",
            "meta": meta,
        }
        return out, meta

    def token_ohlcv(self, mint: str, *, ohlcv_type: str = "1H", limit_hours: int = 48) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        now = int(time.time())
        body, meta = self._get(
            "/defi/ohlcv",
            {
                "address": mint,
                "type": ohlcv_type,
                "time_from": now - limit_hours * 3600,
                "time_to": now,
            },
        )
        if not body:
            return None, meta
        data = body.get("data") if isinstance(body, dict) else None
        items = (data or {}).get("items") if isinstance(data, dict) else None
        out = {
            "mint": mint,
            "type": ohlcv_type,
            "candles": items if isinstance(items, list) else [],
            "n": len(items) if isinstance(items, list) else 0,
            "source": "birdeye",
            "meta": meta,
        }
        return out, meta

    def wallet_pnl_summary(self, wallet: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        body, meta = self._get("/wallet/v2/pnl/summary", {"wallet": wallet})
        if not body:
            return None, meta
        data = body.get("data") if isinstance(body, dict) else body
        if not isinstance(data, dict):
            return None, {**meta, "ok": False, "reason": "no_data"}
        out = {"wallet": wallet, "pnl": data, "source": "birdeye", "meta": meta}
        return out, meta

    def top_traders(self, mint: str, *, limit: int = 10) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        body, meta = self._get(
            "/defi/v2/tokens/top_traders",
            {"address": mint, "time_frame": "24h", "sort_by": "volume", "sort_type": "desc", "limit": limit},
        )
        if not body:
            # try alternate path
            body2, meta2 = self._get("/defi/v2/tokens/top_traders", {"address": mint, "limit": limit})
            if not body2:
                return None, meta2 if meta2.get("blocked") else meta
            body, meta = body2, meta2
        data = body.get("data") if isinstance(body, dict) else body
        items = data.get("items") if isinstance(data, dict) else data
        out = {
            "mint": mint,
            "traders": items if isinstance(items, list) else [],
            "source": "birdeye",
            "meta": meta,
        }
        return out, meta


def fetch_birdeye_for_mints(
    mints: list[str],
    out_dir: Path,
    *,
    max_mints: int = 12,
    want_ohlcv: bool = True,
) -> dict[str, Any]:
    """Fetch price (+ optional OHLCV) for mints; write under out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    client = BirdeyeClient()
    results = []
    for mint in mints[:max_mints]:
        price, pmeta = client.token_price(mint)
        ohlcv = None
        ometa: dict[str, Any] = {}
        if want_ohlcv and pmeta.get("ok"):
            ohlcv, ometa = client.token_ohlcv(mint)
        doc = {
            "mint": mint,
            "fetched_at": _now(),
            "source": "birdeye",
            "price": price,
            "ohlcv": ohlcv,
            "price_meta": pmeta,
            "ohlcv_meta": ometa,
        }
        (out_dir / f"{mint}.birdeye.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        results.append({"mint": mint, "price_ok": bool(price), "ohlcv_ok": bool(ohlcv)})
    blocked = list(client.blocked)
    (out_dir / "_birdeye_blocked.json").write_text(
        json.dumps({"blocked": blocked, "fetched_at": _now()}, indent=2), encoding="utf-8"
    )
    return {"ok": True, "n": len(results), "results": results, "blocked": blocked}


def fetch_birdeye_wallet_pnl(
    wallets: list[str],
    out_dir: Path,
    *,
    max_wallets: int = 8,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    client = BirdeyeClient()
    results = []
    for w in wallets[:max_wallets]:
        pnl, meta = client.wallet_pnl_summary(w)
        doc = {"wallet": w, "fetched_at": _now(), "source": "birdeye", "pnl": pnl, "meta": meta}
        (out_dir / f"{w}.pnl.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        results.append({"wallet": w, "ok": bool(pnl), "blocked": bool(meta.get("blocked"))})
    return {"ok": True, "n": len(results), "results": results, "blocked": list(client.blocked)}
