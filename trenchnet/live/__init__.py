"""TRENCHNET LIVE trading package.

DISARMED BY DEFAULT. No key is ever logged, returned by API, or written to data.js.
Agent/automation must never call send_transaction; only simulateTransaction is used
unless Jeremy himself arms LIVE in the GUI and confirms each (or ARM AUTO) order.
"""
from __future__ import annotations

__all__ = [
    "is_armed",
    "disarm",
    "wallet_pubkey_only",
    "LIVE_DISABLED_REASON",
]

LIVE_DISABLED_REASON = "LIVE disarmed by default — Jeremy must arm in GUI"

def is_armed() -> bool:
    from trenchnet.live.state import load_state
    return bool(load_state().get("armed"))

def disarm(reason: str = "manual") -> dict:
    from trenchnet.live.state import disarm as _disarm
    return _disarm(reason)

def wallet_pubkey_only() -> str | None:
    from trenchnet.live.wallet import public_address
    return public_address()
