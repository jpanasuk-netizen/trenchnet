"""Multi free no-signup Solana RPC pool. Observe-only. No paid keys."""
from __future__ import annotations

import itertools
import threading
import time
from typing import Any

from trenchnet.data_solana import SolanaRPC

# Verified answering getSlot on 2026-09-24 without signup/API key.
FREE_RPC_URLS = (
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
    "https://api.mainnet.solana.com",
)


class MultiEndpointRPC:
    """Round-robin across free endpoints with per-URL polite sleep + 429 backoff."""

    def __init__(self, urls: tuple[str, ...] | list[str] | None = None, sleep_ms: int = 350):
        self.urls = list(urls or FREE_RPC_URLS)
        self.sleep_ms = sleep_ms
        self._lock = threading.Lock()
        self._cycle = itertools.cycle(range(len(self.urls)))
        self._clients = {u: SolanaRPC(u, sleep_ms=sleep_ms) for u in self.urls}
        self._fail: dict[str, float] = {u: 0.0 for u in self.urls}  # cooldown until

    def _pick(self) -> str:
        now = time.time()
        with self._lock:
            for _ in range(len(self.urls)):
                i = next(self._cycle)
                u = self.urls[i]
                if self._fail[u] <= now:
                    return u
            # all cooling — pick soonest
            return min(self.urls, key=lambda u: self._fail[u])

    def call(self, method: str, params: list[Any]) -> Any:
        last_exc: Exception | None = None
        for _ in range(len(self.urls) * 2):
            url = self._pick()
            client = self._clients[url]
            try:
                return client.call(method, params)
            except Exception as exc:
                last_exc = exc
                msg = str(exc).lower()
                cool = 8.0 if ("429" in msg or "rate" in msg) else 3.0
                with self._lock:
                    self._fail[url] = time.time() + cool
                continue
        raise RuntimeError(f"MultiEndpointRPC failed: {method}: {last_exc}")

    def bind_wallet(self, wallet_index: int) -> SolanaRPC:
        """Sticky SolanaRPC for one worker (spread wallets across endpoints)."""
        url = self.urls[wallet_index % len(self.urls)]
        return SolanaRPC(url, sleep_ms=self.sleep_ms)
