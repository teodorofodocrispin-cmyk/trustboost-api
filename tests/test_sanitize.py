"""Unit tests for TrustBoost helpers that don't require live API credentials.

Run with:  python -m pytest tests/

These tests deliberately exercise only the pure functions (`compute_score`,
`_parse_model_json`) so they pass in CI without OpenAI / Supabase / Helius
keys. End-to-end tests that hit the real `/sanitize` endpoint live in
`tests/test_live.py` and are skipped unless `TRUSTBOOST_LIVE=1` is set.
"""

import os
import sys

# Stub envs so `import main` doesn't crash on missing creds.
os.environ.setdefault("OPENAI_API_KEY", "stub")
os.environ.setdefault("TRIAL_QUOTA", "50")
os.environ.setdefault("PAID_QUOTA", "10000")
os.environ.setdefault("REQUIRED_PAYMENT_USDC", "149")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402


# ── compute_score ──────────────────────────────────────────────────────────

def test_score_clean():
    assert main.compute_score([]) == (0.0, "CLEAN")


def test_score_single_private():
    entities = [{"type": "email", "category": "PRIVATE", "redacted_text": "a@b.c"}]
    assert main.compute_score(entities) == (0.2, "PRIVATE")


def test_score_critical_dominates():
    entities = [
        {"type": "aws_access_key", "category": "CRITICAL", "redacted_text": "AKIA..."},
        {"type": "email", "category": "PRIVATE", "redacted_text": "a@b.c"},
    ]
    score, category = main.compute_score(entities)
    assert score == 0.6
    assert category == "CRITICAL"


def test_score_capped_at_one():
    entities = [{"type": "k", "category": "CRITICAL", "redacted_text": "x"}] * 5
    score, category = main.compute_score(entities)
    assert score == 1.0
    assert category == "CRITICAL"


def test_score_unknown_category_is_sensitive():
    entities = [{"type": "x", "category": "BOGUS", "redacted_text": "q"}]
    score, category = main.compute_score(entities)
    assert score == 0.05
    assert category == "SENSITIVE"


def test_score_picks_highest_tier():
    # PRIVATE + SENSITIVE → category should be PRIVATE
    entities = [
        {"type": "email", "category": "PRIVATE", "redacted_text": "a@b.c"},
        {"type": "handle", "category": "SENSITIVE", "redacted_text": "@x"},
    ]
    score, category = main.compute_score(entities)
    assert category == "PRIVATE"
    # 0.20 + 0.05 = 0.25
    assert abs(score - 0.25) < 1e-6


# ── _parse_model_json (failsafe parser) ────────────────────────────────────

def test_parse_valid_json():
    raw = '{"status":"success","cleaned_text":"x","entities":[]}'
    assert main._parse_model_json(raw, original_text="x") == {
        "status": "success",
        "cleaned_text": "x",
        "entities": [],
    }


def test_parse_recovers_wrapped_json():
    raw = 'noise {"status":"success","cleaned_text":"x","entities":[]} more noise'
    parsed = main._parse_model_json(raw, original_text="x")
    assert parsed["status"] == "success"
    assert parsed["entities"] == []


def test_parse_failsafe_on_garbage():
    parsed = main._parse_model_json("totally not json", original_text="leak me")
    # Failsafe must redact the whole input rather than leak it.
    assert parsed["cleaned_text"] == "[REDACTED]"
    assert len(parsed["entities"]) == 1
    ent = parsed["entities"][0]
    assert ent["category"] == "CRITICAL"
    assert ent["redacted_text"] == "leak me"
    assert ent["type"] == "sanitizer_failsafe"


def test_parse_failsafe_on_empty():
    parsed = main._parse_model_json("", original_text="hello")
    assert parsed["cleaned_text"] == "[REDACTED]"
    assert parsed["entities"][0]["redacted_text"] == "hello"


# ── enforce_redaction ───────────────────────────────────

def _ent(t, c, r):
    return {"type": t, "category": c, "redacted_text": r}


