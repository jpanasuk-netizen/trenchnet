"""Pass 9 follow-up: My Wallet read-only card + address never in git-tracked files."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_mywallet_module_masks_and_no_send():
    from trenchnet.mywallet import mask_address, fetch_my_wallet
    assert mask_address("ABCD1234WXYZ5678") == "ABCD…5678"
    # Source must not mention signing/send controls
    src = (ROOT / "trenchnet" / "mywallet.py").read_text(encoding="utf-8")
    assert "read-only" in src.lower() or "Read-only" in src
    assert "sign_transaction" not in src.lower()
    assert "private_key" not in src.lower()


def test_webui_has_mywallet_route():
    src = (ROOT / "trenchnet" / "webui.py").read_text(encoding="utf-8")
    assert "/api/mywallet" in src


def test_interactive_has_my_wallet_card():
    js = (ROOT / "out" / "assets" / "interactive.js").read_text(encoding="utf-8")
    assert "myWalletCard" in js
    assert "READ-ONLY" in js
    assert "loadMyWallet" in js
    assert "300000" in js  # 5 min refresh
    assert "no signing" in js.lower() or "no signing" in js


def test_env_example_documents_key_without_value():
    ex = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "MY_WALLET_ADDRESS=" in ex
    # example must not contain a real-looking 32+ char address assignment
    for line in ex.splitlines():
        if line.strip().startswith("MY_WALLET_ADDRESS="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            assert val == "" or val.startswith("#") or "your_" in val.lower() or "example" in val.lower()


def test_full_wallet_address_not_in_git_tracked_files():
    """If MY_WALLET_ADDRESS is set locally, it must not appear in any tracked file."""
    from trenchnet.secrets import get_secret

    addr = (get_secret("MY_WALLET_ADDRESS") or "").strip()
    if not addr or len(addr) < 32:
        pytest.skip("MY_WALLET_ADDRESS not configured in local .env")

    # Ensure .env itself is ignored
    ign = subprocess.run(
        ["git", "check-ignore", "-v", ".env"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert ign.returncode == 0, ".env must be gitignored"

    listed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    offenders = []
    for raw in listed:
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        path = ROOT / rel
        if not path.is_file():
            continue
        # skip binary-ish by extension
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bin", ".pdf"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if addr in text:
            offenders.append(rel)
    assert offenders == [], f"Full MY_WALLET_ADDRESS found in tracked files: {offenders}"


def test_api_payload_never_includes_full_address_when_configured():
    from trenchnet.mywallet import configured_address, fetch_my_wallet, mask_address
    import json

    addr = configured_address()
    doc = fetch_my_wallet()
    blob = json.dumps(doc)
    if addr:
        assert addr not in blob
        assert doc.get("masked_address") == mask_address(addr)
        assert doc.get("read_only") is True
    else:
        assert doc.get("configured") is False
