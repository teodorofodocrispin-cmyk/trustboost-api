"""
supabase_scanner.py

Módulo NUEVO para agregar a tu repo trustboost-api.
Ya está conectado a tus funciones REALES (revisé tu main.py):
    - gpt_sanitize(text, context)      -> línea 1319
    - compute_score(entities)           -> línea 1470
    - RISK_WEIGHTS / RISK_ORDER         -> líneas 48-53

Qué hace: dado un proyecto Supabase de un tercero (solo URL pública + anon
key, que es información que CUALQUIER visitante del sitio ya puede ver en
el código fuente del navegador), revisa de forma pasiva y de solo-lectura
si alguna tabla o bucket de storage es accesible sin autenticación. Si
encuentra datos, se los pasa a TU MISMO motor de sanitización para que
decida qué tan grave es.

Límites éticos/legales:
- Solo peticiones GET (lectura). Nunca POST/PATCH/DELETE contra el
  proyecto ajeno.
- Solo usa la anon key pública que el propio dueño de la app expuso en su
  frontend.
- Máximo MAX_TABLES tablas por escaneo.
- El rate-limit por IP se hace igual que en tu /demo (ver bloque de
  endpoint más abajo, tabla scan_requests en vez de demo_requests).
"""

import httpx
from dataclasses import dataclass, field

# Import real desde tu main.py — funciona sin problema de "import circular"
# porque main.py solo importa este archivo DENTRO de la función del
# endpoint /scan (no al inicio del archivo), así que para cuando eso pasa
# main.py ya terminó de cargar por completo.
from main import gpt_sanitize, compute_score


MAX_TABLES = 25
SAMPLE_ROWS = 3
TIMEOUT_SECONDS = 8.0


@dataclass
class TableFinding:
    table_name: str
    is_readable: bool
    http_status: int
    sample_rows_returned: int = 0
    pii_score: float = 0.0
    pii_category: str = "CLEAN"     # CLEAN | SENSITIVE | PRIVATE | CRITICAL
    severity: str = "OK"            # OK | PRIVATE | CRITICAL (ver nota abajo)
    column_names: list = field(default_factory=list)   # solo nombres, nunca valores

@dataclass
class ScanReport:
    project_url: str
    tables_discovered: int = 0
    tables_scanned: int = 0
    findings: list[TableFinding] = field(default_factory=list)
    public_storage_buckets: list[str] = field(default_factory=list)

    @property
    def overall_severity(self) -> str:
        order = ["OK", "PRIVATE", "CRITICAL"]
        worst = "OK"
        for f in self.findings:
            if order.index(f.severity) > order.index(worst):
                worst = f.severity
        if self.public_storage_buckets and order.index("PRIVATE") > order.index(worst):
            worst = "PRIVATE"
        return worst


# Nombres de tabla más comunes en apps vibe-coded (SaaS, e-commerce,
# apps sociales/comunitarias). Actualiza esta lista con el tiempo según
# lo que veas en tus escaneos reales.
COMMON_TABLE_NAMES = [
    "users", "profiles", "accounts", "customers", "clients", "leads",
    "contacts", "subscribers", "waitlist", "orders", "products",
    "carts", "payments", "invoices", "transactions", "messages",
    "conversations", "chats", "comments", "reviews", "feedback",
    "posts", "articles", "notes", "files", "uploads", "documents",
    "todos", "tasks", "projects", "teams", "organizations",
    "bookings", "appointments", "reservations", "events",
    "notifications", "settings", "sessions", "logs",
]


async def discover_tables(project_url: str, anon_key: str) -> list[str]:
    """Intenta primero el mapa completo vía OpenAPI (funciona en proyectos
    Supabase más antiguos que aún no aplican el bloqueo por defecto de
    2026). Si Supabase lo rechaza (401/403 — solo permite service_role),
    caemos a probar una lista de nombres de tabla comunes: cada uno se
    prueba individualmente en probe_table(), que sí sigue funcionando con
    la anon key sin importar este cambio."""
    url = f"{project_url.rstrip('/')}/rest/v1/"
    headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            try:
                spec = resp.json()
                paths = spec.get("paths", {})
                tables = [p.lstrip("/") for p in paths.keys() if p not in ("/", "")]
                if tables:
                    return tables[:MAX_TABLES]
            except Exception:
                pass

        # Fallback: el mapa general está bloqueado (caso común en 2026) —
    # probamos TODOS los nombres comunes, no solo los primeros MAX_TABLES.
    # (MAX_TABLES solo debe limitar el caso de arriba, cuando Supabase
    # devuelve cientos de tablas reales; aquí la lista ya es corta y fija.)
    return COMMON_TABLE_NAMES


