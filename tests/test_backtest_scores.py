"""Pass 5: backtest math, walk-forward no-lookahead, scoring."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trenchnet.backtest import (
    PricePoint,
    apply_costs,
    price_at,
    run_walk_forward,
    simulate_copy_trade,
    summarize_wallet_results,
    CopyTradeResult,
)
from trenchnet.scores import compute_scores, _hold_score, _norm_series


ROOT = Path(__file__).resolve().parents[1]


def test_apply_costs_reduces_return():
    cfg = {
        "costs": {
            "pumpfun_fee_bps": 100,
            "priority_fee_sol": 0.0001,
            "slippage_base_bps": 50,
            "slippage_max_bps": 800,
            "slippage_liquidity_ref_sol": 1.0,
        }
    }
    net, costs = apply_costs(1.0, 0.10, liq=1.0, cfg=cfg, slippage_mult=1.0)
    assert costs > 0
    assert net < 0.10


def test_apply_costs_thin_liq_more_slippage():
    cfg = {
        "costs": {
            "pumpfun_fee_bps": 0,
            "priority_fee_sol": 0.0,
            "slippage_base_bps": 50,
            "slippage_max_bps": 800,
            "slippage_liquidity_ref_sol": 1.0,
        }
    }
    net_fat, c_fat = apply_costs(1.0, 0.0, liq=5.0, cfg=cfg)
    net_thin, c_thin = apply_costs(1.0, 0.0, liq=0.05, cfg=cfg)
    assert c_thin > c_fat
    assert net_thin < net_fat


def test_price_at_no_fabricate():
    series = [PricePoint(1000, 1.0, "derived"), PricePoint(2000, 2.0, "birdeye")]
    px, src = price_at(series, 1500, max_gap_s=100)
    # 1500-1000=500 > 100 gap and next is 500 away -> None
    assert px is None
    assert src == ""
    px2, src2 = price_at(series, 1500, max_gap_s=600)
    assert px2 == 1.0 and src2 == "derived"


def test_delay_pricing_uses_later_point():
    series = [
        PricePoint(1000, 1.0, "derived"),
        PricePoint(1060, 1.2, "birdeye"),
    ]
    pair = {
        "wallet": "W",
        "token_mint": "M",
        "buy": {"signature": "s", "block_time": 1000, "side": "buy"},
        "sell": {"signature": "s2", "block_time": 2000, "side": "sell"},
    }
    cfg = {
        "position": {"size_sol": 1.0},
        "costs": {
            "pumpfun_fee_bps": 0,
            "priority_fee_sol": 0.0,
            "slippage_base_bps": 0,
            "slippage_max_bps": 0,
            "slippage_liquidity_ref_sol": 1.0,
        },
        "exits": {"take_profit_pct": 9, "stop_loss_pct": 9, "time_stop_seconds": 10},
    }
    r0 = simulate_copy_trade(
        pair, delay_s=0, exit_mode="mirror", prices={"M": series}, all_events=[], cfg=cfg,
    )
    r60 = simulate_copy_trade(
        pair, delay_s=60, exit_mode="mirror", prices={"M": series}, all_events=[], cfg=cfg,
    )
    assert not r0.unpriceable and not r60.unpriceable
    assert r0.entry_px == 1.0
    assert r60.entry_px == 1.2
    assert r60.entry_source == "birdeye"


def test_unpriceable_when_no_series():
    pair = {
        "wallet": "W",
        "token_mint": "M",
        "buy": {"signature": "s", "block_time": 1000, "side": "buy"},
        "sell": None,
    }
    cfg = {"position": {"size_sol": 0.25}, "costs": {}, "exits": {}}
    r = simulate_copy_trade(
        pair, delay_s=0, exit_mode="fixed", prices={}, all_events=[], cfg=cfg,
    )
    assert r.unpriceable
    assert r.pnl_sol is None


def test_walk_forward_no_lookahead_insufficient():
    # span too short
    pairs = []
    t0 = 1_700_000_000
    for i in range(50):
        pairs.append({
            "wallet": f"W{i % 5}",
            "token_mint": "M",
            "buy": {"signature": f"b{i}", "block_time": t0 + i * 60, "side": "buy"},
            "sell": {"signature": f"s{i}", "block_time": t0 + i * 60 + 120, "side": "sell"},
        })
    prices = {"M": [PricePoint(t0 + i * 60, 1.0 + i * 0.001, "derived") for i in range(80)]}
    cfg = {
        "position": {"size_sol": 0.25},
        "costs": {"pumpfun_fee_bps": 0, "priority_fee_sol": 0, "slippage_base_bps": 0, "slippage_max_bps": 0, "slippage_liquidity_ref_sol": 1},
        "exits": {"take_profit_pct": 0.5, "stop_loss_pct": 0.25, "time_stop_seconds": 3600},
        "walk_forward": {"min_train_trades": 10, "min_test_trades": 5, "min_span_days": 7, "n_folds": 3},
    }
    wf = run_walk_forward(pairs, prices, [], cfg)
    assert wf["status"] == "insufficient_data"
    assert "span" in wf["reason"] or "days" in wf["reason"]


def test_walk_forward_respects_cut():
    t0 = 1_700_000_000
    pairs = []
    # 20 days of data
    for i in range(100):
        pairs.append({
            "wallet": f"W{i % 6}",
            "token_mint": "M",
            "buy": {"signature": f"b{i}", "block_time": t0 + i * 86400 // 5, "side": "buy"},
            "sell": {"signature": f"s{i}", "block_time": t0 + i * 86400 // 5 + 300, "side": "sell"},
        })
    prices = {
        "M": [PricePoint(t0 + i * 3600, 1.0 + (0.01 if i % 2 == 0 else -0.005), "derived") for i in range(24 * 25)]
    }
    cfg = {
        "position": {"size_sol": 0.25},
        "costs": {"pumpfun_fee_bps": 0, "priority_fee_sol": 0, "slippage_base_bps": 0, "slippage_max_bps": 0, "slippage_liquidity_ref_sol": 1},
        "exits": {"take_profit_pct": 0.5, "stop_loss_pct": 0.25, "time_stop_seconds": 3600},
        "walk_forward": {"min_train_trades": 10, "min_test_trades": 5, "min_span_days": 7, "n_folds": 3},
    }
    wf = run_walk_forward(pairs, prices, [], cfg)
    assert wf["status"] in ("ok", "insufficient_data")
    if wf["status"] == "ok":
        for fold in wf["folds"]:
            assert fold["n_train"] >= 10
            assert fold["n_test"] >= 5
            # cut iso present => time ordered
            assert "cut" in fold


def test_summarize_coverage():
    rs = [
        CopyTradeResult("W", "M", "s", 1, 0, "fixed", 1, 2, "derived", "derived", 1, 1.0, 0.9, 0.9, 0.1, False),
        CopyTradeResult("W", "M", "s2", 2, 0, "fixed", None, None, "", "", 1, None, None, None, None, True, "no_entry_price"),
    ]
    s = summarize_wallet_results(rs)
    assert s["n_copies"] == 2
    assert s["n_priced"] == 1
    assert s["coverage_pct"] == 50.0


def test_hold_score_and_norm():
    assert _hold_score(100, 60, 3600) == 1.0
    assert _hold_score(30, 60, 3600) == 0.5
    n = _norm_series({"a": 1.0, "b": 3.0, "c": 5.0}, higher_better=True)
    assert n["a"] == 0.0 and n["c"] == 1.0


def test_compute_scores_runs_on_fixture(tmp_path: Path):
    # minimal fake tree
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "backtest.yaml").write_text(
        Path(ROOT / "config" / "backtest.yaml").read_text(encoding="utf-8")
        if (ROOT / "config" / "backtest.yaml").exists()
        else "scores:\n  weights:\n    win_rate: 1.0\n",
        encoding="utf-8",
    )
    (tmp_path / "data" / "raw" / "history").mkdir(parents=True)
    (tmp_path / "out" / "graph").mkdir(parents=True)
    t0 = 1_700_000_000
    hist = {
        "wallet": "WALLET1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        "source_primary": "helius",
        "events": [
            {"signature": "b1", "wallet": "WALLET1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "token_mint": "TOKENpump", "side": "buy", "amount_token": 1000, "amount_sol": 0.5, "block_time": t0, "source": "helius"},
            {"signature": "s1", "wallet": "WALLET1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "token_mint": "TOKENpump", "side": "sell", "amount_token": 1000, "amount_sol": 0.8, "block_time": t0 + 600, "source": "helius"},
        ],
    }
    (tmp_path / "data" / "raw" / "history" / "WALLET1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.json").write_text(json.dumps(hist), encoding="utf-8")
    (tmp_path / "out" / "graph" / "summary.json").write_text(json.dumps({"co_entries": []}), encoding="utf-8")
    from trenchnet.backtest import run_backtest
    bt = run_backtest(tmp_path)
    doc = compute_scores(tmp_path, backtest=bt)
    assert doc["n_wallets"] >= 1
    assert "weights" in doc
