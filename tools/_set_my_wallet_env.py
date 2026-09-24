"""Append/update MY_WALLET_ADDRESS in local .env. Never prints the value."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
KEY = "MY_WALLET_ADDRESS"

def main() -> int:
    val = (os.environ.get(KEY) or "").strip()
    if not val:
        # optional: read from first CLI arg (still not printed)
        if len(sys.argv) > 1:
            val = sys.argv[1].strip()
    if not val or len(val) < 32:
        print("MISSING_OR_SHORT")
        return 2
    lines = []
    if ENV.exists():
        lines = ENV.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    out = []
    found = False
    for line in lines:
        if line.strip().startswith(KEY + "=") or line.strip().startswith(KEY + " ="):
            out.append(f"{KEY}={val}")
            found = True
        else:
            out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(f"# Public Solana address for read-only My Wallet card (never commit)")
        out.append(f"{KEY}={val}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("UPDATED" if found else "APPENDED")
    print("MASKED", val[:4] + "…" + val[-4:])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
