"""PAPER-ONLY trading engine for TRENCHNET. Observe-only project.

- Every fill is simulated and appended to data/paper/ledger.jsonl with mode="PAPER".
- Fill price comes from the most recent REAL on-chain trade event for that token
  (parsed from Solana RPC); the price-source tx signature is stored on the fill.
- No price -> REFUSED with a reason. Refusals are logged as type="refusal".
- Hygiene/veto gates run BEFORE any fill (see docs/LESSONS.md): kill switch,
  live-guard, no-price, oversized-vs-typical, daily paper loss cap, loss streak.
- LIVE mode: DISABLED stub with NO implementation. "LIVE is off until Jeremy names
  a ticket." There is no code path anywhere that can send a real order.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from trenchnet.models import TradeEvent

PAPER_DIR_NAME = "data/paper"
LEDGER_NAME = "ledger.jsonl"
KILL_FILE_NAME = "KILL_SWITCH"

# Env vars that (if ever present) abort paper fills — mirrors alpha-engine gates.
_PRIVATE_KEY_ENVS = ("PRIVATE_KEY", "WALLET_KEY", "SOLANA_KEYPAIR", "API_SECRET")

LIVE_TOGGLE_STUB = "LIVE is off until Jeremy names a ticket. No implementation exists."


# --------------------------------------------------------------------- helpers

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ------------------------------------------------------------------- settings

def default_paper_settings() -> dict[str, Any]:
    """Config-driven PAPER risk controls (docs/LESSONS.md #3/#4)."""
    return {
        "enabled": True,
        "starting_balance_sol": 10.0,
        "act_threshold": 0.65,          # inspired by clear_edge 0.65
        "chop_threshold": 0.75,         # reserved: inspired by chop_min_edge 0.75
        "oversized_ratio": 4.0,         # refuse buy > 4x wallet typical_buy_size_sol
        "skip_streak_halt": 20,         # consecutive refusals halt new fills
        "loss_streak_halt": 5,          # consecutive losing closes halt new buys
        "daily_loss_cap_sol": 3.0,      # max realized paper loss per UTC day
        "max_fill_fraction": 0.10,      # max fraction of current balance per buy
        "max_fill_sol": 1.0,            # absolute cap per buy
        "live_toggle": "DISABLED",      # stub only — NEVER implemented
        "live_toggle_note": LIVE_TOGGLE_STUB,
    }


def paper_settings_from(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Accept full settings (settings['paper']) or a flat paper config dict (idempotent).

    Full-settings top-level keys (solana, fcc, paths, ...) never collide with
    paper keys, so merging directly when 'paper' is absent is safe.
    """
    base = default_paper_settings()
    if not isinstance(settings, dict) or not settings:
        return base
    paper = settings.get("paper") if isinstance(settings.get("paper"), dict) else settings
    for k, v in paper.items():
        if k in base:
            base[k] = v
    return base


# ---------------------------------------------------------------- price source

def most_recent_price(events: Iterable[TradeEvent], token_mint: str) -> dict[str, Any] | None:
    """Most recent REAL on-chain trade price for a token, from parsed trade events.

    Price per token = amount_sol / amount_token from the newest event (by
    block_time then slot) that has both amounts. Returns None if no real trade
    exists — callers must refuse the fill rather than invent a price.
    """
    best: TradeEvent | None = None
    for e in events:
        if e.token_mint != token_mint or e.side not in ("buy", "sell"):
            continue
        if not e.amount_token or not e.amount_sol or e.amount_sol <= 0:
            continue
        if best is None or (e.block_time or 0, e.slot or 0) > (best.block_time or 0, best.slot or 0):
            best = e
    if best is None:
        return None
    return {
        "price_sol_per_token": float(best.amount_sol) / float(best.amount_token),
        "source_signature": best.signature,
        "source_block_time": best.block_time,
        "source_side": best.side,
        "source_amount_token": float(best.amount_token),
        "source_amount_sol": float(best.amount_sol),
    }


# --------------------------------------------------------------------- ledger

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    row.setdefault("id", str(uuid.uuid4()))
    row.setdefault("recorded_at", _now_iso())
    row.setdefault("mode", "PAPER")
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    return row


def iter_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ----------------------------------------------------------------- state view

def paper_state(ledger_path: Path, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Balances/positions derived ONLY from ledger rows (no invented numbers)."""
    cfg = settings or default_paper_settings()
    rows = iter_records(ledger_path)
    balance = float(cfg.get("starting_balance_sol", 10.0))
    positions: dict[str, dict[str, Any]] = {}
    realized = 0.0
    realized_by_day: dict[str, float] = {}
    fills: list[dict[str, Any]] = []
    refusals: list[dict[str, Any]] = []
    for r in rows:
        rtype = r.get("type")
        if rtype == "refusal":
            refusals.append(r)
            continue
        if rtype != "fill":
            continue
        fills.append(r)
        side = r.get("side")
        sol = float(r.get("amount_sol") or 0.0)
        token = r.get("token_mint") or ""
        qty = float(r.get("amount_token") or 0.0)
        if side == "buy":
            balance -= sol
            pos = positions.setdefault(token, {"qty": 0.0, "cost_sol": 0.0})
            pos["qty"] += qty
            pos["cost_sol"] += sol
        elif side == "sell":
            balance += sol
            delta = float(r.get("realized_delta_sol") or 0.0)
            realized += delta
            realized_by_day[r.get("day") or ""] = realized_by_day.get(r.get("day") or "", 0.0) + delta
            pos = positions.get(token)
            if pos:
                frac = min(1.0, qty / pos["qty"]) if pos["qty"] > 0 else 0.0
                cost = pos["cost_sol"] * frac
                pos["cost_sol"] -= cost
                pos["qty"] -= qty  # qty is the amount actually sold
                if pos["qty"] <= 1e-12:
                    positions.pop(token, None)
    return {
        "balance_sol": round(balance, 9),
        "realized_pnl_sol": round(realized, 9),
        "realized_by_day": realized_by_day,
        "open_positions": positions,
        "fills": fills,
        "refusals": refusals,
    }


# ------------------------------------------------------------------ streaks

def skip_streak(rows: list[dict[str, Any]]) -> int:
    """Trailing consecutive refusals (fill or external action resets)."""
    streak = 0
    for r in reversed(rows):
        if r.get("type") == "refusal":
            streak += 1
        elif r.get("type") == "fill":
            break
    return streak


def loss_streak(rows: list[dict[str, Any]]) -> int:
    """Trailing consecutive losing closes (sell fills with negative realized delta)."""
    streak = 0
    for r in reversed(rows):
        if r.get("type") != "fill" or r.get("side") != "sell":
            continue
        if float(r.get("realized_delta_sol") or 0.0) < 0:
            streak += 1
        else:
            break
    return streak


def daily_realized_pnl(rows: list[dict[str, Any]], day: str | None = None) -> float:
    day = day or _utc_day()
    return round(
        sum(
            float(r.get("realized_delta_sol") or 0.0)
            for r in rows
            if r.get("type") == "fill" and r.get("side") == "sell" and r.get("day") == day
        ),
        9,
    )


# ----------------------------------------------------------------- kill switch

def kill_switch_path(data_dir: Path) -> Path:
    return data_dir / KILL_FILE_NAME


def set_kill_switch(data_dir: Path, on: bool) -> bool:
    p = kill_switch_path(data_dir)
    _ensure_parent(p)
    if on:
        p.write_text("PAPER KILL SWITCH — new paper fills blocked. LIVE remains unimplemented.\n", encoding="utf-8")
    else:
        if p.exists():
            p.unlink()
    return on


def kill_switch_on(data_dir: Path) -> bool:
    return kill_switch_path(data_dir).exists()


# ------------------------------------------------------------------- sizing

def paper_buy_size_sol(current_balance: float, cfg: dict[str, Any]) -> float:
    fraction = float(cfg.get("max_fill_fraction", 0.10))
    cap = float(cfg.get("max_fill_sol", 1.0))
    size = max(0.0, min(float(current_balance) * fraction, cap))
    return round(size, 9)


# ------------------------------------------------------------------- the gate

def check_gates(
    action: str,
    wallet: str,
    token_mint: str,
    *,
    events: Iterable[TradeEvent],
    ledger_path: Path,
    settings: dict[str, Any] | None = None,
    data_dir: Path,
) -> tuple[bool, str, dict[str, Any]]:
    """Hygiene/veto gates BEFORE any paper fill. SKIP is a valid answer.

    Returns (allowed, reason, context). Reasons are stable strings used in
    refusal rows and the UI: kill_switch, live_guard, paper_disabled,
    no_real_price, oversized_vs_typical, skip_streak_halt, loss_streak_halt,
    daily_loss_cap, insufficient_balance.
    """
    cfg = paper_settings_from(settings)

    if kill_switch_on(data_dir):
        return False, "kill_switch", {"kill_file": str(kill_switch_path(data_dir))}
    for env in _PRIVATE_KEY_ENVS:
        if os.environ.get(env):
            return False, "live_guard", {"env": env}
    if not cfg.get("enabled", True):
        return False, "paper_disabled", {}
    if str(cfg.get("live_toggle", "DISABLED")) != "DISABLED":
        # Even if someone edits the yaml, there is NO live implementation.
        return False, "live_guard", {"note": LIVE_TOGGLE_STUB}

    rows = iter_records(ledger_path)
    state = paper_state(ledger_path, cfg)

    if skip_streak_halt(cfg) and skip_streak(rows) >= int(cfg["skip_streak_halt"]):
        return False, "skip_streak_halt", {"streak": skip_streak(rows)}

    if action == "buy":
        if loss_streak_halt(cfg) and loss_streak(rows) >= int(cfg["loss_streak_halt"]):
            return False, "loss_streak_halt", {"streak": loss_streak(rows)}
        cap = float(cfg.get("daily_loss_cap_sol", 0.0))
        day_pnl = daily_realized_pnl(rows)
        if cap > 0 and day_pnl <= -cap:
            return False, "daily_loss_cap", {"day_pnl_sol": day_pnl, "cap_sol": cap}
    price = most_recent_price(events, token_mint)
    if price is None:
        return False, "no_real_price", {"token_mint": token_mint}
    if action == "buy":
        size = paper_buy_size_sol(state["balance_sol"], cfg)
        if size <= 0 or size > state["balance_sol"]:
            return False, "insufficient_balance", {"balance_sol": state["balance_sol"]}
        # oversized vs the traded wallet's typical buy
        typical = _typical_buy_size(events, wallet)
        ratio_cfg = float(cfg.get("oversized_ratio", 4.0))
        if typical and typical > 0 and size > typical * ratio_cfg:
            return False, "oversized_vs_typical", {
                "size_sol": size, "typical_buy_size_sol": typical, "ratio": round(size / typical, 3),
            }
    return True, "ok", {"price": price}


def skip_streak_halt(cfg: dict[str, Any]) -> bool:
    return int(cfg.get("skip_streak_halt", 0) or 0) > 0


def loss_streak_halt(cfg: dict[str, Any]) -> bool:
    return int(cfg.get("loss_streak_halt", 0) or 0) > 0


def _typical_buy_size(events: Iterable[TradeEvent], wallet: str) -> float | None:
    from statistics import median
    sizes = [float(e.amount_sol or 0.0) for e in events if e.wallet == wallet and e.side == "buy" and e.amount_sol]
    return round(median(sizes), 9) if sizes else None


# -------------------------------------------------------------------- fills

def paper_fill(
    action: str,
    wallet: str,
    token_mint: str,
    *,
    events: Iterable[TradeEvent],
    ledger_path: Path,
    data_dir: Path,
    settings: dict[str, Any] | None = None,
    amount_token: float | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Buy/Sell/Close as a PAPER fill priced from the most recent REAL trade.

    - buy: size = min(max_fill_fraction * balance, max_fill_sol)
    - sell: sells `amount_token` or all if None
    - close: alias for sell-all of that token
    Refusals are appended as type="refusal" rows with the reason. All rows are
    mode="PAPER". No network order exists anywhere in this module.
    """
    cfg = paper_settings_from(settings)
    if action == "close":
        action = "sell"
        amount_token = None  # close = full position

    allowed, reason, ctx = check_gates(
        action, wallet, token_mint,
        events=events, ledger_path=ledger_path, settings=cfg, data_dir=data_dir,
    )
    if not allowed:
        row = append_record(ledger_path, {
            "type": "refusal",
            "action": action,
            "wallet": wallet,
            "token_mint": token_mint,
            "reason": reason,
            "context": ctx,
            "note": note,
            "day": _utc_day(),
        })
        return {"ok": False, "reason": reason, "record": row}

    state = paper_state(ledger_path, cfg)
    price = ctx["price"]
    px = float(price["price_sol_per_token"])
    ts = _now_iso()
    day = _utc_day()

    if action == "buy":
        size_sol = paper_buy_size_sol(state["balance_sol"], cfg)
        qty = size_sol / px if px > 0 else 0.0
        row = append_record(ledger_path, {
            "type": "fill",
            "side": "buy",
            "wallet": wallet,
            "token_mint": token_mint,
            "amount_sol": size_sol,
            "amount_token": qty,
            "price_sol_per_token": px,
            "price_source_signature": price["source_signature"],
            "price_source_block_time": price.get("source_block_time"),
            "day": day,
            "timestamp": ts,
            "note": note or "paper-copy of watched wallet entry",
        })
        return {"ok": True, "fill": row}

    # sell (open position only)
    pos = state["open_positions"].get(token_mint)
    if not pos or pos["qty"] <= 1e-12:
        row = append_record(ledger_path, {
            "type": "refusal",
            "action": "sell",
            "wallet": wallet,
            "token_mint": token_mint,
            "reason": "no_open_position",
            "context": {"token_mint": token_mint},
            "note": note,
            "day": day,
        })
        return {"ok": False, "reason": "no_open_position", "record": row}

    qty = pos["qty"] if amount_token is None else min(float(amount_token), pos["qty"])
    proceeds = qty * px
    frac = min(1.0, qty / pos["qty"]) if pos["qty"] > 0 else 0.0
    cost = pos["cost_sol"] * frac
    realized_delta = proceeds - cost
    row = append_record(ledger_path, {
        "type": "fill",
        "side": "sell",
        "wallet": wallet,
        "token_mint": token_mint,
        "amount_sol": proceeds,
        "amount_token": qty,
        "price_sol_per_token": px,
        "price_source_signature": price["source_signature"],
        "price_source_block_time": price.get("source_block_time"),
        "realized_delta_sol": round(realized_delta, 9),
        "cost_basis_sol": round(cost, 9),
        "day": day,
        "timestamp": ts,
        "note": note or "paper close",
    })
    return {"ok": True, "fill": row, "realized_delta_sol": round(realized_delta, 9)}


def write_receipt(fills: list[dict[str, Any]], out_dir: Path) -> Path:
    """Settle/receipt evidence file citing price-source tx signatures (LESSONS #5)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    path = out_dir / f"paper_receipt_{ts}.json"
    path.write_text(json.dumps({
        "mode": "PAPER",
        "generated_at_utc": ts,
        "fills": fills,
        "price_source_signatures": sorted({f.get("price_source_signature") or "" for f in fills if f.get("price_source_signature")}),
        "observe_only": True,
    }, indent=2), encoding="utf-8")
    return path
