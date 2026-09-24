"""Mocked unit tests for Helius / Birdeye clients — no real keys required."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trenchnet.helius_client import HeliusClient, parse_enhanced_swap, redact_url
from trenchnet.birdeye_client import BirdeyeClient


def test_redact_url_strips_api_key():
    u = "https://api.helius.xyz/v0/addresses/Abc/transactions?api-key=SUPERSECRET&limit=10"
    out = redact_url(u)
    assert "SUPERSECRET" not in out
    assert "REDACTED" in out
    assert "limit=10" in out


def test_parse_enhanced_swap_token_transfers():
    wallet = "Wallet111111111111111111111111111111111111111"
    mint = "TokenMint11111111111111111111111111111111111"
    tx = {
        "signature": "Sig111",
        "type": "SWAP",
        "source": "PUMP_FUN",
        "slot": 123,
        "timestamp": 1700000000,
        "tokenTransfers": [
            {
                "mint": mint,
                "fromUserAccount": "Other",
                "toUserAccount": wallet,
                "tokenAmount": 1000.5,
            }
        ],
        "events": {},
    }
    evs = parse_enhanced_swap(tx, wallet)
    assert len(evs) == 1
    assert evs[0].side == "buy"
    assert evs[0].source == "helius"
    assert evs[0].token_mint == mint
    assert evs[0].amount_token == 1000.5


@patch("trenchnet.helius_client.get_secret", return_value="fake-helius-key")
@patch("trenchnet.helius_client.httpx.get")
def test_helius_fetch_page_ok(mock_get, _secret):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"signature": "S1", "type": "SWAP", "source": "PUMP_FUN", "tokenTransfers": [], "events": {}}
    ]
    mock_get.return_value = mock_resp
    c = HeliusClient(sleep_ms=0)
    page = c.fetch_enhanced_page("WalletX", limit=5)
    assert len(page) == 1
    assert page[0]["signature"] == "S1"
    # ensure api-key was passed but we never assert its value in logs
    assert mock_get.called


@patch("trenchnet.helius_client.get_secret", return_value="fake-helius-key")
@patch("trenchnet.helius_client.httpx.get")
def test_helius_429_then_ok(mock_get, _secret):
    r429 = MagicMock(); r429.status_code = 429
    r200 = MagicMock(); r200.status_code = 200; r200.json.return_value = []
    mock_get.side_effect = [r429, r200]
    c = HeliusClient(sleep_ms=0, max_retries=3)
    page = c.fetch_enhanced_page("WalletX")
    assert page == []
    assert mock_get.call_count == 2


@patch("trenchnet.birdeye_client.get_secret", return_value="fake-birdeye-key")
@patch("trenchnet.birdeye_client.httpx.get")
def test_birdeye_price_ok(mock_get, _secret):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"success": True, "data": {"value": 1.23, "liquidity": 9}}
    mock_get.return_value = mock_resp
    c = BirdeyeClient(sleep_ms=0)
    price, meta = c.token_price("MintX")
    assert price is not None
    assert price["price_usd"] == 1.23
    assert price["source"] == "birdeye"
    assert meta["ok"] is True


@patch("trenchnet.birdeye_client.get_secret", return_value="fake-birdeye-key")
@patch("trenchnet.birdeye_client.httpx.get")
def test_birdeye_blocked_403(mock_get, _secret):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_get.return_value = mock_resp
    c = BirdeyeClient(sleep_ms=0)
    pnl, meta = c.wallet_pnl_summary("WalletY")
    assert pnl is None
    assert meta.get("blocked") is True
    assert c.blocked and c.blocked[0]["status"] == 403
