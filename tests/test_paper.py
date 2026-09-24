"""PAPER ledger + hygiene gates + kill switch. No network, no real orders."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import trenchnet.paper as paper
from trenchnet.models import TradeEvent

W = "WalletA1111111111111111111111111111111111111"
TOK = "Token111111111111111111111111111111111111111"


def _ev(sig, side, sol, qty, t, mint=TOK, wallet=W):
    return TradeEvent(sig, wallet, mint, side, qty, sol, 1, t)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paper.os, "environ", {k: "" for k in paper._PRIVATE_KEY_ENVS})
    return {"data": tmp_path / "data", "ledger": tmp_path / "data" / "paper" / "ledger.jsonl"}


def _events_with_price():
    return [
        _ev("sig_buy_real_1", "buy", 1.0, 1_000_000.0, 1000),
        _ev("sig_sell_real_1", "sell", 2.0, 1_000_000.0, 1100),  # price 2e-6 SOL/token
    ]


def test_most_recent_price_picks_newest_and_cites_sig(env):
    px = paper.most_recent_price(_events_with_price(), TOK)
    assert px is not None
    assert px["source_signature"] == "sig_sell_real_1"
    assert abs(px["price_sol_per_token"] - 2.0e-6) < 1e-12


def test_most_recent_price_none_when_no_trades(env):
    assert paper.most_recent_price(_events_with_price(), "OtherToken2222222222222222222222222222222222") is None


def test_buy_fill_priced_from_real_tx_and_appends_paper_row(env):
    e = env
    res = paper.paper_fill(
        "buy", W, TOK,
        events=_events_with_price(),
        ledger_path=e["ledger"], data_dir=e["data"],
        settings={"max_fill_fraction": 0.10, "max_fill_sol": 1.0, "starting_balance_sol": 10.0},
    )
    assert res["ok"] is True
    fill = res["fill"]
    assert fill["mode"] == "PAPER" and fill["type"] == "fill" and fill["side"] == "buy"
    assert fill["price_source_signature"] == "sig_sell_real_1"
    assert abs(fill["amount_sol"] - 1.0) < 1e-9  # min(10%*10, 1.0)
    rows = paper.iter_records(e["ledger"])
    assert len(rows) == 1 and rows[0]["mode"] == "PAPER"


def test_refusal_logged_when_no_real_price(env):
    e = env
    res = paper.paper_fill(
        "buy", W, TOK,
        events=[_ev("sig1", "buy", 1.0, 1_000_000.0, 1000, mint="OtherMint33333333333333333333333333333333333")],
        ledger_path=e["ledger"], data_dir=e["data"],
    )
    assert res["ok"] is False and res["reason"] == "no_real_price"
    rows = paper.iter_records(e["ledger"])
    assert rows[0]["type"] == "refusal" and rows[0]["reason"] == "no_real_price"
    assert rows[0]["mode"] == "PAPER"


def test_sell_and_close_realize_pnl_from_ledger(env):
    e = env
    common = dict(events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    paper.paper_fill("buy", W, TOK, **common)
    res = paper.paper_fill("close", W, TOK, **common)  # close = sell all at 2e-6
    assert res["ok"] is True
    # bought 1.0 SOL of token at 2e-6 -> 500,000 tokens; close proceeds = 1.0 SOL -> delta 0
    assert abs(res["realized_delta_sol"]) < 1e-9
    st = paper.paper_state(e["ledger"])
    assert st["open_positions"] == {}
    assert abs(st["balance_sol"] - 10.0) < 1e-9
    # a later sell with nothing open refuses
    res2 = paper.paper_fill("sell", W, TOK, **common)
    assert res2["ok"] is False and res2["reason"] == "no_open_position"


def test_oversized_vs_typical_refused(env):
    e = env
    big = [
        _ev("b1", "buy", 0.1, 100_000.0, 1000),
        _ev("b2", "buy", 0.1, 100_000.0, 1010),
        _ev("s1", "sell", 0.2, 200_000.0, 1100),
    ]
    cfg = {"max_fill_fraction": 1.0, "max_fill_sol": 5.0, "oversized_ratio": 4.0, "starting_balance_sol": 10.0}
    res = paper.paper_fill("buy", W, TOK, events=big, ledger_path=e["ledger"], data_dir=e["data"], settings=cfg)
    assert res["ok"] is False and res["reason"] == "oversized_vs_typical"
    assert res["record"]["context"]["typical_buy_size_sol"] == pytest.approx(0.1)


def test_kill_switch_blocks_fills(env):
    e = env
    assert paper.set_kill_switch(e["data"], True) is True
    res = paper.paper_fill("buy", W, TOK, events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    assert res["ok"] is False and res["reason"] == "kill_switch"
    paper.set_kill_switch(e["data"], False)
    res2 = paper.paper_fill("buy", W, TOK, events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    assert res2["ok"] is True


def test_live_guard_blocks_when_private_key_env_set(env, monkeypatch):
    e = env
    monkeypatch.setenv("PRIVATE_KEY", "x")
    res = paper.paper_fill("buy", W, TOK, events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    assert res["ok"] is False and res["reason"] == "live_guard"


def test_live_toggle_must_stay_disabled(env):
    e = env
    cfg = paper.paper_settings_from({"paper": {"live_toggle": "LIVE"}})
    allowed, reason, _ctx = paper.check_gates(
        "buy", W, TOK,
        events=_events_with_price(), ledger_path=e["ledger"],
        settings=cfg, data_dir=e["data"],
    )
    assert allowed is False and reason == "live_guard"
    assert "Jeremy" in paper.LIVE_TOGGLE_STUB


def test_skip_streak_halt_after_n_refusals(env):
    e = env
    no_price = [_ev("s1", "buy", 1.0, 1_000_000.0, 1000, mint="NoPriceToken44444444444444444444444444444444")]
    cfg = {"skip_streak_halt": 3}
    for _ in range(3):
        paper.paper_fill("buy", W, TOK, events=no_price, ledger_path=e["ledger"], data_dir=e["data"], settings=cfg)
    res = paper.paper_fill("buy", W, TOK, events=no_price, ledger_path=e["ledger"], data_dir=e["data"], settings=cfg)
    assert res["ok"] is False and res["reason"] == "skip_streak_halt"
    # a successful fill resets the streak
    ok = paper.paper_fill("buy", W, TOK, events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    assert ok["ok"] is True


def test_loss_streak_and_daily_cap_block_new_buys(env):
    e = env
    cheap = [_ev("cheapbuy", "buy", 1.0, 1_000_000.0, 1000)]  # price 1e-6
    pricey = [_ev("pricesell", "sell", 2.0, 1_000_000.0, 1100)]  # price 2e-6
    common = dict(ledger_path=e["ledger"], data_dir=e["data"])
    cfg = {"loss_streak_halt": 2, "daily_loss_cap_sol": 5.0}
    # two losing closes: buy at 2e-6, close at 1e-6 -> -0.5 SOL each
    for _ in range(2):
        paper.paper_fill("buy", W, TOK, events=pricey, **common)
        paper.paper_fill("close", W, TOK, events=cheap, **common)
    res = paper.paper_fill("buy", W, TOK, events=cheap, **common, settings=cfg)
    assert res["ok"] is False and res["reason"] == "loss_streak_halt"
    # daily loss cap: 2 * -0.5 = -1.0; cap at 0.9 blocks
    cfg2 = {"daily_loss_cap_sol": 0.9}
    res2 = paper.paper_fill("buy", W, TOK, events=cheap, **common, settings=cfg2)
    assert res2["ok"] is False and res2["reason"] == "daily_loss_cap"


def test_paper_state_math(env):
    e = env
    common = dict(events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    paper.paper_fill("buy", W, TOK, **common)               # -1.0 SOL, 500k tokens @2e-6
    res = paper.paper_fill("sell", W, TOK, amount_token=250_000.0, **common)  # half @2e-6
    assert res["ok"] is True
    st = paper.paper_state(e["ledger"])
    # 10 - 1.0 spent + 0.5 proceeds = 9.5 SOL (token price unchanged -> no pnl)
    assert abs(st["balance_sol"] - 9.5) < 1e-9
    assert TOK in st["open_positions"]
    assert st["open_positions"][TOK]["qty"] == pytest.approx(250_000.0)
    assert len(st["fills"]) == 2


def test_receipt_cites_price_source_sigs(env):
    e = env
    common = dict(events=_events_with_price(), ledger_path=e["ledger"], data_dir=e["data"])
    paper.paper_fill("buy", W, TOK, **common)
    st = paper.paper_state(e["ledger"])
    p = paper.write_receipt(st["fills"], e["data"] / "receipts")
    assert p.is_file()
    import json
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["mode"] == "PAPER"
    assert "sig_sell_real_1" in doc["price_source_signatures"]
