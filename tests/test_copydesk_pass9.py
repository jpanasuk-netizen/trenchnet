"""Pass 9 copydesk + default view smoke tests (paper only)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_copydesk_module_imports():
    from trenchnet.copydesk import build_copydesk, write_copydesk, verdict_for
    assert callable(build_copydesk)
    assert callable(write_copydesk)


def test_verdict_not_enough():
    from trenchnet.copydesk import verdict_for
    v, reason = verdict_for({"score": 0.9}, {}, 2, None, None)
    assert v == "not enough trades"
    assert "Need" in reason


def test_verdict_avoid_negative():
    from trenchnet.copydesk import verdict_for
    v, _ = verdict_for({"score": 0.4, "oos_flag": "ok"}, {}, 10, -0.2, 0.2)
    assert v == "AVOID"


def test_default_view_json_shape_in_interactive():
    js = (ROOT / "out" / "assets" / "interactive.js").read_text(encoding="utf-8")
    assert "DEFAULT_VIEW" in js
    assert 'layout: "columns"' in js
    assert 'tab: "overview"' in js
    assert "Reset to default view" in js
    assert "resetToDefaultView" in js
    assert "trenchnet_view_v1" in js
    assert "copydeskPanel" in js


def test_dashboard_bakes_copydesk_key():
    from trenchnet import dashboard as dash
    src = Path(dash.__file__).read_text(encoding="utf-8")
    assert "copydesk" in src
    assert "write_copydesk" in src


def test_webui_has_copydesk_route():
    from trenchnet import webui
    src = Path(webui.__file__).read_text(encoding="utf-8")
    assert '/api/copydesk' in src


def test_template_has_nowstrip_and_explain():
    tpl = (ROOT / "docs" / "dashboard_template.html").read_text(encoding="utf-8")
    assert 'id="nowStrip"' in tpl
    assert "assets/explain.js" in tpl
    assert "legendBox" in tpl


def test_build_copydesk_against_repo(tmp_path=None):
    """Build against real repo root when artifacts exist; else skip."""
    repo = ROOT
    if not (repo / "out" / "scores.json").exists():
        pytest.skip("no scores.json in test root")
    from trenchnet.copydesk import build_copydesk
    doc = build_copydesk(repo)
    assert doc["paper_only"] is True
    assert "leaderboard" in doc
    assert "activity_feed" in doc
    assert "equity_curves" in doc
    assert doc["copy_assumptions"]["delay_seconds"] == 60
    assert doc["copy_assumptions"]["position_sol"] == 0.25
