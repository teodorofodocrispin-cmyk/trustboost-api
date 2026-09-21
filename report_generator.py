"""
report_generator.py

Convierte el resultado crudo de supabase_scanner.py en un reporte legible
para humanos, con explicación en lenguaje simple + SQL exacto de arreglo
por cada tabla encontrada.

PRIVACIDAD — esto es lo más importante del archivo:
Al modelo de IA SOLO le mandamos metadatos (nombre de tabla, severidad,
categoría, nombres de columnas, cuántas filas se vieron). NUNCA le
mandamos los valores reales de las filas (los emails, nombres, etc. que
encontró el escáner). Eso protege al dueño del proyecto Y a las personas
cuyos datos aparecieron ahí — ni nosotros ni OpenAI necesitan verlos para
generar el reporte.

Reusa el mismo cliente y patrón que ya usa gpt_sanitize() en main.py
(modelo gpt-4o-mini, json_object, fail-closed si OpenAI no responde).
"""

import json
from dataclasses import asdict


REPORT_SYSTEM_PROMPT = """You are a security engineer writing a report for a non-expert founder whose app was built with an AI tool (Lovable, Bolt, Base44) on top of Supabase.

You will receive a JSON list of findings. Each finding has: table name, severity (CRITICAL or PRIVATE), pii_category, how many sample rows were readable, and the column names of that table (never the actual data values).

For EACH finding, write in the SAME language as the table/column names look like they're targeting (default to English unless names look Spanish/Portuguese), producing:
- "plain_explanation": 2-3 sentences a non-technical founder can understand, explaining what this specific finding means in practice.
- "business_impact": 1-2 sentences on realistic consequences (e.g. "any visitor can read your users' data" / "competitors could scrape your customer list").
- "sql_fix": the exact PostgreSQL statements to enable RLS and add a reasonable policy for this table. If a column looks like a user/owner identifier (user_id, owner_id, created_by, auth_id, etc.), write a policy scoped to auth.uid() matching that column. Otherwise, default to a policy that only allows access to authenticated users, and add a one-line SQL comment noting the founder should tighten it further based on their actual access rules.
- "compliance_note": one short sentence naming which compliance frameworks this specific finding would likely fail under, if the founder's users are covered by them (choose from: GDPR Article 32 "security of processing", SOC 2 CC6.1 "logical access controls", ISO 27001 A.9 "access control", CCPA "reasonable security procedures" — pick whichever applies, or write "No specific compliance framework typically applies to this finding" if genuinely none do, e.g. for non-personal data).

Also write one "overall_summary": 2-3 sentences summarizing the scan results as a whole, in a calm, non-alarmist tone.

Respond ONLY as a JSON object with this exact shape:
{
  "overall_summary": "...",
  "findings": [
    {"table": "...", "plain_explanation": "...", "business_impact": "...", "sql_fix": "...", "compliance_note": "..."}
  ]
}
"""

SERVICE_ROLE_LEAK_FINDING_TEMPLATE = {
    "table": "⚠ service_role key",
    "plain_explanation": (
        "Your Supabase service_role key was found exposed where any visitor's browser can read it. "
        "This is not the same as the public anon key — the service_role key bypasses every Row Level "
        "Security policy you have, meaning it grants full read, write, and delete access to your "
        "entire database, no matter how your tables are configured."
    ),
    "business_impact": (
        "Anyone who finds this key has the same level of access as you do as the project owner — "
        "they could read, modify, or delete any data in your project, not just the tables this scan checked."
    ),
    "sql_fix": (
        "-- This is not fixable with a SQL policy change.\n"
        "-- 1. Go to Supabase Dashboard -> Project Settings -> API.\n"
        "-- 2. Click \"Reset\" next to the service_role key to rotate it immediately.\n"
        "-- 3. Remove it from any client-side code, .env files committed to git, or public repos.\n"
        "-- 4. The service_role key should only ever be used in a trusted server environment, never in browser-facing code."
    ),
    "compliance_note": (
        "GDPR Article 32 (security of processing), SOC 2 CC6.1 (logical access controls), and ISO 27001 A.9 "
        "would all treat this as a critical control failure — it is the equivalent of exposing a database "
        "administrator password."
    ),
}


