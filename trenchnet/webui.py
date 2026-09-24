"""TRENCHNET desk UI server — stdlib http.server, PAPER-only endpoints.

Serves out/dashboard.html + assets (file:// compatible) and a small JSON API:
  GET  /                -> dashboard (WATCH-ONLY + PAPER badges baked in)
  GET  /assets/*        -> vendored assets (data.js etc.)
  GET  /paper           -> paper portfolio page
  GET  /api/overview    -> real out/ data summary (json)
GET  /api/data-version -> freshness token for UI poll (no secrets)
GET  /api/backtest/summary -> paper backtest summary
GET  /api/scores       -> wallet composite scores
GET  /api/coindesk/state -> read-only Coin Desk (Base/hood.fun) live or JSONL fallback
GET  /api/picks        -> Top Pick card payload (paper; rebuild with ?rebuild=1)
GET  /api/hottakes    -> Hot Takes feed + scoreboard (paper)
GET  /api/hottakes/tracker -> tracker status
GET  /api/copydesk   -> Copy Wallets command center (paper)
  GET  /health          -> kill switch + counters
  GET  /api/events      -> SSE ping stream (live status feed)
  POST /api/paper/buy|sell|close  {wallet, token_mint?, amount_token?}
       -> PAPER fill priced from most recent REAL on-chain trade (sig cited)
  POST /api/kill        {on: bool} -> paper kill switch
  POST /api/fetch-history {max_pages?, max_tx?} -> background resumable fetch
  POST /api/replay      -> background replay + dashboard regen
LIVE trading: NOT IMPLEMENTED anywhere. There is no order endpoint at all.
"""

from __future__ import annotations

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from trenchnet import dashboard
from trenchnet.config_load import ROOT, load_roster, load_settings
from trenchnet.data_solana import SolanaRPC, events_from_raw, load_raw_dir
from trenchnet.history import history_dir
from trenchnet.paper import (
    _utc_day,
    iter_records,
    kill_switch_on,
    paper_fill,
    paper_settings_from,
    paper_state,
    set_kill_switch,
)

MIME = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
        ".json": "application/json", ".ico": "image/x-icon", ".png": "image/png"}


def _all_events(root: Path) -> list:
    """Every parsed real trade event: data/raw/*.json + full-history caches."""
    settings = load_settings()
    raw_dir = root / settings.get("paths", {}).get("raw_dir", "data/raw")
    events = events_from_raw(load_raw_dir(raw_dir))
    hdir = history_dir(raw_dir)
    if hdir.is_dir():
        from trenchnet.history import history_events_for_wallet
        for p in sorted(hdir.glob("*.json")):
            events.extend(history_events_for_wallet(hdir, p.stem))
    return events