def test_enforce_model_already_correct():
    """When the model's cleaned_text already matches the entity list, source=model."""
    original = "My email is a@b.c"
    model_cleaned = "My email is [REDACTED]"
    entities = [_ent("email", "PRIVATE", "a@b.c")]
    cleaned, source, unmatched = main.enforce_redaction(original, model_cleaned, entities)
    assert cleaned == "My email is [REDACTED]"
    assert source == "model"
    assert unmatched == []


def test_enforce_fixes_model_leak():
    """Regression for the v2.1 田中太郎 miss: entity reported but not removed."""
    original = "田中太郎、マイナンバー：123456789012"
    # Model identified both entities but only redacted one in cleaned_text.
    model_cleaned = "田中太郎、マイナンバー：[REDACTED]"
    entities = [
        _ent("jp_my_number", "PRIVATE", "123456789012"),
        _ent("jp_full_name", "PRIVATE", "田中太郎"),
    ]
    cleaned, source, unmatched = main.enforce_redaction(original, model_cleaned, entities)
    assert "田中太郎" not in cleaned
    assert "123456789012" not in cleaned
    assert source == "server"  # enforcer had to fix the leak
    assert unmatched == []


def test_enforce_replaces_all_occurrences():
    """Conservative redaction: every occurrence of the same name is removed."""
    original = "田中太郎は同僚です。田中太郎の電話番号は 090-1234-5678 です。"
    model_cleaned = original  # model produced no redactions at all
    entities = [
        _ent("jp_full_name", "PRIVATE", "田中太郎"),
        _ent("jp_phone", "PRIVATE", "090-1234-5678"),
    ]
    cleaned, source, unmatched = main.enforce_redaction(original, model_cleaned, entities)
    assert cleaned.count("[REDACTED]") == 3  # name x2 + phone x1
    assert "田中太郎" not in cleaned
    assert "090-1234-5678" not in cleaned
    assert source == "server"


def test_enforce_longer_entities_first():
    """When entities overlap, the longer one wins so we don't get partial redaction."""
    # "+1-555-0123" contains "555" — if the short one ran first, the long one
    # would no longer match. Sort-by-length-desc prevents that.
    original = "Call me at +1-555-0123 anytime"
    model_cleaned = original
    entities = [
        _ent("phone_partial", "SENSITIVE", "555"),
        _ent("phone", "PRIVATE", "+1-555-0123"),
    ]
    cleaned, source, unmatched = main.enforce_redaction(original, model_cleaned, entities)
    # The full phone got replaced; the leftover "555" needle now has nothing
    # to match (it was inside the redacted span).
    assert cleaned == "Call me at [REDACTED] anytime"
    assert source == "server"
    assert unmatched == []


def test_enforce_unmatched_entity():
    """Model claims to have redacted something that isn't in the input verbatim."""
    original = "My name is John Smith"
    model_cleaned = "My name is [REDACTED]"
    entities = [
        # The model said it redacted "john smith" (lowercase) but that exact
        # substring isn't in the input. Server-side enforcer can't replace
        # what it can't find; the entity still counts but lands in unmatched.
        _ent("full_name", "PRIVATE", "john smith"),
    ]
    cleaned, source, unmatched = main.enforce_redaction(original, model_cleaned, entities)
    assert len(unmatched) == 1
    assert unmatched[0]["redacted_text"] == "john smith"
    # Because the enforcer couldn't replace anything, its cleaned_text
    # equals the original input — different from model_cleaned, so source=server.
    assert source == "server"


def test_enforce_skips_empty_redacted_text():
    original = "hello world"
    entities = [_ent("weird", "SENSITIVE", "")]
    cleaned, source, unmatched = main.enforce_redaction(original, original, entities)
    assert cleaned == original
    assert unmatched == []  # empty redacted_text is silently skipped, not flagged
    assert source == "model"


def test_enforce_clean_input_no_entities():
    original = "Just a normal sentence."
    cleaned, source, unmatched = main.enforce_redaction(original, original, [])
    assert cleaned == original
    assert source == "model"
    assert unmatched == []


