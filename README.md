# TrustBoost PII Sanitizer

A precision PII redaction layer for autonomous AI agent pipelines.
Detects and redacts personally identifiable information **before** it reaches
LLM providers, across English, Spanish (LATAM), Portuguese (BR/PT), German,
and Japanese.

- **Endpoint:** `https://api.trustboost.dev/sanitize`
- **Stack:** FastAPI · OpenAI `gpt-4o-mini` (temperature 0) · Supabase · Solana payments via Helius

## Quick start

```bash
curl -X POST https://api.trustboost.dev/sanitize \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "My email is jane@example.com and my AWS key is AKIAIOSFODNN7EXAMPLE",
    "tx_hash": "TRIAL",
    "wallet_address": "your-agent-id"
  }'
```

Trial mode (`tx_hash="TRIAL"`) gives 50 free sanitizations per `wallet_address`.
Paid mode requires 149 USDC on Solana to the configured payment wallet, which
unlocks 10,000 sanitizations per transaction signature.

## Response schema (v2.1)

```json
{
  "status": "success",
  "request_id": "TRIAL",
  "data": {
    "message": "Content successfully sanitized and logged.",
    "sanitized_content": "My email is [REDACTED] and my AWS key is [REDACTED]",
    "safety_score": 0.6,
    "risk_category": "CRITICAL",
    "entities_removed": true,
    "entities": [
      { "type": "email",          "category": "PRIVATE",  "redacted_text": "jane@example.com" },
      { "type": "aws_access_key", "category": "CRITICAL", "redacted_text": "AKIAIOSFODNN7EXAMPLE" }
    ],
    "timestamp": "2026-05-03T23:48:14.500705+00:00",
    "usage_metrics": { "quota_remaining": 48, "quota_limit": 50 }
  },
  "billing": { "license_type": "TRIAL", "status": "active" }
}
```

### Field guide

| Field              | Type                 | Notes                                                                   |
| ------------------ | -------------------- | ----------------------------------------------------------------------- |
| `sanitized_content`| `string`             | Same language and structure as input, with PII replaced by `[REDACTED]`. |
| `entities`         | `Entity[]`           | One element per `[REDACTED]` tag. Stable, machine-friendly.              |
| `safety_score`     | `float` 0.0 – 1.0    | **Server-side, deterministic.** Computed from `entities`, not the model. |
| `risk_category`    | `CRITICAL`/`PRIVATE`/`SENSITIVE`/`CLEAN` | Highest tier present in `entities`.                  |
| `entities_removed` | `bool`               | Convenience: `true` iff `entities` is non-empty.                         |

### Risk weights

`safety_score` is the sum of per-entity weights, capped at 1.0:

- `CRITICAL` → 0.40 (API keys, private keys, seed phrases, credentials, card numbers, …)
- `PRIVATE`  → 0.20 (emails, phone numbers, national IDs, addresses, names, …)
- `SENSITIVE`→ 0.05 (handles, partial identifiers, DOB, …)

`risk_category` is the highest-severity tier with at least one entity, or
`"CLEAN"` if `entities` is empty.

## Failure mode: fail-safe, not fail-open

If the upstream model returns malformed JSON, the response degrades to a
single `CRITICAL` entity covering the entire input rather than risking a
silent leak. Over-redaction is always preferred over under-redaction.

## Languages and patterns

The system prompt covers, among others:

- **English (global):** emails, phones, SSN, credit cards, IBAN, IPs, addresses, and provider-specific API keys (OpenAI, Anthropic, GitHub, AWS, Google, Slack, HuggingFace, Stripe), private keys, crypto wallets, seed phrases.
- **Spanish (LATAM):** RFC, CURP, CUIT/CUIL, RUT, DNI, RUC, NIT, Cédula, country phones.
- **Portuguese (BR/PT):** CPF, CNPJ, RG, NIF, NUS, CEP, country phones.
- **German (DE/AT/CH):** Personalausweis, Steuer-IDs, Sozialversicherungsnummer, IBAN DE, addresses.
- **Japanese:** マイナンバー, 法人番号, 運転免許証, パスポート, 健康保険証, 電話番号, 住所, and 氏名 (full names in kanji, mixed scripts, katakana, or hiragana).

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env  # then fill in real keys
uvicorn main:app --reload
```

Required environment variables:

- `OPENAI_API_KEY`
- `SUPABASE_URL`, `SUPABASE_KEY`
- `HELIUS_API_KEY`, `PAYMENT_WALLET`
- Optional: `TRIAL_QUOTA` (default 50), `PAID_QUOTA` (default 10000), `REQUIRED_PAYMENT_USDC` (default 149)

## Tests

```bash
pip install pytest
python -m pytest tests/test_sanitize.py -v          # unit tests, no creds needed
TRUSTBOOST_LIVE=1 python -m pytest tests/test_live.py -v   # hits real /sanitize
```

The live tests consume TRIAL quota; set `TRUSTBOOST_WALLET` to a CI-specific
identifier so they don't share quota with developer wallets.

## Versioning

- **2.1** — structured `entities` array, server-side deterministic scoring, hardened JSON parsing, improved Japanese 氏名 detection.
- **2.0** — multilingual prompt rewrite.
