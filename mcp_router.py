# mcp_router.py
# TrustBoost MCP Server — Model Context Protocol
# Compatible with JSON-RPC 2.0 (Claude Code, Cursor, Windsurf, Glama)

import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

MCP_MANIFEST = {
    "schema_version": "v1",
    "name": "trustboost",
    "description": "Sanitize PII from text before it reaches LLMs. Redacts emails, phone numbers, national IDs, private keys, and financial data. Supports EN, ES (LATAM), PT (BR/PT), DE, JA.",
    "tools": [
        {
            "name": "sanitize_pii",
            "description": "Detect and redact PII from text before sending to any LLM or external API.",
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
            }
        }
    ]
}


@router.get("/mcp")
async def mcp_manifest():
    return JSONResponse(content=MCP_MANIFEST)


async def _execute_sanitize(tool_input: dict):
    from main import gpt_sanitize, enforce_redaction, compute_score, get_trial_count, increment_trial, TRIAL_QUOTA

    text = tool_input.get("text", "").strip()
    if not text:
        return {"sanitized_content": "", "safety_score": 0.0, "risk_category": "CLEAN", "entities_removed": False}

    tx_hash = tool_input.get("tx_hash", "TRIAL").upper()
    wallet = tool_input.get("wallet_address", "mcp-agent")

    if tx_hash == "TRIAL":
        used = await get_trial_count(wallet)
        if used >= TRIAL_QUOTA:
            raise Exception("QUOTA_EXHAUSTED")
        await increment_trial(wallet)

    result = await gpt_sanitize(text)
    entities = result.get("entities", [])
    sanitized, source, _ = enforce_redaction(text, result.get("cleaned_text", ""), entities)
    score, risk = compute_score(entities)

    return {
        "sanitized_content": sanitized,
        "safety_score": score,
        "risk_category": risk,
        "entities_removed": len(entities) > 0,
        "entities": entities,
        "redaction_source": source
    }


@router.post("/mcp")
async def mcp_execute(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    # Detectar formato — JSON-RPC 2.0 o formato simple
    is_jsonrpc = "jsonrpc" in body and "method" in body

    if is_jsonrpc:
        # Formato estándar MCP — Claude Code, Cursor, Glama
        method = body.get("method", "")
        request_id = body.get("id", 1)
        params = body.get("params", {})

        # Inicialización del servidor MCP
        if method == "initialize":
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "trustboost", "version": "2.2.0"}
                }
            })

        # Lista de herramientas disponibles
        if method == "tools/list":
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": MCP_MANIFEST["tools"]}
            })

        # Llamada a herramienta
        if method == "tools/call":
            tool_name = params.get("name")
            tool_input = params.get("arguments", {})

            if tool_name != "sanitize_pii":
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                })

            try:
                result = await _execute_sanitize(tool_input)
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result)}]
                    }
                })
            except Exception as e:
                if "QUOTA_EXHAUSTED" in str(e):
                    return JSONResponse(content={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": "TRIAL quota exhausted. Send 149 USDC on Solana.",
                            "data": {"payment_address": "giu4VciTkfWJNG1oeP6SzHEJwmabikJSMB91GaFNWE4"}
                        }
                    })
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": "Service temporarily unavailable."}
                })

        # Notificaciones — no requieren respuesta
        if method.startswith("notifications/"):
            return JSONResponse(content={})

        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })

    else:
        # Formato simple — compatibilidad hacia atrás
        tool_name = body.get("tool")
        tool_input = body.get("input", {})

        if tool_name != "sanitize_pii":
            return JSONResponse(status_code=400, content={
                "error": f"Unknown tool: {tool_name}",
                "available_tools": ["sanitize_pii"]
            })

        try:
            result = await _execute_sanitize(tool_input)
            return JSONResponse(content=result)
        except Exception as e:
            if "QUOTA_EXHAUSTED" in str(e):
                return JSONResponse(status_code=402, content={
                    "error": "TRIAL quota exhausted.",
                    "payment_address": "giu4VciTkfWJNG1oeP6SzHEJwmabikJSMB91GaFNWE4"
                })
            return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable."})