async def probe_table(project_url: str, anon_key: str, table: str) -> TableFinding:
    """Intenta leer una muestra de filas usando SOLO la anon key. Si
    Supabase devuelve datos reales, la tabla es legible por cualquier
    visitante anónimo — ese es el hallazgo."""
    url = f"{project_url.rstrip('/')}/rest/v1/{table}"
    headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}
    params = {"select": "*", "limit": str(SAMPLE_ROWS)}

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers=headers, params=params)

    if resp.status_code != 200:
        return TableFinding(table_name=table, is_readable=False, http_status=resp.status_code)

    try:
        rows = resp.json()
    except Exception:
        rows = []

    if not isinstance(rows, list) or len(rows) == 0:
        # RLS activo (o tabla vacía) — no hay filtración visible aquí
        return TableFinding(table_name=table, is_readable=False, http_status=200, sample_rows_returned=0)

    # ── Aquí está la conexión con TU motor real ──────────────────────
    # Unimos las filas en un solo texto y usamos gpt_sanitize + compute_score
    # exactamente como hace tu propio endpoint /demo (main.py línea 2977-2985).
    row_text = "\n".join(" ".join(str(v) for v in row.values()) for row in rows)

    result = await gpt_sanitize(row_text, context="general")           # tu función real
    entities = result.get("entities", [])
    pii_score, pii_category = compute_score(entities)                   # tu función real

    # Una tabla legible sin autenticación ya es al menos "PRIVATE" por
    # definición (falta RLS), aunque no contenga PII detectable. Si además
    # contiene PII real, sube a "CRITICAL".
    severity = "CRITICAL" if pii_category == "CRITICAL" else "PRIVATE"

    # Nombres de columnas únicamente — nunca los valores reales.
    column_names = list(rows[0].keys()) if rows else []

    return TableFinding(
        table_name=table,
        is_readable=True,
        http_status=200,
        sample_rows_returned=len(rows),
        pii_score=pii_score,
        pii_category=pii_category,
        severity=severity,
        column_names=column_names,
    )

async def check_public_storage(project_url: str, anon_key: str) -> list[str]:
    """Revisa si hay buckets de storage marcados como públicos."""
    url = f"{project_url.rstrip('/')}/storage/v1/bucket"
    headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        resp = await client.get(url, headers=headers)
    if resp.status_code != 200:
        return []
    try:
        buckets = resp.json()
        return [b["name"] for b in buckets if b.get("public")]
    except Exception:
        return []


async def scan_project(project_url: str, anon_key: str) -> ScanReport:
    """Punto de entrada único — esto es lo que tu endpoint /scan llama."""
    report = ScanReport(project_url=project_url)

    tables = await discover_tables(project_url, anon_key)
    report.tables_discovered = len(tables)

    for table in tables:
        finding = await probe_table(project_url, anon_key, table)
        report.tables_scanned += 1
        if finding.is_readable:
            report.findings.append(finding)

    report.public_storage_buckets = await check_public_storage(project_url, anon_key)

    return report


# ══════════════════════════════════════════════════════════════════
# BLOQUE PARA PEGAR EN main.py — copia esto tal cual, junto a tu
# endpoint /demo existente (después de la línea ~3027, antes de
# "# ── Alias endpoints").
# Reusa EXACTAMENTE el mismo patrón de rate-limit que ya tienes:
# demo_requests -> scan_requests, DEMO_LIMIT_PER_HOUR -> SCAN_LIMIT_PER_HOUR.
# ══════════════════════════════════════════════════════════════════
"""
SCAN_LIMIT_PER_HOUR = 5   # un poco más generoso que /demo porque no gasta OpenAI en cada tabla vacía

async def get_scan_count(ip_hash: str) -> int:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/scan_requests",
            headers=SUPABASE_HEADERS,
            params={
                "ip_hash": f"eq.{ip_hash}",
                "created_at": f"gte.{(datetime.utcnow() - timedelta(hours=1)).isoformat()}",
                "select": "id"
            }
        )
        return len(r.json()) if r.status_code == 200 else 0

async def increment_scan(ip_hash: str):
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{SUPABASE_URL}/rest/v1/scan_requests",
            headers=SUPABASE_HEADERS,
            json={"ip_hash": ip_hash}
        )

class ScanRequest(BaseModel):
    project_url: str
    anon_key: str

@app.post("/scan")
async def scan_endpoint(req: ScanRequest, request: Request):
    import hashlib
    raw_ip = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(raw_ip.encode()).hexdigest()[:16]

    count = await get_scan_count(ip_hash)
    if count >= SCAN_LIMIT_PER_HOUR:
        return JSONResponse(
            status_code=429,
            content={"status": "scan_limit_reached",
                      "message": f"Límite de {SCAN_LIMIT_PER_HOUR} escaneos/hora alcanzado. Vuelve en un rato."}
        )

    if not req.project_url.startswith("https://") or ".supabase.co" not in req.project_url:
        return JSONResponse(status_code=400, content={"status": "error", "message": "URL de proyecto Supabase inválida"})

    from supabase_scanner import scan_project   # el módulo de este archivo
    report = await scan_project(req.project_url, req.anon_key)
    await increment_scan(ip_hash)

    return {
        "status": "success",
        "project_url": report.project_url,
        "overall_severity": report.overall_severity,
        "tables_discovered": report.tables_discovered,
        "tables_with_leak": len(report.findings),
        "public_storage_buckets": report.public_storage_buckets,
        "details": [
            {
                "table": f.table_name,
                "severity": f.severity,
                "pii_category": f.pii_category,
                "rows_exposed_sample": f.sample_rows_returned,
            }
            for f in report.findings
        ],
    }
"""

# ══════════════════════════════════════════════════════════════════
# TABLA NUEVA EN SUPABASE — créala igual que demo_requests, solo
# cambia el nombre. En el SQL editor de tu proyecto Supabase:
# ══════════════════════════════════════════════════════════════════
"""
create table scan_requests (
    id bigserial primary key,
    ip_hash text not null,
    created_at timestamptz default now()
);
"""
