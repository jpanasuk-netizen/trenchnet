"""Redact secrets from strings/exceptions/logs. Never print key material."""
from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = (
    "TRENCHNET_WALLET_KEY",
    "HELIUS_API_KEY",
    "BIRDEYE_API_KEY",
    "TYPESAFE_API_KEY",
    "FCC_API_KEY",
    "PUMPFUN_JWT",
    "private_key",
    "secret_key",
    "secretKey",
    "seed",
)

# long base58-ish blobs (32+ chars of base58 alphabet)
_B58 = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{40,}\b")
_HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")
_JSON_BYTE_ARR = re.compile(r"\[\s*\d{1,3}\s*(,\s*\d{1,3}\s*){20,}\]")


def redact_text(text: str, *, extra: list[str] | None = None) -> str:
    if not text:
        return text
    out = str(text)
    for k in _SECRET_KEYS:
        out = re.sub(rf"({re.escape(k)}\s*[=:]\s*)\S+", r"\1[REDACTED]", out, flags=re.I)
    for e in extra or []:
        if e and len(e) >= 8:
            out = out.replace(e, "[REDACTED]")
    out = _JSON_BYTE_ARR.sub("[REDACTED_BYTE_ARRAY]", out)
    out = _HEX64.sub("[REDACTED_HEX]", out)
    out = _B58.sub("[REDACTED_B58]", out)
    return out


def redact_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {redact_text(str(exc))}"


def scrub_dict(d: dict[str, Any]) -> dict[str, Any]:
    bad = {"secret", "private_key", "secret_key", "seed", "keypair", "TRENCHNET_WALLET_KEY", "secretKey"}
    out = {}
    for k, v in d.items():
        if k in bad or any(b in k.lower() for b in ("secret", "private", "seed")):
            out[k] = "[REDACTED]"
        elif isinstance(v, dict):
            out[k] = scrub_dict(v)
        elif isinstance(v, str):
            out[k] = redact_text(v)
        else:
            out[k] = v
    return out
