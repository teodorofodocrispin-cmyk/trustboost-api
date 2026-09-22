# TrustBoost — Descripción completa del producto

> A diferencia de `VIBECODE_SCAN_STATE.md` (la bitácora cronológica de
> decisiones), este documento explica **qué es el producto hoy**, sin
> importar cómo se llegó ahí. Léelo si necesitas entender TrustBoost de
> punta a punta sin repasar la historia completa de su construcción —
> por ejemplo, para explicárselo a alguien nuevo, o para retomar el
> proyecto después de un tiempo sin tocarlo.
>
> Última actualización: 22 de septiembre de 2026.

---

## 1. Qué es, en una frase

TrustBoost es un escáner de seguridad gratuito para aplicaciones
construidas con herramientas de IA (Lovable, Bolt.new, Base44, Replit
Agent, y otras) sobre Supabase, que detecta si la base de datos está
exponiendo información a cualquier visitante sin que el dueño de la
app lo sepa — y vende, como upsell opcional, un reporte detallado con
la explicación en lenguaje simple y el SQL exacto para arreglarlo.

---

## 2. La necesidad de mercado

### 2.1 El problema técnico de fondo

Las herramientas de "vibe coding" generan aplicaciones completas a
partir de instrucciones en lenguaje natural, conectándolas casi
siempre a una base de datos Supabase. Supabase exige que el
desarrollador active explícitamente **Row Level Security (RLS)** y
escriba las políticas de quién puede leer qué — un paso que la IA
generadora, optimizada para "que la app funcione", frecuentemente
omite. El resultado: una base de datos completamente pública, legible
por cualquiera que conozca la URL del proyecto y su llave pública
(`anon key`) — algo que cualquier visitante del navegador ya tiene
acceso a ver, sin necesitar hackear nada.

### 2.2 La evidencia de que esto es real y frecuente, no un caso aislado

- **CVE-2025-48757** — 170+ apps de Lovable con RLS mal configurado,
  CVSS 9.3.
- **Taimur Khan (The Register, feb. 2026)** — una sola app de Lovable
  (para exámenes/notas escolares) expuso 18,697 registros de usuarios,
  incluyendo estudiantes de UC Berkeley y UC Davis, posiblemente
  menores de edad.
- **Moltbook (Wiz Security, CVE-2026-2256, ene. 2026)** — red social
  para agentes de IA con RLS completamente desactivado, expuso 1.5
  millones de tokens de autenticación y 35,000 correos.
- **Symbiotic Security** — 1,072 apps "vibe-coded" auditadas, 98% con
  al menos un problema de seguridad.
- **Escape.tech** — 5,600 apps auditadas, 2,000+ vulnerabilidades,
  400+ secretos expuestos.
- **Veracode (2026)** — 100+ modelos de IA probados en 80 tareas: 45%
  del código generado tiene vulnerabilidades del OWASP Top-10, sin
  mejora en 2 años pese a modelos más nuevos.
- **Andrej Karpathy**, quien acuñó el término "vibe coding", declaró
  que solo es apto para "proyectos de fin de semana desechables" —
  nunca para producción.

### 2.3 Por qué esto no se resuelve solo

Supabase sí tiene una herramienta gratuita propia (**Security
Advisor**, dentro del dashboard del proyecto) que detecta lo mismo.
Pero el **63% de quienes hacen vibe coding no tiene formación de
programación** (dato de investigación de mercado) — esa persona nunca
abre un dashboard técnico de Supabase, porque la promesa completa de
herramientas como Lovable es que nunca tenga que hacerlo. El problema
no es la falta de una herramienta — es que la herramienta que ya
existe nunca llega a quien más la necesita.

### 2.4 El tamaño y la forma del mercado

- Mercado de vibe coding: ~$4.5B en 2026, proyectado a $12.3B en 2027.
- Solo Lovable agrega ~1 millón de proyectos nuevos por semana (50
  millones acumulados) — un flujo de gente nueva con el mismo miedo,
  constantemente, no una lista fija que se agota.
- **60.5%** de quienes hacen vibe coding aún no monetiza lo que
  construyó — sin presupuesto para una auditoría tradicional de
  $2,000-5,000. Un precio de $49, pago único, es lo que esa audiencia
  específica sí puede pagar sin pensarlo dos veces.

---

## 3. El modelo de negocio

Embudo de dos pasos, sin suscripción obligatoria:

1. **Escaneo gratuito** (`/free-scan` o cualquiera de las 20 páginas de
   `/check/{plataforma}`) — el usuario pega la URL de su proyecto
   Supabase y su `anon key` pública. Resultado en menos de un minuto,
   sin registro.
