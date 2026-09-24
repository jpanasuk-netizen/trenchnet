from pathlib import Path
import json
import py_compile

p = Path("trenchnet/webui.py")
t = p.read_text(encoding="utf-8")
if "/api/live/state" in t and "_handle_live_api" in t:
    print("already_patched")
else:
    helper = r'''
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


'''
    if "_handle_live_api" not in t:
        t = t.replace("def build_handler(root: Path):", helper + "def build_handler(root: Path):", 1)
    if 'elif p == "/live":' not in t:
        for needle in ['elif p == "/paper":', 'if p == "/paper":', 'elif p.startswith("/paper")']:
            if needle in t:
                t = t.replace(needle, 'elif p == "/live":\n                self._file(root / "out" / "live.html")\n            ' + needle, 1)
                break
        else:
            # fallback after / dashboard
            t = t.replace(
                'if p in ("/", "/index.html"):',
                'if p == "/live":\n                self._file(root / "out" / "live.html")\n            elif p in ("/", "/index.html"):',
                1,
            )
    if 'elif p.startswith("/api/live/")' not in t:
        for needle in ['elif p == "/api/overview":', 'if p == "/api/overview":', 'elif p.startswith("/api/")']:
            if needle in t:
                t = t.replace(
                    needle,
                    'elif p.startswith("/api/live/"):\n                self._json(_handle_live_api(root, "GET", p, {}))\n            ' + needle,
                    1,
                )
                break
    if 'p.startswith("/api/live/")' not in t.split("def do_POST", 1)[-1][:1500]:
        marker = "def do_POST(self):"
        if marker in t:
            insert = marker + '''
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                body = {}
            p = (self.path or "").split("?")[0]
            if p.startswith("/api/live/"):
                self._json(_handle_live_api(root, "POST", p, body if isinstance(body, dict) else {}))
                return
'''
            # avoid double-read if do_POST already reads body — check
            post = t.split(marker, 1)[1][:400]
            if "Content-Length" in post:
                # insert only the live branch after body parse — softer
                t = t.replace(
                    marker,
                    marker + '''
            # LIVE APIs (scrubbed) — handled early if path matches after body parse below
''',
                    1,
                )
                # try find place after body =
                if 'if p.startswith("/api/paper' in t or "api/paper" in t:
                    t = t.replace(
                        'if p.startswith("/api/paper',
                        'if p.startswith("/api/live/"):\n                self._json(_handle_live_api(root, "POST", p, body if isinstance(body, dict) else {}))\n                return\n            if p.startswith("/api/paper',
                        1,
                    )
                elif "api/kill" in t:
                    t = t.replace(
                        'if p == "/api/kill"',
                        'if p.startswith("/api/live/"):\n                self._json(_handle_live_api(root, "POST", p, body if isinstance(body, dict) else {}))\n                return\n            if p == "/api/kill"',
                        1,
                    )
            else:
                t = t.replace(marker, insert, 1)
    p.write_text(t, encoding="utf-8")
    print("patched")

py_compile.compile("trenchnet/webui.py", doraise=True)
print("compile_ok")
# show live route presence
text = Path("trenchnet/webui.py").read_text(encoding="utf-8")
print("has_/live", "/live" in text)
print("has_handle", "_handle_live_api" in text)
