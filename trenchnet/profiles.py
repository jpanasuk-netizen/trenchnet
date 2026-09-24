
"""Build roster profiles: code metrics + LLM/template narrative."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trenchnet.llm_fcc import FCCWriter, PROFILE_SYSTEM, template_profile
from trenchnet.models import TradeEvent
from trenchnet.pnl import compute_wallet_metrics


def order_metrics(metrics_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        metrics_list,
        key=lambda m: (-float(m.get("realized_pnl_sol") or 0.0), -int(m.get("trade_count") or 0), m.get("wallet") or ""),
    )


def build_profiles(
    roster_wallets: list[dict[str, Any]],
    events: list[TradeEvent],
    writer: FCCWriter,
    out_dir: Path,
) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    profiles: list[dict[str, Any]] = []
    for w in roster_wallets:
        addr = w["address"]
        label = w.get("label") or addr[:8]
        m = compute_wallet_metrics(addr, label, events).to_dict()
        m["source_url"] = w.get("source_url")
        m["source_name"] = w.get("source_name")
        user_payload = {
            "metrics": m,
            "instructions": "Write the profile now. Cite only metrics.cited_signatures.",
        }
        text = writer.complete(PROFILE_SYSTEM, json.dumps(user_payload, ensure_ascii=False))
        if not text.strip():
            text = template_profile(m)
            writer_mode = "template_fallback"
        else:
            writer_mode = writer.mode
        prof = {
            "wallet": addr,
            "label": label,
            "metrics": m,
            "profile_text": text,
            "writer_mode": writer_mode,
            "observe_only": True,
        }
        profiles.append(prof)
        (out_dir / f"{addr}.json").write_text(json.dumps(prof, indent=2), encoding="utf-8")
        (out_dir / f"{addr}.md").write_text(
            f"# Profile: {label}\n\nWallet: `{addr}`\n\nWriter: {writer_mode}\n\n{text}\n",
            encoding="utf-8",
        )
    ordered = order_metrics([p["metrics"] for p in profiles])
    # reorder profiles to match
    by_w = {p["wallet"]: p for p in profiles}
    profiles_ordered = [by_w[m["wallet"]] for m in ordered if m["wallet"] in by_w]
    (out_dir / "roster_ordered.json").write_text(
        json.dumps({"ordering": "realized_pnl_sol desc, trade_count desc, address asc", "profiles": profiles_ordered}, indent=2),
        encoding="utf-8",
    )
    return profiles_ordered
