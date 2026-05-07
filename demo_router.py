# demo_router.py
# Marketing endpoint — /sanitize/preview
# Zero changes to core model. Read-only addition.

import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
import httpx
import os

router = APIRouter()

_rate_store: dict = {}

PREVIEW_LIMIT = 3
WINDOW_HOURS = 24
COOLDOWN_HOURS = 4

INTERNAL_SANITIZE_URL = "http://localhost:8000/sanitize"
TRIAL_URL = "https://github.com/teodorofodocrispin-cmyk/TrustBoost-PII-Sanitizer#trial"
TRIAL_TX = os.getenv("TRIAL_TX_HASH", "TRIAL")


class PreviewRequest(BaseModel):
    text: str


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


def _check_rate_limit(ip: str) -> tuple[bool, bool]:
    now = datetime.utcnow()
    record = _rate_store.get(ip)

    if record is None:
        _rate_store[ip] = {"count": 1, "window_start": now, "cooldown_until": None}
        return True, False

    if record["cooldown_until"] and now < record["cooldown_until"]:
        return False, True

    if now - record["window_start"] > timedelta(hours=WINDOW_HOURS):
        _rate_store[ip] = {"count": 1, "window_start": now, "cooldown_until": None}
        return True, False

    if record["count"] < PREVIEW_LIMIT:
        record["count"] += 1
        return True, False

    record["cooldown_until"] = now + timedelta(hours=COOLDOWN_HOURS)
    return False, True


@router.post("/sanitize/preview")
async def sanitize_preview(payload: PreviewRequest, request: Request):
    ip = _get_client_ip(request)
    allowed, in_cooldown = _check_rate_limit(ip)

    if in_cooldown:
        await asyncio.sleep(14400)
        raise HTTPException(status_code=429, detail={
            "message": "Preview limit reached.",
            "next": TRIAL_URL
        })

    if not allowed:
        raise HTTPException(status_code=429, detail={
            "message": "Preview limit reached.",
            "next": TRIAL_URL
        })

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                INTERNAL_SANITIZE_URL,
                json={"text": payload.text, "tx_hash": TRIAL_TX, "wallet_address": "preview"}
            )
            result = response.json()
        except Exception:
            raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    ip_record = _rate_store.get(ip, {})
    remaining = max(0, PREVIEW_LIMIT - ip_record.get("count", 0))

    return {
        "sanitized_content": result.get("sanitized_content", ""),
        "safety_score": result.get("safety_score", 0.0),
        "risk_category": result.get("risk_category", "UNKNOWN"),
        "demo": True,
        "requests_remaining": remaining,
        "next": TRIAL_URL
    }
