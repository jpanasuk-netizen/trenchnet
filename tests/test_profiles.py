"""Tests for profiles.build_profiles — fail-fast path when FCC is unavailable."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trenchnet.models import TradeEvent
from trenchnet.llm_fcc import FCCWriter
from trenchnet.profiles import build_profiles


def test_build_profiles_skips_llm_when_probe_failed():
    """When writer._probe_ok is False, build_profiles must not call complete()."""
    writer = MagicMock(spec=FCCWriter)
    writer._probe_ok = False
    writer.mode = "template_fallback"
    writer.last_error = None

    wallets = [{"address": "W1", "label": "Test1"}, {"address": "W2", "label": "Test2"}]
    events = [
        TradeEvent(
            signature="sig1",
            wallet="W1",
            token_mint="TKN1",
            side="buy",
            amount_token=100.0,
            amount_sol=0.5,
            slot=1,
            block_time=1000,
        ),
    ]

    profiles = build_profiles(wallets, events, writer, Path("/tmp/profile_test"))
    assert len(profiles) == 2
    # complete() should NEVER have been called
    writer.complete.assert_not_called()
    # all profiles should use template fallback
    assert all(p["writer_mode"] == "template_fallback" for p in profiles)


def test_build_profiles_wallet_limit():
    """wallet_limit should cap the number of profiles built."""
    writer = MagicMock(spec=FCCWriter)
    writer._probe_ok = False

    wallets = [{"address": f"W{i}", "label": f"W{i}"} for i in range(10)]
    events = []

    profiles = build_profiles(wallets, events, writer, Path("/tmp/profile_test"), wallet_limit=3)
    assert len(profiles) == 3
