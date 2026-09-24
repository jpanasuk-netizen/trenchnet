
"""Token timeline view ? static markdown/HTML per token."""

from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from trenchnet.models import TradeEvent


def build_token_timelines(events: list[TradeEvent], out_dir: Path, label_map: dict[str, str] | None = None) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    label_map = label_map or {}
    by_tok: dict[str, list[TradeEvent]] = defaultdict(list)
    for e in events:
        if e.side in ("buy", "sell"):
            by_tok[e.token_mint].append(e)
    written: list[str] = []
    for tok, lst in sorted(by_tok.items(), key=lambda kv: -len(kv[1])):
        lst_sorted = sorted(lst, key=lambda e: (e.block_time or 0, e.signature))
        lines = [
            f"# Token timeline: `{tok}`",
            "",
            "Observe-only. Timing patterns are not ownership claims.",
            "",
            "| time_unix | wallet | label | side | size_sol | size_token | signature |",
            "|---|---|---|---|---|---|---|",
        ]
        html_rows = []
        for e in lst_sorted:
            lab = label_map.get(e.wallet, e.wallet[:8])
            lines.append(
                f"| {e.block_time} | `{e.wallet}` | {lab} | {e.side} | {e.amount_sol} | {e.amount_token} | `{e.signature}` |"
            )
            html_rows.append(
                "<tr>"
                f"<td>{html.escape(str(e.block_time))}</td>"
                f"<td><code>{html.escape(e.wallet)}</code></td>"
                f"<td>{html.escape(lab)}</td>"
                f"<td>{html.escape(e.side)}</td>"
                f"<td>{html.escape(str(e.amount_sol))}</td>"
                f"<td>{html.escape(str(e.amount_token))}</td>"
                f"<td><code>{html.escape(e.signature)}</code></td>"
                "</tr>"
            )
        md_path = out_dir / f"{tok}.md"
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        html_doc = (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>Token timeline {html.escape(tok)}</title>"
            "<style>body{font-family:sans-serif} td,th{border:1px solid #ccc;padding:4px} table{border-collapse:collapse}</style>"
            "</head><body>"
            f"<h1>Token timeline <code>{html.escape(tok)}</code></h1>"
            "<p>Observe-only. Timing patterns are not ownership claims.</p>"
            "<table><thead><tr><th>time</th><th>wallet</th><th>label</th><th>side</th><th>sol</th><th>token</th><th>sig</th></tr></thead>"
            f"<tbody>{''.join(html_rows)}</tbody></table></body></html>"
        )
        (out_dir / f"{tok}.html").write_text(html_doc, encoding="utf-8")
        # compact json
        (out_dir / f"{tok}.json").write_text(
            json.dumps([e.to_dict() for e in lst_sorted], indent=2),
            encoding="utf-8",
        )
        written.append(tok)
        if len(written) >= 20:
            break
    (out_dir / "index.md").write_text(
        "# Token timelines\n\n" + "\n".join(f"- [`{t}`](./{t}.md) / [html](./{t}.html)" for t in written) + "\n",
        encoding="utf-8",
    )
    return written
