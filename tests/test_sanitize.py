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
