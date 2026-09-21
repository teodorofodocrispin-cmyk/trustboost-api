# Vibecode Scan — Bitácora del proyecto

> Documento de referencia. No es documentación de usuario ni de API — es la
> memoria del proyecto: qué se decidió, por qué, qué se probó y falló, y en
> qué estado quedó cada pieza. Léelo antes de retomar el proyecto después de
> un tiempo sin tocarlo, o antes de decidir un cambio grande.
>
> Última actualización: 20 de septiembre de 2026.

---

## 1. De dónde viene esto

TrustBoost nació como un motor de sanitización de PII (`/sanitize`, `/detect`,
`/redact` — los endpoints originales del proyecto siguen ahí y funcionan,
ver `main.py`). En septiembre de 2026, sin tracción de uso externo pagado
en ese producto, se decidió pivotar reutilizando el mismo motor de scoring
de PII hacia un problema más específico y con demanda visiblemente
demostrada: **apps construidas con herramientas de IA (Lovable, Bolt.new,
Base44, Replit Agent, etc.) que conectan a Supabase sin activar Row Level
Security**, dejando datos de usuarios leíbles por cualquiera.

La evidencia que sostiene el pivote (todas fuentes públicas, citables):

- **CVE-2025-48757** — 170+ apps de Lovable en producción con RLS mal
  configurado, CVSS 9.3.
- **Symbiotic Security** — 1,072 apps "vibe-coded" auditadas, 98% con al
  menos un problema de seguridad, 16% crítico.
- **Escape.tech** — 5,600 apps auditadas, 2,000+ vulnerabilidades, 400+
  secretos expuestos.
- **CodeRabbit** — 45% del código generado por IA en pull requests contiene
  una debilidad de seguridad.
- Un segundo incidente de Lovable en abril de 2026 permitió que cualquier
  cuenta gratuita leyera código fuente y credenciales de otros usuarios.

---

## 2. El modelo de negocio

**Embudo de dos pasos, pago único (no suscripción):**

1. **Free scan** (`/free-scan`, o cualquiera de las páginas `/check/{slug}`)
   — el usuario pega la URL de su proyecto Supabase y su `anon key`
   (pública, ya visible en el código de su propia app). El escaneo es
   gratis, siempre, sin excepción — **esto se aclara explícitamente en la
   página antes de que la persona escanee**, ver sección 6.
2. **Detailed report ($49, pago único)** — si el escaneo encuentra algo,
   se ofrece un reporte generado con IA que explica cada hallazgo en
   lenguaje plano y da el SQL exacto para arreglarlo.

**Decisiones descartadas, y por qué:**

- **"Fix + Verification" (remediación pagada)** — Polar.sh la rechazó por
  política (categoría de soporte técnico/reparación prohibida). Se
  reenviaron los términos sin lenguaje de remediación y esa parte del
  producto quedó **pausada indefinidamente** — el fundador tampoco se
  sentía en confianza entregando ese trabajo personalmente.
- **Monitoreo mensual recurrente** — mencionado como idea a futuro, nunca
  implementado. Si se retoma, sería la única fuente de ingreso recurrente
  del producto (hoy todo es pago único).
- **Cacería manual/automatizada de apps de terceros para investigación de
  mercado** — se intentó extensamente (ver sección 8) y se abandonó por
  no ser confiable a la escala necesaria. Se reemplazó por citar estudios
  ya publicados de terceros en el contenido de marketing.

---

## 3. Arquitectura técnica

Stack: **FastAPI + Supabase + Render**, todo en el repo
`teodorofodocrispin-cmyk/trustboost-api`, un solo `main.py` (~4,300 líneas)
con módulos auxiliares importados.

### Archivos nuevos añadidos durante este proyecto

| Archivo | Qué hace |
|---|---|
| `supabase_scanner.py` | Descubre tablas (fallback: prueba 40 nombres comunes, ya que Supabase bloqueó el mapa OpenAPI con anon key en 2026), prueba cada una con la anon key, aplica el scoring de PII ya existente (`gpt_sanitize()` + `compute_score()`, importados de `main.py`). |
| `report_generator.py` | Toma los metadatos del escaneo (nunca los valores reales de PII) y llama a OpenAI (gpt-4o-mini) para generar `overall_summary` + explicación por hallazgo (`plain_explanation`, `business_impact`, `sql_fix`). Tiene un `_fallback_report()` si OpenAI falla. |
| `usdc_verify.py` | Verifica pagos en USDC leyendo directamente la blockchain de Base (`eth_getTransactionReceipt` contra `https://mainnet.base.org`), sin depender de un indexador de terceros. Revisa que el destinatario sea `WALLET_BASE` y que el monto esté dentro de 2% de tolerancia. |
| `discover_credentials.py` | Intenta extraer automáticamente la URL y anon key de Supabase desde el código público de una app (para investigación de mercado). **Ver sección 8 — su tasa de éxito real terminó siendo muy baja** contra apps modernas con code-splitting. |
| `scan-landing.html` | La landing page original de `/free-scan`. Tema oscuro, tipografías Space Grotesk + IBM Plex Mono, logo embebido en base64. |
| `seo-template.html` | Plantilla compartida para las páginas de SEO programático (`/check/{slug}`). Ver sección 6. |
| `seo_pages_data.py` | Diccionario de contenido (título, hero, FAQ) por plataforma, consumido por la plantilla de arriba. |