2. **Reporte detallado ($49, pago único)** — si el escaneo encuentra
   algo, un reporte generado con IA explica cada hallazgo en lenguaje
   simple, con el SQL exacto para arreglarlo y su mapeo a marcos de
   cumplimiento (GDPR, SOC 2, ISO 27001).

Si el escaneo sale **100% limpio**, el usuario recibe gratis un
**badge de confianza embebible** para su propio sitio (ver sección 6.5).

**Descartado deliberadamente:** un tier de "arreglo + verificación"
(Polar.sh lo rechazó por política, y el fundador no se sentía en
confianza entregando ese trabajo personalmente) y el análisis profundo
de lógica de políticas RLS (técnicamente posible, pero exige pedirle
al usuario un dato adicional — un token o una cuenta de prueba — y se
decidió no agregar esa fricción sin evidencia de que los usuarios lo
pidan).

---

## 4. Cómo funciona, de punta a punta (experiencia del usuario)

1. La persona llega a una de las 21 páginas de entrada (`/free-scan` o
   una de las 20 de `/check/{slug}`), típicamente porque buscó algo
   como "is my lovable app safe" y encontró la página por SEO.
2. Ve, antes de escanear nada, un aviso explícito: el escaneo es
   gratis siempre; si encuentra algo, hay un reporte de $49 opcional
   — nunca oculto.
3. Pega su Supabase project URL y su anon key (ambos ya visibles en el
   código de su propia app). Opcionalmente, la URL de su app (para el
   chequeo extra de service_role key filtrado) y marca la casilla de
   consentimiento ("soy el dueño, o tengo autorización explícita").
4. En ~10-30 segundos ve el resultado: severidad (OK/PRIVATE/CRITICAL),
   cuántas tablas se revisaron, y el detalle de cualquier hallazgo.
5. **Si salió limpio:** aparece la opción de generar un badge gratis
   para su sitio, con un link de verificación público.
6. **Si encontró algo:** puede pagar $49 (tarjeta vía Polar, o USDC en
   Base conectando su wallet) para desbloquear el reporte completo.
7. Tras pagar, ve el reporte en pantalla, un botón de **descarga de
   PDF real** (generado en el servidor, un clic, sin diálogos), y una
   caja destacada con un **link permanente** para volver a acceder al
   reporte en cualquier momento — incluso si cierra la pestaña. El PDF
   mismo también incluye ese link de rescate en su pie de página.

---

## 5. Arquitectura técnica — mapa completo

### 5.1 Stack

FastAPI (Python) + Supabase (Postgres + Auth + Storage) + Render
(hosting), todo en un solo repositorio:
`teodorofodocrispin-cmyk/trustboost-api`.

### 5.2 Archivos del proyecto y su propósito

| Archivo | Qué hace |
|---|---|
| `main.py` | El backend completo — todas las rutas HTTP, incluidas las heredadas del producto original de sanitización de PII (x402, MCP, agent discovery) y las nuevas de este pivote |
| `supabase_scanner.py` | El escáner en sí: descubre tablas, prueba lectura anónima, detecta service_role key filtrado, chequea storage público, headers de seguridad, y DMARC |
| `report_generator.py` | Genera el reporte pagado con IA (OpenAI gpt-4o-mini) — explicación en lenguaje simple, impacto de negocio, SQL de arreglo, y nota de cumplimiento por cada hallazgo |
| `report_pdf.py` | Genera el PDF real del reporte, en el servidor, con `xhtml2pdf` — sin depender del navegador del usuario |
| `tb_logo_base64.txt` | El logo real de TrustBoost, incrustado en base64, usado en el PDF |
| `seo_pages_data.py` | Diccionario con el contenido (título, texto de bienvenida, preguntas frecuentes) de cada una de las 20 páginas de SEO |
| `scan-landing.html` | La página principal (`/free-scan`) — formulario, animación de escaneo, resultado, y reporte pagado |
| `seo-template.html` | La plantilla compartida por las 20 páginas de `/check/{slug}` — idéntica a `scan-landing.html` en toda la parte funcional, solo cambia el texto de bienvenida |
| `discover_credentials.py` | Módulo de investigación de mercado (intento de descubrir credenciales de apps de terceros automáticamente) — **abandonado como estrategia**, ver `VIBECODE_SCAN_STATE.md` sección 8 |
| `usdc_verify.py` | Verifica pagos en USDC leyendo la blockchain de Base directamente |
| `demo_router.py`, `mcp_router.py`, `mcp_stdio.py`, `x402_direct_verify.py` | Heredados del producto original de sanitización de PII — sin relación directa con el escáner de seguridad, pero coexisten en el mismo servidor |

### 5.3 Las rutas HTTP relevantes al escáner de seguridad

