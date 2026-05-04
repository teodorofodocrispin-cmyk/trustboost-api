import os
import json
from datetime import datetime, timezone
from typing import Optional, List, Literal
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from dotenv import load_dotenv

# ── Risk weights — server-side, deterministic ──────────────
# Used to compute safety_score from the entity list returned by the model,
# so scoring no longer depends on the model doing arithmetic correctly.
RISK_WEIGHTS = {
    "CRITICAL": 0.40,
    "PRIVATE": 0.20,
    "SENSITIVE": 0.05,
}
RISK_ORDER = ["CRITICAL", "PRIVATE", "SENSITIVE"]

load_dotenv()

OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
HELIUS_API_KEY        = os.getenv("HELIUS_API_KEY")
SUPABASE_URL          = os.getenv("SUPABASE_URL")
SUPABASE_KEY          = os.getenv("SUPABASE_KEY")
PAYMENT_WALLET        = os.getenv("PAYMENT_WALLET")
TRIAL_QUOTA           = int(os.getenv("TRIAL_QUOTA", "50"))
PAID_QUOTA            = int(os.getenv("PAID_QUOTA", "10000"))
REQUIRED_PAYMENT_USDC = int(os.getenv("REQUIRED_PAYMENT_USDC", "149"))

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
app = FastAPI(title="TrustBoost PII Sanitizer v2.1")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

class SanitizeRequest(BaseModel):
    text: str
    tx_hash: str
    wallet_address: Optional[str] = None


class Entity(BaseModel):
    """A single PII entity detected in the input.

    `type` is a short machine-friendly label (e.g. "email", "aws_access_key",
    "jp_my_number", "jp_full_name"). `category` is the risk tier used for
    scoring. `redacted_text` is the original substring that was replaced with
    [REDACTED]; it is returned so callers can audit *what* was removed without
    having to diff input vs output. Callers that don't need it can ignore it.
    """
    type: str
    category: Literal["CRITICAL", "PRIVATE", "SENSITIVE"]
    redacted_text: str

# ── TRIAL: contador por wallet ──────────────────────────────

async def get_trial_count(wallet: str) -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/trial_requests",
            headers=SUPABASE_HEADERS,
            params={"wallet_address": f"eq.{wallet}", "select": "id"}
        )
        if r.status_code == 200:
            return len(r.json())
        return 0

async def increment_trial(wallet: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SUPABASE_URL}/rest/v1/trial_requests",
            headers=SUPABASE_HEADERS,
            json={"wallet_address": wallet}
        )

# ── PAID: verificar y contar por tx_hash ───────────────────

async def check_replay(tx_hash: str) -> bool:
    """Verifica si el tx_hash existe en used_tx — primer uso."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/used_tx",
            headers=SUPABASE_HEADERS,
            params={"tx_hash": f"eq.{tx_hash}", "select": "tx_hash"}
        )
        if r.status_code == 200 and len(r.json()) > 0:
            return True  # Ya existe — no es replay, es reutilización válida
        return False  # No existe — primer uso

async def register_tx_hash(tx_hash: str):
    """Registra el tx_hash en used_tx la primera vez."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SUPABASE_URL}/rest/v1/used_tx",
            headers={**SUPABASE_HEADERS, "Prefer": "return=minimal"},
            json={"tx_hash": tx_hash}
        )

async def get_paid_count(tx_hash: str) -> int:
    """Cuenta cuántas sanitizaciones se han usado de este tx_hash."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/paid_requests",
            headers=SUPABASE_HEADERS,
            params={"tx_hash": f"eq.{tx_hash}", "select": "id"}
        )
        if r.status_code == 200:
            return len(r.json())
        return 0

async def increment_paid(tx_hash: str):
    """Registra una sanitización usada contra este tx_hash."""
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SUPABASE_URL}/rest/v1/paid_requests",
            headers=SUPABASE_HEADERS,
            json={"tx_hash": tx_hash}
        )

# ── HELIUS: verificar pago en Solana ───────────────────────

async def helius_verify(tx_hash: str) -> tuple[bool, float]:
    url = f"https://api.helius.xyz/v0/addresses/{PAYMENT_WALLET}/transactions"
    async with httpx.AsyncClient() as client:
        for _ in range(3):
            try:
                r = await client.post(
                    url,
                    params={"api-key": HELIUS_API_KEY},
                    json={"transactions": [tx_hash]},
                    timeout=15
                )
                if r.status_code == 200:
                    data = r.json()
                    if data:
                        for t in data[0].get("tokenTransfers", []):
                            if t.get("tokenAmount", 0) >= REQUIRED_PAYMENT_USDC:
                                return True, t["tokenAmount"]
                return False, 0
            except Exception:
                continue
    return False, 0

# ── GPT-4o-mini: sanitización multilingüe ──────────────────

async def gpt_sanitize(text: str) -> dict:
    system_prompt = """You are TrustBoost AI Sanitizer — a precision PII redaction engine for autonomous AI agent pipelines. Your sole function is to detect and neutralize Personally Identifiable Information before it reaches LLM providers.