def _do_paper(root: Path, action: str, body: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    cfg = paper_settings_from(settings)
    data_dir = root / "data"
    ledger = data_dir / "paper" / "ledger.jsonl"
    wallet = str(body.get("wallet") or "")
    token = body.get("token_mint") or None
    amount = body.get("amount_token")
    events = _all_events(root)
    if token is None and wallet:
        # paper-copy this wallet's most recent entry
        mine = [e for e in events if e.wallet == wallet and e.side == "buy"]
        mine.sort(key=lambda e: (e.block_time or 0, e.slot or 0))
        if mine:
            token = mine[-1].token_mint
    if not wallet or not token:
        return {"ok": False, "reason": "no_real_price",
                "context": {"why": "no wallet/token with a real on-chain trade price found"}}
    res = paper_fill(
        action, wallet, token,
        events=events, ledger_path=ledger, data_dir=data_dir,
        settings=cfg,
        amount_token=float(amount) if amount else None,
        note="desk UI",
    )
    return res


def _start_background(root: Path, fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def _bg_fetch_history(root: Path, max_pages: int | None, max_tx: int | None) -> None:
    settings = load_settings()
    roster = load_roster()
    raw_dir = root / settings.get("paths", {}).get("raw_dir", "data/raw")
    sol = settings.get("solana", {})
    rpc = SolanaRPC(sol.get("rpc_url", "https://api.mainnet-beta.solana.com"),
                    sleep_ms=int(sol.get("request_sleep_ms", 500)))
    from trenchnet.history import fetch_wallet_history
    for w in roster.get("wallets") or []:
        try:
            fetch_wallet_history(rpc, w["address"], history_dir(raw_dir) / f"{w['address']}.json",
                                 max_pages=max_pages, max_tx=max_tx)
        except Exception:
            continue
        finally:
            dashboard.bake_data_js(root)


def _bg_replay(root: Path) -> None:
    from trenchnet.pipeline import run_replay
    try:
        run_replay()
    finally:
        dashboard.regenerate(root)



def _live_json_scrub(obj):
    bad = {"secret", "private_key", "secret_key", "seed", "keypair", "secret64"}
    if isinstance(obj, dict):
        return {k: _live_json_scrub(v) for k, v in obj.items() if k not in bad and "secret" not in k.lower()}
    if isinstance(obj, list):
        return [_live_json_scrub(x) for x in obj]
    return obj


def _handle_live_api(root: Path, method: str, path: str, body: dict) -> dict:
    from trenchnet.live import state as live_state
    from trenchnet.live import wallet as live_wallet
    from trenchnet.live import orders as live_orders
    if path == "/api/live/state" and method == "GET":
        return live_state.public_state()
    if path == "/api/live/ledger" and method == "GET":
        lp = root / "data" / "live" / "ledger.jsonl"
        rows = []
        if lp.is_file():
            for line in lp.read_text(encoding="utf-8").splitlines()[-100:]:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
        return {"rows": _live_json_scrub(rows)}
    if path == "/api/live/balances" and method == "GET":
        pub = live_wallet.public_address()
        if not pub:
            return {"sol": None, "error": "no_wallet"}
        st = live_state.load_state()
        rpc = st.get("rpc_url") or "https://api.mainnet-beta.solana.com"
        try:
            import httpx
            r = httpx.post(rpc, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [pub]}, timeout=30.0)
            lam = (((r.json() or {}).get("result") or {}).get("value"))
            return {"sol": (lam / 1_000_000_000) if lam is not None else None, "pubkey": pub}
        except Exception as exc:
            return {"sol": None, "error": type(exc).__name__, "pubkey": pub}
    if path == "/api/live/wallet/generate" and method == "POST":
        return _live_json_scrub(live_wallet.generate_keypair())
    if path == "/api/live/wallet/import" and method == "POST":
        sec = body.get("secret") or ""
        raw = None
        try:
            if isinstance(sec, str) and sec.strip().startswith("["):
                raw = bytes(json.loads(sec))
            else:
                from solders.keypair import Keypair
                try:
                    kp = Keypair.from_base58_string(sec.strip())
                    raw = bytes(kp)
                except Exception:
                    return {"ok": False, "error": "unsupported_secret_format"}
        except Exception:
            return {"ok": False, "error": "bad_secret"}
        return _live_json_scrub(live_wallet.import_secret_bytes(raw))
    if path == "/api/live/limits" and method == "POST":
        lim = {k: body.get(k) for k in (
            "max_sol_per_trade", "daily_loss_cap_sol", "max_trades_per_day",
            "max_open_positions", "max_slippage_pct", "max_priority_fee_lamports"
        ) if k in body}
        live_state.set_limits(lim)
        st = live_state.load_state()
        if "rpc_url" in body:
            st["rpc_url"] = body["rpc_url"]
        if "pumpportal_opt_in" in body:
            st["pumpportal_opt_in"] = bool(body["pumpportal_opt_in"])
        live_state.save_state(st)
        return live_state.public_state()
    if path == "/api/live/arm" and method == "POST":
        return live_state.try_arm(body.get("phrase") or "", auto=bool(body.get("auto")))
    if path == "/api/live/disarm" and method == "POST":
        return live_state.disarm("manual_api")
    if path == "/api/live/kill" and method == "POST":
        return live_state.set_kill(bool(body.get("on", True)))
    if path == "/api/live/order" and method == "POST":
        return _live_json_scrub(live_orders.execute(
            side=body.get("side") or "buy",
            token_mint=body.get("token_mint") or "",
            sol_amount=float(body.get("sol_amount") or 0),
            slippage_pct=float(body.get("slippage_pct") or 0),
            priority_fee_lamports=int(body.get("priority_fee_lamports") or 0),
            confirm_phrase=body.get("confirm_phrase") or "",
            mode=body.get("mode") or "simulate",
        ))
    return {"error": "unknown_live_api", "path": path}


def build_handler(root: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj: Any, status: int = 200) -> None:
            b = json.dumps(obj, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _file(self, path: Path, status: int = 200) -> None:
            if not path.is_file():
                self._json({"error": "not found", "path": str(path)}, 404)
                return
            b = path.read_bytes()
            self.send_response(status)
            self.send_header("Content-Type", MIME.get(path.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        # ------------------------------------------------------------ GET
        def do_GET(self):
            p = self.path.split("?")[0]
            if p in ("/", "/dashboard", "/index.html"):
                dashboard.regenerate(root)  # always fresh real data
                self._file(root / "out" / "dashboard.html")
            elif p.startswith("/assets/"):
                self._file(root / "out" / p.lstrip("/"))
            elif p == "/live":
                self._file(root / "out" / "live.html")
            elif p == "/paper":
                self._file(root / "out" / "dashboard.html")  # portfolio lives in dashboard
            elif p.startswith("/api/live/"):
                self._json(_handle_live_api(root, "GET", p, {}))
            elif p == "/api/overview":
                self._json(dashboard.collect_data(root))
            elif p == "/api/data-version":
                # Read-only freshness signal for the interactive dashboard poller.
                bsum = root / "out" / "backtest_summary.json"
                scores = root / "out" / "scores.json"
                data_js = root / "out" / "assets" / "data.js"
                def _mtime(path):
                    try:
                        return path.stat().st_mtime
                    except OSError:
                        return None
                ver = {
                    "ok": True,
                    "paper_only": True,
                    "generated_at_utc": None,
                    "mtime": {
                        "backtest_summary": _mtime(bsum),
                        "scores": _mtime(scores),
                        "data_js": _mtime(data_js),
                    },
                }
                try:
                    import json as _json
                    if bsum.exists():
                        ver["generated_at_utc"] = (_json.loads(bsum.read_text(encoding="utf-8")).get("generated_at_utc"))
                except Exception:
                    pass
                # version token = max mtime (no secrets)
                mt = [v for v in ver["mtime"].values() if v is not None]
                ver["version"] = str(max(mt) if mt else 0)
                self._json(ver)
            elif p == "/api/backtest/summary":
                import json as _json
                pth = root / "out" / "backtest_summary.json"
                if not pth.exists():
                    self._json({"error": "missing", "note": "run: python -m trenchnet.cli backtest"}, 404)
                else:
                    self._json(_json.loads(pth.read_text(encoding="utf-8")))
            elif p == "/api/scores":
                import json as _json
                pth = root / "out" / "scores.json"
                if not pth.exists():
                    self._json({"error": "missing"}, 404)
                else:
                    self._json(_json.loads(pth.read_text(encoding="utf-8")))
            elif p == "/api/coindesk/state":
                # Read-only: never start/stop Coin Desk. Live :3010 or JSONL fallback.
                try:
                    from trenchnet.coindesk import get_coindesk_state
                    self._json(get_coindesk_state())
                except Exception as exc:
                    self._json({
                        "ok": False,
                        "status": "error",
                        "chain": "Base",
                        "venue": "hood.fun",
                        "label": "Base / hood.fun — PAPER watch (not Solana)",
                        "cards": [],
                        "note": f"coindesk_error:{type(exc).__name__}",
                        "paper_only": True,
                    }, 500)
            elif p == "/api/picks":
                import json as _json
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                rebuild = (qs.get("rebuild") or ["0"])[0] in ("1", "true", "yes")
                pth = root / "out" / "top_pick.json"
                if rebuild or not pth.exists():
                    try:
                        from trenchnet.picks import build_picks_payload
                        payload = build_picks_payload(root)
                        self._json(payload)
                    except Exception as exc:
                        self._json({"error": type(exc).__name__, "note": "picks_build_failed", "paper_only": True}, 500)
                else:
                    self._json(_json.loads(pth.read_text(encoding="utf-8")))
            elif p == "/api/hottakes":
                try:
                    from trenchnet.hottakes import build_hottakes_payload, ensure_tracker
                    ensure_tracker(root)  # no-op if already running
                    self._json(build_hottakes_payload(root))
                except Exception as exc:
                    self._json({"error": type(exc).__name__, "paper_only": True, "takes": []}, 500)
            elif p == "/api/hottakes/tracker":
                try:
                    from trenchnet.hottakes import ensure_tracker, get_tracker
                    tr = ensure_tracker(root)
                    self._json({"ok": True, "tracker": (tr.state if tr else {}), "paper_only": True})
                except Exception as exc:
                    self._json({"ok": False, "error": type(exc).__name__}, 500)
            elif p == "/api/copydesk":
                try:
                    from trenchnet.copydesk import build_copydesk, write_copydesk
                    doc = build_copydesk(root)
                    try:
                        write_copydesk(root)
                    except Exception:
                        pass
                    self._json(doc)
                except Exception as exc:
                    self._json({"error": type(exc).__name__, "paper_only": True, "leaderboard": []}, 500)
            elif p == "/health":
                settings = load_settings()
                cfg = paper_settings_from(settings)
                st = paper_state(root / "data" / "paper" / "ledger.jsonl", cfg)
                self._json({
                    "ok": True, "mode": "PAPER", "observe_only": True,
                    "kill_switch": kill_switch_on(root / "data"),
                    "fills": len(st["fills"]), "refusals": len(st["refusals"]),
                    "live": "disarmed-by-default (GUI /live; simulate until ARM LIVE)",
                })
            elif p == "/api/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    for _ in range(120):  # ~10 min then client reconnects
                        settings = load_settings()
                        cfg = paper_settings_from(settings)
                        st = paper_state(root / "data" / "paper" / "ledger.jsonl", cfg)
                        msg = json.dumps({
                            "type": "status", "mode": "PAPER",
                            "kill_switch": kill_switch_on(root / "data"),
                            "fills": len(st["fills"]), "refusals": len(st["refusals"]),
                            "balance_sol": st["balance_sol"],
                        })
                        self.wfile.write(f"data: {msg}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(5)
                except Exception:
                    pass
            else:
                self._json({"error": "unknown route", "route": p}, 404)

        # ----------------------------------------------------------- POST
        def do_POST(self):
            # LIVE APIs (scrubbed) — handled early if path matches after body parse below

            p = self.path.split("?")[0]
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            except Exception:
                body = {}
            if p in ("/api/paper/buy", "/api/paper/sell", "/api/paper/close"):
                action = p.rsplit("/", 1)[-1]
                self._json(_do_paper(root, action, body))
            elif p == "/api/kill":
                on = bool(body.get("on"))
                set_kill_switch(root / "data", on)
                self._json({"ok": True, "kill_switch": on, "mode": "PAPER"})
            elif p == "/api/fetch-history":
                mp = body.get("max_pages"); mt = body.get("max_tx")
                _start_background(root, _bg_fetch_history, root,
                                  int(mp) if mp else None, int(mt) if mt else None)
                self._json({"ok": True, "started": True, "note": "background, resumable; free RPC only"})
            elif p == "/api/replay":
                _start_background(root, _bg_replay, root)
                self._json({"ok": True, "started": True})
            else:
                self._json({"error": "unknown route", "route": p}, 404)

    return Handler


def serve(root: Path = ROOT, host: str = "127.0.0.1", port: int = 8791, open_browser: bool = True) -> None:
    dashboard.regenerate(root)
    # Pass 8: start Hot Take tracker daemon (non-blocking)
    try:
        from trenchnet.hottakes import ensure_tracker
        tr = ensure_tracker(root)
        print(f"Hot Take tracker started (poll={tr.state.get('poll_interval_seconds')}s) — paper only.")
    except Exception as exc:
        print(f"Hot Take tracker not started: {type(exc).__name__}")
    httpd = ThreadingHTTPServer((host, port), build_handler(root))
    url = f"http://{host}:{port}/"
    print(f"TRENCHNET desk (WATCH-ONLY / PAPER) at {url}  — LIVE off, no implementation.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