### Endpoints clave añadidos (dentro de `main.py`)

| Endpoint | Qué hace |
|---|---|
| `GET /free-scan` | Sirve `scan-landing.html`. |
| `GET /check/{slug}` | Sirve dinámicamente cualquiera de las páginas de SEO, rellenando `seo-template.html` con los datos de `seo_pages_data.py`. Ver sección 6 — **esta es la única ruta que existe para todas las páginas de SEO, nunca se agregó una ruta por plataforma.** |
| `POST /scan` | Corre el escaneo gratuito real. |
| `POST /report` | Genera el reporte pagado tras verificar el pago con Polar (checkout_id). |
| `POST /report-usdc` | Genera el reporte pagado tras verificar un pago en USDC on-chain. |
| `POST /admin/scan-batch` | Escaneo en lote para investigación de mercado, protegido por header `X-Admin-Secret`. **Abandonado como estrategia — ver sección 8.** |
| `GET /admin/research-stats` | Estadísticas agregadas de `research_scans`. Mismo estado: sin usar activamente. |

### Tablas en Supabase (proyecto `furzsqnvoydwwdartkgt`)

```sql
create table scan_requests (id bigserial primary key, ip_hash text not null, created_at timestamptz default now());
create table usdc_used_hashes (tx_hash text primary key, created_at timestamptz default now());
create table research_scans (id bigserial primary key, homepage text, project_url text, tables_discovered int, tables_with_leak int, overall_severity text, public_storage_buckets jsonb, findings jsonb, created_at timestamptz default now());
```

### Variables de entorno relevantes en Render

- `ADMIN_SECRET` — protege `/admin/scan-batch` y `/admin/research-stats`.
- Las ya existentes del proyecto original (OpenAI, Supabase, wallet de pago).

---

## 4. Pagos — dos vías, ambas probadas y funcionando

### Tarjeta, vía Polar.sh
- Colombia soportada sin necesidad de entidad en EE.UU.
- Checkout: `https://buy.polar.sh/polar_cl_OTntcCWeVUMxe0jiLlgkwdJNvxDBUMD7X9nbh1srAXb`
- Cuenta de pago conectada a banco colombiano (no la cuenta USD de Littio,
  porque Stripe Connect Express exige que país/moneda de la cuenta
  coincidan).

### USDC en Base
- Wallet: `0xCf1d31020A7915421f6d66B9835Dcb6f422337E7` (`WALLET_BASE`)
- Precio: `REPORT_PRICE_USDC = "49"` en `main.py`, y `const REPORT_PRICE_USDC = 49` en el JS de la landing.
- Flujo: la página conecta la wallet del navegador (`window.ethereum`),
  cambia a la red Base, envía el pago, y el frontend hace polling a
  `/report-usdc` cada 4 segundos (hasta 10 intentos) hasta que el backend
  confirma la transacción on-chain.
- Protección contra reuso: la tabla `usdc_used_hashes` marca cada
  `tx_hash` ya usado.
- Probado end-to-end con un pago real de $0.10 antes de subir el precio a $49.

---

## 5. Transparencia de precio — un problema real que se corrigió

**Historial del problema:** la primera versión de la landing decía "FREE
SCAN" en grande, y el precio de $49 solo aparecía dentro de una sección
oculta (`display:none`) que solo se revelaba **después** de correr el
escaneo. Alguien podía compartir o promocionar la página como "gratis" sin
que un visitante nuevo tuviera forma de saber, antes de escanear, que
existía un segundo nivel de pago.

**Por qué importaba:** justo antes de detectarse, el producto se había
publicado en Hacker News, LinkedIn, X y dev.to invitando a probar la
herramienta "gratis". Un usuario sorprendido con un muro de pago no
anticipado es exactamente el tipo de queja que se vuelve pública y daña
la reputación del lanzamiento — en HN en particular, ese patrón se conoce
como "bait and switch" y se señala sin filtro.

**La corrección aplicada** (en `scan-landing.html` y `seo-template.html`,
justo debajo del título "FREE SCAN", antes de cualquier campo del
formulario):

> *"The scan itself is 100% free, always. If it finds something, a $49
> report explaining the exact fix is offered afterward — entirely
> optional, never required to see your scan result."*

El mismo texto (adaptado) se replicó también en el post de LinkedIn, que
originalmente tampoco mencionaba el precio.

**Lección para el futuro:** cualquier página o pieza de contenido nueva
que promocione "el escáner gratis" debe incluir esta misma divulgación
desde el primer vistazo, no solo después de una acción del usuario.

