"""Pass 6: pool tick reconstruction, no-lookahead, staleness."""
from __future__ import annotations

from trenchnet.backtest import PricePoint, price_at, lookup_entry_exit
from trenchnet.pool_prices import extract_pool_ticks_from_tx, resample_bars, Tick


def test_extract_from_swap_event_decimals():
    tx = {
        "signature": "sig1",
        "timestamp": 1000,
        "events": {
            "swap": {
                "nativeInput": {"amount": "1000000000"},  # 1 SOL
                "tokenOutputs": [{
                    "mint": "MINTpump",
                    "rawTokenAmount": {"tokenAmount": "1000000", "decimals": 6},
                }],
            }
        },
    }
    ticks = extract_pool_ticks_from_tx(tx, "MINTpump")
    assert len(ticks) == 1
    assert abs(ticks[0].token - 1.0) < 1e-9  # 1e6 / 10^6
    assert abs(ticks[0].sol - 1.0) < 1e-9
    assert abs(ticks[0].px - 1.0) < 1e-9
    assert ticks[0].source_tag == "helius_pool"


def test_extract_from_transfers_and_native():
    tx = {
        "signature": "sig2",
        "timestamp": 2000,
        "tokenTransfers": [
            {"mint": "MINTpump", "tokenAmount": 5000.0},
        ],
        "accountData": [
            {"account": "trader", "nativeBalanceChange": -250000000},  # -0.25 SOL
            {"account": "pool", "nativeBalanceChange": 250000000},
        ],
    }
    ticks = extract_pool_ticks_from_tx(tx, "MINTpump")
    assert len(ticks) == 1
    assert abs(ticks[0].sol - 0.25) < 1e-9
    assert abs(ticks[0].token - 5000.0) < 1e-9
    assert abs(ticks[0].px - (0.25 / 5000.0)) < 1e-12


def test_extract_dust_filtered():
    tx = {
        "signature": "sig3",
        "timestamp": 3000,
        "tokenTransfers": [{"mint": "MINTpump", "tokenAmount": 10.0}],
        "accountData": [{"account": "x", "nativeBalanceChange": 100}],  # 1e-7 SOL
    }
    assert extract_pool_ticks_from_tx(tx, "MINTpump") == []


def test_no_lookahead_price_at():
    series = [PricePoint(1000, 1.0, "helius_pool"), PricePoint(1100, 2.0, "helius_pool")]
    # target 1050 -> must use 1100 (after), not 1000 (before)
    px, src = price_at(series, 1050, max_gap_s=60)
    assert px == 2.0 and src == "helius_pool"
    # target 1050 with staleness 40 -> 1100 is 50 away > 40 -> None
    px2, _ = price_at(series, 1050, max_gap_s=40)
    assert px2 is None


def test_staleness_cutoff():
    series = [PricePoint(2000, 3.0, "derived")]
    assert price_at(series, 1900, max_gap_s=50)[0] is None  # 100s late
    assert price_at(series, 1950, max_gap_s=60)[0] == 3.0


def test_lookup_never_mixes_usd_with_sol():
    fams = {
        "helius_pool": {"M": [PricePoint(1000, 0.01, "helius_pool")]},
        "derived": {},
        "birdeye": {"M": [PricePoint(1100, 0.5, "birdeye")]},  # USD-ish different scale
    }
    # entry at 1000 from pool; exit at 1100 only in birdeye -> should NOT pair across units
    e, x, es, xs = lookup_entry_exit("M", 1000, 1100, fams, max_staleness_s=60)
    assert e is None and x is None


def test_resample_bars():
    ticks = [Tick(t=0, px=1.0, sol=0.1, token=0.1), Tick(t=3, px=2.0, sol=0.2, token=0.1), Tick(t=6, px=1.5, sol=0.1, token=0.1)]
    bars = resample_bars(ticks, 5)
    assert len(bars) == 2
    assert bars[0]["o"] == 1.0 and bars[0]["c"] == 2.0
