"""Tests for the payment-entry flows of the PII endpoints (offline, no creds).

Covers the regressions that left the API effectively closed for TRIAL / prepaid
callers: the x402 discovery middleware used to answer 402 to *every* request
without a payment header, including legitimate POSTs that carry a JSON body
with ``tx_hash="TRIAL"`` or a prepaid ``tx_hash``.

Run with:  python -m pytest tests/test_x402_flows.py -v
"""

import base64
import json
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

PAID_PATHS = ["/sanitize", "/redact", "/trustboost-pii-sanitizer"]
GPT_OK = {
    "status": "success",
    "cleaned_text": "mail [REDACTED]",
    "entities": [{"type": "email", "category": "PRIVATE", "redacted_text": "a@b.c"}],
}


@pytest.fixture
def client(monkeypatch):
    async def fake_get_trial_count(wallet):
        return 0

    async def fake_increment_trial(wallet):
        return None

    async def fake_log_audit(*a, **k):
        return None

    async def fake_gpt(text, *a, **k):
        return GPT_OK

    monkeypatch.setattr(main, "get_trial_count", fake_get_trial_count)
    monkeypatch.setattr(main, "increment_trial", fake_increment_trial)
    monkeypatch.setattr(main, "log_audit", fake_log_audit)
    monkeypatch.setattr(main, "gpt_sanitize", fake_gpt)
    return TestClient(main.app)


def _decode_payment_required(resp):
    raw = resp.headers.get("payment-required")
    assert raw, "402 must carry a PAYMENT-REQUIRED header"
    return json.loads(base64.b64decode(raw))


# ── TRIAL / body-credential flows must reach the handler ─────────────────────
@pytest.mark.parametrize("path", PAID_PATHS)
def test_trial_post_is_served(client, path):
    r = client.post(path, json={"text": "mail a@b.c", "tx_hash": "TRIAL", "wallet_address": "w1"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["sanitized_content"] == "mail [REDACTED]"


def test_prepaid_tx_hash_reaches_handler(client, monkeypatch):
    """A prepaid tx_hash must reach the handler (verification), not be 402'd by the middleware."""
    seen = {}

    async def fake_check_replay(tx):
        return False

    async def fake_helius(tx):
        seen["tx"] = tx
        return False, 0

    monkeypatch.setattr(main, "check_replay", fake_check_replay)
    monkeypatch.setattr(main, "helius_verify", fake_helius)
    tx = "5" * 88
    r = client.post("/sanitize", json={"text": "mail a@b.c", "tx_hash": tx, "wallet_address": "w1"})
    assert seen.get("tx") == tx, "handler must verify the prepaid tx_hash on-chain"
    assert r.status_code == 402
    assert r.json()["code"] == "QUOTA_EXHAUSTED_OR_PAYMENT_REQUIRED"


def test_prepaid_valid_tx_is_served(client, monkeypatch):
    async def fake_check_replay(tx):
        return True

    async def fake_paid_count(tx):
        return 5

    monkeypatch.setattr(main, "check_replay", fake_check_replay)
    monkeypatch.setattr(main, "get_paid_count", fake_paid_count)
    async def _noop(*a, **k):
        return None
    for name in ("register_tx_hash", "anchor_proof_on_solana", "increment_paid"):
        if hasattr(main, name):
            monkeypatch.setattr(main, name, _noop)
    r = client.post("/sanitize", json={"text": "mail a@b.c", "tx_hash": "6" * 88, "wallet_address": "w1"})
    assert r.status_code == 200, r.text
    assert r.json()["billing"]["license_type"] != "TRIAL"


# ── Discovery probes still get a valid x402 402 ──────────────────────────────
@pytest.mark.parametrize("path", PAID_PATHS + ["/sanitize/quick"])
def test_get_probe_gets_402_with_header(client, path):
    r = client.get(path)
    assert r.status_code == 402
    info = _decode_payment_required(r)
    assert info["x402Version"] == 2
    assert info["accepts"]


@pytest.mark.parametrize("path", PAID_PATHS + ["/sanitize/quick"])
def test_empty_post_probe_gets_402_with_header(client, path):
    r = client.post(path)
    assert r.status_code == 402
    _decode_payment_required(r)


def test_quick_with_text_but_no_payment_is_402(client):
    r = client.post("/sanitize/quick", json={"text": "mail a@b.c"})
    assert r.status_code == 402
    _decode_payment_required(r)


# ── Payment header without text -> actionable 422, not a misleading 402 ─────
def test_payment_header_without_text_returns_422_schema(client):
    r = client.post("/sanitize", json={}, headers={"PAYMENT-SIGNATURE": "abc"})
    assert r.status_code == 422
    body = r.json()
    assert "text" in json.dumps(body)


# ── Alias forwards payment headers instead of dropping them ──────────────────
def test_alias_forwards_payment_header(client, monkeypatch):
    got = {}

    async def fake_verify(header, price, url):
        got["header"] = header
        return True, "payer-1"

    monkeypatch.setattr(main, "verify_payment_percall", fake_verify)
    r = client.post(
        "/trustboost-pii-sanitizer",
        json={"text": "mail a@b.c"},
        headers={"PAYMENT-SIGNATURE": "sig-123"},
    )
    assert r.status_code == 200, r.text
    assert got["header"] == "sig-123"


def test_alias_invalid_json_is_4xx_not_500(client):
    r = client.post("/trustboost-pii-sanitizer", content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code in (400, 402, 422)


# ── /.well-known/x402.json advertises what the API really accepts ───────────
def test_well_known_matches_payment_info(client):
    r = client.get("/.well-known/x402.json")
    assert r.status_code == 200
    accepts = r.json()["accepts"]
    nets = {(a["network"], a["amount"]) for a in accepts}
    assert ("eip155:8453", "10000") in nets          # Base $0.01 per call
    assert ("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "10000") in nets
    assert ("solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "149000000") in nets  # prepaid bundle


# ── Proof of Sanitization: the memo tx must build with a real Hash ──────────
def test_anchor_builds_and_sends_signed_tx(monkeypatch):
    import asyncio

    import base58
    from solders.hash import Hash
    from solders.keypair import Keypair

    kp = Keypair()
    monkeypatch.setattr(main, "SOLANA_SERVICE_KEY", base58.b58encode(bytes(kp)).decode())
    fake_blockhash = str(Hash.default())
    sent = {}

    class FakeResp:
        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            if json["method"] == "getLatestBlockhash":
                return FakeResp({"result": {"value": {"blockhash": fake_blockhash}}})
            sent["tx"] = json["params"][0]
            return FakeResp({"result": "SIG123"})

    monkeypatch.setattr(main.httpx, "AsyncClient", lambda *a, **k: FakeClient())
    sig = asyncio.run(main.anchor_proof_on_solana("wallet", 0.6, "PRIVATE", 42))
    assert sig == "SIG123"
    assert sent["tx"]
