import os
import json
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from pydantic import BaseModel
from dotenv import load_dotenv

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
app = FastAPI(title="TrustBoost PII Sanitizer v2.0")

SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

class SanitizeRequest(BaseModel):
    text: str
    tx_hash: str
    wallet_address: Optional[str] = None

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
    system_prompt = """Role: You are the "TrustBoost AI Sanitizer," a high-performance security layer for Autonomous Agents.
Objective: Scan the provided text, replace sensitive data with [REDACTED], and categorize the security threat.
Language Protocol: Detect language automatically. Return cleaned_text in SAME language as input.
Apply country-specific PII patterns:
- Spanish LATAM: RFC, CUIT, CUIL, RUT, DNI, CURP, Cedula, RUC
- Portuguese Brazil/Portugal: CPF, CNPJ, RG, NIF, NUS
- German: Personalausweis, Steuernummer, IBAN DE, Reisepass
- Japanese: マイナンバー, 運転免許証, パスポート番号, 住所
Risk: CRITICAL=keys/passwords/cards. PRIVATE=emails/IDs/phones. SENSITIVE=handles/locations.
Output ONLY valid JSON: {"status":"success","cleaned_text":"...","entities_removed":true,"safety_score":0.0,"risk_category":"CRITICAL"}
If empty input: {"status":"empty_input"}"""
    r = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        max_tokens=1000,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]
    )
    return json.loads(r.choices[0].message.content)

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
            "version": "2.0.0",
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
    score = float(result.get("safety_score", 0.0))
    category = result.get("risk_category", "SENSITIVE")
    entities = result.get("entities_removed", False)

    # ── Audit trail ────────────────────────────────────────
    await log_audit(req.tx_hash, len(req.text), sanitized, score, category, wallet, license_type)

    # ── Respuesta final ────────────────────────────────────
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
                "entities_removed": entities,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "usage_metrics": {
                    "quota_remaining": quota_remaining,
                    "quota_limit": PAID_QUOTA if license_type != "TRIAL" else TRIAL_QUOTA
                }
            },
            "billing": {"license_type": license_type, "status": "active"}
        }
    )
