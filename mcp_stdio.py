#!/usr/bin/env python3
"""
TrustBoost MCP stdio wrapper for Glama compatibility.
Bridges stdio MCP protocol to the HTTP FastAPI server.
"""
import sys
import json
import asyncio
import httpx

API_URL = "http://localhost:8000"

async def handle_request(request: dict) -> dict:
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
                    "description": "Sanitize PII from text before sending to LLMs.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Text to sanitize"},
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
        tool_name = params.get("name")
        tool_input = params.get("arguments", {})

        if tool_name == "sanitize_pii":
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.post(
                        f"{API_URL}/sanitize",
                        json={
                            "text": tool_input.get("text", ""),
                            "tx_hash": tool_input.get("tx_hash", "TRIAL"),
                            "wallet_address": tool_input.get("wallet_address", "mcp-agent")
                        }
                    )
                    data = r.json()
                    sanitized = data.get("data", {}).get("sanitized_content", "")
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": sanitized}]
                        }
                    }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"[BLOCKED: {str(e)}]"}],
                        "isError": True
                    }
                }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


async def main():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    writer_transport, writer_protocol = await loop.connect_write_pipe(
        asyncio.BaseProtocol, sys.stdout.buffer
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            request = json.loads(line.decode())
            response = await handle_request(request)
            if response is not None:
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
        except Exception:
            break


if __name__ == "__main__":
    asyncio.run(main())
