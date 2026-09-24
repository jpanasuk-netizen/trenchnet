"""PASS 3 tests: token_context (mocked HTTP), sources_expand (mocked), rpc_pool failover."""

from __future__ import annotations

import json

import pytest
import yaml

import trenchnet.rpc_pool as rpc_pool
import trenchnet.sources_expand as sources_expand
import trenchnet.token_context as token_context


# ------------------------------------------------------------- token_context

class _FakeResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_fetch_token_context_pair_and_mentions(tmp_path, monkeypatch):
    dex = {"pairs": [{
        "chainId": "solana", "dexId": "raydium", "pairAddress": "pair1",
        "url": "https://dexscreener.com/solana/pair1",
        "baseToken": {"symbol": "DOJI"}, "quoteToken": {"symbol": "WSOL"},
        "priceUsd": "0.0012", "liquidity": {"usd": 25000}, "volume": {"h24": 9000},
        "priceChange": {"h24": 12.5}, "fdv": 100000,
        "info": {"socials": [{"type": "twitter", "url": "https://x.com/doji"}],
                 "websites": [{"label": "web", "url": "https://doji.xyz"}]},
    }]}
    gecko = {"data": {"attributes": {"name": "Doji"}}}
    ohlcv = {"attributes": {"ohlcv_list": [[1789000000000, "0.001", "0.002", "0.0009", "0.0018", "100"]]}}
    seq = [_FakeResp(200, dex), _FakeResp(200, gecko), _FakeResp(200, ohlcv)]
    monkeypatch.setattr(token_context.httpx, "get", lambda url, timeout=None, headers=None: seq.pop(0))
    snap = token_context.fetch_token_context("Mint1", tmp_path)
    assert snap["dexscreener"]["pair"]["priceUsd"] == "0.0012"
    assert snap["dexscreener"]["pair"]["base_symbol"] == "DOJI"
    assert len(snap["mentions"]) == 2  # thin mentions with URLs; no X API anywhere
    assert snap["links"]["solscan"].endswith("/token/Mint1")
    assert snap["thin_data"] is False
    saved = json.loads((tmp_path / "Mint1.json").read_text(encoding="utf-8"))
    assert saved["mint"] == "Mint1" and saved["fetched_at"]


def test_fetch_token_context_thin_when_no_pair(tmp_path, monkeypatch):
    seq = [_FakeResp(200, {"pairs": []}), _FakeResp(404, {}), _FakeResp(200, {})]
    monkeypatch.setattr(token_context.httpx, "get", lambda url, timeout=None, headers=None: seq.pop(0))
    snap = token_context.fetch_token_context("Mint2", tmp_path)
    assert snap["dexscreener"]["pair"] is None
    assert snap["thin_data"] is True and "No Dexscreener" in snap["note"]


def test_load_all_contexts_skips_broken(tmp_path):
    d = tmp_path / "token_context"
    d.mkdir()
    (d / "MintA.json").write_text(json.dumps({"mint": "MintA"}), encoding="utf-8")
    (d / "bad.json").write_text("{not json", encoding="utf-8")
    out = token_context.load_all_contexts(tmp_path)
    assert out.get("MintA", {}).get("mint") == "MintA"
    assert "bad" not in out


# ------------------------------------------------------------ sources_expand

def test_fetch_kolscan_snapshot_parses(monkeypatch):
    body = {"leaderboard": [
        {"address": "A" * 44, "name": "kolA", "rank": 1},
        {"address": "short", "name": "bad"},        # filtered: too short
        {"wallet": "B" * 44, "username": "kolB"},   # alt key names
    ]}
    monkeypatch.setattr(sources_expand, "_get_json", lambda url: body)
    rows, meta = sources_expand.fetch_kolscan_snapshot()
    assert meta["ok"] is True and len(rows) == 2
    assert rows[0]["role"] == "expanded"
    assert rows[0]["provenance"]["source_url"].startswith("https://raw.githubusercontent.com/")
    assert rows[0]["provenance"]["fetched_at"]


