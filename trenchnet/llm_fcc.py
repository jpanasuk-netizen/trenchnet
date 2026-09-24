"""FCC writer — primary: Anthropic-style POST {base}/messages; fallback: labeled template.

Endpoint proven by out/fcc_probe_results.json:
  POST http://127.0.0.1:8082/v1/messages  (Authorization: Bearer <FCC_API_KEY>)
  -> HTTP 200, body {"content": [{"type": "thinking", ...}, {"type": "text", "text": "..."}]}
OpenAI-style /chat/completions stays HTTP 404 on this server, so it is NOT used.
Never prints or logs the API key.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from trenchnet.secrets import get_secret


class FCCWriter:
    def __init__(self, base_url: str, model: str, timeout: float = 90.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.mode = "fcc"
        self.last_error: str | None = None

    # ------------------------------------------------------------------ auth
    def _bearer_headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _xapi_headers(self, key: str) -> dict[str, str]:
        return {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------- discovery
    def available(self) -> bool:
        """Cheap /models probe (GET). Key never logged."""
        key = get_secret("FCC_API_KEY")
        if not key:
            self.last_error = "FCC_API_KEY missing"
            return False
        try:
            r = httpx.get(
                f"{self.base_url}/models",
                headers=self._bearer_headers(key),
                timeout=10.0,
            )
            if r.status_code >= 400:
                self.last_error = f"FCC /models HTTP {r.status_code}"
                return False
            return True
        except Exception as exc:
            self.last_error = f"FCC unreachable: {exc}"
            return False

    # -------------------------------------------------------------- response
    @staticmethod
    def _text_from_messages_response(data: dict[str, Any]) -> str:
        """Join content blocks with type == 'text' (skip thinking blocks)."""
        blocks = data.get("content") or []
        parts: list[str] = []
        if isinstance(blocks, list):
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = b.get("text")
                    if t:
                        parts.append(str(t))
        return "\n".join(parts)

    # ------------------------------------------------------------ completion
    def complete(self, system: str, user: str, max_tokens: int = 1200) -> str:
        """POST {base}/messages Anthropic-style. Empty string -> use template."""
        key = get_secret("FCC_API_KEY")
        if not key:
            self.mode = "template_fallback"
            self.last_error = "FCC_API_KEY missing"
            return ""
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # Attempt 1: Authorization Bearer. Attempt 2: x-api-key (Anthropic style).
        attempts: list[tuple[str, dict[str, str]]] = [
            ("bearer", self._bearer_headers(key)),
            ("x-api-key", self._xapi_headers(key)),
        ]
        last_status: int | None = None
        for label, headers in attempts:
            try:
                r = httpx.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                last_status = r.status_code
                if r.status_code >= 400:
                    self.mode = "template_fallback"
                    self.last_error = f"FCC /messages HTTP {r.status_code} ({label})"
                    # 404/401/403 -> try the next auth style; otherwise stop.
                    if r.status_code in (400, 401, 403, 404, 405):
                        continue
                    return ""
                try:
                    data = r.json()
                except Exception:
                    self.mode = "template_fallback"
                    self.last_error = f"FCC /messages non-JSON response ({label})"
                    return ""
                text = self._text_from_messages_response(data)
                if not text.strip():
                    self.mode = "template_fallback"
                    self.last_error = f"FCC /messages empty text ({label})"
                    return ""
                self.mode = "fcc"
                self.last_error = None
                return text
            except Exception as exc:
                self.mode = "template_fallback"
                self.last_error = f"FCC /messages error ({label}): {exc}"
                continue
        _ = last_status
        return ""


def template_profile(metrics: dict[str, Any]) -> str:
    cites = ", ".join((metrics.get("cited_signatures") or [])[:5]) or "(none in sample)"
    return (
        "[TEMPLATE WRITER - FCC unavailable or failed]\n"
        f"Wallet {metrics.get('label')} ({metrics.get('wallet')}).\n"
        f"Trading style (code metrics only): buys={metrics.get('buy_count')}, "
        f"sells={metrics.get('sell_count')}, realized_pnl_sol={metrics.get('realized_pnl_sol')}, "
        f"typical_buy_size_sol={metrics.get('typical_buy_size_sol')}, "
        f"median_hold_seconds={metrics.get('median_hold_seconds')}, "
        f"profit_concentration={metrics.get('profit_concentration')}, "
        f"history_flag={metrics.get('history_flag')}.\n"
        f"Evidence citations (tx signatures): {cites}.\n"
        "Behavior to watch: a buy much larger than typical_buy_size_sol deserves a look "
        "(observe-only; not an order).\n"
        "No motives inferred. Missing history flagged via history_flag.\n"
    )


def template_situation(payload: dict[str, Any]) -> str:
    return (
        "[TEMPLATE WRITER - FCC unavailable or failed]\n"
        "FACTS:\n"
        f"- Event snapshot: {json.dumps(payload.get('facts', {}), ensure_ascii=False)[:1500]}\n"
        "INTERPRETATION:\n"
        "- Code-only summary; LLM interpretation skipped because FCC was unavailable.\n"
        "MISSING:\n"
        "- Full off-sample history; any unpaid indexer fields; TypeSafe live judgment if dry-run.\n"
        "WHAT WOULD CHANGE THE READ NEXT:\n"
        "- New buy/sell with cited signature that breaks typical size or co-entry pattern.\n"
        "No motives. No price targets. Observe-only.\n"
    )


PROFILE_SYSTEM = (
    "You write observe-only trader profiles for Solana pump.fun wallets. "
    "Separate facts from interpretation. Cite only provided tx signatures. "
    "Never invent wallets, signatures, PnL, or motives. No price targets. "
    "No trading advice or orders. Flag missing/sparse history explicitly. "
    "Include: trading style, evidence for inclusion, behavior to watch "
    "(e.g. buy much larger than normal entry deserves a look)."
)

SITUATION_SYSTEM = (
    "You write observe-only situation reports. Sections: FACTS, INTERPRETATION, MISSING, "
    "WHAT WOULD CHANGE THE READ NEXT. No motives, no price targets, no orders. "
    "Cite only provided signatures. Partial sell = reduction; transfer is not a sale."
)
