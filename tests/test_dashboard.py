"""Tests for PASS 2: history dedupe/merge + dashboard panel helpers (real-data derivations)."""

from __future__ import annotations

import pytest

from trenchnet import dashboard
from trenchnet.history import dedupe_events
from trenchnet.models import TradeEvent

W1 = "WalletA1111111111111111111111111111111111111"
W2 = "WalletB1111111111111111111111111111111111111"
T1 = "Token111111111111111111111111111111111111111"


def _ev(wallet, sig, mint, side="buy", sol=1.0, qty=1_000_000.0, t=1000):
    return TradeEvent(sig, wallet, mint, side, qty, sol, 1, t)


def _d(e: TradeEvent) -> dict:
    return e.to_dict()


# ---------------- dedupe / merge ----------------

def test_dedupe_removes_dup_wallet_sig_mint():
    a = _ev(W1, "sig1", T1)
    b = _ev(W1, "sig1", T1, side="sell")  # same identity, conflicting fields — first wins
    out = dedupe_events([a, b])
    assert len(out) == 1 and out[0].side == "buy"


def test_dedupe_keeps_distinct_tokens_same_tx():
    t2 = "Token222222222222222222222222222222222222222"
    out = dedupe_events([_ev(W1, "sig1", T1), _ev(W1, "sig1", T2_MINT(t2))])
    assert len(out) == 2


def T2_MINT(t):
    return t


def test_dedupe_keeps_different_wallets_or_sigs():
    out = dedupe_events([
        _ev(W1, "sig1", T1),
        _ev(W2, "sig1", T1),
        _ev(W1, "sig2", T1),
    ])
    assert len(out) == 3


def test_dedupe_works_on_dicts_and_keeps_malformed():
    d = _d(_ev(W1, "sig9", T1))
    out = dedupe_events([d, d, {"wallet": W1, "signature": None, "token_mint": None}])
    assert len(out) == 2  # dup dict dropped; malformed kept verbatim


# ---------------- heatmap ----------------

def test_heatmap_counts_by_utc_hour_and_day():
    # 2026-09-21 is a Monday; 10:30 UTC -> (0, 10); two trades same slot
    t = 1758455400  # Mon 2026-09-21 10:30 UTC (verified by datetime in-code below)
    import datetime as _dt
    dt = _dt.datetime.fromtimestamp(t, tz=_dt.timezone.utc)
    events = [_d(_ev(W1, "s1", T1, t=int(t))), _d(_ev(W1, "s2", T1, t=int(t)))]
    hm = dashboard.derive_heatmap(events)
    assert hm["grid"][dt.weekday()][dt.hour] == 2
    assert hm["total"] == 2
    assert hm["tz"] == "UTC"


def test_heatmap_empty_when_no_times():
    hm = dashboard.derive_heatmap([_d(_ev(W1, "s1", T1, t=None))])
    assert hm["total"] == 0


# ---------------- token flows ----------------

def test_token_flows_running_net_and_real_points():
    events = [
        _d(_ev(W1, "s1", T1, "buy", 1.0, 1_000_000, 1000)),
        _d(_ev(W1, "s2", T1, "sell", 0.4, 1_000_000, 1100)),
        _d(_ev(W1, "s3", T1, "buy", 0.5, 500_000, 1200)),
    ]
    flows = dashboard.derive_token_flows(events)
    assert len(flows) == 1
    pts = flows[0]["points"]
    assert [p["cum_sol"] for p in pts] == pytest.approx([1.0, 0.6, 1.1])
    assert all(p["sig"] for p in pts)  # every point carries its real tx
    assert flows[0]["tx_count"] == 3


def test_token_flows_sorted_by_time_and_ignores_unknown_side():
    events = [
        _d(_ev(W1, "s3", T1, "buy", 0.5, 100, 1200)),
        _d(_ev(W1, "s1", T1, "buy", 1.0, 100, 1000)),
        _d(_ev(W1, "s4", T1, "transfer_out", 9.0, 100, 1300)),  # not buy/sell
    ]
    flows = dashboard.derive_token_flows(events)
    pts = flows[0]["points"]
    assert [p["t"] for p in pts] == [1000, 1200]
    assert pts[-1]["cum_sol"] == pytest.approx(1.5)


# ---------------- co-entry matrix ----------------

def test_coentry_matrix_indexes_wallets_and_cells():
    g = {"co_entries": [
        {"wallet_a": W1, "wallet_b": W2, "shared_tokens": 2, "jaccard": 0.5},
        {"wallet_a": W2, "wallet_b": W1, "shared_tokens": 2, "jaccard": 0.5},  # dup pair, reverse
    ]}
    m = dashboard.derive_coentry_matrix(g)
    assert m["wallets"] == [W1, W2]
    assert len(m["cells"]) == 2
    assert m["cells"][0]["shared"] == 2


def test_coentry_matrix_empty_state():
    assert dashboard.derive_coentry_matrix({"co_entries": []})["wallets"] == []


# ---------------- paper table ----------------

def test_paper_table_maps_fills_and_refusals():
    paper = {
        "fills": [{"side": "buy", "wallet": W1, "token_mint": T1, "amount_sol": 1.0,
                    "amount_token": 1.0, "price_source_signature": "sigA", "recorded_at": "t2"}],
        "refusals": [{"reason": "no_real_price", "wallet": W2, "token_mint": None, "recorded_at": "t1"}],
    }
    rows = dashboard.derive_paper_table(paper)
    assert rows[0]["kind"] == "refusal"  # sorted by ts
    assert rows[1]["kind"] == "fill" and rows[1]["sig"] == "sigA"


# ---------------- derive_panels aggregation ----------------

def test_derive_panels_thin_data_flag():
    panels = dashboard.derive_panels([_d(_ev(W1, "s1", T1))], [], {}, {}, {})
    assert panels["thin_data"]["events"] == 1
    assert panels["thin_data"]["note"] == "thin data — recent poll sample only"
    assert panels["heatmap"]["total"] == 1


def test_derive_panels_labels_map():
    profiles = [{"wallet": W1, "label": "Doji"}]
    panels = dashboard.derive_panels([], profiles, {}, {}, {})
    assert panels["labels"][W1] == "Doji"
