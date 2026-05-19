# TrustBoost PII Sanitizer

A precision PII redaction layer for autonomous AI agent pipelines.
Detects and redacts personally identifiable information **before** it reaches
LLM providers, across English, Spanish (LATAM), Portuguese (BR/PT), German,
Japanese, French, Italian, and Korean.

- **Endpoint:** `https://api.trustboost.dev/sanitize`
- **Stack:** FastAPI · OpenAI `gpt-4o-mini` (temperature 0) · Supabase · Solana payments via Helius

## Try it in 10 seconds — no wallet needed

```bash
curl -X POST https://api.trustboost.dev/sanitize/preview \
  -H "Content-Type: application/json" \
  -d '{"text": "My name is John Doe, email john@gmail.com, SSN 123-45-6789"}'
```

```json
{
  "sanitized_content": "My name is [REDACTED], email [REDACTED], SSN [REDACTED]",
  "safety_score": 0.6,
  "risk_category": "PRIVATE",
  "demo": true,
  "requests_remaining": 2,
  "next": "https://github.com/teodorofodocrispin-cmyk/TrustBoost-PII-Sanitizer#trial"
}
```

3 free previews per IP · no account · no wallet · no setup.
Ready for more? See [Trial mode](#trial) below — 50 free sanitizations with a Solana wallet.

---

## MCP Server — Claude, Cursor & Windsurf native integration

TrustBoost is available as an MCP (Model Context Protocol) server.
Add it to any MCP-compatible agent in one line:

```json
{
  "mcpServers": {
    "trustboost": {
      "url": "https://api.trustboost.dev/mcp"
    }
  }
}
```

Once connected, your agent can call `sanitize_pii` automatically
before sending any text to an LLM:

```bash
# Manifest
curl https://api.trustboost.dev/mcp

# Execute
curl -X POST https://api.trustboost.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"tool": "sanitize_pii", "input": {"text": "My email is john@gmail.com"}}'
```

Compatible with: Claude Code · Cursor · Windsurf · Any MCP-compatible agent

---

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

## Response schema (v2.5.0)

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
    "redaction_source": "server",
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
| `redaction_source` | `"model" \| "server" \| "fallback_full_redaction"` | Telemetry: who actually performed the redaction (see below).                 |
| `unmatched_entities` | `Entity[]` (optional) | Entities the model reported but whose `redacted_text` wasn't found verbatim in the input. Omitted when empty. |

### Risk weights

`safety_score` is the sum of per-entity weights, capped at 1.0:

- `CRITICAL` → 0.40 (API keys, private keys, seed phrases, credentials, card numbers, …)
- `PRIVATE`  → 0.20 (emails, phone numbers, national IDs, addresses, names, …)
- `SENSITIVE`→ 0.05 (handles, partial identifiers, DOB, …)

`risk_category` is the highest-severity tier with at least one entity, or
`"CLEAN"` if `entities` is empty.

## Server-side redaction enforcement (v2.5.0)

The model returns two things that have to agree: `cleaned_text` and
`entities`. In practice they sometimes disagree — the model can correctly
identify an entity in `entities` but fail to actually replace it in
`cleaned_text`. That produces a `sanitized_content` that still leaks PII
while the audit trail says everything is fine, which is worse than no audit
trail.

v2.2 fixes this structurally. The model is now treated purely as a
*detector*: it returns the entity list. The server is the *redactor*: for
every entity whose `redacted_text` is a non-empty substring of the original
input, the server replaces **all** occurrences with `[REDACTED]`. Long
entities are processed before short ones to avoid partial overlap.

Conservative redaction by design: if the same value (e.g. `田中太郎`)
appears twice in the input, both occurrences are scrubbed.

The `redaction_source` field tells you what happened:

- `"model"` — the model's `cleaned_text` already matched the entity list,
  so server-side enforcement was a no-op (the model did its job).
- `"server"` — the server-side enforcer replaced one or more entities the
  model failed to remove. Track this metric over time as a model-reliability
  signal: a rising `server` rate means the prompt or model is drifting.
- `"fallback_full_redaction"` — the model returned malformed JSON; the
  failsafe parser triggered and the entire input was redacted as a single
  `CRITICAL` entity. Should be near-zero in steady state.

When the model's `redacted_text` does not appear verbatim in the input
(paraphrasing, normalization, or hallucination), the entity is preserved in
`entities` (and counts toward `safety_score`) but is also returned in
`unmatched_entities` so callers can audit it.

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
- **French (FR/BE/CH/CA):** NIR (Numéro de Sécurité Sociale), SIRET, SIREN, Carte Vitale, IBAN FR, Numéro fiscal, country phones +33/+32/+41.
- **Italian (IT):** Codice Fiscale, Partita IVA, Carta d'Identità (CIE), Tessera Sanitaria, IBAN IT, Patente di Guida, country phone +39.
- **Korean (KR):** 주민등록번호 (RRN), 사업자등록번호, 여권번호, 운전면허번호, 건강보험번호, 외국인등록번호, country phone +82.

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

- **2.2** — server-side redaction enforcer, `redaction_source` telemetry, `unmatched_entities` audit field. Conservative replace-all-occurrences. Fixes the v2.1 class of bug where an entity could appear in `entities[]` without being removed from `sanitized_content`.
- **2.3** — Context-Aware Sanitization: `context` field in `/sanitize` (legal/financial/medical/code/general). Adjusts sanitization depth per context type. Adds `context_applied` to response.
- **2.4** — Privacy Budget per Agent: `agent_budgets` table in Supabase. Operators configure daily limits once, agents operate autonomously within them.
- **2.5** — TrustBoost Score: `/score/{wallet}` endpoint. M2M trust verification with trust tier (TRUSTED/VERIFIED/ACTIVE/NEW). Aggregated from audit_log.
- **2.1** — structured `entities` array, server-side deterministic scoring, hardened JSON parsing, improved Japanese 氏名 detection.
- **2.0** — multilingual prompt rewrite.
