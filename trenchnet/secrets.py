"""Load secrets from env or known local .env files. Never print values."""

from __future__ import annotations

import os
from pathlib import Path

HERMES_ENV = Path(os.environ.get(
    "HERMES_ENV_PATH",
    r"C:\Users\jpana\AppData\Local\hermes\.env",
))
LOCAL_ENV = Path(__file__).resolve().parents[1] / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip().lstrip("\ufeff")
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def get_secret(name: str) -> str | None:
    """Return secret value if present; never log it."""
    raw = os.environ.get(name)
    if raw and raw.strip():
        return raw.strip()
    for path in (LOCAL_ENV, HERMES_ENV):
        val = _parse_env_file(path).get(name)
        if val and val.strip():
            # inject into process env for SDKs that read os.environ
            os.environ[name] = val.strip()
            return val.strip()
    return None


def secret_present(name: str) -> bool:
    return bool(get_secret(name))
