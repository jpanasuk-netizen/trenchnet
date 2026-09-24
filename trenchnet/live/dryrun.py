"""DRY RUN: quote + build unsigned swap for MY_WALLET_ADDRESS + simulateTransaction.

NO signing with TRENCHNET_WALLET_KEY. NO sendTransaction.
Uses public MY_WALLET_ADDRESS from .env only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from trenchnet.live import routes as live_routes
from trenchnet.live.gates import pre_trade_gate, SPEC
from trenchnet.live.hygiene import check_mint_authorities
from trenchnet.live.orders import simulate_b64_tx
from trenchnet.live.redaction import redact_exc, scrub_dict
from trenchnet.live.state import kill_file_present, load_state

WSOL = "So11111111111111111111111111111111111111112"


def _my_public_wallet() -> str | None:
    from trenchnet.mywallet import configured_address
    return configured_address()


def dry_run_candidate(
    *,
    token_mint: str,
    sol_amount: float = 0.25,
    slippage_pct: float = 5.0,
    rpc_url: str | None = None,
) -> dict[str, Any]:
    """Fetch Jupiter quote, build unsigned tx for MY_WALLET_ADDRESS, simulate. Never send."""
    st = load_state()
    rpc = rpc_url or st.get("rpc_url") or "https://api.mainnet-beta.solana.com"
    pub = _my_public_wallet()
    out: dict[str, Any] = {
        "ok": False,
        "mode": "dry_run",
        "token_mint": token_mint,
        "sol_amount": sol_amount,
        "pubkey_masked": (pub[:4] + "…" + pub[-4:]) if pub and len(pub) > 8 else None,
        "signed": False,
        "sent": False,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "no_edge_disclaimer": "No measured edge yet — simulated only.",
    }
    if not pub:
        out["error"] = "MY_WALLET_ADDRESS not set in .env"
        return scrub_dict(out)

    # Gate checks (dry-run reports pass/fail; does not require armed)
    auth = check_mint_authorities(rpc, token_mint)
    lamports = int(float(sol_amount) * 1_000_000_000)
    slip_bps = int(float(slippage_pct) * 100)
    quote = live_routes.jupiter_quote(input_mint=WSOL, output_mint=token_mint, amount_lamports=lamports, slippage_bps=slip_bps)
    route = "jupiter"
    if not quote.get("ok"):
        # try pumpportal local quote hint (unsigned build may still fail)
        pp = live_routes.pumpportal_local_tx_hint(token_mint=token_mint, sol_amount=sol_amount, user_pubkey=pub, side="buy")
        out["pumpportal_hint"] = {k: pp.get(k) for k in ("ok", "status", "note", "error") if k in pp}
        route = "pumpportal_attempt"

    gate = pre_trade_gate(
        side="buy",
        sol_amount=sol_amount,
        token_mint=token_mint,
        state={**st, "armed": True, "limits": {**(st.get("limits") or {}), "max_sol_per_trade": max(float((st.get("limits") or {}).get("max_sol_per_trade") or 0), 0.25), "max_open_positions": max(int((st.get("limits") or {}).get("max_open_positions") or 0), 4)}},
        open_positions=0,
        buys_this_token=0,
        mint_authority_revoked=auth.get("mint_authority_revoked"),
        freeze_authority_revoked=auth.get("freeze_authority_revoked"),
        can_sell_ok=True if quote.get("ok") else None,
        kill_file_present=kill_file_present(),
        cfg=SPEC,
    )
    # For dry-run display we evaluate checks even when disarmed in real state
    out["gate_checks"] = gate
    out["hygiene"] = auth
    out["quote"] = {
        "ok": quote.get("ok"),
        "status": quote.get("status"),
        "error": quote.get("error"),
        "out_amount": ((quote.get("data") or {}) or {}).get("outAmount"),
        "price_impact_pct": ((quote.get("data") or {}) or {}).get("priceImpactPct"),
        "route_plan_len": len(((quote.get("data") or {}) or {}).get("routePlan") or []),
    }
    out["route"] = route

    if not quote.get("ok") or not quote.get("data"):
        out["simulation"] = {"ok": False, "skipped": True, "reason": "no_quote", "fallback": "quote_only"}
        out["ok"] = True  # dry-run completed honestly
        out["note"] = "Quote failed — common for fresh pump tokens or empty wallet context. No tx sent."
        return scrub_dict(out)

    swap = live_routes.jupiter_swap_tx(quote=quote["data"], user_pubkey=pub)
    out["swap_build"] = {"ok": swap.get("ok"), "status": swap.get("status"), "error": swap.get("error"), "fee_note": swap.get("fee_note")}
    if not swap.get("ok") or not swap.get("swapTransaction"):
        out["simulation"] = {"ok": False, "skipped": True, "reason": "swap_tx_build_failed", "fallback": "quote_only"}
        out["ok"] = True
        return scrub_dict(out)

    try:
        sim = simulate_b64_tx(rpc, swap["swapTransaction"])
        err = None
        if isinstance(sim.get("result"), dict):
            err = (sim["result"].get("value") or {}).get("err")
        out["simulation"] = {
            "ok": bool(sim.get("ok") and err is None),
            "err": err,
            "rpc_error": sim.get("error"),
            "method": "simulateTransaction",
            "sigVerify": False,
            "replaceRecentBlockhash": True,
            "note": "Unsigned/public wallet simulation — failure is OK if wallet has no SOL.",
        }
    except Exception as exc:
        out["simulation"] = {"ok": False, "error": redact_exc(exc)}
    out["ok"] = True
    out["expected_out"] = out["quote"].get("out_amount")
    out["price_impact_pct"] = out["quote"].get("price_impact_pct")
    return scrub_dict(out)


def dry_run_top_candidates(limit: int = 3, sol_amount: float = 0.25) -> dict[str, Any]:
    """Dry-run against current top pick / hot tokens / co-entry sample."""
    from trenchnet.config_load import ROOT
    import json
    mints: list[str] = []
    tp = ROOT / "out" / "top_pick.json"
    if tp.is_file():
        try:
            doc = json.loads(tp.read_text(encoding="utf-8"))
            if (doc.get("top_pick") or {}).get("token_mint"):
                mints.append(doc["top_pick"]["token_mint"])
            for c in doc.get("candidates") or []:
                m = c.get("token_mint")
                if m and m not in mints:
                    mints.append(m)
        except Exception:
            pass
    cd = ROOT / "out" / "copydesk.json"
    if cd.is_file():
        try:
            doc = json.loads(cd.read_text(encoding="utf-8"))
            for h in doc.get("hot_tokens") or []:
                m = h.get("token_mint")
                if m and m not in mints:
                    mints.append(m)
        except Exception:
            pass
    results = []
    for m in mints[:limit]:
        results.append(dry_run_candidate(token_mint=m, sol_amount=sol_amount))
    return {
        "ok": True,
        "mode": "dry_run_batch",
        "n": len(results),
        "results": results,
        "sent": False,
        "signed": False,
        "no_edge_disclaimer": "No measured edge yet — simulated only.",
    }