| Ruta | Método | Qué hace |
|---|---|---|
| `/free-scan` | GET | Página principal del escáner |
| `/check/{slug}` | GET | Cualquiera de las 20 páginas de SEO (ver lista completa en sección 7) |
| `/scan` | POST | Corre el escaneo gratuito, devuelve severidad + hallazgos + (si salió limpio) un `badge_scan_id` |
| `/report` | POST | Genera el reporte pagado (flujo de tarjeta vía Polar) |
| `/report-usdc` | POST | Genera el reporte pagado (flujo de USDC en Base) |
| `/report/{report_id}` | GET | Página web permanente para volver a ver un reporte ya pagado |
| `/report/{report_id}/pdf` | GET | Descarga el PDF real del reporte, generado on-demand desde los datos guardados |
| `/badge/{scan_id}.svg` | GET | El badge embebible, como imagen SVG |
| `/verified/{scan_id}` | GET | Página pública de verificación de un escaneo limpio |
| `/admin/scan-batch`, `/admin/research-stats` | POST/GET | Herramientas de investigación de mercado, protegidas por `X-Admin-Secret` — sin uso activo actualmente |

### 5.4 Tablas en Supabase (proyecto `furzsqnvoydwwdartkgt`)

```sql
create table scan_requests (id bigserial primary key, ip_hash text not null, created_at timestamptz default now());
create table usdc_used_hashes (tx_hash text primary key, created_at timestamptz default now());
create table research_scans (id bigserial primary key, homepage text, project_url text, tables_discovered int, tables_with_leak int, overall_severity text, public_storage_buckets jsonb, findings jsonb, created_at timestamptz default now());

create table badge_scans (
  scan_id uuid primary key default gen_random_uuid(),
  app_url text,
  tables_scanned int,
  created_at timestamptz default now()
);
alter table badge_scans disable row level security;

create table paid_reports (
  report_id uuid primary key default gen_random_uuid(),
  project_url text,
  overall_severity text,
  overall_summary text,
  findings jsonb,
  payment_line text,
  created_at timestamptz default now()
);
alter table paid_reports disable row level security;
```

**Regla obligatoria para cualquier tabla nueva de uso interno del
backend (nunca expuesta directamente a clientes externos):** siempre
incluir `alter table <nombre> disable row level security;` en la misma
sentencia de creación. Este bug (RLS activado sin política) ya ocurrió
dos veces (`badge_scans`, `paid_reports`) antes de convertirse en
regla explícita.

### 5.5 Variables de entorno relevantes en Render

Las ya existentes del producto original (OpenAI, Supabase, wallet de
pago) más `ADMIN_SECRET` (protege las rutas de `/admin/*`).

### 5.6 Dependencias añadidas específicamente para el escáner

`xhtml2pdf==0.2.20` — elegida deliberadamente por ser Python puro, sin
dependencias de sistema (Pango/Cairo), para evitar sorpresas de
"funciona en local pero no en Render".

---

## 6. Los cuatro sistemas que diferencian a TrustBoost

### 6.1 Detección de service_role key filtrado

Decodifica el JWT (sin verificar firma, solo lee el claim `role`) de
la key que el usuario pega y, opcionalmente, del código público de su
app. Si detecta `service_role` en la key pegada, **no continúa con el
escaneo normal** — evita el falso positivo masivo que se daría al
probar tablas con una key que salta todo RLS, y devuelve de una vez el
hallazgo más grave posible.

### 6.2 Mapeo de cumplimiento

Cada hallazgo del reporte pagado incluye una nota de qué marco de
cumplimiento (GDPR Art. 32, SOC 2 CC6.1, ISO 27001 A.9) aplicaría —
algo que ningún competidor investigado ofrece en su reporte.

### 6.3 Chequeos adicionales (headers + DMARC)

Si el usuario da la URL de su app, se revisan además headers de
seguridad HTTP (CSP, HSTS, X-Frame-Options) y si el dominio tiene un
registro DMARC — informativo, no afecta la severidad principal.

### 6.4 Reporte en PDF real + persistencia permanente

El reporte pagado se guarda con un ID único y puede volver a
descargarse o consultarse en cualquier momento vía
`/report/{report_id}` — resolviendo el riesgo de que alguien pague y
pierda su reporte si cierra la pestaña. El PDF se genera en el
servidor (no en el navegador), con diseño propio (fondo blanco, azul y
dorado corporativos, logo real).

### 6.5 Badge de confianza embebible

Inspirado en el modelo de Snyk para librerías de código abierto:
cualquier escaneo 100% limpio genera un badge SVG + una página pública
de verificación con link "dofollow" de vuelta a TrustBoost. Cada embed
es simultáneamente prueba de confianza para los visitantes de esa app
y tráfico/autoridad de dominio de vuelta a TrustBoost — el mismo
mecanismo que ayudó a Snyk a escalar a $300M ARR.

