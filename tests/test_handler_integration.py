"""Integration tests for the /sanitize handler with gpt_sanitize mocked.

These exercise the full response shape and the interaction between
gpt_sanitize, enforce_redaction, compute_score, and the response builder,
without making live OpenAI / Supabase / Helius calls.

Run with:  python -m pytest tests/test_handler_integration.py -v
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "stub")
os.environ.setdefault("SUPABASE_URL", "http://stub.invalid")
os.environ.setdefault("SUPABASE_KEY", "stub")
os.environ.setdefault("HELIUS_API_KEY", "stub")
os.environ.setdefault("PAYMENT_WALLET", "stub")
os.environ.setdefault("TRIAL_QUOTA", "1000")
os.environ.setdefault("PAID_QUOTA", "10000")
os.environ.setdefault("REQUIRED_PAYMENT_USDC", "149")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    """Return a TestClient with TRIAL quota / audit / model calls stubbed."""
    async def fake_get_trial_count(wallet):
        return 0

    async def fake_increment_trial(wallet):
        return None

    async def fake_log_audit(*args, **kwargs):
        return None

    monkeypatch.setattr(main, "get_trial_count", fake_get_trial_count)
    monkeypatch.setattr(main, "increment_trial", fake_increment_trial)
    monkeypatch.setattr(main, "log_audit", fake_log_audit)
    return TestClient(main.app)


def _stub_gpt(monkeypatch, response: dict):
    async def fake_gpt_sanitize(text):
        return response
    monkeypatch.setattr(main, "gpt_sanitize", fake_gpt_sanitize)


def _post(client, text):
    resp = client.post(
        "/sanitize",
        json={"text": text, "tx_hash": "TRIAL", "wallet_address": "test-wallet"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_handler_model_already_correct(client, monkeypatch):
    """Model returned a perfectly-redacted cleaned_text → source=model."""
    _stub_gpt(monkeypatch, {
        "status": "success",
        "cleaned_text": "My email is [REDACTED]",
        "entities": [
            {"type": "email", "category": "PRIVATE", "redacted_text": "a@b.c"},
        ],
    })
    body = _post(client, "My email is a@b.c")
    d = body["data"]
    assert d["sanitized_content"] == "My email is [REDACTED]"
    assert d["redaction_source"] == "model"
    assert d["safety_score"] == 0.2
    assert d["risk_category"] == "PRIVATE"
    assert d["entities_removed"] is True
    assert "unmatched_entities" not in d


def test_handler_server_fixes_leak(client, monkeypatch):
    """Regression for v2.1: name in entities[] but not removed from cleaned_text."""
    _stub_gpt(monkeypatch, {
        "status": "success",
        "cleaned_text": "田中太郎、マイナンバー：[REDACTED]",  # name still present
        "entities": [
            {"type": "jp_my_number", "category": "PRIVATE", "redacted_text": "123456789012"},
            {"type": "jp_full_name", "category": "PRIVATE", "redacted_text": "田中太郎"},
        ],
    })
    body = _post(client, "田中太郎、マイナンバー：123456789012")
    d = body["data"]
    assert "田中太郎" not in d["sanitized_content"], d["sanitized_content"]
    assert "123456789012" not in d["sanitized_content"]
    assert d["redaction_source"] == "server"
    assert d["safety_score"] == 0.4  # 2 × PRIVATE
    assert d["risk_category"] == "PRIVATE"


def test_handler_fallback_full_redaction(client, monkeypatch):
    """When gpt_sanitize returns the failsafe shape, redaction_source reflects it."""
    failsafe = {
        "status": "success",
        "cleaned_text": "[REDACTED]",
        "entities": [
            {"type": "sanitizer_failsafe", "category": "CRITICAL", "redacted_text": "secret stuff"},
        ],
    }
    _stub_gpt(monkeypatch, failsafe)
    body = _post(client, "secret stuff")
    d = body["data"]
    assert d["sanitized_content"] == "[REDACTED]"
    assert d["redaction_source"] == "fallback_full_redaction"
    assert d["risk_category"] == "CRITICAL"


def test_handler_clean_input(client, monkeypatch):
    _stub_gpt(monkeypatch, {
        "status": "success",
        "cleaned_text": "Just a normal sentence.",
        "entities": [],
    })
    body = _post(client, "Just a normal sentence.")
    d = body["data"]
    assert d["sanitized_content"] == "Just a normal sentence."
    assert d["redaction_source"] == "model"
    assert d["safety_score"] == 0.0
    assert d["risk_category"] == "CLEAN"
    assert d["entities_removed"] is False
    assert d["entities"] == []


def test_handler_unmatched_entity_surfaces(client, monkeypatch):
    """Model claims to have redacted text that doesn't appear verbatim."""
    _stub_gpt(monkeypatch, {
        "status": "success",
        "cleaned_text": "My name is [REDACTED]",
        "entities": [
            # Wrong case; not present verbatim in input.
            {"type": "full_name", "category": "PRIVATE", "redacted_text": "john smith"},
        ],
    })
    body = _post(client, "My name is John Smith")
    d = body["data"]
    assert "unmatched_entities" in d
    assert len(d["unmatched_entities"]) == 1
    assert d["unmatched_entities"][0]["redacted_text"] == "john smith"
    # Server couldn't enforce, but score still reflects detection.
    assert d["safety_score"] == 0.2


def test_handler_repeated_value_redacted_everywhere(client, monkeypatch):
    """Same name appears twice → both occurrences scrubbed."""
    _stub_gpt(monkeypatch, {
        "status": "success",
        "cleaned_text": "田中太郎は同僚です。田中太郎の電話は 090-1234-5678 です。",  # nothing redacted
        "entities": [
            {"type": "jp_full_name", "category": "PRIVATE", "redacted_text": "田中太郎"},
            {"type": "jp_phone", "category": "PRIVATE", "redacted_text": "090-1234-5678"},
        ],
    })
    body = _post(client, "田中太郎は同僚です。田中太郎の電話は 090-1234-5678 です。")
    d = body["data"]
    assert "田中太郎" not in d["sanitized_content"]
    assert "090-1234-5678" not in d["sanitized_content"]
    assert d["sanitized_content"].count("[REDACTED]") == 3
    assert d["redaction_source"] == "server"
