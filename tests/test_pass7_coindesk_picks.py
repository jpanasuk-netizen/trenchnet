"""Pass 7: Coin Desk route + Top Pick rules / track record / no-lookahead."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from trenchnet.backtest import PricePoint
from trenchnet.coindesk import (
    fetch_live_state,
    get_coindesk_state,
    normalize_card,
    read_decisions_jsonl,
)
from trenchnet.picks import (
    backfill_picks,
    evaluate_candidates,
    outcome_at_horizons,
    summarize_track_record,
)
from trenchnet.webui import build_handler

PICKS_YAML = """
thresholds:
  min_wallet_score: 0.55
  min_top_wallets: 2
  max_cobuy_span_seconds: 3600
  min_copy_pnl_60s_sol: -0.05
  jev_ok_routes: [send_for_analysis, keep_observing]
safety:
  min_token_age_seconds: 0
  max_token_age_seconds: 99999999
  min_liquidity_proxy_sol: 0.001
  min_liquidity_usd: 1
  skip_mints: []
confidence:
  base: 0.2
  per_top_wallet: 0.1
  jev_live_bonus: 0.15
  safety_pass_bonus: 0.15
  copy_positive_bonus: 0.1
  oos_insufficient_penalty: 0.2
  max: 0.95
track_record:
  horizons_seconds: [900, 3600, 14400, 86400]
  max_staleness_seconds: 300
backfill:
  enabled: true
