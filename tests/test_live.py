"""End-to-end tests against a real `/sanitize` deployment.

Skipped by default. Run with:

    TRUSTBOOST_LIVE=1 \
    TRUSTBOOST_URL=https://api.trustboost.dev/sanitize \
    TRUSTBOOST_WALLET=ci-tester \
    python -m pytest tests/test_live.py -v

These tests consume TRIAL quota against the configured wallet.
"""

import json
import os
import urllib.request

import pytest

LIVE = os.environ.get("TRUSTBOOST_LIVE") == "1"
URL = os.environ.get("TRUSTBOOST_URL", "https://api.trustboost.dev/sanitize")
WALLET = os.environ.get("TRUSTBOOST_WALLET", "ci-tester")

pytestmark = pytest.mark.skipif(not LIVE, reason="set TRUSTBOOST_LIVE=1 to run")


def _post(text: str) -> dict:
    payload = {"text": text, "tx_hash": "TRIAL", "wallet_address": WALLET}
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _data(resp: dict) -> dict:
    assert resp["status"] == "success", resp
    return resp["data"]


def test_english_email_and_aws_key():
    d = _data(_post("My email is john@example.com and my AWS key is AKIAIOSFODNN7EXAMPLE"))
    assert "[REDACTED]" in d["sanitized_content"]
    assert "john@example.com" not in d["sanitized_content"]
    assert "AKIAIOSFODNN7EXAMPLE" not in d["sanitized_content"]
    # New contract: structured entity list.
    assert isinstance(d["entities"], list)
    assert len(d["entities"]) >= 2
    cats = {e["category"] for e in d["entities"]}
    assert "CRITICAL" in cats  # AWS key
    assert d["risk_category"] == "CRITICAL"


def test_japanese_name_is_redacted():
    """Regression test for the v2.0 miss where 田中太郎 was preserved."""
    d = _data(_post("田中太郎、マイナンバー：123456789012"))
    assert "田中太郎" not in d["sanitized_content"], (
        "Japanese full name leaked: " + d["sanitized_content"]
    )
    assert "123456789012" not in d["sanitized_content"]
    types = {e["type"] for e in d["entities"]}
    # We don't pin exact label strings, just that something name-flavored was reported.
    assert any("name" in t.lower() or "氏名" in t for t in types) or len(d["entities"]) >= 2


def test_json_structure_preserved():
    d = _data(_post('{"user": "john@example.com", "amount": 149}'))
    assert '"user"' in d["sanitized_content"]
    assert "[REDACTED]" in d["sanitized_content"]
    assert "149" in d["sanitized_content"]


def test_clean_input_returns_no_entities():
    d = _data(_post("The weather in Bogotá is mild today."))
    assert d["entities"] == []
    assert d["risk_category"] == "CLEAN"
    assert d["safety_score"] == 0.0
    assert d["entities_removed"] is False
