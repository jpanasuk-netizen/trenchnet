"""Pass 8 Hot Takes: rule, dedup, outcomes, resume, backfill, API."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from trenchnet.backtest import PricePoint
from trenchnet.hottakes import (
    HotTakeTracker,
    backfill_hottakes,
    build_hottakes_payload,
    dedupe_new_takes,
    evaluate_hot_take_signals,
    load_ledger,
    mark_horizon_outcome,
    rewrite_ledger,
    scoreboard,
    update_take_outcomes,
)

HT_YAML = """
rule:
  min_wallet_score: 0.55
  min_top_wallets: 2
  max_cobuy_span_seconds: 900
  min_follow_buys: 2
  follow_window_seconds: 180
  jev_ok_routes: [send_for_analysis, keep_observing]
dedup_hours: 6
horizons_seconds: [900, 3600, 14400, 86400]
max_staleness_seconds: 300
close_after_seconds: 86400
position_size_sol: 0.25
tracker:
  poll_interval_seconds: 90
  enabled: false
helius:
  max_wallets_per_poll: 2
  max_pages_per_wallet: 1
  estimated_credits_per_page: 100
safety_flags:
  min_token_age_seconds: 0
  max_token_age_seconds: 99999999
  min_liquidity_proxy_sol: 0.05
  min_liquidity_usd: 1000
backfill:
  enabled: true
  label: backtested Hot Takes
"""

BT_YAML = """
costs:
  pumpfun_fee_bps: 100
  priority_fee_sol: 0.00005
  slippage_base_bps: 50
  slippage_max_bps: 800
  slippage_liquidity_ref_sol: 1.0
position:
  size_sol: 0.25
