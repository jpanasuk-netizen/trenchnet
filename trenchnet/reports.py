
"""Situation reports ? versioned, facts vs interpretation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trenchnet.llm_fcc import FCCWriter, SITUATION_SYSTEM, template_situation


def write_situation_report(
    writer: FCCWriter,
    facts: dict[str, Any],
    out_dir: Path,
    event_id: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"facts": facts, "event_id": event_id, "generated_at_utc": ts}
    text = writer.complete(SITUATION_SYSTEM, json.dumps(payload, ensure_ascii=False))
    mode = writer.mode
    if not text.strip():
        text = template_situation(payload)
        mode = "template_fallback"
    doc = {
        "event_id": event_id,
        "generated_at_utc": ts,
        "facts": facts,
        "report_text": text,
        "writer_mode": mode,
        "observe_only": True,
        "versioning_note": "New events create new versions; old reports stay attached to old evidence.",
    }
    base = out_dir / f"{event_id}_{ts.replace(':', '')}"
    base.with_suffix(".json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    base.with_suffix(".md").write_text(
        f"# Situation report `{event_id}`\n\nGenerated: {ts}\nWriter: {mode}\n\n{text}\n",
        encoding="utf-8",
    )
    # also write a stable latest pointer
    (out_dir / f"{event_id}_latest.md").write_text(
        f"# Situation report `{event_id}` (latest)\n\nGenerated: {ts}\nWriter: {mode}\n\n{text}\n",
        encoding="utf-8",
    )
    return doc
