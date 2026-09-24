"""TRENCHNET LIVE trading package.

DISARMED BY DEFAULT. Private key only from .env TRENCHNET_WALLET_KEY (Jeremy pastes).
Agents must never arm, never send, never read the key value.
"""
from __future__ import annotations

__all__ = ["is_armed", "disarm", "LIVE_DISABLED_REASON"]

LIVE_DISABLED_REASON = "LIVE disarmed by default — Jeremy must arm in GUI with ARM TRENCHNET LIVE"

def is_armed() -> bool:
    from trenchnet.live.state import load_state
    return bool(load_state().get("armed"))

def disarm(reason: str = "manual") -> dict:
    from trenchnet.live.state import disarm as _disarm
    return _disarm(reason)
