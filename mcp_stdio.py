#!/usr/bin/env python3
"""
TrustBoost MCP stdio wrapper for Glama.
Zero external dependencies — pure Python stdlib only.
"""
import sys
import json
import urllib.request
import urllib.error

API_URL = "http://localhost:8000"

def call_sanitize(text, tx_hash="TRIAL", wallet="mcp-agent"):
    payload = json.dumps({
        "text": text,
        "tx_hash": tx_hash,
        "wallet_address": wallet
    }).encode()
    req = urllib.request.Request(
        f"{API_URL}/sanitize",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("data", {}).get("sanitized_content", "")
    except Exception as e:
        return f"[BLOCKED: {str(e)}]"

def handle(request):
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "trustboost", "version": "2.6.0"}
            }
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [{
                    "name": "sanitize_pii",
                    "description": "Sanitize PII from text before sending to LLMs. Returns sanitized text with PII replaced by [REDACTED].",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "tx_hash": {"type": "string", "default": "TRIAL"},
                            "wallet_address": {"type": "string", "default": "mcp-agent"}
                        },
                        "required": ["text"]
                    }
                }]
            }
        }

    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "sanitize_pii":
            result = call_sanitize(
                args.get("text", ""),
                args.get("tx_hash", "TRIAL"),
                args.get("wallet_address", "mcp-agent")
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": result}]}
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except Exception as e:
            error = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(e)}
            }
            sys.stdout.write(json.dumps(error) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