## CORE DIRECTIVE
Scan the input text, replace ALL detected PII with the literal tag [REDACTED], and return a structured JSON assessment listing every entity you redacted. Preserve the original language, tone, structure, and non-PII content exactly.

## CONSERVATIVE REDACTION PRINCIPLE
When uncertain whether a pattern is PII: REDACT IT.
A false positive (over-redaction) is always safer than a false negative (missed PII).
Exception: Do not redact generic numbers, common words, or public information.

## LANGUAGE DETECTION & PROTOCOL
Automatically detect the input language.
Return cleaned_text in the EXACT SAME language as the input.
Apply the country-specific patterns for the detected language.

## PII PATTERNS BY LANGUAGE

### ENGLISH (Global)
- Emails: any RFC 5322 format (user@domain.tld)
- Phone numbers: E.164 (+1-555-0123), US (555) 123-4567, international formats
- Physical addresses: street numbers, zip codes, postal codes
- Full names: first + last name combinations in personal context
- Social Security Numbers: XXX-XX-XXXX (reject 000/666/9XX prefixes)
- Credit/debit cards: 13-19 digit sequences (Luhn-validated when possible)
- IBAN: CC##[alphanumeric]{10-30}
- API Keys by provider:
  * OpenAI: sk-[alphanumeric]{32,}  or  sk-proj-[alphanumeric]{32,}
  * Anthropic: sk-ant-[alphanumeric]{32,}
  * GitHub: gho_[alphanumeric]{36}  ghp_[alphanumeric]{36}  ghs_[alphanumeric]{36}  github_pat_[alphanumeric]{80,}
  * AWS: AKIA[A-Z0-9]{16}
  * Google: AIza[A-Za-z0-9_-]{35}
  * Slack: xox[bapirs]-[alphanumeric-]{10,}
  * HuggingFace: hf_[alphanumeric]{34,}
  * Stripe: sk_live_[alphanumeric]{24,}  pk_live_[alphanumeric]{24,}
  * Generic: any string matching [A-Za-z0-9_-]{32,} in a key/token/secret context
- Private keys: PEM blocks (-----BEGIN * PRIVATE KEY----- ... -----END * PRIVATE KEY-----)
- Crypto wallet addresses: Ethereum 0x[a-fA-F0-9]{40}, Solana base58 32-44 chars, Bitcoin 1/3/bc1 prefixes
- Seed phrases: 12 or 24 word BIP39 mnemonic sequences
- Passwords: values in password/passwd/pwd/secret context
- IP addresses: IPv4 (x.x.x.x), IPv6, unless clearly public/example
- Biometric identifiers: fingerprint IDs, facial recognition data references
- Medical record numbers, patient IDs, insurance numbers

### SPANISH — LATIN AMERICA
- RFC (Mexico): [A-Z]{4}[0-9]{6}[A-Z0-9]{3} — tax ID
- CUIT/CUIL (Argentina): XX-XXXXXXXX-X format
- RUT (Chile/Colombia): XX.XXX.XXX-X format
- DNI (Peru/Argentina): 8-digit national ID
- CURP (Mexico): [A-Z]{4}[0-9]{6}[HM][A-Z]{5}[A-Z0-9]{2} — 18 chars
- Cédula de Ciudadanía (Colombia/Venezuela): 6-10 digit ID
- RUC (Ecuador/Peru/Panama): 11-13 digit tax ID
- NIT (Colombia): XX.XXX.XXX-X format
- Phone formats: +52 (MX), +57 (CO), +54 (AR), +56 (CL), +51 (PE)

### PORTUGUESE — BRAZIL & PORTUGAL
- CPF (Brazil): XXX.XXX.XXX-XX — 11 digits, validated format
- CNPJ (Brazil): XX.XXX.XXX/XXXX-XX — 14 digits
- RG (Brazil): X.XXX.XXX-X — Registro Geral
- NIF (Portugal): 9-digit Número de Identificação Fiscal
- NUS (Portugal): Número de Utente de Saúde
- NIF Empresarial (Portugal): 9-digit company tax number
- Phone formats: +55 (BR) XX XXXXX-XXXX, +351 (PT) XXX XXX XXX
- CEP (Brazil postal code): XXXXX-XXX

