"""
TrustBoost — Discovery Registration Script
Run after deploy: python scripts/register_bazaar.py
Registra los endpoints en 402 Index (Bazaar de agentic.market).
Patron replicado de veradata/scripts/register_bazaar.py.
"""
import asyncio
import httpx

BASE_URL = "https://api.trustboost.dev"

ENDPOINTS = [
    {
        "url": f"{BASE_URL}/sanitize",
        "name": "TrustBoost /sanitize — PII Sanitizer (pay-per-call)",
        "description": "PII sanitization for autonomous AI agent pipelines. Redacts emails, phones, national IDs, API keys, financial data before LLM calls. Pay-per-call $0.01 USDC via x402 on Base and Solana. 50 free TRIAL sanitizations. Immutable proof anchored on Solana. EU AI Act Art.10 compliant.",
        "category": "privacy",
    },
    {
        "url": f"{BASE_URL}/redact",
        "name": "TrustBoost /redact — PII Redaction",
        "description": "Redacts PII from text via x402 pay-per-call ($0.01 USDC, Base/Solana). Same sanitization engine as /sanitize exposed as /redact for agent tooling compatibility. Returns redacted text + sanitization hash (SHA-256).",
        "category": "privacy",
    },
    {
        "url": f"{BASE_URL}/detect",
        "name": "TrustBoost /detect — PII Detection",
        "description": "Detects PII entities in text without redacting. x402 pay-per-call ($0.01 USDC, Base/Solana). Returns entity types, categories and risk score. Useful for pre-flight compliance checks in agent pipelines.",
        "category": "compliance",
    },
    {
        "url": f"{BASE_URL}/sanitize/quick",
        "name": "TrustBoost /sanitize/quick — Fast PII Sanitizer",
        "description": "Lightweight pay-per-call PII sanitization ($0.01 USDC via x402 on Base preferred, Solana alternate). No TRIAL/bundle — pure per-call. Returns redacted text + entities removed. For high-throughput agent pipelines.",
        "category": "privacy",
    },
]


async def register_all():
    async with httpx.AsyncClient(timeout=30.0) as client:
        for ep in ENDPOINTS:
            print(f"Registering {ep['url']}...")
            try:
                r = await client.post(
                    "https://402index.io/api/v1/register",
                    headers={"Content-Type": "application/json"},
                    json={
                        "url": ep["url"],
                        "name": ep["name"],
                        "protocol": "x402",
                        "provider": "TrustBoost",
                        "description": ep["description"],
                        "category": ep["category"],
                        "http_method": "POST",
                    },
                )
                print(f"  -> {r.status_code}: {r.text[:120]}")
            except Exception as e:
                print(f"  -> ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(register_all())