"""


def _setup(root: Path, *, wallets, events, routes=None):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "out" / "routes").mkdir(parents=True, exist_ok=True)
    (root / "data" / "raw" / "history").mkdir(parents=True, exist_ok=True)
    (root / "data" / "prices" / "helius_pool").mkdir(parents=True, exist_ok=True)
    (root / "config" / "hottakes.yaml").write_text(HT_YAML, encoding="utf-8")
    (root / "config" / "backtest.yaml").write_text(BT_YAML, encoding="utf-8")
    (root / "out" / "scores.json").write_text(
        json.dumps({"wallets": wallets, "walk_forward_status": "insufficient_data"}), encoding="utf-8"
    )
    (root / "out" / "routes" / "all_routes.json").write_text(json.dumps(routes or []), encoding="utf-8")
    by = {}
    for e in events:
        by.setdefault(e["wallet"], []).append(e)
    for w, evs in by.items():
        (root / "data" / "raw" / "history" / f"{w}.json").write_text(
            json.dumps({"wallet": w, "events": evs, "source_primary": "test"}), encoding="utf-8"
        )


def test_rule_path_a_cobuy_even_if_liquidity_fails(tmp_path: Path):
    mint = "HtMintAAA111111111111111111111111111111111"
    t0 = 1_700_200_000
    wallets = [
        {"wallet": "WA", "score": 0.9},
        {"wallet": "WB", "score": 0.8},
    ]
    # tiny sols → liquidity flag fails but Hot Take still fires
    events = [
        {"wallet": "WA", "token_mint": mint, "side": "buy", "block_time": t0, "amount_sol": 0.01, "amount_token": 100, "signature": "a"},
        {"wallet": "WB", "token_mint": mint, "side": "buy", "block_time": t0 + 30, "amount_sol": 0.01, "amount_token": 100, "signature": "b"},
    ]
    routes = [
        {"wallet": "WA", "route": "send_for_analysis"},
        {"wallet": "WB", "route": "keep_observing"},
    ]
    _setup(tmp_path, wallets=wallets, events=events, routes=routes)
    cands = evaluate_hot_take_signals(tmp_path)
    assert len(cands) >= 1
    c = next(x for x in cands if x["token_mint"] == mint)
    assert c["path"] == "A_cobuy_top_wallets"
    assert c["flags"]["liquidity"]["ok"] is False
    assert "liquidity" in c["flags"]


def test_rule_path_b_fast_follow(tmp_path: Path):
    mint = "HtMintBBB222222222222222222222222222222222"
    t0 = 1_700_300_000
    wallets = [{"wallet": "WA", "score": 0.9}]
    events = [
        {"wallet": "WA", "token_mint": mint, "side": "buy", "block_time": t0, "amount_sol": 1.0, "amount_token": 100, "signature": "a"},
        {"wallet": "WX", "token_mint": mint, "side": "buy", "block_time": t0 + 20, "amount_sol": 0.5, "amount_token": 50, "signature": "x"},
        {"wallet": "WY", "token_mint": mint, "side": "buy", "block_time": t0 + 40, "amount_sol": 0.5, "amount_token": 50, "signature": "y"},
    ]
    _setup(tmp_path, wallets=wallets, events=events)
    cands = evaluate_hot_take_signals(tmp_path)
    c = next(x for x in cands if x["token_mint"] == mint)
    assert c["path"] == "B_top_plus_fast_follow"


def test_dedup_per_token(tmp_path: Path):
    existing = [{"token_mint": "M1", "flagged_at": int(time.time()) - 100, "kind": "live"}]
    cands = [
        {"token_mint": "M1", "flagged_at": int(time.time())},
        {"token_mint": "M2", "flagged_at": int(time.time())},
    ]
    out = dedupe_new_takes(cands, existing, dedup_hours=6)
    assert [c["token_mint"] for c in out] == ["M2"]


def test_outcome_win_loss_unpriced(tmp_path: Path):
    cfg = yaml.safe_load(HT_YAML)
    bt = yaml.safe_load(BT_YAML)
    mint = "HtMintCCC333333333333333333333333333333333"
    t0 = 1_700_400_000
    take = {
        "token_mint": mint,
        "flagged_at": t0,
        "entry_price": 1.0,
        "flags": {"liquidity": {"ok": True, "detail": "proxy_sol=1.0"}},
        "outcomes": {},
    }
    families = {
        "helius_pool": {
            mint: [
                PricePoint(t0, 1.0, "helius_pool"),
                PricePoint(t0 + 900, 1.2, "helius_pool"),  # up → WIN after costs likely
                # no price at +3600 → UNPRICED
                PricePoint(t0 + 14400, 0.5, "helius_pool"),  # down → LOSS
            ]
        },
        "derived": {},
        "birdeye": {},
    }
    # force due by now_ts far in future
    now = t0 + 20000
    cell15 = mark_horizon_outcome(take, 900, families, cfg=cfg, bt_cfg=bt, now_ts=now)
    assert cell15["result"] == "WIN"
    assert cell15["net_return"] > 0
    cell1h = mark_horizon_outcome(take, 3600, families, cfg=cfg, bt_cfg=bt, now_ts=now)
    assert cell1h["result"] == "UNPRICED"
    cell4h = mark_horizon_outcome(take, 14400, families, cfg=cfg, bt_cfg=bt, now_ts=now)
    assert cell4h["result"] == "LOSS"
    # not due yet
    early = mark_horizon_outcome(take, 86400, families, cfg=cfg, bt_cfg=bt, now_ts=t0 + 100)
    assert early is None


def test_restart_resume(tmp_path: Path):
    _setup(
        tmp_path,
        wallets=[{"wallet": "WA", "score": 0.9}, {"wallet": "WB", "score": 0.8}],
        events=[
            {"wallet": "WA", "token_mint": "M", "side": "buy", "block_time": 100, "amount_sol": 1, "amount_token": 10, "signature": "a"},
            {"wallet": "WB", "token_mint": "M", "side": "buy", "block_time": 130, "amount_sol": 1, "amount_token": 10, "signature": "b"},
        ],
    )
    row = {
        "kind": "live",
        "token_mint": "M",
        "flagged_at": 130,
        "entry_price": 0.1,
        "status": "open",
        "outcomes": {},
        "flags": {"liquidity": {"ok": True, "detail": "proxy_sol=1"}},
    }
    rewrite_ledger(tmp_path, [row])
    # plant prices
    (tmp_path / "data" / "prices" / "helius_pool" / "M.json").write_text(
        json.dumps({"mint": "M", "ticks_compact": [[130, 0.1], [130 + 900, 0.15]]}),
        encoding="utf-8",
    )
    loaded = load_ledger(tmp_path)
    assert loaded[0]["status"] == "open"
    cfg = yaml.safe_load(HT_YAML)
    bt = yaml.safe_load(BT_YAML)
    from trenchnet.hottakes import _price_families
    fam = _price_families(tmp_path)
    updated = update_take_outcomes(loaded[0], fam, cfg=cfg, bt_cfg=bt, now_ts=130 + 1000)
    assert updated["outcomes"]["900"]["result"] in ("WIN", "LOSS", "UNPRICED")
    rewrite_ledger(tmp_path, [updated])
    again = load_ledger(tmp_path)
    assert "900" in (again[0].get("outcomes") or {})


def test_backfill_no_lookahead(tmp_path: Path):
    mint = "HtMintDDD444444444444444444444444444444444"
    t0 = 1_700_500_000
    wallets = [
        {"wallet": "WA", "score": 0.9},
        {"wallet": "WB", "score": 0.85},
    ]
    events = [
        {"wallet": "WA", "token_mint": mint, "side": "buy", "block_time": t0, "amount_sol": 1.0, "amount_token": 100, "signature": "a"},
        {"wallet": "WB", "token_mint": mint, "side": "buy", "block_time": t0 + 10, "amount_sol": 1.0, "amount_token": 100, "signature": "b"},
        {"wallet": "WA", "token_mint": mint, "side": "sell", "block_time": t0 + 900, "amount_sol": 1.2, "amount_token": 100, "signature": "s"},
    ]
    _setup(tmp_path, wallets=wallets, events=events, routes=[
        {"wallet": "WA", "route": "send_for_analysis"},
        {"wallet": "WB", "route": "keep_observing"},
    ])
    (tmp_path / "data" / "prices" / "helius_pool" / f"{mint}.json").write_text(
        json.dumps({"mint": mint, "ticks_compact": [
            [t0 - 50, 9.0],  # pre-flag spike must not create absurd future marks wrongly
            [t0, 1.0], [t0 + 10, 1.0], [t0 + 900, 1.15], [t0 + 3600, 0.9],
        ]}),
        encoding="utf-8",
    )
    doc = backfill_hottakes(tmp_path)
    assert doc["n"] >= 1
    for t in doc.get("takes") or []:
        assert t["kind"] == "backtested"
        assert t["flagged_at"] >= t0 + 10
        for cell in (t.get("outcomes") or {}).values():
            if cell.get("net_return") is not None:
                assert abs(cell["net_return"]) < 5


def test_scoreboard_separates_unpriced():
    rows = [
        {"kind": "live", "status": "closed", "outcomes": {"3600": {"result": "WIN", "net_return": 0.1}}},
        {"kind": "live", "status": "closed", "outcomes": {"3600": {"result": "LOSS", "net_return": -0.2}}},
        {"kind": "live", "status": "closed", "outcomes": {"3600": {"result": "UNPRICED"}}},
        {"kind": "live", "status": "open", "outcomes": {}},
    ]
    s = scoreboard(rows, kind="live")
    assert s["total"] == 4
    assert s["open"] == 1
    assert s["by_horizon"]["3600"]["wins"] == 1
    assert s["by_horizon"]["3600"]["losses"] == 1
    assert s["by_horizon"]["3600"]["unpriced"] == 1
    assert s["by_horizon"]["3600"]["win_rate"] == 0.5


def test_api_hottakes(tmp_path: Path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "dashboard.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "hottakes.yaml").write_text(HT_YAML, encoding="utf-8")
    (tmp_path / "config" / "backtest.yaml").write_text(BT_YAML, encoding="utf-8")
    (tmp_path / "data" / "hottakes").mkdir(parents=True)
    (tmp_path / "data" / "hottakes" / "backtested_summary.json").write_text(
        json.dumps({"n": 0, "scoreboard": scoreboard([], kind="backtested")}), encoding="utf-8"
    )
    (tmp_path / "out" / "scores.json").write_text(json.dumps({"wallets": []}), encoding="utf-8")

    from trenchnet.webui import build_handler

    Handler = build_handler(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with patch("trenchnet.hottakes.ensure_tracker") as et:
            et.return_value = type("T", (), {"state": {"running": False}})()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/hottakes", timeout=5) as r:
                body = json.loads(r.read().decode())
        assert body["paper_only"] is True
        assert "live_scoreboard" in body
        assert "caption" in body
    finally:
        httpd.shutdown()
