"""AUTOBUY loop built from this repo's live/history/Jev pieces.

Requires TRADING armed and AUTOBUY latched. Then, each tick:
  1. runners from history + scores (>= 0.40)
  2. open Hot Takes
  3. Jev via judge_snapshot / combine_jev_answers
  4. Jupiter quote
  5. pre_trade_gate (armed / caps / kill / fee reserve)
Only then execute(mode='send', confirm_phrase='CONFIRM LIVE ORDER').
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from trenchnet.live.gates import pre_trade_gate
from trenchnet.live.runners import (
    DEFAULT_JEV_THRESHOLD,
    detect_runners,
    jev_threshold_for,
    top_wallets_from_scores,
)
from trenchnet.live.routes import WSOL, jupiter_quote
from trenchnet.live.state import kill_file_present, load_state

logger = logging.getLogger(__name__)
CONFIRM = "CONFIRM LIVE ORDER"
JEV_OK_ROUTES = {"send_for_analysis", "keep_observing"}
SPEC_TICKET_SOL = 0.025
SPEC_STOP_PCT = 0.25
_LOOP: AutoBuyLoop | None = None


def status_path(root: Path) -> Path:
    return root / "data" / "live" / "autobuy_status.json"


def load_status(root: Path) -> dict[str, Any]:
    path = status_path(root)
    if not path.is_file():
        return {"buys": 0, "skips": 0, "last": None, "candidates": [], "last_run_iso": None}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"buys": 0, "skips": 0, "last": None, "candidates": []}
    except Exception:
        return {"buys": 0, "skips": 0, "last": None, "candidates": [], "last_run_iso": None}


def save_status(root: Path, doc: dict[str, Any]) -> None:
    path = status_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")


def public_status(root: Path) -> dict[str, Any]:
    from trenchnet.live.state import autobuy_public
    base = autobuy_public()
    st = load_status(root)
    base.update({
        "buys": int(st.get("buys") or 0),
        "skips": int(st.get("skips") or 0),
        "last": st.get("last"),
        "candidates": st.get("candidates") or [],
        "last_run_iso": st.get("last_run_iso"),
        "note": "AUTOBUY buys runners/hot takes after Jev + quote + pre_trade_gate.",
    })
    return base


def jev_entry_from_routed(routed: dict[str, Any], *, threshold: float) -> dict[str, Any]:
    """Map observe-route Jev output to an entry word + probability."""
    route = str((routed or {}).get("route") or "")
    try:
        prob = float((routed or {}).get("confidence") or 0)
    except (TypeError, ValueError):
        prob = 0.0
    word = "BUY" if route in JEV_OK_ROUTES else "HOLD"
    return {
        "word": word,
        "probability": prob,
        "threshold": float(threshold),
        "route": route,
        "jev_mode": (routed or {}).get("jev_mode"),
        "ok_for_entry": bool(word == "BUY" and prob >= float(threshold)),
        "reasons": list((routed or {}).get("reasons") or []),
    }


def _ticket_and_stop(lim: dict[str, Any]) -> tuple[float, float]:
    ticket = float(lim.get("max_sol_per_trade") or 0) or SPEC_TICKET_SOL
    stop = float(lim.get("stop_loss_pct") or 0) or SPEC_STOP_PCT
    return ticket, stop


def _load_scores(root: Path) -> dict[str, Any]:
    try:
        return json.loads((root / "out" / "scores.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _history_events(root: Path) -> list[dict[str, Any]]:
    try:
        from trenchnet.backtest import load_all_history_events
        return list(load_all_history_events(root) or [])
    except Exception:
        return []


def _open_hottakes(root: Path) -> list[dict[str, Any]]:
    path = root / "data" / "hottakes" / "hottakes.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("kind") == "backtested" or rec.get("status") == "closed":
            continue
        mint = rec.get("token_mint") or rec.get("mint")
        if mint:
            rec["token_mint"] = mint
            rows.append(rec)
    rows.sort(key=lambda r: float(r.get("flagged_at") or 0), reverse=True)
    return rows


def _n_open() -> int:
    try:
        from trenchnet.live.ledger import load_open_positions, open_from_ledger
        return len(load_open_positions() or open_from_ledger() or [])
    except Exception:
        return 0


def _quote_ok(mint: str, sol_amount: float, slippage_pct: float) -> tuple[bool, str]:
    lamports = int(round(float(sol_amount) * 1e9))
    slip_bps = int(round(float(slippage_pct) * 100))
    q = jupiter_quote(
        input_mint=WSOL,
        output_mint=mint,
        amount_lamports=lamports,
        slippage_bps=slip_bps,
    )
    if not q.get("ok") or not q.get("data"):
        return False, f"quote_failed:{q.get('status') or q.get('error') or 'empty'}"
    data = q["data"]
    try:
        out = int(data.get("outAmount") or data.get("out_amount") or 0)
    except (TypeError, ValueError):
        out = 0
    if out < 1:
        return False, "quote_zero_out"
    return True, f"quote_ok:{out}"


def _jev_snapshot(mint: str, *, events: list[dict[str, Any]], runner: dict[str, Any] | None, ticket: float) -> dict[str, Any]:
    mint_ev = [e for e in events if str(e.get("token_mint") or "") == mint]
    n = len(mint_ev)
    return {
        "focus_token": mint,
        "history_flag": "ok" if n else "missing_history",
        "trade_count": n,
        "current_buy_sol": ticket,
        "typical_buy_size_sol": ticket,
        "attention_hint": "new_situation" if runner else "needs_update",
        "n_top_wallets": int((runner or {}).get("n_top") or 0),
        "is_runner": bool(runner),
        "wallet_score": {
            "available": bool(runner),
            "score": (runner or {}).get("score"),
            "n_top": (runner or {}).get("n_top"),
        },
    }


def collect_candidates(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events = _history_events(root)
    scores = _load_scores(root)
    top = top_wallets_from_scores(scores)
    runners = detect_runners(events, top.keys())
    takes = _open_hottakes(root)
    seen: set[str] = set()
    cands: list[dict[str, Any]] = []
    for r in runners:
        mint = str(r.get("mint") or "")
        if not mint or mint in seen:
            continue
        seen.add(mint)
        cands.append({
            "token_mint": mint,
            "kind": "runner",
            "n_top": r.get("n_top"),
            "score": r.get("score"),
            "flagged_at": r.get("flagged_at"),
            "wallets": r.get("wallets"),
        })
    for take in takes:
        mint = str(take.get("token_mint") or "")
        if not mint or mint in seen:
            continue
        seen.add(mint)
        cands.append({
            "token_mint": mint,
            "kind": "hottake",
            "flagged_at": take.get("flagged_at"),
            "status": take.get("status"),
        })
    return cands[:8], runners, events


def run_autobuy_once(root: Path, *, execute_fn=None) -> dict[str, Any]:
    """One tick. execute_fn is injectable so tests never broadcast."""
    live = load_state()
    status = load_status(root)
    if live.get("kill_switch") or kill_file_present():
        return {"ok": False, "reason": "kill_switch"}
    if not live.get("armed"):
        return {"ok": False, "reason": "desk_disarmed"}
    if not live.get("auto_armed"):
        return {"ok": False, "reason": "autobuy_disarmed"}

    lim = live.get("limits") or {}
    ticket, stop_pct = _ticket_and_stop(lim)
    slip = float(lim.get("max_slippage_pct") or 5.0)
    prio = int(lim.get("max_priority_fee_lamports") or 0)
    cands, runners, events = collect_candidates(root)
    status["candidates"] = cands
    status["last_run_iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    from trenchnet.jev_gate import judge_snapshot

    for cand in cands:
        mint = str(cand.get("token_mint") or "")
        if not mint:
            continue
        runner = next((r for r in runners if r.get("mint") == mint), None)
        thr = jev_threshold_for(mint, runners) if runners else DEFAULT_JEV_THRESHOLD
        routed = judge_snapshot(_jev_snapshot(mint, events=events, runner=runner, ticket=ticket))
        jev = jev_entry_from_routed(routed, threshold=thr)
        if not jev.get("ok_for_entry"):
            status["skips"] = int(status.get("skips") or 0) + 1
            status["last"] = {"mint": mint, "skip": f"jev_{jev.get('word')}_{jev.get('probability')}", "jev": jev}
            save_status(root, status)
            continue
        q_ok, q_reason = _quote_ok(mint, ticket, slip)
        if not q_ok:
            status["skips"] = int(status.get("skips") or 0) + 1
            status["last"] = {"mint": mint, "skip": q_reason, "jev": jev}
            save_status(root, status)
            continue
        gate = pre_trade_gate(
            side="buy",
            sol_amount=ticket,
            token_mint=mint,
            state=live,
            open_positions=_n_open(),
        )
        if not gate.get("ok"):
            status["skips"] = int(status.get("skips") or 0) + 1
            status["last"] = {"mint": mint, "skip": gate.get("reason"), "jev": jev, "gate": gate.get("reason")}
            save_status(root, status)
            continue
        fn = execute_fn
        if fn is None:
            from trenchnet.live.orders import execute
            fn = execute
        res = fn(
            side="buy",
            token_mint=mint,
            sol_amount=ticket,
            slippage_pct=slip,
            priority_fee_lamports=prio,
            confirm_phrase=CONFIRM,
            mode="send",
        )
        ok = bool(isinstance(res, dict) and res.get("ok"))
        if ok:
            status["buys"] = int(status.get("buys") or 0) + 1
        else:
            status["skips"] = int(status.get("skips") or 0) + 1
        status["last"] = {
            "mint": mint,
            "jev": jev,
            "gate": gate.get("reason"),
            "stop_loss_pct": stop_pct,
            "ticket_sol": ticket,
            "result": res,
        }
        save_status(root, status)
        return {"ok": ok, "mint": mint, "jev": jev, "result": res, "stop_loss_pct": stop_pct}

    save_status(root, status)
    return {"ok": True, "reason": "no_entry", "skips": status.get("skips"), "candidates": cands}


class AutoBuyLoop:
    def __init__(self, root: Path, interval_s: float = 60.0):
        self.root = root
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="trenchnet-autobuy")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                st = load_state()
                if st.get("armed") and st.get("auto_armed") and not st.get("kill_switch"):
                    run_autobuy_once(self.root)
            except Exception as exc:
                logger.warning("autobuy tick failed: %s", type(exc).__name__)
            self._stop.wait(self.interval_s)


def ensure_loop(root: Path, *, interval_s: float = 60.0) -> AutoBuyLoop:
    global _LOOP
    if _LOOP is None:
        _LOOP = AutoBuyLoop(root, interval_s=interval_s)
    _LOOP.start()
    return _LOOP
