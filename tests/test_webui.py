"""Desk UI route tests (stdlib http.server) — real out/ data only, PAPER endpoints."""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from trenchnet import webui
from trenchnet.config_load import ROOT
from trenchnet.paper import iter_records, set_kill_switch


@pytest.fixture(scope="module")
def server():
    import tempfile
    root = Path(tempfile.mkdtemp(prefix="tn_ui_"))
    (root / "out").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    # minimal real-shape data so the dashboard baker has something honest to bake
    (root / "out" / "run_summary.json").write_text(json.dumps({"events": 0, "fcc_mode": "template_fallback"}))
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "settings.yaml").write_text("paths:\n  raw_dir: data/raw\n  out_dir: out\npaper:\n  enabled: true\n")
    (root / "config" / "roster.yaml").write_text("wallets: []\n")
    import shutil
    tpl = ROOT / "docs" / "dashboard_template.html"
    (root / "docs").mkdir(exist_ok=True)
    shutil.copy(tpl, root / "docs" / "dashboard_template.html")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webui.build_handler(root))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", root
    httpd.shutdown()
    set_kill_switch(root / "data", False)


from pathlib import Path  # noqa: E402


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, json.loads(r.read())


def test_dashboard_200_with_badges(server):
    url, _ = server
    status, body = _get(url + "/")
    assert status == 200
    html = body.decode("utf-8")
    assert "WATCH-ONLY" in html and "PAPER" in html and "LIVE OFF" in html
    assert "TRENCHNET_DATA" in html


def test_data_js_baked_real_data_only(server):
    url, root = server
    status, body = _get(url + "/assets/data.js")
    assert status == 200
    assert b"window.TRENCHNET_DATA" in body
    payload = body.decode().split("=", 1)[1].strip().rstrip(";").strip()
    data = json.loads(payload)
    assert data["mode"] == "PAPER" and data["observe_only"] is True


def test_health_and_overview(server):
    url, _ = server
    s1, b1 = _get(url + "/health")
    assert s1 == 200 and json.loads(b1)["mode"] == "PAPER"
    s2, b2 = _get(url + "/api/overview")
    assert s2 == 200 and "profiles" in json.loads(b2)


def test_paper_endpoint_refuses_without_real_price(server):
    url, root = server
    s, body = _post(url + "/api/paper/buy", {"wallet": "W" * 44, "token_mint": "T" * 44})
    assert s == 200
    doc = json.loads(body) if isinstance(body, (bytes, str)) else body
    doc = body if isinstance(body, dict) else json.loads(body)
    assert doc["ok"] is False and doc["reason"] == "no_real_price"
    # refusal is logged in the ledger as PAPER
    rows = iter_records(root / "data" / "paper" / "ledger.jsonl")
    assert rows and rows[-1]["type"] == "refusal" and rows[-1]["mode"] == "PAPER"


def test_kill_switch_endpoint_blocks_fill(server):
    url, root = server
    s, body = _post(url + "/api/kill", {"on": True})
    doc = body if isinstance(body, dict) else json.loads(body)
    assert doc["kill_switch"] is True
    s, body = _post(url + "/api/paper/buy", {"wallet": "W" * 44, "token_mint": "T" * 44})
    doc = body if isinstance(body, dict) else json.loads(body)
    assert doc["reason"] == "kill_switch"
    _post(url + "/api/kill", {"on": False})
