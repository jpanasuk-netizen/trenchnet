"""Tests for the FCC /messages client — mocked HTTP, no network, no real key."""

from __future__ import annotations

import json

import httpx
import pytest

import trenchnet.llm_fcc as llm_fcc
from trenchnet.llm_fcc import FCCWriter, template_profile, template_situation

BASE = "http://127.0.0.1:8082/v1"
MODEL = "anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code"
KEY = "test-key-not-real"

OK_MESSAGES_BODY = {
    "id": "msg_test",
    "type": "message",
    "role": "assistant",
    "content": [
        {"type": "thinking", "thinking": "silent reasoning", "signature": ""},
        {"type": "text", "text": "OK PROFILE TEXT"},
    ],
    "model": MODEL,
}


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture()
def no_key(monkeypatch):
    monkeypatch.setattr(llm_fcc, "get_secret", lambda name: None)


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setattr(llm_fcc, "get_secret", lambda name: KEY)
    return monkeypatch


def test_messages_success_bearer(with_key, monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return FakeResponse(200, OK_MESSAGES_BODY)

    monkeypatch.setattr(httpx, "post", fake_post)
    w = FCCWriter(BASE, MODEL)
    out = w.complete("SYS", "USER")
    assert out == "OK PROFILE TEXT"  # thinking block skipped, text joined
    assert w.mode == "fcc"
    assert w.last_error is None
    assert len(calls) == 1  # bearer worked on first try
    c = calls[0]
    assert c["url"].endswith("/v1/messages")
    assert c["headers"]["Authorization"] == f"Bearer {KEY}"
    assert c["json"]["model"] == MODEL
    assert c["json"]["system"] == "SYS"
    assert c["json"]["messages"] == [{"role": "user", "content": "USER"}]
    assert "max_tokens" in c["json"]


def test_bearer_401_then_xapi_success(with_key, monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(headers)
        if "Authorization" in (headers or {}):
            return FakeResponse(401, {"detail": "nope"})
        assert headers.get("x-api-key") == KEY
        return FakeResponse(200, OK_MESSAGES_BODY)

    monkeypatch.setattr(httpx, "post", fake_post)
    w = FCCWriter(BASE, MODEL)
    out = w.complete("SYS", "USER")
    assert out == "OK PROFILE TEXT"
    assert w.mode == "fcc"
    assert len(calls) == 2


def test_messages_404_falls_back_to_template(with_key, monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return FakeResponse(404, {"detail": "Not Found"})

    monkeypatch.setattr(httpx, "post", fake_post)
    w = FCCWriter(BASE, MODEL)
    out = w.complete("SYS", "USER")
    assert out == ""
    assert w.mode == "template_fallback"
    assert "404" in (w.last_error or "")
    assert len(calls) == 2  # tried bearer then x-api-key
    # labeled fallback text mentions template
    prof = template_profile({"label": "L", "wallet": "W", "cited_signatures": []})
    assert "TEMPLATE WRITER" in prof


def test_missing_key_short_circuits(no_key):
    w = FCCWriter(BASE, MODEL)
    assert w.available() is False
    assert "FCC_API_KEY missing" in (w.last_error or "")
    out = w.complete("SYS", "USER")
    assert out == ""
    assert w.mode == "template_fallback"


def test_available_models_probe(with_key, monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url.endswith("/v1/models")
        assert headers["Authorization"] == f"Bearer {KEY}"
        return FakeResponse(200, {"data": [{"id": MODEL}]})

    monkeypatch.setattr(httpx, "get", fake_get)
    w = FCCWriter(BASE, MODEL)
    assert w.available() is True
    assert w.last_error is None


def test_available_models_500(with_key, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: FakeResponse(500))
    w = FCCWriter(BASE, MODEL)
    assert w.available() is False
    assert "500" in (w.last_error or "")


def test_network_error_falls_back(with_key, monkeypatch):
    def boom(url, headers=None, json=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", boom)
    w = FCCWriter(BASE, MODEL)
    out = w.complete("SYS", "USER")
    assert out == ""
    assert w.mode == "template_fallback"
    assert "error" in (w.last_error or "").lower()


def test_non_json_response_falls_back(with_key, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, headers=None, json=None, timeout=None: FakeResponse(200, None, text="oops"))
    w = FCCWriter(BASE, MODEL)
    out = w.complete("SYS", "USER")
    assert out == ""
    assert w.mode == "template_fallback"


def test_empty_text_falls_back(with_key, monkeypatch):
    body = {"content": [{"type": "thinking", "thinking": "only thoughts", "signature": ""}]}
    monkeypatch.setattr(httpx, "post", lambda url, headers=None, json=None, timeout=None: FakeResponse(200, body))
    w = FCCWriter(BASE, MODEL)
    out = w.complete("SYS", "USER")
    assert out == ""
    assert w.mode == "template_fallback"


def test_templates_labeled_and_json_safe():
    p = template_profile({"label": "Doji", "wallet": "5Zu", "cited_signatures": ["sig1"], "buy_count": 2})
    s = template_situation({"facts": {"a": 1}})
    assert json.dumps({"p": p, "s": s})  # serializable
    assert "[TEMPLATE WRITER" in p and "[TEMPLATE WRITER" in s
