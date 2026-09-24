"""Load YAML settings + roster."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def load_settings(path: Path | None = None) -> dict[str, Any]:
    p = path or (CONFIG_DIR / "settings.yaml")
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_roster(path: Path | None = None) -> dict[str, Any]:
    p = path or (CONFIG_DIR / "roster.yaml")
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
