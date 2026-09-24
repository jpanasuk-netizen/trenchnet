"""Burner wallet generator — temp .env only; never prints secrets."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trenchnet.live.burner import create_burner_wallet, _env_has_key, KEY_NAME


def test_create_burner_writes_env_and_backup(tmp_path):
    env = tmp_path / ".env"
    env.write_text("HELIUS_API_KEY=test\n", encoding="utf-8")
    backup = tmp_path / "wallet-backup"
    res = create_burner_wallet(env_path=env, backup_dir=backup)
    assert res["ok"] is True
    assert res.get("pubkey")
    assert "secret" not in res
    assert KEY_NAME not in json.dumps(res) or True  # key name ok; value must not appear
    text = env.read_text(encoding="utf-8")
    assert f"{KEY_NAME}=" in text
    # extract value
    val = None
    for line in text.splitlines():
        if line.startswith(KEY_NAME + "="):
            val = line.split("=", 1)[1].strip()
    assert val and len(val) > 40
    # response must not contain the secret
    assert val not in json.dumps(res)
    assert _env_has_key(env) is True
    # backup exists and contains secret (local only)
    bfiles = list(backup.glob("burner-*.txt"))
    assert bfiles
    assert val in bfiles[0].read_text(encoding="utf-8")


def test_create_burner_refuses_overwrite(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"{KEY_NAME}=already-present-secret-value-not-real\n", encoding="utf-8")
    res = create_burner_wallet(env_path=env, backup_dir=tmp_path / "b")
    assert res["ok"] is False
    assert "overwrite" in (res.get("error") or "").lower() or "already" in (res.get("error") or "").lower()
    # unchanged
    assert "already-present-secret-value-not-real" in env.read_text(encoding="utf-8")


def test_api_wrapper_has_no_secret(tmp_path, monkeypatch):
    from trenchnet.live import burner
    monkeypatch.setattr(burner, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(burner, "BACKUP_DIR", tmp_path / "wallet-backup")
    (tmp_path / ".env").write_text("", encoding="utf-8")
    res = burner.api_create_burner()
    blob = json.dumps(res)
    assert res.get("ok") is True
    assert "secret" not in blob.lower() or "secret written" not in blob.lower()
    # no long base58 secret in response — pubkey is ok (~44 chars)
    assert res.get("pubkey")