"""


def test_normalize_card_pass_base_labels():
    card = normalize_card(
        {
            "verdict": "PASS",
            "name": "Arbitrum Robinhood",
            "symbol": "ARBIHOOD",
            "address": "0xDB67986A10d2c5aa9d26B9051712c945478f600d",
            "logged_at": 1790063542.0,
            "reason": "fresh launch with a real buy",
            "age_sec": 67,
            "real_eth": 0.008,
        },
        source="test",
    )
    assert card["chain"] == "Base"
    assert card["venue"] == "hood.fun"
    assert card["call"] == "PASS"
    assert card["execute"] is False
    assert card["paper_only"] is True
    assert "basescan.org" in (card["link_basescan"] or "")


def test_read_decisions_jsonl_and_offline_fallback(tmp_path: Path):
    p = tmp_path / "decisions.jsonl"
    row = {
        "verdict": "PASS",
        "name": "T",
        "symbol": "T",
        "address": "0xabc",
        "logged_at": 1700000000,
        "reason": "x",
    }
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert len(read_decisions_jsonl(p)) == 1
    with patch("trenchnet.coindesk.fetch_live_state", return_value=None):
        st = get_coindesk_state(decisions_file=p, timeout_s=0.1)
    assert st["status"] == "offline"
    assert "offline, data as of" in st["note"]
    assert st["chain"] == "Base"
    assert st["cards"][0]["call"] == "PASS"


def test_coindesk_live_path_mocked():
    live = {
        "token_count": 3,
        "board_up": True,
        "fresh": [
            {
                "verdict": "PASS",
                "name": "LiveTok",
                "symbol": "LV",
                "address": "0x111",
                "logged_at": time.time(),
                "gate": {"stage": "WATCH", "reasons": ["approval required"], "execute": False},
            }
        ],
        "newest": [],
    }
    with patch("trenchnet.coindesk.fetch_live_state", return_value=live):
        st = get_coindesk_state(timeout_s=0.1, decisions_file=Path("/nonexistent/decisions.jsonl"))
    assert st["status"] == "live"
    assert st["cards"]
    assert st["cards"][0]["source"].startswith("live")
    assert "Base" in st["label"]


def test_fetch_live_state_timeout_returns_none():
    with patch("trenchnet.coindesk.httpx.get", side_effect=TimeoutError("x")):
        assert fetch_live_state(timeout_s=0.05) is None


def test_webui_coindesk_route_live_and_offline(tmp_path: Path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "dashboard.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "data").mkdir()
    Handler = build_handler(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with patch("trenchnet.coindesk.fetch_live_state", return_value=None):
            with patch("trenchnet.coindesk.decisions_path", return_value=tmp_path / "missing.jsonl"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/coindesk/state", timeout=3) as r:
                    body = json.loads(r.read().decode())
        assert body["status"] == "offline"
        assert body["chain"] == "Base"

        live = {
            "fresh": [
                {"verdict": "WATCH", "name": "N", "symbol": "S", "address": "0x2", "logged_at": 1}
            ],
            "newest": [],
        }
        with patch("trenchnet.coindesk.fetch_live_state", return_value=live):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/coindesk/state", timeout=3) as r:
                body2 = json.loads(r.read().decode())
        assert body2["status"] == "live"
        assert body2["cards"][0]["call"] in ("WATCH", "PASS")
    finally:
        httpd.shutdown()


def _write_min_artifacts(root: Path, *, wallets, events, routes, bt_wallets):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "out" / "routes").mkdir(parents=True, exist_ok=True)
    (root / "data" / "raw" / "history").mkdir(parents=True, exist_ok=True)
    (root / "config" / "picks.yaml").write_text(PICKS_YAML, encoding="utf-8")
    (root / "out" / "scores.json").write_text(
        json.dumps({"wallets": wallets, "walk_forward_status": "insufficient_data"}), encoding="utf-8"
    )
    (root / "out" / "backtest_summary.json").write_text(
        json.dumps({"wallets": bt_wallets, "walk_forward": {"status": "insufficient_data"}}),
        encoding="utf-8",
    )
    (root / "out" / "routes" / "all_routes.json").write_text(json.dumps(routes), encoding="utf-8")
    by_w: dict[str, list] = {}
    for e in events:
        by_w.setdefault(e["wallet"], []).append(e)
    for w, evs in by_w.items():
        (root / "data" / "raw" / "history" / f"{w}.json").write_text(
            json.dumps({"wallet": w, "events": evs, "source_primary": "test"}), encoding="utf-8"
        )


def test_evaluate_no_buy_when_insufficient_confirmations(tmp_path: Path):
    mint = "MintAAA1111111111111111111111111111111111111"
    t0 = 1_700_000_000
    wallets = [{"wallet": "W1", "label": "w1", "score": 0.9, "oos_flag": "insufficient_oos"}]
    events = [
        {
            "wallet": "W1",
            "token_mint": mint,
            "side": "buy",
            "block_time": t0,
            "amount_sol": 0.5,
            "amount_token": 1000,
            "signature": "s1",
        }
    ]
    routes = [{"wallet": "W1", "route": "insufficient_evidence", "jev_mode": "dry_run", "jev_call_ok": False}]
    bt = [{"wallet": "W1", "copy_pnl_60s": -1.0, "coverage_60s": 10}]
    _write_min_artifacts(tmp_path, wallets=wallets, events=events, routes=routes, bt_wallets=bt)
    ev = evaluate_candidates(tmp_path)
    assert ev["headline"] == "No buy right now"
    assert ev["top_pick"] is None
    calls = {c["token_mint"]: c["call"] for c in ev["candidates"]}
    assert mint in calls
    assert calls[mint] in ("AVOID", "WATCH")


def test_evaluate_buy_candidate_needs_multi_confirm(tmp_path: Path):
    mint = "MintBBB2222222222222222222222222222222222222"
    t0 = 1_700_000_100
    wallets = [
        {"wallet": "WA", "label": "a", "score": 0.8, "oos_flag": "insufficient_oos"},
        {"wallet": "WB", "label": "b", "score": 0.7, "oos_flag": "insufficient_oos"},
    ]
    events = [
        {
            "wallet": "WA",
            "token_mint": mint,
            "side": "buy",
            "block_time": t0,
            "amount_sol": 1.0,
            "amount_token": 100,
            "signature": "a",
        },
        {
            "wallet": "WB",
            "token_mint": mint,
            "side": "buy",
            "block_time": t0 + 30,
            "amount_sol": 0.8,
            "amount_token": 80,
            "signature": "b",
        },
        {
            "wallet": "WA",
            "token_mint": mint,
            "side": "sell",
            "block_time": t0 + 60,
            "amount_sol": 0.2,
            "amount_token": 20,
            "signature": "c",
        },
    ]
    routes = [
        {"wallet": "WA", "route": "send_for_analysis", "jev_mode": "typesafe_live", "jev_call_ok": True},
        {"wallet": "WB", "route": "keep_observing", "jev_mode": "typesafe_live", "jev_call_ok": True},
    ]
    bt = [
        {"wallet": "WA", "copy_pnl_60s": 0.01, "coverage_60s": 20},
        {"wallet": "WB", "copy_pnl_60s": 0.02, "coverage_60s": 15},
    ]
    _write_min_artifacts(tmp_path, wallets=wallets, events=events, routes=routes, bt_wallets=bt)
    ev = evaluate_candidates(tmp_path)
    buys = [c for c in ev["candidates"] if c["call"] == "BUY candidate"]
    assert buys, f"expected BUY, got {[(c['call'], c.get('reason')) for c in ev['candidates']]}"
    assert ev["headline"] == "BUY candidate"
    assert ev["top_pick"]["token_mint"] == mint
    assert ev["top_pick"]["confidence"] > 0


def test_track_record_math():
    horizons = [900, 3600, 14400, 86400]
    rows = [
        {
            "token_mint": "A",
            "call_time": 1,
            "outcome": {
                "horizons": {
                    "900": {"return": 0.1, "unpriceable": False},
                    "3600": {"return": 0.2, "unpriceable": False},
                    "14400": {"return": 0.05, "unpriceable": False},
                    "86400": {"return": -0.1, "unpriceable": False},
                }
            },
        },
        {
            "token_mint": "B",
            "call_time": 2,
            "outcome": {
                "horizons": {
                    "900": {"return": -0.5, "unpriceable": False},
                    "3600": {"return": -0.4, "unpriceable": False},
                    "14400": {"return": None, "unpriceable": True},
                    "86400": {"return": None, "unpriceable": True},
                }
            },
        },
        {
            "token_mint": "C",
            "call_time": 3,
            "outcome": {"horizons": {"900": {"return": None, "unpriceable": True}}},
        },
    ]
    s = summarize_track_record(rows, horizons)
    assert s["n"] == 2
    assert s["win_rate"] == 0.5
    assert s["by_horizon"]["900"]["n"] == 2
    assert s["by_horizon"]["900"]["median"] == pytest.approx(-0.2)
    assert s["worst"]["token_mint"] == "B"


def test_outcome_no_lookahead_and_backfill(tmp_path: Path):
    mint = "MintCCC3333333333333333333333333333333333333"
    t0 = 1_700_100_000
    families = {
        "helius_pool": {
            mint: [
                PricePoint(t0 - 10, 9.0, "helius_pool"),
                PricePoint(t0, 1.0, "helius_pool"),
                PricePoint(t0 + 900, 1.1, "helius_pool"),
                PricePoint(t0 + 3600, 1.2, "helius_pool"),
            ]
        },
        "derived": {},
        "birdeye": {},
    }
    oc = outcome_at_horizons(mint, t0, 1.0, families, [900, 3600], 300)
    assert oc["horizons"]["900"]["return"] == pytest.approx(0.1)
    assert oc["horizons"]["3600"]["return"] == pytest.approx(0.2)

    wallets = [
        {"wallet": "WA", "label": "a", "score": 0.9, "oos_flag": "ok"},
        {"wallet": "WB", "label": "b", "score": 0.85, "oos_flag": "ok"},
    ]
    events = [
        {
            "wallet": "WA",
            "token_mint": mint,
            "side": "buy",
            "block_time": t0,
            "amount_sol": 1.0,
            "amount_token": 100,
            "signature": "a",
        },
        {
            "wallet": "WB",
            "token_mint": mint,
            "side": "buy",
            "block_time": t0 + 10,
            "amount_sol": 1.0,
            "amount_token": 100,
            "signature": "b",
        },
        {
            "wallet": "WA",
            "token_mint": mint,
            "side": "sell",
            "block_time": t0 + 900,
            "amount_sol": 1.25,
            "amount_token": 100,
            "signature": "x",
        },
    ]
    routes = [
        {"wallet": "WA", "route": "send_for_analysis", "jev_mode": "typesafe_live", "jev_call_ok": True},
        {"wallet": "WB", "route": "keep_observing", "jev_mode": "typesafe_live", "jev_call_ok": True},
    ]
    bt = [
        {"wallet": "WA", "copy_pnl_60s": 0.05, "coverage_60s": 20},
        {"wallet": "WB", "copy_pnl_60s": 0.05, "coverage_60s": 20},
    ]
    _write_min_artifacts(tmp_path, wallets=wallets, events=events, routes=routes, bt_wallets=bt)
    pdir = tmp_path / "data" / "prices" / "helius_pool"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{mint}.json").write_text(
        json.dumps(
            {
                "mint": mint,
                "ticks_compact": [
                    [t0 - 10, 9.0],
                    [t0, 1.0],
                    [t0 + 10, 1.0],
                    [t0 + 900, 1.25],
                    [t0 + 3600, 0.8],
                ],
            }
        ),
        encoding="utf-8",
    )
    doc = backfill_picks(tmp_path)
    assert doc.get("kind") == "backtested_picks"
    assert doc.get("n_picks", 0) >= 1
    for pk in doc.get("picks") or []:
        assert pk["call_time"] >= t0 + 10
        assert pk["kind"] == "backtested"
        for cell in (pk.get("outcome") or {}).get("horizons", {}).values():
            if cell.get("return") is not None:
                assert abs(cell["return"]) < 5


def test_api_picks_route(tmp_path: Path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "dashboard.html").write_text("<html></html>", encoding="utf-8")
    payload = {
        "headline": "No buy right now",
        "headline_reason": "test",
        "paper_only": True,
        "candidates": [],
        "caveats": ["PAPER only"],
    }
    (tmp_path / "out" / "top_pick.json").write_text(json.dumps(payload), encoding="utf-8")
    Handler = build_handler(tmp_path)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/picks", timeout=5) as r:
            body = json.loads(r.read().decode())
        assert body["headline"] == "No buy right now"
        assert body["paper_only"] is True
    finally:
        httpd.shutdown()