def test_fetch_kolscan_blocked_records_honestly(monkeypatch):
    monkeypatch.setattr(sources_expand, "_get_json", lambda url: {"_blocked": True, "status": 403})
    rows, meta = sources_expand.fetch_kolscan_snapshot()
    assert rows == [] and meta["ok"] is False


def test_expand_roster_seeds_kept_and_cap(monkeypatch, tmp_path):
    fake_roster = {"wallets": [{"address": f"S{i}" + "x" * 43, "label": f"seed{i}"} for i in range(8)]}
    (tmp_path / "roster.yaml").write_text(yaml.safe_dump(fake_roster), encoding="utf-8")
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(sources_expand, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(sources_expand, "ROOT", tmp_path)
    kols = [{"address": f"K{i}" + "y" * 43, "label": f"kol{i}", "role": "expanded",
             "kolscan_rank_monthly": i + 1, "source_name": "s", "source_url": "u",
             "provenance": {"source_url": "u", "fetched_at": "t", "role": "expanded"}}
            for i in range(10)]
    monkeypatch.setattr(sources_expand, "fetch_kolscan_snapshot",
                        lambda url=None: (kols, {"ok": True, "source_url": "u", "fetched_at": "t"}))
    monkeypatch.setattr(sources_expand, "_get_json", lambda url: {"_blocked": True, "status": 403})
    rep = sources_expand.expand_roster(max_total=12, do_cobuy=False)
    assert rep["seed"] == 8 and rep["expanded"] == 4 and rep["total"] == 12
    doc = yaml.safe_load((tmp_path / "roster.yaml").read_text(encoding="utf-8"))
    ws = doc["wallets"]
    assert [w.get("role") for w in ws[:8]] == ["seed"] * 8          # original 8 preserved as seed
    assert len(ws) == 12 and all(w.get("role") == "expanded" for w in ws[8:])
    assert doc["roster_meta"]["needs_free_signup"]                  # honest blocked list for Jeremy
    assert rep["blocked"]                                           # pump.fun probe recorded, NOT signed up


# ------------------------------------------------------------------ rpc_pool

def test_rpc_pool_failover_on_429(monkeypatch):
    calls = {"a": 0, "b": 0}

    class FakeInner:
        def __init__(self, url, sleep_ms=0):
            self.url = url

        def call(self, method, params):
            key = "a" if self.url.endswith("a") else "b"
            calls[key] += 1
            if key == "a":
                raise RuntimeError("HTTP 429 rate limited")
            return {"ok": self.url}

    monkeypatch.setattr(rpc_pool, "SolanaRPC", FakeInner)
    pool = rpc_pool.MultiEndpointRPC(("https://rpca", "https://rpcb"))
    res = pool.call("getSlot", [])
    assert res == {"ok": "https://rpcb"}           # failed over past the 429 endpoint
    assert calls["a"] == 1
    assert pool._fail["https://rpca"] > 0           # 429 endpoint put in cooldown


def test_rpc_pool_all_endpoints_fail(monkeypatch):
    class FakeInner:
        def __init__(self, url, sleep_ms=0):
            self.url = url

        def call(self, method, params):
            raise RuntimeError("429")

    monkeypatch.setattr(rpc_pool, "SolanaRPC", FakeInner)
    pool = rpc_pool.MultiEndpointRPC(("https://x1", "https://x2"))
    with pytest.raises(RuntimeError):
        pool.call("getSlot", [])


def test_free_rpc_urls_verified_set():
    urls = list(rpc_pool.FREE_RPC_URLS)
    assert len(urls) == 3 and len(set(urls)) == 3
    assert "https://api.mainnet-beta.solana.com" in urls
    assert "https://solana-rpc.publicnode.com" in urls
    assert "https://api.mainnet.solana.com" in urls
