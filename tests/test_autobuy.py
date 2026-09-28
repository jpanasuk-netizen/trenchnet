"""AUTOBUY: runners + Jev thresholds + fail-closed ticks (no broadcast)."""
from __future__ import annotations

import json
from pathlib import Path

from trenchnet.live import autobuy, runners
from trenchnet.live import state as live_state


def _events(mint: str = "MintRunner111111111111111111111111111111111") -> list[dict]:
    t0 = 1_700_000_000.0
    return [
        {"wallet": "W1", "token_mint": mint, "side": "buy", "block_time": t0},
        {"wallet": "W2", "token_mint": mint, "side": "buy", "block_time": t0 + 10},
        {"wallet": "W3", "token_mint": mint, "side": "buy", "block_time": t0 + 20},
        {"wallet": "W4", "token_mint": mint, "side": "sell", "block_time": t0 + 25},
    ]


def test_detect_runners_three_top_wallets_in_window():
    mint = "MintRunner111111111111111111111111111111111"
    found = runners.detect_runners(_events(mint), {"W1", "W2", "W3", "W4"})
    assert len(found) == 1
    assert found[0]["mint"] == mint
    assert found[0]["n_top"] == 3
    assert found[0]["kind"] == "runner"


def test_detect_runners_ignores_low_score_wallets():
    mint = "MintRunner111111111111111111111111111111111"
    found = runners.detect_runners(_events(mint), {"W1"})
    assert found == []


def test_jev_threshold_runner_vs_normal():
    mint = "MintRunner111111111111111111111111111111111"
    other = "MintOther1111111111111111111111111111111111"
    run_row = {"mint": mint, "n_top": 3}
    assert runners.jev_threshold_for(mint, [run_row]) == 0.50
    assert runners.jev_threshold_for(other, [run_row]) == 0.68
    assert runners.jev_threshold_for(other, []) == 0.68


def test_jev_entry_waits_below_threshold():
    wait = autobuy.jev_entry_from_routed(
        {"route": "send_for_analysis", "confidence": 0.49, "jev_mode": "test"},
        threshold=0.50,
    )
    assert wait["word"] == "BUY"
    assert wait["ok_for_entry"] is False
    ready = autobuy.jev_entry_from_routed(
        {"route": "send_for_analysis", "confidence": 0.50, "jev_mode": "test"},
        threshold=0.50,
    )
    assert ready["ok_for_entry"] is True
    normal = autobuy.jev_entry_from_routed(
        {"route": "keep_observing", "confidence": 0.67, "jev_mode": "test"},
        threshold=0.68,
    )
    assert normal["ok_for_entry"] is False


def test_jev_hold_on_insufficient_evidence():
    d = autobuy.jev_entry_from_routed(
        {"route": "insufficient_evidence", "confidence": 0.99},
        threshold=0.50,
    )
    assert d["word"] == "HOLD"
    assert d["ok_for_entry"] is False


def _arm_tmp(tmp_path: Path, monkeypatch, *, armed=True, auto=True, kill=False):
    sp = tmp_path / "state.json"
    monkeypatch.setattr(live_state, "STATE_PATH", sp)
    monkeypatch.setattr(live_state, "KILL_FILE", tmp_path / "TRENCHNET_KILL")
    monkeypatch.setattr(live_state, "HEARTBEAT_FILE", tmp_path / "hb.json")
    st = live_state.load_state()
    st["armed"] = armed
    st["auto_armed"] = auto
    st["kill_switch"] = kill
    st["limits"] = {
        "max_sol_per_trade": 0.025,
        "daily_loss_cap_sol": 2.0,
        "total_loss_kill_sol": 4.0,
        "max_open_positions": 4,
        "max_slippage_pct": 5.0,
        "max_priority_fee_lamports": 1000,
        "max_trades_per_day": 40,
        "stop_loss_pct": 0.25,
    }
    live_state.save_state(st)
    return st


def test_autobuy_blocked_when_disarmed(tmp_path, monkeypatch):
    _arm_tmp(tmp_path, monkeypatch, armed=False, auto=True)
    sent = []

    def boom(**kwargs):
        sent.append(kwargs)
        return {"ok": True}

    out = autobuy.run_autobuy_once(tmp_path, execute_fn=boom)
    assert out["ok"] is False
    assert out["reason"] == "desk_disarmed"
    assert sent == []


def test_autobuy_blocked_when_autobuy_off(tmp_path, monkeypatch):
    _arm_tmp(tmp_path, monkeypatch, armed=True, auto=False)
    sent = []
    out = autobuy.run_autobuy_once(tmp_path, execute_fn=lambda **k: sent.append(k) or {"ok": True})
    assert out["reason"] == "autobuy_disarmed"
    assert sent == []


def test_autobuy_skips_when_jev_waits(tmp_path, monkeypatch):
    _arm_tmp(tmp_path, monkeypatch, armed=True, auto=True)
    mint = "MintRunner111111111111111111111111111111111"
    scores = {"wallets": [
        {"wallet": "W1", "score": 0.7},
        {"wallet": "W2", "score": 0.7},
        {"wallet": "W3", "score": 0.7},
    ]}
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
    monkeypatch.setattr(autobuy, "_history_events", lambda root: _events(mint))
    monkeypatch.setattr(autobuy, "_open_hottakes", lambda root: [])
    monkeypatch.setattr(
        "trenchnet.jev_gate.judge_snapshot",
        lambda snapshot, model="jev-latest": {"route": "send_for_analysis", "confidence": 0.40, "jev_mode": "test_wait"},
    )
    sent = []

    def capture(**kwargs):
        sent.append(kwargs)
        return {"ok": True, "signature": "should-not-send"}

    out = autobuy.run_autobuy_once(tmp_path, execute_fn=capture)
    assert sent == []
    assert out.get("reason") == "no_entry"
    last = autobuy.load_status(tmp_path).get("last") or {}
    assert str(last.get("skip") or "").startswith("jev_")


def test_autobuy_sends_when_gates_pass(tmp_path, monkeypatch):
    _arm_tmp(tmp_path, monkeypatch, armed=True, auto=True)
    mint = "MintRunner111111111111111111111111111111111"
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "scores.json").write_text(json.dumps({
        "wallets": [{"wallet": "W1", "score": 0.8}, {"wallet": "W2", "score": 0.8}, {"wallet": "W3", "score": 0.8}],
    }), encoding="utf-8")
    monkeypatch.setattr(autobuy, "_history_events", lambda root: _events(mint))
    monkeypatch.setattr(autobuy, "_open_hottakes", lambda root: [])
    monkeypatch.setattr(autobuy, "_quote_ok", lambda *a, **k: (True, "quote_ok:1"))
    monkeypatch.setattr(autobuy, "_n_open", lambda: 0)
    monkeypatch.setattr(
        "trenchnet.jev_gate.judge_snapshot",
        lambda snapshot, model="jev-latest": {"route": "send_for_analysis", "confidence": 0.72, "jev_mode": "test_buy"},
    )
    sent = []

    def capture(**kwargs):
        sent.append(kwargs)
        return {"ok": True, "mode": "send", "signature": "fake"}

    out = autobuy.run_autobuy_once(tmp_path, execute_fn=capture)
    assert out.get("ok") is True
    assert out.get("mint") == mint
    assert len(sent) == 1
    assert sent[0]["mode"] == "send"
    assert sent[0]["confirm_phrase"] == "CONFIRM LIVE ORDER"
    assert sent[0]["sol_amount"] == 0.025
    assert autobuy.load_status(tmp_path).get("buys") == 1
