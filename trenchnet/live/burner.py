"""Create a fresh burner Solana keypair into local .env (never overwrite).

Secret is written only to .env + gitignored wallet-backup file.
Public address may be shown (needed for funding). Secret never logged/returned by API.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from trenchnet.config_load import ROOT
from trenchnet.live.redaction import redact_text
from trenchnet.live.wallet import mask_address

ENV_PATH = ROOT / ".env"
BACKUP_DIR = ROOT / "trenchnet" / "wallet-backup"
KEY_NAME = "TRENCHNET_WALLET_KEY"

_B58_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        out.append(_B58_ALPHABET[r])
    # leading zeros
    for b in data:
        if b == 0:
            out.append(_B58_ALPHABET[0])
        else:
            break
    return out[::-1].decode("ascii")



def _env_has_key(env_path: Path = ENV_PATH) -> bool:
    if not env_path.is_file():
        return False
    for line in env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == KEY_NAME and v.strip().strip('"').strip("'"):
            return True
    return False


def _upsert_env_key(value: str, env_path: Path = ENV_PATH) -> str:
    """Write KEY=value. Returns 'appended' or 'updated'. Caller must refuse overwrite of non-empty."""
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    out: list[str] = []
    found = False
    for line in lines:
        raw = line.strip()
        if raw.startswith(KEY_NAME + "=") or raw.startswith(KEY_NAME + " ="):
            out.append(f"{KEY_NAME}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append("# LIVE burner wallet secret — never commit. Prefer `python -m trenchnet.cli new-wallet`.")
        out.append(f"{KEY_NAME}={value}")
        action = "appended"
    else:
        action = "updated"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return action


def create_burner_wallet(
    *,
    env_path: Path | None = None,
    backup_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate keypair; write base58 secret to .env; backup file; return PUBLIC fields only.

    Refuses if TRENCHNET_WALLET_KEY already has a value (unless force=True — not exposed to CLI/UI).
    """
    from solders.keypair import Keypair

    env_path = env_path or ENV_PATH
    backup_dir = backup_dir or BACKUP_DIR

    if not force and _env_has_key(env_path):
        return {
            "ok": False,
            "error": f"{KEY_NAME} already set in .env — refuse to overwrite. Clear it manually first if you intend a new burner.",
            "pubkey": None,
        }

    kp = Keypair()
    pubkey = str(kp.pubkey())
    # base58 secret export (Phantom-compatible)
    # Encode 64-byte secret as base58 without optional deps (Phantom-compatible).
    secret_b58 = _b58encode(bytes(kp))

    action = _upsert_env_key(secret_b58, env_path)

    backup_dir.mkdir(parents=True, exist_ok=True)
    # ensure a .gitignore inside backup dir too
    gi = backup_dir / ".gitignore"
    if not gi.is_file():
        gi.write_text("*\n!.gitignore\n", encoding="utf-8")
    fname = f"burner-{pubkey[:4]}…{pubkey[-4:]}.txt"
    # Windows-safe filename (ellipsis ok); also provide ascii fallback
    safe = f"burner-{pubkey[:4]}...{pubkey[-4:]}.txt"
    bpath = backup_dir / safe
    bpath.write_text(
        "# TRENCHNET burner wallet backup — NEVER share or commit\n"
        f"pubkey={pubkey}\n"
        f"{KEY_NAME}=<redacted in this comment; see file body below>\n"
        f"{secret_b58}\n",
        encoding="utf-8",
    )
    # wipe local secret ref
    del secret_b58, kp

    return {
        "ok": True,
        "pubkey": pubkey,
        "pubkey_masked": mask_address(pubkey),
        "env_action": action,
        "backup_path": str(bpath),
        "backup_hint": "trenchnet/wallet-backup/ (gitignored)",
        "warning": "Fund ONLY what you can lose. Import backup into Phantom if you want a second copy. Never share the key.",
        "qr_fund_uri": f"solana:{pubkey}",
        # NEVER include secret
    }


def api_create_burner() -> dict[str, Any]:
    """API-safe wrapper: never returns secret fields."""
    res = create_burner_wallet()
    # belt-and-suspenders scrub
    blob = str(res)
    if "secret" in blob.lower() and "TRENCHNET_WALLET_KEY=" in blob:
        return {"ok": False, "error": "refused_to_return_unsafe_payload"}
    return {k: v for k, v in res.items() if k not in ("secret", "private_key", "secret_key")}