---

## 6. SEO programático — arquitectura y estado actual

### El problema que resolvió esta arquitectura

La primera versión de esta idea fue construir una página HTML completa
**por cada plataforma** (Lovable, Bolt, etc.), cada una un archivo de
~800 líneas casi idéntico, con su propia ruta en `main.py`. Se llegó a
construir así una sola página (`/lovable-security-check`) antes de que se
señalara correctamente el problema: escalar esto a 15-20 plataformas
habría significado 15-20 archivos duplicados y 15-20 rutas en un
`main.py` que ya tiene más de 4,000 líneas — un desastre de mantenimiento
donde cualquier cambio de diseño o de lógica del escáner habría que
repetirlo a mano en cada archivo.

### La arquitectura correcta (la que quedó implementada)

- **`seo-template.html`** — una sola plantilla HTML con tokens tipo
  `__PAGE_TITLE__`, `__META_DESCRIPTION__`, `__HERO_H1__`, `__HERO_LEDE__`,
  `__FAQ_HEADING__`, `__FAQ_ITEMS__`. Contiene el escáner, los pagos, el
  reporte y las políticas legales **una sola vez**.
- **`seo_pages_data.py`** — un diccionario Python (`SEO_PAGES`) con una
  entrada por plataforma. Cada entrada trae solo el texto que cambia.
  Incluye un helper `_build_faq()` para armar el HTML de las preguntas
  frecuentes a partir de una lista de tuplas `(pregunta, respuesta)`.
- **Una sola ruta en `main.py`**: `GET /check/{slug}`. Lee el slug de la
  URL, busca la entrada correspondiente en `SEO_PAGES`, y rellena la
  plantilla con `.replace()` (no `.format()` — el HTML/CSS/JS de la
  plantilla está lleno de llaves `{}` legítimas que romperían
  `.format()`).

**Agregar una plataforma nueva, hoy, es exactamente esto:** copiar un
bloque de `seo_pages_data.py`, cambiar el texto, subir el archivo. Cero
cambios en `main.py`, cero archivos nuevos.

### Páginas activas hoy (9 en total)

`lovable`, `bolt`, `base44`, `replit`, `v0`, `create`, `tempo`, `softgen`,
`same` — accesibles en `api.trustboost.dev/check/<slug>`.

**Nota de precisión importante:** solo la página de `lovable` cita un
incidente específico y verificable (CVE-2025-48757, y el incidente de
abril 2026). Las demás páginas (Bolt, Base44, Replit, y las 5 agregadas
después) usan lenguaje genérico citando las estadísticas agregadas
(Symbiotic Security, Escape.tech, CodeRabbit) **porque no se verificó un
incidente específico y nombrado para esas plataformas individualmente**.
Si en el futuro se encuentra un CVE o incidente específico de, por
ejemplo, Bolt.new, vale la pena actualizar esa entrada para que cite el
caso concreto — eso mejora tanto la honestidad como el SEO (Google
prioriza especificidad verificable).

### Indexación

Las 9 páginas fueron enviadas a Google Search Console (propiedad de
dominio `trustboost.dev`, verificada vía registro TXT en Namecheap — **no
borrar ese registro DNS o se pierde la verificación**) y confirmadas como
indexadas el 20 de septiembre de 2026.

---

## 7. Marketing y distribución — qué se publicó y qué pasó

| Canal | Estado | Notas |
|---|---|---|
| dev.to | Publicado | Título: *"98% of Vibe-Coded Apps Have a Security Flaw — I Scanned My Own First, Then Built a Free Tool to Check Yours"*. Hashtags: `#security #supabase #ai #webdev`. |
| X (Twitter) | Publicado | Hilo de 5 tweets + un tweet corto separado con hashtags `#Supabase #VibeCoding #BuildInPublic`. |
| LinkedIn | Publicado | Corregido para incluir la divulgación de precio (ver sección 5). |
| Hacker News | Publicado, marcado `[flagged]` | Post honesto, sin infracciones de las guidelines detectadas — probablemente el filtro automático de HN contra cuentas nuevas publicando un link a producto propio. Se envió un correo a `hn@ycombinator.com` pidiendo revisión (20 de septiembre). **Sin respuesta al momento de escribir esto.** Lección: no vale la pena pelear por reflotar un post específico marcado así — construir karma orgánico primero (comentar genuinamente en otros posts) antes de un segundo intento. |
| Google Search Console | Configurado | Propiedad de dominio verificada, 9 URLs enviadas a indexación y confirmadas indexadas. |

### Descartado explícitamente

- **Reddit** — la cuenta del fundador corre riesgo de ban permanente ahí, se evita.
- **Ads pagados (Google/X)** — quedaron como opción documentada pero no
  activada; se decidió no gastar dinero en adquisición hasta tener
  ingresos propios para reinvertir.
