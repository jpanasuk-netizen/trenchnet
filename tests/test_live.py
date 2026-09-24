"""LIVE safety tests — mocked RPC; never send; never expose key."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trenchnet.live import gates, state, wallet
from trenchnet.live.orders import execute


@pytest.fixture()
def tmp_wallet(tmp_path, monkeypatch):
    p = tmp_path / "live_wallet.bin"
    monkeypatch.setattr(wallet, "wallet_path", lambda: p)
    info = wallet.generate_keypair(p)
    assert "secret" not in info
    return p, info["pubkey"]


@pytest.fixture()
def tmp_state(tmp_path, monkeypatch):
    sp = tmp_path / "state.json"
    monkeypatch.setattr(state, "STATE_PATH", sp)
    st = state.load_state()
    return sp, st


def test_wallet_public_info_has_no_secret(tmp_wallet):
    _, pub = tmp_wallet
    info = wallet.public_info()
    blob = json.dumps(info)
    assert pub == info["pubkey"]
    assert "secret" not in blob
    assert "private" not in blob.lower()


def test_disarmed_blocks_order(tmp_wallet, tmp_state):
    res = execute(
        side="buy", token_mint="So11111111111111111111111111111111111111112",
        sol_amount=0.1, slippage_pct=1.0, priority_fee_lamports=1000,
        confirm_phrase="", mode="simulate",
    )
    assert res["ok"] is False
    assert res["reason"] in {"disarmed", "caps_zero_disarmed"}


def test_caps_zero_blocks(tmp_wallet, tmp_state):
    state.set_limits({
        "max_sol_per_trade": 0, "daily_loss_cap_sol": 1, "max_trades_per_day": 1,
        "max_open_positions": 1, "max_slippage_pct": 1, "max_priority_fee_lamports": 1,
    })
    st = state.load_state()
    st["armed"] = True
    state.save_state(st)
    g = gates.evaluate_live_order(
        side="buy", sol_amount=0.1, slippage_pct=0.5, priority_fee_lamports=1, state=state.load_state()
    )
    assert g["ok"] is False
    assert g["reason"] == "caps_zero_disarmed"


def test_over_cap_blocks(tmp_wallet, tmp_state):
    state.set_limits({
        "max_sol_per_trade": 0.05, "daily_loss_cap_sol": 1, "max_trades_per_day": 10,
        "max_open_positions": 3, "max_slippage_pct": 5, "max_priority_fee_lamports": 10000,
    })
    st = state.load_state()
    st["armed"] = True
    state.save_state(st)
    g = gates.evaluate_live_order(
        side="buy", sol_amount=0.2, slippage_pct=1, priority_fee_lamports=1000, state=state.load_state()
    )
    assert g["ok"] is False
    assert g["reason"] == "over_max_sol_per_trade"


def test_kill_switch_blocks(tmp_wallet, tmp_state):
    state.set_limits({
        "max_sol_per_trade": 1, "daily_loss_cap_sol": 1, "max_trades_per_day": 10,
        "max_open_positions": 3, "max_slippage_pct": 5, "max_priority_fee_lamports": 10000,
    })
    state.set_kill(True)
    g = gates.evaluate_live_order(
        side="buy", sol_amount=0.1, slippage_pct=1, priority_fee_lamports=1000, state=state.load_state()
    )
    assert g["ok"] is False
    assert g["reason"] == "kill_switch"


def test_hygiene_veto_blocks(tmp_wallet, tmp_state):
    state.set_limits({
        "max_sol_per_trade": 1, "daily_loss_cap_sol": 1, "max_trades_per_day": 10,
        "max_open_positions": 3, "max_slippage_pct": 5, "max_priority_fee_lamports": 10000,
    })
    st = state.load_state()
    st["armed"] = True
    st["kill_switch"] = False
    state.save_state(st)
    g = gates.evaluate_live_order(
        side="buy", sol_amount=0.1, slippage_pct=1, priority_fee_lamports=1000,
        state=state.load_state(), hygiene_ok=False,
    )
    assert g["ok"] is False
    assert g["reason"] == "hygiene_veto"


def test_arm_requires_exact_phrase_and_caps(tmp_wallet, tmp_state):
    bad = state.try_arm("arm live")
    assert bad["ok"] is False
    state.set_limits({
        "max_sol_per_trade": 0.1, "daily_loss_cap_sol": 1, "max_trades_per_day": 5,
        "max_open_positions": 2, "max_slippage_pct": 3, "max_priority_fee_lamports": 5000,
    })
    ok = state.try_arm("ARM LIVE")
    assert ok["ok"] is True
    assert ok["armed"] is True
    assert "secret" not in json.dumps(ok)


def test_send_without_confirm_phrase_blocked(tmp_wallet, tmp_state, monkeypatch):
    state.set_limits({
        "max_sol_per_trade": 1, "daily_loss_cap_sol": 1, "max_trades_per_day": 10,
        "max_open_positions": 3, "max_slippage_pct": 5, "max_priority_fee_lamports": 10000,
    })
    st = state.load_state()
    st["armed"] = True
    st["kill_switch"] = False
    state.save_state(st)
    # Avoid network: gate will pass then confirm fails before quote if we short-circuit — confirm checked after gate
    res = execute(
        side="buy", token_mint="So11111111111111111111111111111111111111112",
        sol_amount=0.01, slippage_pct=1, priority_fee_lamports=1000,
        confirm_phrase="nope", mode="send",
    )
    assert res["ok"] is False
    assert res["reason"] == "confirm_phrase_required"


def test_public_state_has_no_secret(tmp_wallet, tmp_state):
    blob = json.dumps(state.public_state())
    assert "secret" not in blob
    assert "private_key" not in blob
