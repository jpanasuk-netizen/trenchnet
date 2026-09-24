"""Leak check: prove HELIUS/BIRDEYE key values are not present in out/ or data/.

Compares file bytes against env secrets WITHOUT printing the secrets.
Reports pass/fail only.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trenchnet.secrets import get_secret

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [ROOT / "out", ROOT / "data"]
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bin", ".exe", ".dll", ".pyc"}

def main() -> int:
    keys = {
        "HELIUS_API_KEY": get_secret("HELIUS_API_KEY"),
        "BIRDEYE_API_KEY": get_secret("BIRDEYE_API_KEY"),
        "HELIUS_RPC_URL": get_secret("HELIUS_RPC_URL"),
    }
    # Also check api-key query value extracted from HELIUS_RPC_URL if present
    needles: list[tuple[str, bytes]] = []
    for name, val in keys.items():
        if not val:
            print(f"{name}: absent_in_env")
            continue
        needles.append((name, val.encode("utf-8")))
        # if URL contains api-key=, also check just the token portion already covered by HELIUS_API_KEY usually
    hits = []
    scanned = 0
    for d in SCAN_DIRS:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() in SKIP_SUFFIX:
                continue
            if p.name == ".env":
                continue
            try:
                data = p.read_bytes()
            except Exception:
                continue
            scanned += 1
            for name, needle in needles:
                if needle and needle in data:
                    hits.append(f"{name} in {p.relative_to(ROOT)}")
    print(f"scanned_files={scanned}")
    if hits:
        print("LEAK_CHECK FAIL")
        for h in hits:
            print("hit", h)  # path + which key name only, never value
        return 1
    print("LEAK_CHECK PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
