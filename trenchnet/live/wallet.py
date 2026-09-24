"""LIVE wallet helpers.

Private key loads at runtime ONLY from .env TRENCHNET_WALLET_KEY (Jeremy pastes it).
Accepts Phantom/MetaMask base58 OR Solana CLI JSON byte array.
NEVER log/print/return the secret. Failures use redacted errors.
Agents must not call load_keypair_from_env() during automation.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from trenchnet.live.redaction import redact_exc, redact_text


def wallet_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or str(Path.home())
    return Path(local) / "trenchnet" / "live_wallet.bin"


def mask_address(addr: str | None) -> str | None:
    if not addr or len(addr) < 8:
        return None
    return f"{addr[:4]}…{addr[-4:]}"


def env_key_configured() -> bool:
    """True if TRENCHNET_WALLET_KEY is present and non-empty. Does not validate format."""
    from trenchnet.secrets import get_secret
    raw = get_secret("TRENCHNET_WALLET_KEY")
    return bool(raw and raw.strip())


def _parse_secret_material(raw: str):
    """Parse base58 string or JSON byte array into bytes. Raises ValueError without echoing value."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("TRENCHNET_WALLET_KEY is empty")
    # JSON byte array (Solana CLI)
    if s.startswith("["):
        try:
            arr = json.loads(s)
        except Exception:
            raise ValueError("TRENCHNET_WALLET_KEY JSON byte array is malformed") from None
        if not isinstance(arr, list) or not arr:
            raise ValueError("TRENCHNET_WALLET_KEY JSON byte array is malformed")
        try:
            data = bytes(int(x) for x in arr)
        except Exception:
            raise ValueError("TRENCHNET_WALLET_KEY JSON byte array has non-integer entries") from None
        if len(data) not in (32, 64):
            raise ValueError("TRENCHNET_WALLET_KEY JSON byte array must be 32 or 64 bytes")
        return data
    # base58 secret (Phantom / MetaMask export)
    try:
        from solders.keypair import Keypair
        # solders accepts base58 via from_base58_string on older; use base58 lib if needed
        try:
            kp = Keypair.from_base58_string(s)
            return bytes(kp)
        except Exception:
            import base58
            data = base58.b58decode(s)
            if len(data) not in (32, 64):
                raise ValueError("decoded length not 32 or 64")
            return data
    except ValueError:
        raise
    except Exception:
        raise ValueError(
            "TRENCHNET_WALLET_KEY must be base58 (Phantom/MetaMask) or a JSON byte array (Solana CLI); value not shown"
        ) from None


def load_keypair_from_env():
    """Internal — load Keypair from TRENCHNET_WALLET_KEY. NEVER log the key.

    Automation/agents: do not call this. Dry-run uses public MY_WALLET_ADDRESS only.
    """
    from solders.keypair import Keypair
    from trenchnet.secrets import get_secret

    raw = get_secret("TRENCHNET_WALLET_KEY")
    if not raw:
        raise FileNotFoundError("TRENCHNET_WALLET_KEY not set in .env")
    try:
        data = _parse_secret_material(raw)
        if len(data) == 64:
            return Keypair.from_bytes(data)
        return Keypair.from_seed(data)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"TRENCHNET_WALLET_KEY could not be loaded: {redact_exc(exc)}") from None


def public_address_from_env() -> str | None:
    """Derive public address from env key without exposing secret. Returns None if unset/malformed."""
    if not env_key_configured():
        return None
    try:
        kp = load_keypair_from_env()
        pub = str(kp.pubkey())
        del kp
        return pub
    except Exception:
        return None


def public_address_masked() -> str | None:
    return mask_address(public_address_from_env_or_store())


# ---- optional DPAPI store (legacy generate/import) ----

def _dpapi_protect(data: bytes) -> bytes:
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        def _blob(b: bytes) -> DATA_BLOB:
            blob = DATA_BLOB()
            blob.cbData = len(b)
            blob.pbData = ctypes.cast(ctypes.create_string_buffer(b, len(b)), ctypes.POINTER(ctypes.c_char))
            return blob

        infile = _blob(data)
        outfile = DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(infile), "trenchnet-live", None, None, None, 0, ctypes.byref(outfile)):
            raise OSError("CryptProtectData failed")
        try:
            return ctypes.string_at(outfile.pbData, outfile.cbData)
        finally:
            kernel32.LocalFree(outfile.pbData)
    from nacl import secret
    key = (os.environ.get("TRENCHNET_TEST_WALLET_KEY") or "test-only-not-for-mainnet!!!!").encode()[:32].ljust(32, b"\0")
    return secret.SecretBox(key).encrypt(data)