---

## 7. Las 20 páginas de SEO — la estrategia de distribución principal

Arquitectura: **una sola plantilla** (`seo-template.html`) + **un
diccionario de datos** (`seo_pages_data.py`) + **una sola ruta**
(`/check/{slug}`) — agregar una plataforma nueva es solo agregar una
entrada al diccionario, sin tocar código.

Plataformas activas: `lovable`, `bolt`, `base44`, `replit`, `v0`,
`create`, `tempo`, `softgen`, `same`, `cursor`, `windsurf`, `emergent`,
`databutton`, `rork`, `glide`, `retool`, `softr`, `flutterflow`,
`bubble`, `adalo`.

Todas indexadas en Google Search Console (propiedad de dominio
`trustboost.dev`, verificada vía registro TXT en Namecheap — nunca
borrar ese registro o se pierde la verificación).

---

## 8. Distribución más allá del SEO

| Canal | Estado |
|---|---|
| dev.to | Publicado — artículo citando las estadísticas de mercado |
| X (Twitter) | Publicado — hilo + tweets cortos individuales |
| LinkedIn | Publicado |
| Hacker News | Post original marcado `[flagged]` (el clasificador de HN detectó texto generado por LLM — regla estricta específica de esa plataforma). De aquí en adelante, cualquier texto para HN debe escribirse a mano, sin ayuda de IA |
| PeerPush | En cola de publicación gratuita, posición #3539, ~2 meses de espera estimada |

---

## 9. Quiénes son los competidores reales (investigado, no supuesto)

- **Vibe App Scanner (VAS)** — ~$500/mes en ingresos verificados por
  Stripe, mismo modelo (free scan → $19 reporte → $99/mes monitoreo).
- **SecureMyVibes** — mismo modelo, €15/€19.
- **VibeDoctor, UNPWNED, VibeLint** — competidores más pequeños,
  encontrados en PeerPush.
- **Cenk Kurtoğlu (`supabase-rls-leak-demo`)** — vende un kit DIY de
  $29 y revisión manual de $15-29; comentó en el artículo de dev.to
  señalando correctamente el hueco de lógica de políticas RLS que
  TrustBoost aún no cubre.
- **`supasec`, `RLSGuard`, `ship-safe`, `supashield`** — herramientas
  CLI/código abierto que revisan el código o las migraciones SQL
  *antes* de desplegar (modelo "shift-left"), en vez de escanear una
  app ya en producción.
- **Supabase Security Advisor** — la herramienta gratuita de la propia
  Supabase, dentro de su dashboard técnico.

**La diferenciación real de TrustBoost no es técnica — es de
audiencia y de traducción.** Todo lo anterior asume que quien lo usa
sabe programar, sabe qué es RLS, o está dispuesto a tocar una terminal
o un dashboard técnico. TrustBoost está diseñado explícitamente para
la mayoría no técnica de este mercado (63% de los vibe coders, según
la investigación), que nunca usaría ninguna de esas herramientas.

---

## 10. Lo que se decidió NO construir (por ahora), y por qué

- **Análisis de lógica de políticas RLS** (detectar una política que
  existe pero no restringe nada real) — técnicamente posible, pero
  exige pedirle al usuario un token de administración o cuentas de
  prueba, agregando fricción a un producto pensado para gente no
  técnica. Pospuesto hasta tener evidencia real de que los usuarios lo
  piden.
- **Calificación por letra (A+ a F)**, inspirada en SSL Labs/Snyk —
  buena idea, pero es una mejora de presentación sobre algo (el badge)
  cuya adopción real aún no se ha medido. Pospuesta hasta tener datos
  de uso.
- **Servidor MCP propio** — considerado tras revisar un informe
  externo que sugería pivotar hacia ahí; se descartó como *reemplazo*
  del modelo actual (ese sub-nicho también está poblado: `RLSGuard`,
  `ship-safe`, `supashield` ya lo hacen), pero queda como una
  extensión razonable a futuro, dado que el resto del negocio de Iv ya
  tiene infraestructura MCP funcionando.
- **Programa formal de partners con Lovable/Bolt** — investigado, no
  existe ninguno abierto actualmente.

---

## 11. Cómo actualizar este documento

Este documento describe el estado actual, no la historia. Cuando algo
cambie de forma permanente (una arquitectura nueva, un canal
descontinuado, un precio distinto), actualiza la sección
correspondiente aquí. El *por qué* y el *cuándo* de cada decisión
siguen viviendo en `VIBECODE_SCAN_STATE.md` — no dupliques ese detalle
aquí, solo refleja el resultado final.
