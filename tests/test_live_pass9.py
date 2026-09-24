"""LIVE mode safety tests — never send; never read real TRENCHNET_WALLET_KEY."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trenchnet.live import gates, state
from trenchnet.live.redaction import redact_text, scrub_dict
from trenchnet.live.sellall import sell_all
from trenchnet.live.gates import pre_trade_gate, arm_balance_ok, SPEC


@pytest.fixture()
def tmp_state(tmp_path, monkeypatch):
    sp = tmp_path / "state.json"
    monkeypatch.setattr(state, "STATE_PATH", sp)
    monkeypatch.setattr(state, "KILL_FILE", tmp_path / "TRENCHNET_KILL")
    monkeypatch.setattr(state, "HEARTBEAT_FILE", tmp_path / "hb.json")
    st = state.load_state()
    assert st["armed"] is False
    return sp, st


def test_default_disarmed(tmp_state):
    st = state.load_state()
    assert st["armed"] is False
    assert st["kill_switch"] is False


def test_pre_trade_gate_caps(tmp_state):
    st = state.load_state()
    st["armed"] = True
    st["limits"] = {
        "max_sol_per_trade": 0.25,
        "max_open_positions": 4,
        "daily_loss_cap_sol": 2.0,
        "total_loss_kill_sol": 4.0,
        "max_slippage_pct": 5,
        "max_priority_fee_lamports": 1,
        "max_trades_per_day": 10,
    }
    state.save_state(st)
    g = pre_trade_gate(side="buy", sol_amount=0.3, state=state.load_state(), open_positions=0)
    assert g["ok"] is False and g["reason"] == "over_max_sol_per_trade"
    g2 = pre_trade_gate(side="buy", sol_amount=0.1, state=state.load_state(), open_positions=4)
    assert g2["ok"] is False and g2["reason"] == "max_open_positions"


def test_daily_and_total_stops(tmp_state):
    st = state.load_state()
    st["armed"] = True
    st["limits"] = {
        "max_sol_per_trade": 0.25, "max_open_positions": 4,
        "daily_loss_cap_sol": 2.0, "total_loss_kill_sol": 4.0,
        "max_slippage_pct": 5, "max_priority_fee_lamports": 1, "max_trades_per_day": 10,
    }
    st["day_realized_pnl_sol"] = -2.0
    state.save_state(st)
    g = pre_trade_gate(side="buy", sol_amount=0.1, state=state.load_state())
    assert g["reason"] == "daily_loss_stop"
    st = state.load_state()
    st["day_realized_pnl_sol"] = 0
    st["total_realized_pnl_sol"] = -4.0
    state.save_state(st)
    g2 = pre_trade_gate(side="buy", sol_amount=0.1, state=state.load_state())
    assert g2["reason"] == "total_loss_kill"


def test_fee_reserve_and_arm_balance(tmp_state):
    bal = arm_balance_ok(0.00125)
    assert bal["ok"] is False
    assert bal["required_sol"] == SPEC["arm_min_balance_sol"]
    assert arm_balance_ok(0.30)["ok"] is True
    st = state.load_state()
    st["armed"] = True
    st["limits"] = {
        "max_sol_per_trade": 0.25, "max_open_positions": 4,
        "daily_loss_cap_sol": 2, "total_loss_kill_sol": 4,
        "max_slippage_pct": 5, "max_priority_fee_lamports": 1, "max_trades_per_day": 10,
    }
    state.save_state(st)
    g = pre_trade_gate(side="buy", sol_amount=0.25, state=state.load_state(), wallet_sol=0.28)
    assert g["ok"] is False and g["reason"] == "fee_reserve"


def test_kill_file_and_switch(tmp_state):
    state.set_kill(True)
    assert state.kill_file_present()
    g = pre_trade_gate(side="buy", sol_amount=0.1, state=state.load_state(), kill_file_present=True)
    assert g["reason"] == "kill_switch"
    state.set_kill(False)


def test_arm_phrase_and_low_balance_refusal(tmp_state, monkeypatch):
    bad = state.try_arm("ARM LIVE", wallet_sol=1.0)
    assert bad["ok"] is False
    state.apply_spec_caps()
    # no wallet configured in test → fails wallet check before balance, or balance
    monkeypatch.setattr("trenchnet.live.wallet.env_key_configured", lambda: True)
    monkeypatch.setattr("trenchnet.live.wallet.public_address_from_env_or_store", lambda: "FakeWallet1111111111111111111111111111111111")
    monkeypatch.setattr("trenchnet.live.wallet.public_address_masked", lambda: "Fake…1111")
    low = state.try_arm(state.ARM_PHRASE, wallet_sol=0.00125)
    assert low["ok"] is False
    assert "balance" in (low.get("error") or "").lower() or low.get("balance_check", {}).get("ok") is False


def test_redaction_hides_key_shaped_material():
    sample = "TRENCHNET_WALLET_KEY=AbcDefGhIjKlMnOpQrStUvWxYz1234567890abcdef"
    out = redact_text(sample)
    assert "AbcDef" not in out
    assert "REDACTED" in out
    d = scrub_dict({"secret": "nope", "ok": True})
    assert d["secret"] == "[REDACTED]"


def test_sell_all_simulate_noop(tmp_state, tmp_path, monkeypatch):
    from trenchnet.live import ledger, sellall
    monkeypatch.setattr(ledger, "LEDGER_JSONL", tmp_path / "trades.jsonl")
    monkeypatch.setattr(ledger, "LEDGER_CSV", tmp_path / "trades.csv")
    monkeypatch.setattr(ledger, "OPEN_PATH", tmp_path / "open.json")
    monkeypatch.setattr(sellall, "disarm", state.disarm)
    res = sell_all(mode="simulate")
    assert res["ok"] is True
    assert res["n"] == 0
    assert res.get("sent") is False
    assert state.load_state()["armed"] is False


def test_position_manager_tick_no_buys(tmp_state, tmp_path, monkeypatch):
    from trenchnet.live import position_manager, ledger
    monkeypatch.setattr(ledger, "OPEN_PATH", tmp_path / "open.json")
    monkeypatch.setattr(ledger, "LEDGER_JSONL", tmp_path / "trades.jsonl")
    monkeypatch.setattr(ledger, "LEDGER_CSV", tmp_path / "trades.csv")
    r = position_manager.tick(once=True)
    assert r["buys_allowed"] is False


def test_full_address_not_in_live_sources():
    """Tracked live sources must not embed Jeremy's public strategy address."""
    from trenchnet.secrets import get_secret
    addr = (get_secret("MY_WALLET_ADDRESS") or "").strip()
    if len(addr) < 32:
        pytest.skip("MY_WALLET_ADDRESS not set")
    root = Path(__file__).resolve().parents[1]
    for rel in [
        "trenchnet/live/gates.py", "trenchnet/live/state.py", "trenchnet/live/wallet.py",
        "trenchnet/live/dryrun.py", "trenchnet/live/sellall.py", "trenchnet/LIVE-RUNBOOK.md",
        "out/live.html",
    ]:
        p = root / rel
        if p.is_file():
            assert addr not in p.read_text(encoding="utf-8", errors="ignore")