def test_enforce_idempotent_duplicate_entities():
    """Same redacted_text listed twice in entities should not break replacement."""
    original = "Email a@b.c and a@b.c"
    entities = [
        _ent("email", "PRIVATE", "a@b.c"),
        _ent("email", "PRIVATE", "a@b.c"),  # duplicate
    ]
    cleaned, source, unmatched = main.enforce_redaction(original, original, entities)
    assert cleaned == "Email [REDACTED] and [REDACTED]"
    assert source == "server"


# ── gpt_sanitize: fails closed when the OpenAI call itself fails ───────────
# Found 2026-08-28 during a cross-repo audit prompted by client-side fixes
# in a downstream tutorial: _parse_model_json already failed safe on a
# malformed RESPONSE from OpenAI, but the API call itself was never wrapped
# in a try/except -- a rate limit, timeout, connection error, or auth
# failure would 500 the whole request instead of failing closed. These
# tests exercise that path directly against the real openai exception
# classes (not generic Exception), since the SDK's __init__ signatures
# require a real httpx.Request/Response to construct.

import asyncio
from unittest.mock import AsyncMock, patch
import openai
import httpx

_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
_FAKE_RESPONSE = httpx.Response(429, request=_FAKE_REQUEST)


def _run(coro):
    return asyncio.run(coro)


def test_gpt_sanitize_fails_closed_on_rate_limit():
    with patch.object(
        main.openai_client.chat.completions, "create",
        new=AsyncMock(side_effect=openai.RateLimitError("rate limited", response=_FAKE_RESPONSE, body=None)),
    ):
        result = _run(main.gpt_sanitize("my email is john@example.com"))
    assert result == main._failsafe_result("my email is john@example.com")
    assert result["entities"][0]["category"] == "CRITICAL"


def test_gpt_sanitize_fails_closed_on_timeout():
    with patch.object(
        main.openai_client.chat.completions, "create",
        new=AsyncMock(side_effect=openai.APITimeoutError(request=_FAKE_REQUEST)),
    ):
        result = _run(main.gpt_sanitize("my SSN is 123-45-6789"))
    assert result["entities"][0]["category"] == "CRITICAL"
    assert result["entities"][0]["type"] == "sanitizer_failsafe"


def test_gpt_sanitize_fails_closed_on_connection_error():
    with patch.object(
        main.openai_client.chat.completions, "create",
        new=AsyncMock(side_effect=openai.APIConnectionError(request=_FAKE_REQUEST)),
    ):
        result = _run(main.gpt_sanitize("sensitive text"))
    assert result["entities"][0]["category"] == "CRITICAL"


def test_gpt_sanitize_fails_closed_on_unexpected_exception():
    """Not just OpenAI's own exception classes -- ANY exception from the
    call (a bug in the SDK, an unexpected error type) must still fail
    closed rather than propagate into a raw 500."""
    with patch.object(
        main.openai_client.chat.completions, "create",
        new=AsyncMock(side_effect=RuntimeError("totally unexpected")),
    ):
        result = _run(main.gpt_sanitize("text"))
    assert result["entities"][0]["category"] == "CRITICAL"


def test_gpt_sanitize_happy_path_unaffected():
    """Regression: wrapping the call in try/except must not change behavior
    when OpenAI responds normally."""
    class _Msg:
        content = '{"cleaned_text": "[REDACTED]", "entities": [{"type": "email", "category": "PRIVATE", "redacted_text": "john@example.com"}]}'

    class _Choice:
        message = _Msg()

    class _Response:
        choices = [_Choice()]

    with patch.object(
        main.openai_client.chat.completions, "create",
        new=AsyncMock(return_value=_Response()),
    ):
        result = _run(main.gpt_sanitize("contact john@example.com"))
    assert result["cleaned_text"] == "[REDACTED]"
    assert result["entities"][0]["category"] == "PRIVATE"


def test_parse_model_json_and_failsafe_result_share_one_shape():
    """_parse_model_json's own failsafe branch and gpt_sanitize's except
    block must never drift apart -- both call the same _failsafe_result()
    helper, extracted specifically so a future edit to one can't silently
    leave the other behind."""
    from_parse = main._parse_model_json("not json {{{", "original text")
    from_helper = main._failsafe_result("original text")
    assert from_parse == from_helper
