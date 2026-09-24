"""LIVE trades ledger (JSONL + CSV). Gitignored. Realized PnL from confirmed fills only."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trenchnet.config_load import ROOT
from trenchnet.live.redaction import scrub_dict

LEDGER_JSONL = ROOT / "data" / "live" / "trades.jsonl"
LEDGER_CSV = ROOT / "data" / "live" / "trades.csv"
OPEN_PATH = ROOT / "data" / "live" / "open_positions.json"

CSV_FIELDS = [
    "ts", "kind", "side", "token_mint", "signature", "sol_in", "sol_out", "fees_sol",
    "realized_pnl_sol", "mode", "ok", "reason", "route",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_trade(row: dict[str, Any]) -> None:
    row = scrub_dict(dict(row))
    row.setdefault("ts", _now())
    LEDGER_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    write_csv_row(row)


def write_csv_row(row: dict[str, Any]) -> None:
    LEDGER_CSV.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER_CSV.is_file()
    with LEDGER_CSV.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in CSV_FIELDS})


def iter_trades() -> list[dict[str, Any]]:
    if not LEDGER_JSONL.is_file():
        return []
    out = []
    for line in LEDGER_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def load_open_positions() -> list[dict[str, Any]]:
    if not OPEN_PATH.is_file():
        return []
    try:
        doc = json.loads(OPEN_PATH.read_text(encoding="utf-8"))
        return list(doc.get("positions") or [])
    except Exception:
        return []


def save_open_positions(positions: list[dict[str, Any]]) -> None:
    OPEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPEN_PATH.write_text(json.dumps({"positions": positions, "updated_at": _now()}, indent=2), encoding="utf-8")


def open_from_ledger() -> list[dict[str, Any]]:
    """Rebuild open positions from buy fills minus sells (confirmed only)."""
    open_map: dict[str, dict[str, Any]] = {}
    for t in iter_trades():
        if not t.get("ok") or t.get("mode") not in ("send", "live"):
            continue
        mint = t.get("token_mint")
        if not mint:
            continue
        if t.get("side") == "buy" and t.get("kind") in (None, "fill", "buy"):
            open_map[mint] = {
                "token_mint": mint,
                "entry_sol": float(t.get("sol_in") or t.get("sol_amount") or 0),
                "entry_ts": t.get("ts"),
                "entry_sig": t.get("signature"),
                "route": t.get("route"),
            }
        elif t.get("side") == "sell":
            open_map.pop(mint, None)
    return list(open_map.values())