def _dpapi_unprotect(data: bytes) -> bytes:
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        def _blob(b: bytes) -> DATA_BLOB:
            blob = DATA_BLOB()
            blob.cbData = len(b)
            blob.pbData = ctypes.cast(ctypes.create_string_buffer(b, len(b)), ctypes.POINTER(ctypes.c_char))
            return blob

        infile = _blob(data)
        outfile = DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(infile), None, None, None, None, 0, ctypes.byref(outfile)):
            raise OSError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(outfile.pbData, outfile.cbData)
        finally:
            kernel32.LocalFree(outfile.pbData)
    from nacl import secret
    key = (os.environ.get("TRENCHNET_TEST_WALLET_KEY") or "test-only-not-for-mainnet!!!!").encode()[:32].ljust(32, b"\0")
    return secret.SecretBox(key).decrypt(data)


def generate_keypair(path: Path | None = None) -> dict[str, Any]:
    from solders.keypair import Keypair
    kp = Keypair()
    secret = bytes(kp)
    pubkey = str(kp.pubkey())
    payload = {"version": 1, "pubkey": pubkey, "secret": list(secret), "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00","Z")}
    enc = _dpapi_protect(json.dumps(payload).encode("utf-8"))
    dest = path or wallet_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(enc)
    del secret, payload
    return {"ok": True, "pubkey": pubkey, "pubkey_masked": mask_address(pubkey), "path": str(dest), "warning": "Prefer TRENCHNET_WALLET_KEY in .env for a burner wallet. Fund ONLY what you can lose."}


def import_secret_bytes(secret64: bytes, path: Path | None = None) -> dict[str, Any]:
    from solders.keypair import Keypair
    if len(secret64) not in (64, 32):
        return {"ok": False, "error": "secret must be 32 or 64 bytes"}
    kp = Keypair.from_bytes(secret64) if len(secret64) == 64 else Keypair.from_seed(secret64)
    pubkey = str(kp.pubkey())
    payload = {"version": 1, "pubkey": pubkey, "secret": list(bytes(kp)), "imported": True}
    enc = _dpapi_protect(json.dumps(payload).encode("utf-8"))
    dest = path or wallet_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(enc)
    return {"ok": True, "pubkey": pubkey, "pubkey_masked": mask_address(pubkey), "path": str(dest)}


def _load_store_payload(path: Path | None = None) -> dict[str, Any] | None:
    dest = path or wallet_path()
    if not dest.is_file():
        return None
    raw = _dpapi_unprotect(dest.read_bytes())
    return json.loads(raw.decode("utf-8"))


def public_address(path: Path | None = None) -> str | None:
    """Prefer env-derived pubkey; fall back to DPAPI store pubkey."""
    return public_address_from_env_or_store(path)


def public_address_from_env_or_store(path: Path | None = None) -> str | None:
    env_pub = public_address_from_env()
    if env_pub:
        return env_pub
    pl = _load_store_payload(path)
    return (pl or {}).get("pubkey")


def wallet_exists(path: Path | None = None) -> bool:
    return env_key_configured() or (path or wallet_path()).is_file()


def load_keypair_for_signing(path: Path | None = None):
    """Prefer env key; else DPAPI store. NEVER print. Agents must not call for dry-run."""
    if env_key_configured():
        return load_keypair_from_env()
    from solders.keypair import Keypair
    pl = _load_store_payload(path)
    if not pl or "secret" not in pl:
        raise FileNotFoundError("LIVE wallet missing (set TRENCHNET_WALLET_KEY in .env)")
    return Keypair.from_bytes(bytes(pl["secret"]))


def public_info(path: Path | None = None) -> dict[str, Any]:
    pub = public_address_from_env_or_store(path)
    return {
        "exists": bool(pub),
        "pubkey": pub,
        "pubkey_masked": mask_address(pub),
        "source": "env:TRENCHNET_WALLET_KEY" if env_key_configured() else ("dpapi_store" if (path or wallet_path()).is_file() else None),
        "path_hint": "%LOCALAPPDATA%\\trenchnet\\live_wallet.bin (legacy) or .env TRENCHNET_WALLET_KEY",
        "qr_fund_uri": f"solana:{pub}" if pub else None,
        "warning": "Use a fresh burner wallet. Never paste a main-wallet seed. Key never shown in UI.",
        "recommend_burner": True,
    }
