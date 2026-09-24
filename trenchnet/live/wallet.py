"""Encrypted local LIVE wallet. NEVER log/print/return the secret key."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Path outside repo
def wallet_path() -> Path:
    local = os.environ.get("LOCALAPPDATA") or os.environ.get("HOME") or str(Path.home())
    return Path(local) / "trenchnet" / "live_wallet.bin"


def _dpapi_protect(data: bytes) -> bytes:
    """Windows DPAPI user-bound encrypt. Falls back to NaCl secretbox with machine path salt only for tests."""
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
    # non-windows test fallback: not for production funds
    from nacl import secret, utils
    from nacl.encoding import RawEncoder
    key = (os.environ.get("TRENCHNET_TEST_WALLET_KEY") or "test-only-not-for-mainnet!!!!").encode()[:32].ljust(32, b"\0")
    box = secret.SecretBox(key)
    return box.encrypt(data)


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
    box = secret.SecretBox(key)
    return box.decrypt(data)


def generate_keypair(path: Path | None = None) -> dict[str, Any]:
    """Create a fresh keypair, store encrypted, return PUBLIC fields only."""
    from solders.keypair import Keypair

    kp = Keypair()
    secret = bytes(kp)  # 64-byte secret key
    pubkey = str(kp.pubkey())
    payload = {
        "version": 1,
        "pubkey": pubkey,
        "secret": list(secret),  # only inside encrypted blob
        "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "warn": "Dedicated trading wallet only — never use main MetaMask/Coinbase seed",
    }
    raw = json.dumps(payload).encode("utf-8")
    enc = _dpapi_protect(raw)
    dest = path or wallet_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(enc)
    # wipe locals
    del secret, raw, payload
    return {
        "ok": True,
        "pubkey": pubkey,
        "path": str(dest),
        "warning": "Fund ONLY what you can lose. Never use your main wallet.",
        # NEVER include secret
    }


def import_secret_bytes(secret64: bytes, path: Path | None = None) -> dict[str, Any]:
    """Import from 64-byte secret. secret64 must not be logged by caller."""
    from solders.keypair import Keypair

    if len(secret64) not in (64, 32):
        return {"ok": False, "error": "secret must be 32 or 64 bytes"}
    kp = Keypair.from_bytes(secret64) if len(secret64) == 64 else Keypair.from_seed(secret64)
    pubkey = str(kp.pubkey())
    payload = {
        "version": 1,
        "pubkey": pubkey,
        "secret": list(bytes(kp)),
        "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "imported": True,
    }
    enc = _dpapi_protect(json.dumps(payload).encode("utf-8"))
    dest = path or wallet_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(enc)
    return {"ok": True, "pubkey": pubkey, "path": str(dest), "warning": "Imported. Fund ONLY what you can lose."}


def _load_payload(path: Path | None = None) -> dict[str, Any] | None:
    dest = path or wallet_path()
    if not dest.is_file():
        return None
    raw = _dpapi_unprotect(dest.read_bytes())
    return json.loads(raw.decode("utf-8"))


def public_address(path: Path | None = None) -> str | None:
    pl = _load_payload(path)
    return (pl or {}).get("pubkey")


def wallet_exists(path: Path | None = None) -> bool:
    return (path or wallet_path()).is_file()


def load_keypair_for_signing(path: Path | None = None):
    """Internal only — callers must never print/log the key. Returns solders Keypair."""
    from solders.keypair import Keypair

    pl = _load_payload(path)
    if not pl or "secret" not in pl:
        raise FileNotFoundError("LIVE wallet missing")
    secret = bytes(pl["secret"])
    return Keypair.from_bytes(secret)


def public_info(path: Path | None = None) -> dict[str, Any]:
    """Safe for API/GUI — pubkey only, never secret."""
    dest = path or wallet_path()
    pub = public_address(dest)
    return {
        "exists": bool(pub),
        "pubkey": pub,
        "path_hint": "%LOCALAPPDATA%\\trenchnet\\live_wallet.bin",
        "qr_fund_uri": f"solana:{pub}" if pub else None,
        "warning": "Never use main MetaMask/Coinbase wallet. Fund only what you can lose.",
    }