- **Automatización de marketing con agentes de IA** — se investigó qué
  herramientas existen (n8n, Zapier AI Agents, Typefully, etc.) pero no
  se implementó nada — quedó como algo a considerar más adelante, no
  como parte del lanzamiento inicial.

---

## 8. El experimento fallido: cazar apps de terceros para investigación de mercado

Vale la pena documentar esto en detalle porque costó mucho tiempo y la
lección es reutilizable.

**El objetivo original:** escanear ~50 apps reales de terceros (Lovable,
Bolt, etc.) para generar una estadística propia ("escaneamos 50 apps, el
X% tenía un problema") para usar como gancho de marketing.

**Por qué falló, en orden de intento:**

1. **Buscar apps vía directorios de lanzamiento** (Fazier, PeerPush,
   Product Hunt) — funcionó parcialmente para encontrar URLs candidatas,
   pero fue lento (requirió `web_fetch` manual página por página).
2. **`discover_credentials.py` (descubrimiento automático de credenciales
   vía scraping del HTML + scripts)** — de 15 apps candidatas, **0 dieron
   resultado**, incluyendo dos que confirmaban explícitamente usar
   Supabase en su propia descripción. Causa raíz: las apps modernas
   (React/Vite) cargan la mayoría de su código en fragmentos que el
   navegador solo pide **después de ejecutar JavaScript** — un scraper
   que solo descarga el HTML crudo nunca ve esos fragmentos. Se mejoró
   el script (más scripts revisados, User-Agent de navegador real, límite
   de tamaño más generoso) — **la mejora no cambió el resultado**, porque
   el problema es estructural, no de configuración.
3. **Snippet de consola del navegador** (pegar JS en DevTools para que el
   propio navegador del usuario, que ya ejecutó todo el JS, revele las
   credenciales) — técnicamente más sólido, pero seguía sin encontrar
   nada en el caso probado (NotesQR), probablemente porque la página
   raíz era solo el marketing/landing y la app real vivía en otra ruta
   o subdominio.
4. **Búsqueda de credenciales expuestas en GitHub** (`filename:.env
   SUPABASE_ANON_KEY`) — no se llegó a probar a fondo; GitHub bloquea el
   fetch automatizado de sus páginas de búsqueda, y además activamente
   escanea y revoca secretos expuestos, por lo que el rendimiento
   esperado de esta vía también es bajo.

**La decisión final:** abandonar la generación de una estadística propia
a partir de apps de terceros, y en su lugar **citar estudios ya
publicados por terceros** (Symbiotic Security, Escape.tech, CodeRabbit,
CVE-2025-48757) — exactamente lo que terminó usándose en todo el
contenido de marketing.

**Si en el futuro se quiere retomar esto:** la única vía que tiene
sentido técnico es usar un navegador real automatizado (Playwright/
Puppeteer) que ejecute el JavaScript de cada sitio antes de buscar las
credenciales — el enfoque de solo descargar HTML con `httpx` está
descartado, ya se probó a fondo y no funciona contra apps modernas.

---

## 9. Proyecciones financieras (modelo de escenarios, no predicción)

Se construyó un modelo de tres escenarios (conservador / medio / exitoso)
a 3, 6 y 12 meses, basado en supuestos de tráfico y conversión — **no en
datos reales**, porque el producto se lanzó públicamente el mismo día que
se construyó el modelo. Los números:

| Escenario | Mes 3 | Mes 6 | Mes 12 |
|---|---|---|---|
| Conservador | ~5 reportes ($245) | ~12 ($588) | ~25 ($1,225) |
| Medio | ~20 ($980) | ~55 ($2,695) | ~150 ($7,350) |
| Exitoso | ~100 ($4,900) | ~300 ($14,700) | ~700 ($34,300) |

**En cuanto existan las primeras 5-10 ventas reales, este modelo debe
reemplazarse por uno basado en la tasa de conversión real observada**, no
en estos supuestos genéricos.

---

## 10. Pendientes abiertos al momento de escribir esto

1. Verificar si Hacker News responde al correo de revisión del post
   marcado `[flagged]`.
2. Seguir el rendimiento en Search Console (indexación real vs. enviada,
   y primeras búsquedas que traigan tráfico).
3. Decidir si se agregan más páginas de SEO (candidatas no usadas aún:
   Windsurf, Cursor — aunque ninguna de las dos conecta a Supabase por
   defecto de la misma forma, revisar si el encuadre aplica antes de
   crearlas).
4. Considerar retomar la idea de monitoreo mensual recurrente si el
   pago único no genera suficiente volumen.
5. El botón "Copy" en el reporte pagado tenía un problema de superposición
   visual con el texto del código — pendiente de confirmar si ya se
   arregló.
6. Dominio `scan.trustboost.dev` (CNAME) — mencionado como opción, nunca
   configurado; no es urgente mientras todo viva en `api.trustboost.dev`.

---

## 11. Diferenciación frente a la competencia (20 de septiembre de 2026)

**La pregunta que originó esto:** ¿un usuario buscaría este modelo, existe
competencia, y podría alguien simplemente hacer este mismo escaneo gratis
con IA o con otra herramienta en vez de pagar $49?

**Lo que se investigó y confirmó:**

- **Supabase tiene su propio "Security Advisor" gratis**, integrado en el
  dashboard de cada proyecto (Database → Security Advisor), basado en un
  linter de código abierto llamado Splinter. Detecta tablas sin RLS,
  políticas débiles y columnas sensibles expuestas — con soluciones de un
  clic. Manda además correos semanales automáticos si hay problemas.
  **Esto no es un competidor nuevo — ya existía, gratis, antes de este
  producto.**
- Existe además competencia indirecta más pequeña: al menos un
  desarrollador independiente ofrece un checker gratis similar (basado en
  pegar SQL manualmente) y otro vende un kit pago para bugs más profundos
  de lógica de RLS (políticas que se cancelan entre sí, membresías mal
  aisladas) que ni Supabase ni este producto detectan hoy.
- **Técnicamente, sí, alguien con conocimiento de programación podría
  pedirle a una IA que le escriba un script** que use su propia anon key
  para probar nombres de tabla comunes — es exactamente lo que hace
  `supabase_scanner.py`, no hay nada mágico ahí.

**Por qué el negocio sigue siendo viable a pesar de esto:** el 63% de
quienes hacen "vibe coding" no tiene formación de programación (dato de
la sección de investigación de mercado). Esa persona no sabe qué es un
"anon key", no sabría pedirle correctamente el script a una IA, no
verificaría si el resultado está bien hecho, y — el punto más importante —
**probablemente ni siquiera sabe que el Security Advisor de Supabase
existe**, porque la promesa completa de herramientas como Lovable o
Bolt.new es que el usuario nunca necesite abrir un dashboard técnico.

**La conclusión, y por qué importa distinguirla bien:** la ventaja de este
producto **no es la detección** (Supabase ya la resuelve gratis para quien
sepa buscarla) — es la **distribución y la traducción**: llegar, vía SEO
y contenido, a la mayoría no técnica del mercado que jamás abriría el
dashboard de Supabase por su cuenta, y explicarle el hallazgo en lenguaje
simple con el SQL exacto para copiar y pegar, en vez de una lista técnica
de "Error/Warning/Info" que asume que sabes leer SQL.

**Cambios aplicados como resultado (en `scan-landing.html`,
`seo-template.html` y `seo_pages_data.py`):**

1. Un cuarto ítem de confianza en la primera pantalla de las 10 páginas
   (`/free-scan` + las 9 de `/check/{slug}`): *"No SQL or dashboard
   needed"*.
2. Una pregunta nueva en el FAQ de las 9 páginas de SEO, reconociendo
   abiertamente que Supabase tiene su propio Security Advisor gratis y
   explicando la diferencia de audiencia y de formato.
3. Una sección de FAQ que no existía antes en `scan-landing.html` (la
   página principal), con esa misma pregunta más "¿esto toca mi código o
   mis datos?" — para que esta honestidad no viva solo en las páginas de
   nicho.

**Por qué se decidió decirlo primero, en vez de omitirlo:** mencionar la
existencia del Security Advisor de Supabase antes de que alguien lo
señale en un comentario público (por ejemplo en Hacker News) genera más
confianza que si pareciera que se estaba ocultando. Es la misma lógica
que ya se aplicó con la transparencia de precio (sección 5).

**Si en el futuro se quiere profundizar la diferenciación real, no solo
la de mensaje:** la vía más sólida sería agregar detección de los casos
que ni Supabase ni este producto cubren hoy — bugs de *lógica* de RLS
(políticas permisivas que cancelan una restrictiva, membresías de
organización mal aisladas), no solo "RLS está apagado o encendido". Eso
sí sería una ventaja técnica real, no solo de audiencia.

---

## 12. Fase 1 de diferenciación técnica — construida y verificada en producción (20 de septiembre de 2026)

Implementado y confirmado funcionando en vivo, en este orden:

1. **Detección de service_role key filtrado** (`supabase_scanner.py`):
   decodifica el JWT (sin verificar firma, solo lee el claim `role`) tanto
   de la key que el usuario pega como, opcionalmente, del código público de
   su app si da su `app_url`. Si detecta `service_role` en la key pegada,
   **no continúa con el escaneo normal** — evita el falso positivo masivo
   que se daría al probar tablas con una key que salta todo RLS. Probado
   en producción pegando una key de prueba: veredicto CRÍTICO correcto,
   cero tablas escaneadas, tal como se diseñó.
2. **Mapeo de cumplimiento** (`report_generator.py`): cada hallazgo del
   reporte pagado ahora incluye una nota de qué marco de cumplimiento
   (GDPR Art. 32, SOC 2 CC6.1, ISO 27001 A.9) aplicaría. El hallazgo de
   service_role usa texto fijo (no gasta llamada a OpenAI, ya que es
   siempre el mismo problema).
3. **Reporte en PDF descargable** (`scan-landing.html` / `seo-template.html`):
   botón "Download PDF" vía `html2pdf.js` (CDN), con ID único de reporte
   (`TB-2026-XXXX`) y diseño en el tema oscuro de la marca.

**Detalle técnico importante para el futuro:** `main.py` tenía un bug
preexistente (no introducido en esta sesión) — usaba `HTTPException` en
dos lugares (`/check/{slug}` y `/admin/scan-batch`) sin haberlo importado
nunca de `fastapi`. Se corrigió al mismo tiempo que se conectó `app_url`
a los tres endpoints de escaneo (`/scan`, `/report`, `/report-usdc`).

**Pendiente de la Fase 2** (documentado en la sección 5 del research
original): lógica real de políticas RLS (no solo si existen), buckets de
Storage sin política, Edge Functions sin verificar JWT, y headers de
seguridad generales (CSP, rate limiting, DMARC).

---

## 13. Fase 2 de diferenciación técnica (parcial) — headers de seguridad y DMARC (20 de septiembre de 2026)

Segunda tanda de chequeos, agregados a `supabase_scanner.py` y conectados
a `main.py` + al frontend (`scan-landing.html` / `seo-template.html`).
Solo corren si el usuario dio su `app_url` opcional (igual que el chequeo
de service_role del frontend en la Fase 1).

1. **Headers de seguridad faltantes** (`check_security_headers`): revisa
   si la respuesta HTTP de `app_url` trae `Content-Security-Policy`,
   `Strict-Transport-Security` y `X-Frame-Options`. Sin credenciales, solo
   lee headers públicos. Probado en vivo contra github.com: 0 headers
   faltantes (correcto, GitHub sí los tiene).
2. **DMARC** (`check_dmarc`): revisa si el dominio tiene un registro TXT
   en `_dmarc.<dominio>` usando el DNS-over-HTTPS de Google
   (`https://dns.google/resolve`) — sin agregar ninguna librería nueva de
   DNS al proyecto. Sin DMARC, cualquiera puede enviar correos de phishing
   que parezcan venir del dominio del usuario.

**Cómo se presentan:** ambos aparecen en el resultado del escaneo gratuito
como una caja separada, marcada explícitamente como "informational, don't
affect severity above" — a propósito NO suman a la severidad
CRÍTICA/PRIVADA del hallazgo principal, para no diluir la señal del
problema real (RLS/datos expuestos) con ruido de menor prioridad.

**Limitación de verificación:** el chequeo de DMARC no se pudo probar en
vivo durante esta sesión — el entorno de desarrollo usado no tiene acceso
de red a `dns.google`. Es una restricción del entorno de pruebas, no del
código; debe confirmarse una vez desplegado en Render (que sí tiene
acceso completo a internet).

**Lo que queda pendiente de la Fase 2 original** (no se abordó en esta
tanda): lógica real de políticas RLS (probar si una política mal escrita
deja pasar datos pese a estar "activada"), buckets de Storage con
políticas mal configuradas más allá de "público sí/no", y Edge Functions
sin verificación de JWT al inicio. Vale la pena abordarlo en una sesión
dedicada, ya que requiere lógica de prueba más elaborada que un chequeo
de presencia/ausencia.

---

## 14. Segunda tanda de páginas SEO indexadas + primera interacción técnica de comunidad (21 de septiembre de 2026)

**5 páginas de SEO más agregadas** a `seo_pages_data.py`, siguiendo el
mismo patrón genérico (sin incidentes específicos inventados): Cursor,
Windsurf, Emergent, Databutton, Rork. Total acumulado: **14 páginas**
(`/check/{slug}`), todas heredando automáticamente el aviso de precio,
la diferenciación frente a Supabase, y los chequeos de las Fases 1 y 2,
al venir de la misma plantilla compartida.

**5 de las páginas ya fueron confirmadas como indexadas por Google
Search Console** — primera señal real de que el flujo de SEO
programático + Search Console (secciones 6 y 11) está funcionando de
punta a punta, desde la publicación hasta la indexación real, no solo
en teoría.

**Primer comentario técnico real en el artículo de dev.to**, de un
usuario identificado como Cenk Kurtoğlu (usuario `cekuu35`) — vale la
pena registrar quién es, porque no es un lector cualquiera: es un
**competidor directo** que vende un "Supabase RLS Audit Kit" ($29) y
mantiene un repo gratuito (`github.com/cekuu35/supabase-rls-leak-demo`)
con contenido técnico muy activo en dev.to y en discusiones de GitHub de
Supabase y Next.js — la misma estrategia de distribución que estamos
usando aquí, pero enfocada específicamente en bugs de lógica de RLS.

Su comentario señaló, con precisión técnica correcta, los dos casos que
un escáner de caja negra (como el nuestro) **no puede ver estructuralmente**:
una política que existe pero no restringe nada real (ej. `to authenticated
using (true)`), y un join entre tenants sin aislar donde el filtro vive en
el cliente, no en la base de datos. Ambos casos pasan un chequeo de
endpoint limpio porque la anon key sí puede leer los datos — es
exactamente la misma limitación ya documentada en la sección 11 como la
ventaja técnica real pendiente de construir.

Se respondió el comentario reconociendo el punto sin exagerar gratitud,
siendo explícito sobre el límite actual del escaneo de caja negra (mejor
decirlo que ocultarlo), y sin promocionar su kit pago dentro de la
respuesta — la información pública que compartió ya tiene valor propio,
no hace falta darle más tráfico del que se ganó él mismo.

---

## 15. Análisis de lógica de políticas RLS — explorado y pospuesto conscientemente (21 de septiembre de 2026)

A raíz del comentario técnico de Cenk Kurtoğlu (sección 14) y su repo
`supabase-rls-leak-demo`, se investigó cómo construir la ventaja técnica
real pendiente desde la sección 11: detectar si una política RLS que
*existe* realmente restringe algo, no solo si está activada.

**Lo que se confirmó investigando su repositorio:** ninguno de sus
productos es un escáner automático en vivo — todo es DIY (un kit de $29
que el usuario corre él mismo) o revisión manual humana ($15-29, 24
horas de espera). El query que necesita esa profundidad
(`select ... from pg_policies`) requiere acceso directo a Postgres, algo
que la anon key no puede dar — por eso ni Supabase ni Cenk lo
automatizan desde afuera.

**Dos caminos técnicos se diseñaron para resolverlo:**

1. **Personal Access Token de Supabase (por escaneo, nunca guardado)** —
   la app corre el query por el usuario vía la Management API de
   Supabase (`POST /v1/projects/{ref}/database/query`), evitando que el
   usuario toque SQL directamente. Detecta ambos bugs que señaló Cenk
   (política permisiva sin restricción real, aislamiento roto entre
   tenants) con precisión, leyendo el SQL real de las políticas.
2. **Cuentas de prueba (email + password, una o dos)** — en vez de leer
   el SQL, se inicia sesión como un usuario de prueba (algo que la anon
   key sí puede hacer) y se compara qué puede leer cada cuenta. Detecta
   los mismos dos bugs por comportamiento real, sin necesitar que el
   usuario entienda qué es un token. No detecta el bug de escritura
   (falta de `WITH CHECK`), que es el menos común de los dos.

**Por qué NO existe una opción sin pedirle nada al usuario:** se
consideró explícitamente si el producto podría alojar un "token general"
para evitarle este paso a cada usuario. No es posible — cada proyecto de
Supabase pertenece a una cuenta distinta, con credenciales distintas;
un token universal que diera acceso a cualquier proyecto sería
exactamente el tipo de fuga masiva que este producto existe para
prevenir. Siempre va a hacer falta que la persona entregue algo propio,
específico a su proyecto, cada vez.

**La decisión final: posponerlo, no descartarlo.** Ninguna de las dos
vías (token o cuentas de prueba) se sintió lo bastante libre de fricción
para la audiencia objetivo (mayoritariamente no-técnica, según la
sección de investigación de mercado) frente al valor de un solo
comentario técnico como señal de demanda. Se decidió **no construir
esto todavía** y esperar evidencia real de que los usuarios lo piden,
en vez de agregar fricción a un producto que ya funciona basándose en
una sola señal externa.

**Si se retoma en el futuro, el orden de preferencia queda así:**
cuentas de prueba primero (menos fricción conceptual, cubre el bug más
común) — el Personal Access Token queda como opción secundaria si se
necesita también el chequeo de escritura (`WITH CHECK`).

---

## 16. Meta de 20 páginas de SEO alcanzada (21 de septiembre de 2026)

Se agregaron las últimas 6 plataformas (Glide, Retool, Softr, FlutterFlow,
Bubble, Adalo) a `seo_pages_data.py`, completando las **20 páginas** de
`/check/{slug}` que se habían propuesto como meta. Las 20 fueron
confirmadas indexadas en Google Search Console el mismo día — sin
retraso notable frente a las tandas anteriores.

Lista completa de slugs activos: `lovable`, `bolt`, `base44`, `replit`,
`v0`, `create`, `tempo`, `softgen`, `same`, `cursor`, `windsurf`,
`emergent`, `databutton`, `rork`, `glide`, `retool`, `softr`,
`flutterflow`, `bubble`, `adalo`.

**Nota de investigación relevante (misma sesión):** se investigó la
posibilidad de un programa formal de partners de seguridad con Lovable,
Bolt.new u otras plataformas — no se encontró ninguno activo. No es una
vía cerrada para siempre, pero no hay una puerta abierta hoy; no vale
la pena invertir tiempo ahí por ahora.

**Idea de crecimiento identificada, aún no construida — el badge
embebible de confianza:** investigación de mercado confirmó que los
"trust badges" (sellos de seguridad visibles) suben la conversión de
sitios que los muestran entre 12% y 42% (Baymard Institute, Blue
Fountain Media, ConversionXL). Snyk construyó exactamente este modelo
para librerías de código abierto — un badge embebible con calificación
A-F y link "dofollow" de vuelta a Snyk — y llegó a $300M ARR usándolo
como motor de distribución, además de la mejora de conversión que le da
a quien lo embebe.

La idea para TrustBoost: cualquiera que escanee su app y salga limpio
podría recibir un badge "Scanned by TrustBoost — No issues found" para
poner en su propio landing page, con link a una página pública de
verificación (`trustboost.dev/verified/{scan_id}`). Cada embed sería
simultáneamente (1) más confianza para los visitantes de esa app, (2) un
link de vuelta a TrustBoost, y (3) exposición de marca en cada app de
vibe coding que lo use — el mismo ciclo que uso Snyk.

**Por qué no se construyó todavía:** requiere una tabla nueva en
Supabase para persistir cada escaneo con un ID único, una página pública
de verificación, y un generador de badge en SVG — más trabajo de
ingeniería que las mejoras anteriores, y se decidió esperar confirmación
explícita antes de construirlo. Sigue pendiente de decisión.

---

## 17. Badge de confianza embebible — construido, con un bug real, y verificado en producción (21 de septiembre de 2026)

Construido a partir de la investigación de la sección 16 (Snyk, trust badges,
12-42% de aumento en conversión medido en estudios independientes).

**Arquitectura implementada:**

1. **Tabla `badge_scans` en Supabase** — un registro por escaneo 100% limpio
   (`scan_id` UUID, `app_url` opcional, `tables_scanned`, `created_at`). Solo
   se crea una fila cuando `overall_severity == "OK"` Y no hay service_role
   leak Y no hay buckets públicos — nunca se emite un badge para algo que no
   esté genuinamente limpio.
2. **`GET /badge/{scan_id}.svg`** — genera el badge como SVG a mano (mismo
   patrón visual que usa Snyk), sin depender de ninguna librería ni servicio
   externo. Cachea 1 hora.
3. **`GET /verified/{scan_id}`** — página pública de verificación, con la
   fecha del escaneo, cuántas tablas se revisaron, y un aviso honesto de que
   es un escaneo puntual, no una garantía permanente ni una certificación.
4. **Frontend**: cuando `/scan` devuelve `badge_scan_id`, aparece una caja
   verde con el badge y un botón "Copy embed code" que da el snippet
   completo (`<a href="/verified/...">` envolviendo el `<img src="/badge/...">`)
   — el link es lo que le da valor SEO real a cada embed, no solo la imagen.

**El bug real que se encontró y corrigió:** el primer intento de registrar
un escaneo limpio falló con error 401 / código Postgres `42501`: *"new row
violates row-level security policy for table badge_scans"*. La tabla se
había creado con RLS activado por defecto (típico al usar el editor visual
de Supabase en vez del SQL Editor) pero sin ninguna política que permitiera
insertar filas — bloqueando incluso al propio backend. Se corrigió con:

```sql
alter table badge_scans disable row level security;
```

Justificación de por qué desactivar RLS aquí es seguro: esta tabla nunca se
expone a un cliente externo directamente — solo el propio backend la lee y
escribe, con la misma llave que ya usan `audit_log` y `scan_requests`.

**Diagnóstico usado para encontrar el bug:** se agregó un log temporal en
`register_clean_scan()` (`print(f"[register_clean_scan] FALLÓ: status=...
body=...")`) que expuso el error exacto de Supabase en los logs de Render.
Esa línea sigue en el código — no hace daño dejarla, solo genera una línea
de log en el caso (ahora raro) de que el registro vuelva a fallar.

**Verificado en producción, de punta a punta:** escaneo real y limpio del
propio proyecto de TrustBoost (40 tablas revisadas, 0 hallazgos) generó
correctamente `badge_scan_id`, la caja verde apareció en el frontend, y
`https://api.trustboost.dev/verified/{scan_id}` carga la página real con
el sello "✓ Verified Secure", la fecha, el conteo de tablas, y el link de
vuelta a `/free-scan`.

**Lección reutilizable para futuras tablas nuevas:** al crear una tabla
nueva en Supabase para que el propio backend la use (nunca expuesta al
público), verificar de entrada si quedó con RLS activado sin política —
mismo patrón de error que ya causó este bug, y podría repetirse en la
próxima tabla que se agregue sin este chequeo explícito.

---

## Cómo actualizar este documento

Cuando se tome una decisión de negocio o de arquitectura (no un simple
arreglo de bug), agrega una entrada aquí — decisión + fecha + por qué —
en la sección que corresponda. Este documento es para leerlo antes de
decidir un cambio, no para llevar el registro de cada commit; el
historial de Git ya hace eso.