def _findings_to_payload(scan_report) -> list[dict]:
    """Extrae SOLO metadatos de cada hallazgo — nunca los valores reales."""
    payload = []
    for f in scan_report.findings:
        payload.append({
            "table": f.table_name,
            "severity": f.severity,
            "pii_category": f.pii_category,
            "rows_sample_count": f.sample_rows_returned,
            "column_names": f.column_names,
        })
    for bucket in scan_report.public_storage_buckets:
        payload.append({
            "table": f"storage:{bucket}",
            "severity": "PRIVATE",
            "pii_category": "N/A",
            "rows_sample_count": 0,
            "column_names": [],
        })
    return payload


async def generate_report(scan_report, openai_client) -> dict:
    """
    scan_report: el objeto ScanReport que devuelve supabase_scanner.scan_project()
    openai_client: el mismo cliente ya inicializado en main.py

    Devuelve un dict con 'overall_summary' y 'findings' (cada uno con
    explicación + SQL + nota de cumplimiento). Si OpenAI falla, devuelve
    un reporte de respaldo simple generado sin IA, para nunca dejar al
    cliente sin nada después de haber pagado.
    """
    findings_payload = _findings_to_payload(scan_report)

    # El hallazgo de service_role key filtrado tiene texto fijo y no
    # depende de IA — es siempre el mismo problema con la misma solución,
    # así que lo agregamos directo, sin gastar una llamada a OpenAI en él.
    service_role_finding = None
    if getattr(scan_report, "service_role_leak", False):
        service_role_finding = dict(SERVICE_ROLE_LEAK_FINDING_TEMPLATE)

    if not findings_payload and not service_role_finding:
        return {
            "overall_summary": "No open tables or public storage buckets were found in this scan.",
            "findings": [],
        }

    if not findings_payload:
        return {
            "overall_summary": "A leaked service_role key was found — this is the most critical finding possible and is explained below.",
            "findings": [service_role_finding],
        }

    try:
        r = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=2200,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": REPORT_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(findings_payload)}
            ]
        )
        raw = r.choices[0].message.content or "{}"
        report = json.loads(raw)
        if "findings" not in report:
            raise ValueError("malformed report shape")
    except Exception as e:
        print(f"[generate_report] OpenAI call failed, using fallback: {type(e).__name__}: {str(e)[:150]}")
        report = _fallback_report(findings_payload)

    if service_role_finding:
        report["findings"] = [service_role_finding] + report.get("findings", [])

    return report


def _fallback_report(findings_payload: list[dict]) -> dict:
    """Reporte de respaldo sin IA — genérico pero honesto, para no dejar
    al cliente sin nada si OpenAI falla justo cuando pagó."""
    findings = []
    for f in findings_payload:
        id_col = next(
            (c for c in f["column_names"] if c.lower() in ("user_id", "owner_id", "created_by", "auth_id")),
            None
        )
        if id_col:
            sql = (
                f'ALTER TABLE public."{f["table"]}" ENABLE ROW LEVEL SECURITY;\n'
                f'CREATE POLICY "owner_only" ON public."{f["table"]}"\n'
                f'  FOR SELECT USING (auth.uid() = {id_col});'
            )
        else:
            sql = (
                f'ALTER TABLE public."{f["table"]}" ENABLE ROW LEVEL SECURITY;\n'
                f'CREATE POLICY "authenticated_only" ON public."{f["table"]}"\n'
                f'  FOR SELECT USING (auth.role() = \'authenticated\');\n'
                f'-- Review: tighten this further based on your actual access rules.'
            )
        findings.append({
            "table": f["table"],
            "plain_explanation": f"This table was readable by anyone, without logging in.",
            "business_impact": "Anyone with your public URL could read this data.",
            "sql_fix": sql,
            "compliance_note": "GDPR Article 32 and SOC 2 CC6.1 both require restricting access to personal data — an openly readable table would typically fail either.",
        })
    return {
        "overall_summary": f"{len(findings)} table(s) were found readable without authentication.",
        "findings": findings,
    }
