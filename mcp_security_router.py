# mcp_security_router.py
# TrustBoost Security Scanner — MCP Server (Model Context Protocol)
# Compatible con JSON-RPC 2.0 (Claude Code, Cursor, Windsurf, Glama)
#
# Servidor MCP separado del de mcp_router.py (que es el del producto
# original de sanitización de PII) — montado en /mcp/scan para no
# chocar con /mcp, que ya está en uso. Mismo patrón exacto, dos
# productos distintos bajo el mismo dominio.

import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

MCP_SECURITY_MANIFEST = {
    "schema_version": "v1",
    "name": "trustboost-scanner",
    "description": "Security scanner for Supabase-backed apps built with AI tools (Lovable, Bolt, Base44, Replit Agent, etc). Two tools: scan_supabase_security checks for exposed tables, leaked service_role keys, and open storage buckets. check_dependencies checks a package.json for AI-hallucinated (slopsquatted) or vulnerable npm packages.",
    "tools": [
        {
            "name": "scan_supabase_security",
            "description": "Scans a Supabase project for the most common vibe-coding security gap: missing Row Level Security, exposed storage buckets, and leaked service_role keys. Read-only — never writes or modifies anything. Input: the project's URL and its public anon key (both already visible in the app's own frontend code).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_url": {
                        "type": "string",
                        "description": "The Supabase project URL, e.g. https://xxxxx.supabase.co"
                    },
                    "anon_key": {
                        "type": "string",
                        "description": "The project's public anon key (never the service_role key)."
                    },
                    "app_url": {
                        "type": "string",
                        "description": "Optional: the deployed app's own URL. Enables an extra check for a leaked service_role key in the app's public frontend code.",
                        "default": ""
                    }
                },
                "required": ["project_url", "anon_key"]
            }
        },
        {
            "name": "check_dependencies",
            "description": "Checks a package.json for packages that look AI-hallucinated (slopsquatting risk) or have known vulnerabilities. Queries the public npm registry and OSV.dev live — never relies on a static, possibly-outdated list of known-bad packages. Input: the raw text content of a package.json file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "package_json": {
                        "type": "string",
                        "description": "The full raw text content of the project's package.json file."
                    }
                },
                "required": ["package_json"]
            }
        }
    ]
}


@router.get("/mcp/scan")
async def mcp_security_manifest():
    return JSONResponse(content=MCP_SECURITY_MANIFEST)


async def _execute_scan_supabase_security(tool_input: dict):
    from supabase_scanner import scan_project

    project_url = (tool_input.get("project_url") or "").strip()
    anon_key = (tool_input.get("anon_key") or "").strip()
    app_url = (tool_input.get("app_url") or "").strip() or None

    if not project_url or ".supabase.co" not in project_url:
        raise ValueError("INVALID_PROJECT_URL")

    report = await scan_project(project_url, anon_key, app_url=app_url)

    return {
        "project_url": report.project_url,
        "overall_severity": report.overall_severity,
        "tables_discovered": report.tables_discovered,
        "tables_with_leak": len(report.findings),
        "public_storage_buckets": report.public_storage_buckets,
        "service_role_leak": report.service_role_leak,
        "service_role_leak_source": report.service_role_leak_source,
        "missing_security_headers": report.missing_security_headers,
        "has_dmarc": report.has_dmarc,
        "details": [
            {
                "table": f.table_name,
                "severity": f.severity,
                "pii_category": f.pii_category,
            }
            for f in report.findings
        ],
    }


async def _execute_check_dependencies(tool_input: dict):
    from dependency_check import check_package_json

    package_json_text = tool_input.get("package_json", "")
    if not package_json_text.strip():
        return {"status": "error", "message": "package_json is empty."}

    return await check_package_json(package_json_text)


TOOL_EXECUTORS = {
    "scan_supabase_security": _execute_scan_supabase_security,
    "check_dependencies": _execute_check_dependencies,
}


@router.post("/mcp/scan")
async def mcp_security_execute(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    is_jsonrpc = "jsonrpc" in body and "method" in body

    if is_jsonrpc:
        method = body.get("method", "")
        request_id = body.get("id", 1)
        params = body.get("params", {})

        if method == "initialize":
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "trustboost-scanner", "version": "1.0.0"}
                }
            })

        if method == "tools/list":
            return JSONResponse(content={
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": MCP_SECURITY_MANIFEST["tools"]}
            })

        if method == "tools/call":
            tool_name = params.get("name")
            tool_input = params.get("arguments", {})

            executor = TOOL_EXECUTORS.get(tool_name)
            if not executor:
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                })

            try:
                result = await executor(tool_input)
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(result)}]
                    }
                })
            except ValueError as e:
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32602, "message": str(e)}
                })
            except Exception as e:
                print(f"[mcp_security_router] tool call failed: {type(e).__name__}: {str(e)[:200]}")
                return JSONResponse(content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": "Service temporarily unavailable."}
                })

        if method.startswith("notifications/"):
            return JSONResponse(content={})

        return JSONResponse(content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })

    else:
        # Formato simple — compatibilidad hacia atrás, mismo patrón que mcp_router.py
        tool_name = body.get("tool")
        tool_input = body.get("input", {})

        executor = TOOL_EXECUTORS.get(tool_name)
        if not executor:
            return JSONResponse(status_code=400, content={
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(TOOL_EXECUTORS.keys())
            })

        try:
            result = await executor(tool_input)
            return JSONResponse(content=result)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        except Exception as e:
            print(f"[mcp_security_router] tool call failed: {type(e).__name__}: {str(e)[:200]}")
            return JSONResponse(status_code=503, content={"error": "Service temporarily unavailable."})
