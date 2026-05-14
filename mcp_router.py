# mcp_router.py
# TrustBoost MCP Server — Model Context Protocol
# Exposes sanitize_pii tool to Claude, Cursor, Windsurf and any MCP-compatible agent
# Zero changes to core model. Read-only addition.

import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

# MCP Server manifest — describes available tools
MCP_MANIFEST = {
    "schema_version": "v1",
    "name": "trustboost",
    "description": "Sanitize PII from text before it reaches LLMs. Redacts emails, phone numbers, national IDs, private keys, and financial data. Supports EN, ES (LATAM), PT (BR/PT), DE, JA.",
    "tools": [
        {
            "name": "sanitize_pii",
            "description": "Detect and redact PII from text before sending to any LLM or external API. Returns sanitized text, safety score, and risk category.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text containing potential PII to sanitize."
                    },
                    "tx_hash": {
                        "type": "string",
                        "description": "Solana tx_hash for paid access. Use 'TRIAL' for 50 free sanitizations.",
                        "default": "TRIAL"
                    },
                    "wallet_address": {
                        "type": "string",
                        "description": "Your agent or wallet identifier for quota tracking.",
                        "default": "mcp-agent"
                    }
                },
                "required": ["text"]
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "sanitized_content": {"type": "string"},
                    "safety_score": {"type": "number"},
                    "risk_category": {"type": "string"},
                    "entities_removed": {"type": "boolean"}
                }
            }
        }
    ]
}


@router.get("/mcp")
async def mcp_manifest():
    """MCP Server manifest — describes available tools to agents."""
    return JSONResponse(content=MCP_MANIFEST)


@router.post("/mcp")
async def mcp_execute(request: Request):
    """Execute MCP tool calls from agents."""
    from main import gpt_sanitize, enforce_redaction, compute_score, get_trial_count, increment_trial, TRIAL_QUOTA

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    tool_name = body.get("tool")
    tool_input = body.get("input", {})

    if tool_name != "sanitize_pii":
        return JSONResponse(status_code=400, content={
            "error": f"Unknown tool: {tool_name}",
            "available_tools": ["sanitize_pii"]
        })

    text = tool_input.get("text", "").strip()
    if not text:
        return JSONResponse(content={"sanitized_content": "", "safety_score": 0.0, "risk_category": "CLEAN", "entities_removed": False})

    tx_hash = tool_input.get("tx_hash", "TRIAL").upper()
    wallet = tool_input.get("wallet_address", "mcp-agent")

    # TRIAL quota check
    if tx_hash == "TRIAL":
        used = await get_trial_count(wallet)
        if used >= TRIAL_QUOTA:
            return JSONResponse(status_code=402, content={
                "error": "TRIAL quota exhausted.",
                "message": "Send 149 USDC on Solana to continue.",
                "payment_address": "giu4VciTkfWJNG1oeP6SzHEJwmabikJSMB91GaFNWE4"
            })
        await increment_trial(wallet)

    try:
        result = await gpt_sanitize(text)
        entities = result.get("entities", [])
        sanitized, source, _ = enforce_redaction(text, result.get("cleaned_text", ""), entities)
        score, risk = compute_score(entities)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable."})

    return JSONResponse(content={
        "sanitized_content": sanitized,
        "safety_score": score,
        "risk_category": risk,
        "entities_removed": len(entities) > 0,
        "entities": entities,
        "redaction_source": source
    })
