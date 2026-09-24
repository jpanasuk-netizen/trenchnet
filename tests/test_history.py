"""History paging tests with a mocked SolanaRPC (no network, no invented trades)."""

from __future__ import annotations

import pytest

import trenchnet.history as history
from trenchnet.data_solana import SolanaRPC

PUMPFUN = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
W = "WalletA1111111111111111111111111111111111111"
WSOL = "So11111111111111111111111111111111111111112"


class MockRPC(SolanaRPC):
    """Deterministic fake RPC: N pages of signatures, canned transactions."""

    def __init__(self, sig_pages, txs, fail_pages=0):
        self.sig_pages = sig_pages  # list of pages; each page = list of sigs
        self.txs = txs              # sig -> tx dict
        self.fail_pages = fail_pages  # raise on first N page calls (429 simulation)
        self.page_calls = 0
        self.tx_calls = 0
        self.sleeps = 0

    def call(self, method, params):
        if method == "getSignaturesForAddress":
            self.page_calls += 1
            if self.page_calls <= self.fail_pages:
                raise RuntimeError("429 rate limited")
            opts = params[1] or {}
            before = opts.get("before")

            def norm(page):
                # pass through dicts (failed-tx rows), wrap bare sig strings
                return [s if isinstance(s, dict) else {"signature": s, "err": None} for s in page]

            if before is None:
                return norm(self.sig_pages[0])
            for i, page in enumerate(self.sig_pages):
                if before in (page[-1] if page else None):
                    nxt = self.sig_pages[i + 1] if i + 1 < len(self.sig_pages) else []
                    return norm(nxt)
            return []
        if method == "getTransaction":
            self.tx_calls += 1
            return self.txs.get(params[0])
        raise AssertionError(f"unexpected method {method}")


def _tx(sig, sol_delta, token_delta):
    """Minimal jsonParsed tx the parser accepts: pump.fun mentioned + balance deltas."""
    return {
        "slot": 1,
        "blockTime": 1000,
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": W, "signer": True},
                    {"pubkey": PUMPFUN, "signer": False},
                ]
            }
        },
        "meta": {
            "err": None,
            "preBalances": [10_000_000_000, 1],
            "postBalances": [10_000_000_000 + int(sol_delta * 1e9), 1],
            "preTokenBalances": [],
            "postTokenBalances": [
                {
                    "owner": W,
                    "mint": "Token111111111111111111111111111111111111111",
                    "uiTokenAmount": {"uiAmount": float(token_delta)},
                }
            ],
        },
    }


def test_pagination_walks_all_pages_and_parses(tmp_path):
    pages = [[f"s{i}" for i in range(0, 3)], ["s3", "s4"], ["s5"]]
    txs = {
        "s0": _tx("s0", -0.5, 1_000_000),   # buy: sol spent, token gained
        "s3": _tx("s3", 0.5, -1_000_000),   # sell
        "s5": _tx("s5", -0.25, 500_000),    # buy
    }
    rpc = MockRPC(pages, txs)
    cache = tmp_path / "hist" / f"{W}.json"
    res = history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert res["complete"] is True
    assert res["pages_fetched"] == 3
    # every unique sig gets one getTransaction (null result when pruned) — 6 sigs
    assert res["txs_fetched"] == 6
    assert res["events"] == 3
    st = history.load_progress(cache.parent, W)
    assert st["complete"] is True
    assert len(st["seen"]) == 6
    mints = {e["token_mint"] for e in st["events"]}
    assert mints == {"Token111111111111111111111111111111111111111"}


def test_resume_skips_already_seen_sigs(tmp_path):
    pages = [["s0", "s1"], ["s2"]]
    txs = {"s0": _tx("s0", -0.5, 1_000_000), "s1": _tx("s1", -0.5, 1_000_000), "s2": _tx("s2", -0.5, 1_000_000)}
    rpc = MockRPC(pages, txs)
    cache = tmp_path / "hist" / f"{W}.json"
    history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN, max_pages=1)
    st1 = history.load_progress(cache.parent, W)
    assert st1["complete"] is False
    assert st1["stopped_early_reason"] == "max_pages"
    txs_after_run1 = rpc.tx_calls  # run1 = page 0 only: s0,s1
    assert txs_after_run1 == 2
    # resume: page-0 sigs are skipped (seen); s2 fetched fresh
    res = history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert res["complete"] is True
    assert rpc.tx_calls == txs_after_run1 + 1
    st2 = history.load_progress(cache.parent, W)
    assert len(st2["events"]) == 3
    # a third run re-fetches nothing
    history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert rpc.tx_calls == txs_after_run1 + 1


def test_rate_limit_page_error_is_recorded_not_fatal(tmp_path):
    pages = [["s0", "s1"], ["s2"]]
    txs = {"s0": _tx("s0", -0.5, 1_000_000), "s1": _tx("s1", -0.5, 1_000_000), "s2": _tx("s2", -0.5, 1_000_000)}
    rpc = MockRPC(pages, txs, fail_pages=1)
    cache = tmp_path / "hist" / f"{W}.json"
    res = history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert res["complete"] is False
    assert "page_error" in (res["stopped_early_reason"] or "")
    st = history.load_progress(cache.parent, W)
    assert any("page_error" in e for e in st["errors"])
    # resume after backoff succeeds and stays resumable
    res2 = history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert res2["complete"] is True


def test_failed_txs_marked_err_are_skipped(tmp_path):
    txs = {"s1": _tx("s1", -0.5, 1_000_000)}
    rpc = MockRPC([], txs)
    # 'bad' is a failed on-chain tx via err flag; must be skipped without fetch
    rpc.sig_pages = [[{"signature": "bad", "err": {"InstructionError": [0]}}, {"signature": "s1", "err": None}]]
    cache = tmp_path / "hist" / f"{W}.json"
    res = history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert res["complete"] is True
    st = history.load_progress(cache.parent, W)
    assert "bad" in st["seen"]
    assert res["events"] == 1


def test_oldest_block_time_tracked(tmp_path):
    pages = [["s0"]]
    tx = _tx("s0", -0.5, 1_000_000)
    tx["blockTime"] = 1788636000  # 2026-09 (real epoch for 2026)
    rpc = MockRPC(pages, {"s0": tx})
    cache = tmp_path / "hist" / f"{W}.json"
    res = history.fetch_wallet_history(rpc, W, cache, program_id=PUMPFUN)
    assert res["oldest_block_time"] == 1788636000
    assert history.oldest_iso(res["oldest_block_time"]).startswith("2026-")