### GERMAN — GERMANY, AUSTRIA, SWITZERLAND
- Personalausweis: [A-Z0-9]{9} — national ID card number
- Reisepass (passport): [A-Z0-9]{9}
- Steuernummer: XX/XXX/XXXXX — tax number (format varies by Bundesland)
- Steueridentifikationsnummer: 11-digit national tax ID
- Sozialversicherungsnummer: XXXXXXXXXX (10 digits)
- Krankenversicherungsnummer: insurance number formats
- IBAN DE: DE[0-9]{20}
- Phone formats: +49 (DE), +43 (AT), +41 (CH)
- German addresses: Straße, Platz, Weg + number + PLZ (5-digit postal)

### JAPANESE — JAPAN
- マイナンバー (My Number): 12-digit individual number
- 法人番号 (Corporate Number): 13-digit corporate number
- 運転免許証 (Driver's License): 12-digit format
- パスポート番号 (Passport): [A-Z]{2}[0-9]{7}
- 健康保険証番号 (Health Insurance): various formats
- 電話番号 (Phone): 0X-XXXX-XXXX, 0XX-XXX-XXXX, 080/090/070 mobile
- 住所 (Address): patterns with 都道府県 (prefecture), 市区町村 (city/ward), 丁目番地号
- 氏名 (Full name): Japanese personal-name patterns in personal-data context.
  This INCLUDES, but is not limited to:
    * Kanji full names: 姓 + 名 (e.g. 田中太郎, 鈴木一郎, 佐藤花子, 山田太郎)
    * Kanji surname followed by katakana/hiragana given name (e.g. 田中タロウ)
    * Full names written entirely in katakana (e.g. タナカタロウ)
    * Full names written entirely in hiragana (e.g. たなかたろう)
  ALWAYS redact a Japanese personal name when it appears next to, or in the
  same record as, ANY other PII (My Number, phone, address, email, ID number,
  health insurance number, or a 「、」/「：」-delimited personal record).
  Examples that MUST be redacted as 氏名:
    * "田中太郎、マイナンバー：123456789012"  →  both 田中太郎 and the number
    * "氏名：鈴木一郎  電話：090-1234-5678"  →  both the name and the phone
    * "佐藤花子さんの住所は東京都..."        →  the name and the address
  When in doubt about a Japanese name, REDACT.

## RISK CLASSIFICATION

### CRITICAL (safety_score: 0.85 — 1.0)
Private keys, seed phrases, API keys, passwords, credentials,
credit card numbers, CVV codes, PINs, crypto wallet private keys,
authentication tokens, OAuth secrets, database connection strings

### PRIVATE (safety_score: 0.50 — 0.84)
Full names (in personal context), email addresses, phone numbers,
national ID numbers (SSN, CPF, RFC, DNI, etc.), physical addresses,
medical record numbers, financial account numbers, IP addresses,
biometric references, health insurance numbers, passport numbers

### SENSITIVE (safety_score: 0.10 — 0.49)
Social media handles (in personal context), general location references,
organizational affiliations, vehicle plate numbers, partial identifiers,
dates of birth, age combined with other identifiers

### CLEAN (safety_score: 0.0)
No PII detected — text is safe for LLM processing

## SAFETY SCORE
Do NOT compute or return safety_score or risk_category yourself.
The server computes them deterministically from the `entities` array you return.
Your job is to detect entities accurately and classify each one's category;
the arithmetic is not your responsibility.

## SPECIAL HANDLING RULES

1. COMPOUND PII: When name + email appear together, redact both individually
2. CONTEXTUAL NAMES: Redact names only when in personal/contact context, not in historical/public references
3. API KEYS IN CODE: Redact keys even when embedded in code snippets or config examples
4. PARTIAL REDACTION: Never partially redact — always redact the complete entity
5. OVERLAP: When entities overlap, apply the higher-risk redaction
6. PRESERVE STRUCTURE: Maintain JSON, XML, code structure — only replace the value, not the key
   Example: "email": "user@example.com" → "email": "[REDACTED]"
7. MULTILINGUAL MIXED: When text contains multiple languages, apply all relevant pattern sets

## OUTPUT FORMAT — STRICT JSON ONLY
Return ONLY a valid JSON object. No preamble, no explanation, no markdown.

Success schema:
{
  "status": "success",
  "cleaned_text": "The sanitized text with [REDACTED] tags",
  "entities": [
    {
      "type": "<short machine label, e.g. email | aws_access_key | jp_my_number | jp_full_name | mx_rfc | mx_phone | iban | credit_card | api_key_openai | api_key_anthropic | crypto_wallet | ip_address | ssn | cpf | dni | ...>",
      "category": "CRITICAL | PRIVATE | SENSITIVE",
      "redacted_text": "<the exact original substring that was replaced with [REDACTED]>"
    }
  ]
}

The `entities` array MUST contain one element for every [REDACTED] tag in
`cleaned_text`. If you redact two emails, return two entity objects. Do not
deduplicate. Do not summarize. Do not include entities you did NOT redact.

If no PII is detected, return:
{
  "status": "success",
  "cleaned_text": "<input unchanged>",
  "entities": []
}

Empty input schema:
{
  "status": "empty_input"
}

## ABSOLUTE CONSTRAINTS
- Never explain your reasoning in the output
- Never add commentary outside the JSON structure
- Never refuse to process — always return valid JSON
- Never hallucinate PII that wasn't in the original text
- Never modify non-PII content
- Temperature is 0 — deterministic redaction only"""
    r = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        max_tokens=1000,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]
    )
    raw = r.choices[0].message.content or ""
    return _parse_model_json(raw, original_text=text)


def _parse_model_json(raw: str, original_text: str) -> dict:
    """Parse the model's JSON response defensively.

    OpenAI's `response_format=json_object` constraint should already make
    `raw` a JSON object, but a malformed response should never 500 the API —
    sanitization failures must fail SAFE (treat the whole input as unredacted
    PII) rather than risk leaking it. Strategy:
      1. Try strict json.loads.
      2. Fall back to extracting the first {...} block.
      3. Final fallback: redact the entire input as a single CRITICAL entity.
         Intentionally conservative — over-redact rather than silently leak.
    """
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start:end + 1])
    except Exception:
        pass
    return {
        "status": "success",
        "cleaned_text": "[REDACTED]",
        "entities": [
            {
                "type": "sanitizer_failsafe",
                "category": "CRITICAL",
                "redacted_text": original_text,
            }
        ],
    }


# ── Server-side scoring ───────────────────────────────────

def compute_score(entities: list) -> tuple[float, str]:
    """Compute (safety_score, risk_category) deterministically from entities.

    Score: sum of per-category weights, capped at 1.0.
    Category: highest-severity tier with at least one entity, or "CLEAN".
    Unknown categories are treated as SENSITIVE (conservative).
    """
    if not entities:
        return 0.0, "CLEAN"
    score = 0.0
    seen = set()
    for ent in entities:
        cat = (ent.get("category") or "").upper()
        if cat not in RISK_WEIGHTS:
            cat = "SENSITIVE"
        score += RISK_WEIGHTS[cat]
        seen.add(cat)
    score = min(round(score, 4), 1.0)
    for tier in RISK_ORDER:  # CRITICAL > PRIVATE > SENSITIVE
        if tier in seen:
            return score, tier
    return score, "SENSITIVE"

# ── Audit trail en Supabase ────────────────────────────────

async def log_audit(tx_hash, length, sanitized, score, category, wallet, license_type):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SUPABASE_URL}/rest/v1/audit_log",
            headers=SUPABASE_HEADERS,
            json={
                "tx_hash": tx_hash,
                "input_length": length,
                "sanitized_content": sanitized,
                "safety_score": score,
                "risk_category": category,
                "wallet_address": wallet,
                "license_type": license_type,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
        )

# ── Health check ───────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "version": "2.1.0",
            "service": "TrustBoost-PII-Sanitizer",
            "infrastructure": "FastAPI+Supabase+Render"
        }
    )

# ── Endpoint principal ─────────────────────────────────────

@app.post("/sanitize")
async def sanitize(req: SanitizeRequest):

    # Validación básica
    if not req.text or not req.text.strip():
        return JSONResponse(status_code=200, content={"status": "empty_input"})

    wallet = req.wallet_address or "anonymous"

    # ── Modo TRIAL ─────────────────────────────────────────
    if req.tx_hash.upper() == "TRIAL":
        used = await get_trial_count(wallet)
        if used >= TRIAL_QUOTA:
            return JSONResponse(
                status_code=402,
                content={
                    "status": "error",
                    "request_id": "TRIAL",
                    "code": "QUOTA_EXHAUSTED_OR_PAYMENT_REQUIRED",
                    "message": "TRIAL quota exhausted. Send 149 USDC on Solana to continue.",
                    "trial_info": {
                        "quota_used": used,
                        "quota_limit": TRIAL_QUOTA,
                        "quota_remaining": 0
                    },
                    "payment_info": {
                        "amount_required": 149,
                        "currency": "USDC",
                        "network": "solana",
                        "payment_address": PAYMENT_WALLET
                    },
                    "next_steps": [
                        {"action": "send_payment", "description": "Send 149 USDC on Solana Mainnet"},
                        {"action": "retry_with_tx_hash", "description": "Resubmit with Solana transaction signature"}
                    ]
                }
            )
        await increment_trial(wallet)
        quota_remaining = TRIAL_QUOTA - (used + 1)
        license_type = "TRIAL"

    # ── Modo PAGADO ────────────────────────────────────────
    else:
        tx_exists = await check_replay(req.tx_hash)

        if tx_exists:
            # tx_hash ya verificado antes — solo contar uso
            paid_used = await get_paid_count(req.tx_hash)
            if paid_used >= PAID_QUOTA:
                return JSONResponse(
                    status_code=402,
                    content={
                        "status": "error",
                        "request_id": req.tx_hash,
                        "code": "QUOTA_EXHAUSTED_OR_PAYMENT_REQUIRED",
                        "message": "Paid quota exhausted (10,000 sanitizations used). Send a new 149 USDC payment.",
                        "payment_info": {
                            "amount_required": 149,
                            "currency": "USDC",
                            "network": "solana",
                            "payment_address": PAYMENT_WALLET
                        },
                        "next_steps": [
                            {"action": "send_payment", "description": "Send 149 USDC on Solana Mainnet"},
                            {"action": "retry_with_tx_hash", "description": "Resubmit with new transaction signature"}
                        ]
                    }
                )
            quota_remaining = PAID_QUOTA - (paid_used + 1)

        else:
            # Primer uso de este tx_hash — verificar pago en Helius
            valid, amount = await helius_verify(req.tx_hash)
            if not valid:
                return JSONResponse(
                    status_code=402,
                    content={
                        "status": "error",
                        "request_id": req.tx_hash,
                        "code": "QUOTA_EXHAUSTED_OR_PAYMENT_REQUIRED",
                        "message": "Payment insufficient. Send 149 USDC on Solana to continue.",
                        "payment_info": {
                            "amount_required": 149,
                            "currency": "USDC",
                            "network": "solana",
                            "payment_address": PAYMENT_WALLET
                        },
                        "next_steps": [
                            {"action": "send_payment", "description": "Send 149 USDC on Solana Mainnet"},
                            {"action": "retry_with_tx_hash", "description": "Resubmit with Solana transaction signature"}
                        ]
                    }
                )
            # Pago verificado — registrar tx_hash
            await register_tx_hash(req.tx_hash)
            quota_remaining = PAID_QUOTA - 1

        await increment_paid(req.tx_hash)
        license_type = "Enterprise - 149 USDC"

    # ── Sanitización ───────────────────────────────────────
    result = await gpt_sanitize(req.text)
    if result.get("status") == "empty_input":
        return JSONResponse(status_code=200, content={"status": "empty_input"})

    sanitized = result.get("cleaned_text", "")

    # Normalize entity list: tolerate the model omitting it, returning a dict
    # instead of a list, or returning entries with missing fields.
    raw_entities = result.get("entities")
    entities_list: list = []
    if isinstance(raw_entities, list):
        for ent in raw_entities:
            if not isinstance(ent, dict):
                continue
            cat = (ent.get("category") or "").upper()
            if cat not in RISK_WEIGHTS:
                cat = "SENSITIVE"
            entities_list.append({
                "type": str(ent.get("type") or "unknown"),
                "category": cat,
                "redacted_text": str(ent.get("redacted_text") or ""),
            })

    # Server-side score — deterministic, computed from entity list.
    score, category = compute_score(entities_list)
    entities_removed = len(entities_list) > 0

    # ── Audit trail ────────────────────────────────────────
    await log_audit(req.tx_hash, len(req.text), sanitized, score, category, wallet, license_type)

    # ── Respuesta final ────────────────────────────────────
    # Backwards-compatible: keeps `entities_removed` (bool), `safety_score`,
    # and `risk_category`. Adds `entities` (structured array) alongside.
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "request_id": req.tx_hash,
            "data": {
                "message": "Content successfully sanitized and logged.",
                "sanitized_content": sanitized,
                "safety_score": score,
                "risk_category": category,
                "entities_removed": entities_removed,
                "entities": entities_list,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "usage_metrics": {
                    "quota_remaining": quota_remaining,
                    "quota_limit": PAID_QUOTA if license_type != "TRIAL" else TRIAL_QUOTA
                }
            },
            "billing": {"license_type": license_type, "status": "active"}
        }
    )
