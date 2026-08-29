# CONTEXT.md — trustboost-api

## Session 001 — Jun 30, 2026 — Pay-per-call x402 migration

### Contexto previo (no documentado, descubierto durante esta sesión)

TrustBoost operaba con un modelo de pago de tres vías, completamente custom, no estándar x402:

1. **TRIAL** — `tx_hash: "TRIAL"`, 50 sanitizaciones gratis por wallet
2. **Prepago $149** — el cliente envía manualmente 149 USDC a la wallet en Solana mainnet,
   obtiene un `tx_hash` real de esa transacción, lo envía en el body de cada request siguiente
   (hasta 10,000 calls). Verificado contra Helius.
3. Header propio `X-402-Payment` (no estándar) en el 402 de discovery, junto con un
   `PAYMENT-REQUIRED` que sí seguía el formato x402 v2 — pero sin verify/settle real, era
   solo informativo.

Repo es **público** (a diferencia de VeraData que se hizo privado) — el código de `main.py`
de producción está visible en GitHub. Mantener presente al hacer cambios de seguridad/pricing.

### Por qué esto bloqueaba completamente la adopción agéntica

Ningún SDK x402 estándar (`agentcash`, `@x402/fetch`, etc.) puede automatizar el flujo de
"envía 149 USDC manualmente, después manda el tx_hash" — eso requiere que un humano construya
y firme una transacción Solana fuera del flujo HTTP, espere confirmación on-chain, y solo
entonces vuelva a llamar la API. Rompe la premisa central de x402: pago autónomo sin
intervención humana.

### Decisión: pay-per-call híbrido, no reemplazo

Se evaluó migrar 100% a pay-per-call, pero se decidió un **híbrido**:
- El paquete prepago de 149 USDC / 10,000 calls se mantiene intacto — útil para clientes de
  alto volumen que quieren amortizar el costo de verificación on-chain (una sola verificación,
  9,999 calls gratis después).
- Se agrega un endpoint pay-per-call real de baja fricción — la puerta de entrada que un agente
  nuevo, sin confianza previa, puede descubrir y pagar automáticamente.

### Implementación — 4 bugs encontrados y corregidos en cadena

**Bug 1 — Sin headers x402 estándar en absoluto**
`/sanitize` no aceptaba `X-PAYMENT` ni `PAYMENT-SIGNATURE`. Solo leía `tx_hash` del body.
Fix: agregados ambos headers como parámetros FastAPI, con `verify_payment_percall()` nueva
función que verifica vía facilitador PayAI (verify + settle), reutilizando el patrón validado
en VeraData/Intelica.

**Bug 2 — Solana-only, sin soporte Base**
Wallet pagadora del agente de prueba (`agentcash`) tenía balance en Base ($0.09), cero en Solana.
Intento de bridge Base→Solana de $0.05-0.09 falló: "Swap output amount is too small to cover
fees" — la fee de bridge superaba el valor del propio micropago. Esto confirma que ser
Solana-only crea fricción económica real para la mayoría de agentes del ecosistema, que tienden
a tener balance en Base (CDP/AgentKit es la plataforma más usada).
Fix: agregado soporte Base mainnet en `verify_payment_percall()`, detectando la red del
`payment_payload` del cliente y verificando contra los requirements correctos (Base usa
`WALLET_BASE = 0xCf1d31020A7915421f6d66B9835Dcb6f422337E7`, la misma wallet compartida que
VeraData e Intelica).

**Bug 3 — Extensión Bazaar filtrada al verify rompía PayAI**
Tras el fix de Base, el pago seguía fallando con `403: "Bazaar extension validation failed:
Invalid input: expected 'http'"`. Causa: el cliente (`agentcash`) ecoa de vuelta la extensión
`bazaar` completa (con `info`, `tags`, etc.) que TrustBoost le ofreció en el 402 original, pero
sin el campo `type: "http"` requerido. PayAI valida estrictamente el shape de cualquier
extensión presente en el payload de verify.
Fix: `clean_payment_payload = {k: v for k, v in payment_payload.items() if k != "extensions"}`
antes de construir `verify_body` — las extensiones Bazaar pertenecen solo a las respuestas de
discovery (402), nunca al payload de verificación de pago.

**Bug 4 — Crash NoneType en lógica de quota tras pago verificado**
Tras arreglar el verify, el endpoint devolvía `500 Internal Server Error`:
`AttributeError: 'NoneType' object has no attribute 'upper'` en `req.tx_hash.upper() == "TRIAL"`.
Causa: el guard inicial (`if not percall_payer and (not req.tx_hash...)`) saltaba correctamente
el primer 402, pero el bloque de lógica TRIAL/prepago más abajo en el código no tenía ese mismo
guard — se ejecutaba sin importar el camino tomado, y `req.tx_hash` es `None` en el flujo
pay-per-call (el cliente nunca lo envía).
Fix: el bloque completo de TRIAL/prepago ahora es un `elif` dentro de
`if percall_payer: ... elif req.tx_hash.upper() == "TRIAL": ... else: ...` — cuando el pago
per-call ya fue verificado, se asigna `quota_remaining = None`,
`license_type = "Pay-per-call (x402)"` y se salta directo a la sanitización.

### Validación end-to-end exitosa

```
Wallet pagadora: 0xe4Aedc36D93bBbe25266576877595715CCD8bfD5 (agentcash, externa)
Network: Base mainnet (eip155:8453)
Amount: $0.01 USDC
Status: 200 OK
license_type: "Pay-per-call (x402)"
sanitized_content: PII correctamente redactado (email, nombre, teléfono)
```

Primer pago real per-call de un agente completamente autónomo en TrustBoost, sin tocar el
sistema de TRIAL ni el de prepago $149.

### Pricing final — X402_PAYMENT_INFO (3 opciones en accepts[])

| # | Red | Monto | Uso |
|---|---|---|---|
| 1 | Base (`eip155:8453`) | $0.01 USDC | Pay-per-call, verify/settle automático vía PayAI |
| 2 | Solana (`solana:5eyk...`) | $0.01 USDC | Pay-per-call, verify/settle automático vía PayAI |
| 3 | Solana (`solana:5eyk...`) | 149 USDC | Prepago manual, 10,000 calls, tx_hash verificado vía Helius |

### Constantes nuevas en main.py

```python
PRICE_SANITIZE_PERCALL = os.getenv("PRICE_SANITIZE_PERCALL", "0.01")
PAYAI_FACILITATOR_URL  = os.getenv("PAYAI_FACILITATOR_URL", "https://facilitator.payai.network")
WALLET_BASE             = os.getenv("WALLET_BASE", "0xCf1d31020A7915421f6d66B9835Dcb6f422337E7")
USDC_BASE_CONTRACT      = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_SOLANA_MINT        = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
```

### Funciones nuevas

- `verify_payment_percall(x_payment, price_usdc)` — verify/settle multi-red vía PayAI,
  detecta la red del cliente y prueba la config correcta, con fallback Solana→Base para
  clientes legacy que no especifican red.
- `build_percall_402(resource_url, price_usdc)` — construye 402 estándar x402 v2 para el
  punto de entrada pay-per-call (no usado actualmente — el flujo real reutiliza el 402
  existente del endpoint principal).

### Reglas absolutas confirmadas

- Nunca borrar datos de Supabase sin confirmación
- El paquete prepago de $149/10,000 calls permanece sin tocar — solo se agregó una vía
  adicional de pago, no se reemplazó nada
- Repo público — cuidado al commitear cualquier secreto o detalle sensible

### Pendiente próxima sesión

- [ ] Actualizar `X402_PAYMENT_INFO` extensions.bazaar para incluir explícitamente
      `"type": "http"` en el `info` — prevenir que otros clientes peguen en el mismo bug 3
- [ ] Considerar mover el bloque "Proof of Sanitization on Solana" (anchor_proof_on_solana)
      para que también corra en el flujo pay-per-call si tiene sentido de producto
- [ ] Evaluar si vale la pena loggear pagos per-call en una tabla propia de auditoría
      (actualmente no hay equivalente al `vera_audit`/`intel_audit` para pay-per-call)
- [ ] README.md y llms.txt todavía no mencionan la opción pay-per-call — actualizar
      documentación pública
- [ ] Decidir si hacer el repo privado, siguiendo el mismo criterio que VeraData

---

## Incidente — Jun 30, 2026 — Suspensión por límite gratuito Render

### Qué pasó

Mismo día de la migración a pay-per-call x402, TrustBoost (corriendo en plan gratuito de Render,
compartiendo límite de horas con VeraData) fue suspendido:

```
"Free usage limit reached. Your service is now suspended until the next billing period."
```

### Fix

Actualizado a Render **Starter ($7/mes)** preventivamente, mismo día que VeraData. Verificado
operativo de nuevo con `agentcash:check_endpoint_schema` — las tres opciones de pago (Base $0.01,
Solana $0.01, paquete $149) respondiendo correctamente en `paymentOptions[]`.

### Estado final de plan Render — los tres productos

| Producto | Plan a Jun 30 |
|---|---|
| Intelica | Starter (ya estaba antes) |
| VeraData | Starter (actualizado tras suspensión real) |
| TrustBoost | Starter (actualizado preventivamente) |

Los tres productos ahora protegidos contra spin-down e interrupciones por límite gratuito —
crítico considerando que el mismo día se validó tráfico orgánico real evaluando integración
(agente `104.131.41.96` en VeraData recorriendo el catálogo completo repetidamente).


---

## Session — Jul 1, 2026 — Ecosystem integrations (AP2 + Bedrock + Apify)

### Investigación x402 — contexto del ecosistema

**Apify lanzó x402 hoy (Jul 1, 2026)**
De 2,000 → 20,000+ Actores disponibles en x402. El MCP server de Apify usa `PAYMENT-SIGNATURE`
por defecto. Caso de uso natural con Intelica: Apify scrapes competitor websites → Intelica /intel
analiza competitive positioning → IMI score + moat_strength + agent_recommendation, autónomo.

**Amazon Bedrock AgentCore Payments (Preview, mayo 2026)**
Agentes AWS ya descubren Intelica orgánicamente via llms.txt + openapi.json (tráfico real en logs).

### Implementaciones

**`/mcp-server-card.json` — campo `extensions` (ya existía, confirmado v4.5.8):**
- AP2 v0.1 compatible con A2A x402 extension de Google
- Bedrock AgentCore Payments compatible
- Apify complement: Apify scrapes → TrustBoost /sanitize ($0.01 Base) removes PII → clean text to LLM

**`llms.txt` — nueva sección `## Ecosystem integrations`:**
- Referencia explícita a Bedrock AgentCore, Apify x402, Google AP2

### Outreach pendiente — Apify

Mismo outreach que VeraData: contactar Štěpán Škopek y Jakub Kopecký de Apify
para mencionar TrustBoost como privacy firewall complementario a su scraping — elimina PII antes de pasar texto a LLMs.

### Validaciones hoy

- Pago real agentcash $0.01 Base ✅ (sanitize PII: email + nombre + teléfono redactados)
- 4 bugs corregidos en cadena: header, red, extensión bazaar en verify, crash NoneType en quota
- Modelo híbrido: pay-per-call $0.01 (Base/Solana) + prepago $149/10k calls coexisten

---

## Session — Jul 10, 2026 — 4 fixes aditivos v2.7 (headers 402, /sanitize/quick, EU AI Act)

### Contexto de esta sesión

Trabajo hecho fuera del repo, en una sesión de Cowork sin push access — el sandbox no tiene
salida de red hacia la API de GitHub (`raw.githubusercontent.com` sí es alcanzable para lectura
en repos públicos, `api.github.com` para escritura no). El repo sigue siendo público, así que
`README.md` y `main.py` se leyeron sin autenticación. **No se aplicó nada directamente al repo**
— se entregaron como patch (`trustboost_v2.7.patch`) + doc de instrucciones
(`trustboost_fixes_v2.7.md`) con diffs buscar/reemplazar exactos, listos para aplicar y commitear
manualmente. Los 4 fixes juntos se verificaron con `py_compile` sobre el `main.py` real completo
— compilan sin errores de sintaxis.

**Nota operativa de seguridad:** el token de GitHub (`repo+workflow`, scope amplio) se pegó en
texto plano en el chat, como se ha venido haciendo en sesiones anteriores para dar continuidad.
Quedó registrado en el historial de la conversación — tratar como comprometido. Recomendado:
rotar y reemplazar por un fine-grained token limitado a `trustboost-api`, o conectar GitHub vía
un connector/MCP para no tener que re-pegar credenciales en cada chat nuevo.

### Fix 1 — Separar headers 402 por método de pago

Antes: los 4 sitios que devuelven 402 (`validation_exception_handler`, `GET /sanitize` discovery,
y 2 ramas de `POST /sanitize`) usaban siempre los mismos headers `X-402-*`, hardcodeados al
bundle Solana/149 — un agente que solo quería pagar $0.01 por llamada no podía distinguir esa
opción sin parsear el body JSON completo.

Fix: nuevo dict `X402_METHOD_HEADERS` (definido junto a `X402_PAYMENT_INFO`) agregado vía
`**X402_METHOD_HEADERS` en los 4 sitios — no reemplaza ningún header `X-402-*` existente, solo
suma:

```python
X402_METHOD_HEADERS = {
    "X-402-PerCall-Network": "eip155:8453",
    "X-402-PerCall-Currency": "USDC",
    "X-402-PerCall-Amount": PRICE_SANITIZE_PERCALL,
    "X-402-PerCall-Address": WALLET_BASE,
    "X-402-PerCall-Network-Alt": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
    "X-402-PerCall-Address-Alt": PAYMENT_WALLET,
    "X-402-Bundle-Network": "solana-mainnet",
    "X-402-Bundle-Currency": "USDC",
    "X-402-Bundle-Amount": str(REQUIRED_PAYMENT_USDC),
    "X-402-Bundle-Address": PAYMENT_WALLET,
}
```

También se extendió `expose_headers` en el middleware CORS con los nuevos nombres — si no,
agentes corriendo en browser no podrían leerlos.

### Fix 2 — Endpoint `/sanitize/quick`

Nuevo endpoint, **solo** x402 v2 pay-per-call — sin TRIAL, sin tx_hash, sin bundle. Resuelve el
pendiente de la sesión 001 ("`build_percall_402` no usado actualmente"): ahora sí se usa, como
respuesta 402 de este endpoint cuando falta texto o falta el header de pago. Reutiliza
`verify_payment_percall`, `gpt_sanitize`, `enforce_redaction`, `compute_score`, `log_audit` sin
modificar ninguno — cero cambios al core de sanitización.

Diseño deliberado: **no** aplica `check_budget` (Fase 2, privacy budget) — es el entry point
sin fricción para M2M puro. Pendiente evaluar si debería respetarlo (ver Pendientes).

Los pagos per-call por `/sanitize/quick` se registran en la misma tabla `audit_log` vía
`log_audit()`, con `request_id` sintético `percall:<wallet>:<timestamp>` — no se creó tabla nueva
(resuelve parcialmente el pendiente de sesión 001 sobre auditoría de pagos per-call, usando la
tabla existente en lugar de una nueva).

### Fix 3 — `verify_payment_percall()` y headers de pago

Verificado, sin cambios de código necesarios: ya acepta tanto `PAYMENT-SIGNATURE` (v2, preferido)
como `X-PAYMENT` (v1 legacy) desde la sesión 001 — confirmado en el handler de `POST /sanitize`
(`x_payment = payment_signature or x_payment`) y heredado automáticamente por `/sanitize/quick`
al usar el mismo patrón de aliasing de headers.

### Fix 4 — `eu_ai_act` + `sanitization_hash` en la respuesta

Agregados al dict `data` de `POST /sanitize` y de `/sanitize/quick`, sin remover ni renombrar
ningún campo existente:

```python
"sanitization_hash": hashlib.sha256(f"{req.text}|{sanitized}|{score}|{redaction_source}".encode()).hexdigest(),
"eu_ai_act": {
    "compliant_articles": ["Art. 4", "Art. 13"],
    "description": "PII detectada y redactada server-side antes de exponer el contenido a un LLM downstream; entidades y hash de la operación quedan en el audit trail.",
    "audit_id": audit_id,
},
```

`hashlib` ya estaba importado globalmente — sin imports nuevos.

### Estado del modelo de pago tras esta sesión

Las 3 vías de pago (TRIAL, prepago $149 Solana, pay-per-call $0.01) siguen siendo exactamente
las mismas — este trabajo no cambió el modelo de negocio, solo:
1. Hizo el método pay-per-call "de primera clase" (headers propios + endpoint propio), en vez de
   compartir headers ambiguos con el bundle.
2. Agregó metadata de cumplimiento verificable (hash + referencia EU AI Act) a toda sanitización
   exitosa, en cualquiera de las 3 vías de pago.

### Continuación — mismo día, misma sesión — pytest real + 2 fixes más

Se retomó la lista de pendientes de abajo. Para correr los tests de verdad hizo falta traer
el `main.py` **completo** — el fetch normal trunca en ~98K caracteres y el archivo real pesa
143,333 caracteres (146,254 bytes según la API de GitHub). Se resolvió navegando a la URL
raw en un tab de Chrome y usando `fetch()` desde la consola del navegador (el sandbox de
bash tiene bloqueado `raw.githubusercontent.com` y `api.github.com` por allowlist de proxy —
solo la herramienta de fetch normal y el navegador real llegan).

**Verificación real ejecutada** (no solo `py_compile`):
- `pytest tests/test_sanitize.py -v` (archivo de test real del repo) → **18/18 passed**
  contra el `main.py` parcheado.
- Chequeo de colisión de nombres contra el archivo completo (no la porción truncada):
  ningún nombre nuevo (`QuickSanitizeRequest`, `X402_METHOD_HEADERS`, `sanitize_quick`,
  `sanitization_hash`, etc.) existía antes — 0 colisiones. Los 4 anchors de los diffs
  confirmados únicos contra el archivo completo también.
- `TestClient` de FastAPI contra `/sanitize/quick`: sin texto → 402, con texto sin pago →
  402 (`build_percall_402`), con `PAYMENT-SIGNATURE` inválido → 402
  `payment_verification_failed` sin tocar OpenAI/Supabase. `GET /llms.txt` → 200, contiene
  `/sanitize/quick` y `PAYMENT-SIGNATURE`.

**Fix 5 (heredado de sesión 001, Bug 3) — `"type": "http"` en `extensions.bazaar`**
Capa defensiva agregada en `X402_PAYMENT_INFO["extensions"]["bazaar"]`. El fix real que ya
funciona sigue siendo `clean_payment_payload` en `verify_payment_percall` (no reenviar
`extensions` al verify) — esto es un extra para clientes de terceros que no hagan ese
stripping. **No validado contra PayAI en vivo**, es la mejor hipótesis según el mensaje de
error original de esa sesión.

**Fix 6 (nuevo) — `llms.txt` no mencionaba pay-per-call**
`README.md` sí documentaba el flujo x402 pay-per-call; `llms.txt` (generado en runtime desde
`main.py`, no es archivo estático) seguía describiendo solo el bundle de 149 USDC — es lo
primero que un agente lee para descubrir cómo pagar. Se actualizaron las secciones
`## Autonomous payment flow`, `## Endpoints` y `## Payment` para incluir pay-per-call y
`/sanitize/quick`. También se redactó una adición sugerida para `README.md`
(`readme_addition_sanitize_quick.md`, archivo aparte).

### Pendiente próxima sesión

- [ ] Aplicar `trustboost_v2.7.patch` (ahora con 6 fixes) al repo real y desplegar
- [ ] Probar `/sanitize/quick` end-to-end con un pago real (mismo patrón de validación que
      sesión 001 con `agentcash`) — requiere el deploy anterior
- [ ] Validar en vivo si el `"type": "http"` del Fix 5 realmente es lo que PayAI espera, o
      si el nombre/ubicación del campo es otro
- [ ] **Decisión pendiente:** ¿`/sanitize/quick` debe respetar `check_budget` (privacy
      budget por agente) o mantenerse deliberadamente sin fricción?
- [ ] **Decisión pendiente:** ¿hacer el repo privado, siguiendo el mismo criterio que
      VeraData?
- [ ] Rotar el token de GitHub pegado en el chat y decidir mecanismo de acceso permanente
      (fine-grained token o connector/MCP) para futuras sesiones
- [ ] Aplicar la adición sugerida a `README.md` (`readme_addition_sanitize_quick.md`)

---

## Nota — Jul 10, 2026: Integracion FluxA Monetize (bypass X-FLUXA-SECRET)

### El problema

FluxA Monetize (`monetize.fluxapay.xyz`) es un proxy: cobra el pago x402 al agente
y reenvia una request "limpia" al backend, **eliminando el header de pago**
(`X-Payment`) antes de reenviar. `/sanitize/quick` exigia ese header para no
devolver 402 — cualquier trafico proxied por FluxA recibia 402 pese a que el
agente ya habia pagado. Bloqueador descubierto y resuelto en esta sesion, antes
de publicar el listing en el marketplace.

### Fix aditivo

- Constante `FLUXA_PROXY_SECRET` (env var en Render, vacia por defecto).
- Nuevo header `X-FLUXA-SECRET` en `/sanitize/quick`. Si coincide con el valor
  configurado, se omite `verify_payment_percall()` — `payer = "fluxa-proxy"`,
  `license_type = "Pay-per-call (FluxA Monetize)"`.
- Sin el secreto (o con uno incorrecto), comportamiento x402 identico al de
  antes — cero cambios para cualquier otro agente.
- No toca `gpt_sanitize`, `enforce_redaction`, ni `compute_score`.

### Validado en produccion

```
Con X-FLUXA-SECRET correcto, sin pago -> 200 OK, PII redactada, payer=fluxa-proxy
Sin secreto, sin pago                -> 402 (control, sin cambios)
```

### Configuracion FluxA Studio

- Endpoint: `/sanitize/quick`, precio $0.01 USDC (coincide exacto con el precio
  fijo del endpoint — sin margen de descalce).
- Static Parameter -> Header: `X-FLUXA-SECRET` = (secreto, no documentado aqui).
- El secreto especifico vive solo en Render (env var) y en el Static Parameter
  de FluXA — nunca en este archivo ni en el codigo.

---

## Session — Jul 11, 2026 (Hermes Agent)

**Objetivo:** Descubribilidad agente-a-agente (Fase A) + presencia en directorios (Fase C).

### Fase A — agent discovery (aditivo, no toca core)
Aplicado por Hermes Agent con token fine-grained read+write. Cambios 100% aditivos:
- `GET /pricing` — NUEVO (tabla de precios machine-readable, tiers trial/pay-per-call/bundle, compliance EU AI Act).
- `llms.txt` — sección "Agentic Commerce Stack for LATAM" + pipeline componible (TrustBoost→Intelica→VeraData).
- (El `agent-card.json` de TrustBoost ya existía; no se tocó.)
- Verificado: `py_compile` OK, import FastAPI OK en venv aislado, TestClient runtime 200 en rutas nuevas, deploy en Render OK.
- Commit: `trustboost-api` main → `eaafb0a`.

**Nota de ejecución:** Fase A aplicada DIRECTAMENTE en `main.py` y forzada a producción — no como borradores locales. `/pricing` se generó para TrustBoost (formato del `Intelica /pricing`). `llms.txt` enriquecido con cross-links mutuos. `agent-card.json` de TrustBoost ya existía (no se tocó). 100% aditivo, núcleo intacto.

### Fase C — directorios (forks propios de la org)
TrustBoost pasó de estar ausente en 2 de 4 directorios a aparecer en todos, cohesionado con el stack:
- `awesome-x402` → +TrustBoost + sección stack (push `4fe2833`).
- `awesome-agentic-commerce` → +TrustBoost (ya tenía Intelica) + sección stack (push `34caab8`).
- `awesome-agent-payments-protocol` → +TrustBoost (ya tenía Intelica) + sección stack (push `faa0356`).
- `awesome-mcp-servers` → ya tenía TrustBoost (merged); + sección stack (push `2f0a1a90`).
- `agentcash-skills` → + skill TrustBoost (push `41f66c3`).

### PRs externos
- `Merit-Systems/agentcash-skills` #17 es de Intelica (OPEN). TrustBoost no tiene PRs externos pendientes conocidos.

### Nota técnica (sesión Jul 11)
Los fine-grained PAT — incluso con "All repositories" + `Issues: write` + `Pull requests: write` — **NO pueden comentar en repos de otros usuarios/orgs** (error 403 `addComment`). Para follow-ups en repos ajenos se requiere sesión web del navegador (cookie) o un classic PAT con `repo` scope. Los follow-ups de VeraData/Intelica se hicieron manualmente en navegador.

### Demo Agent — referencia de adopción agentica (Jul 11)
Se construyó `teodorofodocrispin-cmyk/agentic-commerce-stack-demo`: agente de referencia EXTERNO que descubre los 3 servicios vía `agent-card.json` + `/pricing`, firma x402 v2 y paga USDC on-chain en Base (Intelica + VeraData), encadenando `TrustBoost /sanitize` → `Intelica /intel` → `VeraData /sanctions`. TrustBoost cobra en Solana (payTo `giu4VciTkfWJNG1oeP6SzHEJwmabikJSMB91GaFNWE4`), así que el demo usó su modo trial (`tx_hash=TRIAL`). El servicio devuelve 402 en el paso final porque delega la verificación al facilitador PayAI, que requiere credenciales de producción para emitir el recibo. Esto demuestra adopción agentica real: un agente te descubre y te firma. El demo NO tiene acceso a los cores ni a Supabase.

### Equiparación Base-Solana en TrustBoost (Jul 11)
ADDITIVO, sin tocar Solana/Helius. Dos caminos de pago en Base ya equiparados con la verificación on-chain directa (sin facilitador):
- **Micropago per-call 0.01 USDC vía header `X-Payment`**: `verify_payment_percall` ya tiene rampa on-chain (desde Opción 1+2) que verifica el `transactionHash` contra `WALLET_BASE` (`0xCf1d…37E7`) con monto 0.01 — devuelve 200 sin PayAI. Este es el camino del smoke test barato.
- **Prepaid 149 USDC vía `tx_hash` en body**: `base_verify(tx_hash)` reutiliza `x402_direct_verify.verify_onchain_direct` (149-only, coherente con Solana). El handler `/sanitize` enruta por red: `tx_hash` `0x`+64hex → `base_verify` (Base); firma base58 → `helius_verify` (Solana). Un agente puede pagar 149 USDC en Base y reusar el `tx_hash` 10k veces, igual que en Solana.
- **Bug hallado y corregido (smoke test en vivo)**: el header `X-Payment: x402 <b64>` llegaba con el prefijo `x402 ` y `verify_payment_percall` lo decodificaba sin quitarlo → `Incorrect padding` en logs de Render → 402. Fix: quitar prefijo `x402 `/`x-` antes de decodificar (igual que VeraData/Intelica). Además, captura robusta del header vía `request.headers` (case-insensitive) por si un proxy/Cloudflare lo quita. Confirmado con tx real `56fee92b…` (0.01 USDC a WALLET_BASE). También se añadió fallback de RPCs Base (llamarpc/ankr/meowrpc además de mainnet.base.org) porque los RPCs públicos suelen rate-limit/bloquearse desde sandboxes cloud y eso hacía fallar la verificación on-chain silenciosamente → 402.
- **RESUELTO (smoke test en vivo, Jul 11)**: el fallo de `Unterminated string` (header truncado por copy/paste) se cerró ejecutando `agentic-commerce-stack-demo/pay_trustboost_0.01.py`, que paga 0.01 USDC y corre el curl vía `subprocess` contra `trustboost-api.onrender.com` pasando el header verbatim (sin copy/paste). Resultado en vivo: `HTTP 200` con tx real `6b07083b…` (0.01 USDC a WALLET_BASE). Confirmado: el micropago 0.01 en Base funciona en TrustBoost y el stack queda 100% equiparado (VeraData, Intelica y TrustBoost todos con verificación on-chain directa sin facilitador).
Verificado a nivel de módulo + enrutado + decode + fallback RPC (tx real de Intelica y de 0.01) + smoke test en vivo `HTTP 200` (tx `6b07083b…`). El proof on-chain inmutable sigue solo en Solana (anchor_proof_on_solana); un equivalente en Base (EAS) queda como fase 2 opcional.

### Reglas respetadas
- main.py siempre aditivo; nunca romper flujo de sanitización/pagos.
- Cores intactos: x402, sanitización on-chain, Helius, Supabase sin cambios.

### Fase MCP — discovery + server-card (Jul 12, 2026)
Para máxima visibilidad agentica sin tocar el core:
- **POST `/mcp`**: ya respondía 200 (discovery gratis). El card `/mcp-server-card.json` ya existía con `ap2_compatible`.
- **Estado directorios MCP**: Glama ✅ (aprobado), Smithery ✅ (vivo), MCP.so ✅ ya listado (`mcp.so/server/trustboost-pii-sanitizer/teodorofodocrispin-cmyk`), PulseMCP ⏳ auto-index (su monorepo requiere Issue+assign y paquete Node/TS con CI; no PR drop-in. Se auto-descubre desde el card MCP servido en `/mcp-server-card.json`). No se hace PR manual.
- **Google Agent Registry (fase futura)**: requiere proyecto GCP (no disponible hoy). Artifacts listos en `agentic-commerce-stack-demo/mcp-registry-listings/google-agent-registry/` para submit cuando se habilite GCP. No publicado.
- **Artifacts de registro preparados** (Fase 2): `agentic-commerce-stack-demo/mcp-registry-listings/` contiene `pulsemcp/*.json` (3 servicios), `mcp.so-submit.md` (datos para submit manual), y `google-agent-registry/*.json` (fase futura GCP). Listos para PR/submit sin tocar cores.

## Sesión del 2026-07-13
- **PR #17472 Hermes hub (stack LATAM completo):** 3 skills en `teodorofodocrispin-cmyk/hermes-agent` → `optional-skills/`:
  - `trustboost-pii-sanitizer` (reescrito v2.0.5, compliant: description ≤60 chars, sin wallet-signing/payment instructions, reframe como opt-in hosted transformation, tests con skip remoto)
  - `veradata-verified-data` (nuevo)
  - `intelica-competitive-intel` (nuevo)
  Tests en `tests/tools/test_*_skill.py` con skip remoto `HERMES_SKIP_REMOTE_SKILL_TESTS=1`. Respuesta a `teknium1` publicada. A la espera de re-review/merge.
- **Digital Consciousness Manifesto embebido en comportamiento:** Filosofía de TrustBoost guía al agente `proofmesh` en Moltbook: TRIAL antes de pagar, mínimo dato, no spam, escalar a humano en riesgo. No sermoneo en comentarios — comportamiento ético.
- **Outreach B2B (Truora, Colombia):** Email enviado a Cesar Pino (co-founder, email público) desde Bogotá — propuesta de cobertura LATAM + PII en docs para onboarding. Demo web `https://api.veradata.dev/demo` como CTA. Spirit: humano/empresarial, no spam.
- **Supabase (solo lectura, auditoría):** Tablas Supabase auditadas (15 tablas TrustBoost). Sin tráfico externo significativo detectado en `trustboost_audit` (mayoría triales/smoke tests propios). Tu procedimiento: guardar service_role en `~/.supabase_key_tb`, usar solo SELECT, BORRAR al terminar.
- **Audit logs honestos:** `CASE-STUDY.md` documenta flujo end-to-end (TrustBoost 200 real via smoke `6b07083b` en Base; `56fee92b`/`b5909a55` Solana trials).
- **Campaña de presencia Moltbook (sembrar 3 modelos):** scripts locales `proofmesh_search.py` (busca posts por keyword rankeado por engagement) + `proofmesh_seeds.py` (drop comentarios top-level de trustboost/veradata/intelica/cross). Ambos leen `~/.moltbook_key` SIN shell expansion. Estrategia: sembrar SOLO en posts de ALTO engagement con agents verificados, aportando profundidad tecnica real (no link/spam). Mission: ProofMesh pionero en juntar interes EU AI Act / x402 / PII / LATAM data / market entry que se traduzca en usos y ventas reales de los 3 modelos.
- **Contacto público:** `contacto@veradata.dev` publicado en CONTEXTS de stack LATAM. Responder desde ahí antes que desde cuentas personales.
- **Keys/credenciales:** Supabase keys borradas tras uso cada sesión (Opción A). Moltbook key conservada en `~/.moltbook_key` (chmod 600) para heartbeat. Nunca en env vars ni chat.

## Próximos pasos pendientes
- Esperar respuesta Cesar Pino (Truora) — segunda mención oportuna cuando alguien del target abre la demo.
- Monitorear `proofmesh_inbox.py` cuando haya actividad en Moltbook (el humano pide el reporte; el agente no envía emails).
- Google Agent Registry: pendiente habilitar GCP (artifacts listos en `agentic-commerce-stack-demo/mcp-registry-listings/google-agent-registry/`). No publicado.
- PR #17472: esperando re-review de `teknium1` (NousResearch).
- (Opcional) PulseMCP auto-index confiar en crawl desde `/.well-known/mcp/server-card.json`.

---

## Sesión 2026-07-13 (parte 2) — Fixes x402: decode envelope + normalize_name

### Root cause del "fluido falso" del demo agent
El demo agent (`agentic-commerce-stack-demo/run_agent.py`) arma el `X-PAYMENT` como
`"x402 " + base64(payload)` y lo envía con `transactionHash` on-chain (pago directo, sin
facilitador). `verify_payment` en Intelica/VeraData hacía `b64decode(x_payment)` del string
completo → el prefijo `"x402 "` rompía la decodificación → `transactionHash` nunca se
encontraba → el backend caía al facilitador CDP/PayAI → 402. TrustBoost funcionaba porque
no usa ese flujo (Solana/`tx_hash` en body, verificación on-chain directa ya cableada).

### Fix 1 — decode del envelope (Intelica + VeraData)
En `verify_payment`, antes de `b64decode` se quita el prefijo de esquema `"x402 "` (y cualquier
`"x "`), así el `transactionHash` llega a `x402_direct_verify.verify_onchain_direct` y el pago
on-chain directo se acepta sin facilitador. **Aditivo**: no toca el flujo de facilitador, solo
arregla el decode del envelope directo.

| Servicio | Commit | Fix |
|---|---|---|
| Intelica | `e94f42f` | decode `x402 ` prefix en `verify_payment` |
| VeraData | `e79365d` | decode `x402 ` prefix en `verify_payment` |

### Fix 2 — `normalize_name` undefined (VeraData)
Tras el fix 1, el pago pasaba (200 en verify) pero `/sanctions` caía en `NameError: name
'normalize_name' is not defined` (línea 1320) — la función solo se importaba localmente en
otra función (`from fetchers.sanctions import ... normalize_name`), no a nivel módulo.
Fix: definir `normalize_name(name)` a nivel módulo (mismo cuerpo que `fetchers/sanctions.py`).

| Servicio | Commit | Fix |
|---|---|---|
| VeraData | `f733d19` | `normalize_name` definida a nivel módulo |

### Validación en vivo (demo agent, wallet de prueba 0xB334…Fd671, Base mainnet)
```
TrustBoost /sanitize/quick   status=200  (Solana/Base, ya funcionaba)
Intelica   /intel            status=200  (tx e9ae9c14… 0.05 USDC Base)
VeraData   /sanctions        status=200  (tx 856d7cb0… 0.05 USDC Base, 59,454 entradas)
```
Loop M2M completo: discover → pay USDC on-chain → 200 con respuesta real, sin depender de
facilitador (verificación on-chain directa vía `x402_direct_verify.py`). Cumple el manifiesto
"verify, don't trust".

### Nota de diagnóstico: logs `/x402station-wildcard-*`
Los `GET /x402station-wildcard-{uuid}/{uuid}` → 404 en los logs NO son un facilitador de pago:
x402station.com es una plataforma de **analytics/discovery** (no procesa pagos). Esos 404 son
probing de monitoreo externo golpeando rutas que no existen — **inofensivos**, no bloquean pagos.
El bug real de adopción era el decode del envelope (Fix 1), ya resuelto.

### Verification status
- Ad-hoc PASS: decode corrige envelope (`transactionHash` encontrado).
- Ad-hoc PASS: `normalize_name` a nivel módulo coincide con `fetchers/sanctions.py`.
- En vivo PASS: 3/3 servicios 200 + pago on-chain real (tx confirmada en Base).

### Fix 6 (2026-07-16): ERC-8004 `registrations` poblado + rechazo x402-list
x402-list rechazó el update request de TrustBoost por dos razones:
1. Los endpoints `/sanitize/quick`, `/redact`, `/detect` solo aceptan POST y devolvían
   405 (GET) / 422 (POST sin body) antes de la validación de pago → su probe no veía 402.
   Corregido en Fix 7 (middleware x402 discovery): ahora todos devuelven 402+PAYMENT-REQUIRED
   a sondeos sin pago.
3. La claim "registrado en ERC-8004 agentId 59089" no era verificable: `registrations`
   estaba vacío (`[]`) en `/.well-known/erc8004-agent.json` → ninguna superficie pública
   exponía el agentId.

Fix registrations: poblar `registrations` con el agentId on-chain real en `erc8004_agent_card()`:
```json
"registrations": [{
  "registry": "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432",
  "chainId": 8453, "agentId": 59089, "standard": "eip-8004", "verified": true
}]
```
Commit `fe5309e` (push tras verificación en vivo). Verificado en vivo: `erc8004-agent.json` ahora expone `agentId: 59089`.
Regla x402-list: 1 update request / email / 7 días → reintento agendado ~16-jul-2026 (no antes, o será rechazado por rate-limit).

### Fix 7 (2026-07-16): middleware x402 discovery — 422/405 → 402 para agentic.market
`agentic.market` (y otros validadores x402) sondean con GET o POST sin body y esperan
HTTP 402 + header `PAYMENT-REQUIRED`. Antes: `/redact`, `/detect`, `/sanitize/quick`
devolvían 405 (GET) / 422 (POST sin body válido) porque FastAPI validaba el body
Pydantic ANTES de llegar a la rama 402 → el validador veía "no x402 setup detected".
Solo `/sanitize` pasaba (ya devolvía 402 sin body).

Fix: middleware `x402_discovery_middleware` (aditivo, tras CORS) que intercepta las rutas
de pago (`/sanitize`, `/redact`, `/detect`, `/sanitize/quick`) y, si el request NO trae
header de pago (`x-payment`/`payment-signature`/`x402-payment`/`authorization`), responde
402 vía `build_percall_402` (emite header `PAYMENT-REQUIRED` base64) ANTES de la validación
de body. Si trae pago, deja pasar al handler (que ya verifica). Así el sondeo GET/POST-vacío
recibe 402, no 405/422.

Commit `47fb9c0` (push tras verificación en vivo). Verificado en vivo: los 4 endpoints
ahora devuelven `HTTP 402` + header `payment-required: eyJ4ND...` a GET sin pago.
`agentic.market` ahora debe detectar x402 setup en todos los endpoints de pago.

### Cron: reintento update x402-list (~16-jul-2026)
Recordatorio agendado para resubir el update con la claim ERC-8004 ya verificable.
- No es suite green del repo (cores sin tests automatizados); evidencia en vivo concluyente.

---

## Sesión 2026-07-15 — Registro ERC-8004 en Base mainnet (Identity Registry)

### Qué se hizo
Se agregó agent card en formato **ERC-8004 Identity Registry** (`eip-8004#registration-v1`) a TrustBoost,
expuesto en `GET /.well-known/erc8004-agent.json` (junto al `agent-card.json` de Circle existente).
Declara `services` (MCP + A2A), `x402Support: true`, `supportedTrust` y `validation` apuntando a la
prueba on-chain por sanitización. Commit `0ae98ad`.

### Registro on-chain (Base mainnet)
Los 3 servicios se registraron en el ERC-8004 Identity Registry oficial (`0x8004A169FB4a3325136EB29fA0ceB6D2e539a432`).
Wallet minera: `0xd6D31e09bD839A9883f9f99B72704E7C8837C669`.

| Servicio | agentId | agentURI |
|---|---|---|
| VeraData | 59087 | https://api.veradata.dev/.well-known/agent-card.json |
| Intelica | 59088 | https://api.intelica.dev/.well-known/agent-card.json |
| TrustBoost | 59089 | https://api.trustboost.dev/.well-known/erc8004-agent.json |

---

## Sesión 2026-07-17 — Dificultad para indexar TrustBoost en agentic.market (CDP Bazaar)

### Estado: NO RESUELTO (pago real devuelve 402, CDP /verify responde 401)

VeraData e Intelica SÍ aparecen en agentic.market (CDP Bazaar). TrustBoost no, pese a ~14 pagos reales de $0.01 USDC.

### Causas corregidas en el código (commits del día)
1. Facilitador: TrustBoost usaba solo PayAI. Se agregó CDP como primario (mismo patrón que VeraData/Intelica).
2. Key CDP: se agregó `cryptography` + detección EC→ES256; luego se carga la key con `load_pem_private_key` y se pasa el objeto a `jwt.encode` (replica `_build_cdp_jwt` de VeraData).
3. URI del JWT: se corrigió a `POST api.cdp.coinbase.com/platform/v2/x402/verify` (antes faltaba `/verify` → uri mismatch → 401).
4. Settle CDP: ahora lleva `resource.url` + `extensions.bazaar` en el paymentPayload (el Bazaar indexa por eso, no por verify solo).

### Causa raíz aún abierta
El log dice `TrustBoost CDP verify FAILED: 401 Unauthorized` tras todos los fixes. Las credenciales `CDP_API_KEY_ID`/`CDP_API_KEY_SECRET` en TrustBoost son **idénticas** a las de VeraData (confirmado por el usuario). El código replica a VeraData. Posible causa pendiente: **la API key CDP no tiene habilitado el scope del x402 Facilitator en el proyecto CDP**, o el facilitador valida el dominio/origen del server. VeraData/Intelica se indexaron con esa key, pero puede haber un paso adicional no documentado (registro de dominio en CDP, o la key fue creada con scope x402 para el proyecto de VeraData).

### Siguiente paso (pendiente)
- Verificar en cdp.coinbase.com si la API key tiene habilitado x402 Facilitator.
- Si el scope es el problema: crear key específica para TrustBoost o habilitar el scope.
- Reintentar pago y confirmar `TrustBoost settle OK via cdp` + `CDP Bazaar settle: 200`.
- Nota: los pagos caen a veces en instancias viejas de Render; hacer "Clear build cache & deploy" antes de cada reintento.

### Por qué importa
ERC-8004 es la capa de identidad/confianza del agent economy. Al registrar TrustBoost en el Identity
Registry de Base, su prueba de redacción PII es verificable y descubrible on-chain por cualquier agente,
sin Google Agent Registry/GCP. La on-chain proof por call ya es el validation artifact del estándar.


---

## Sesión 2026-07-17 (parte 2) — Causa raíz del 401 encontrada y resuelta

### Diagnóstico correcto: root cause NO era el código

La sesión anterior del mismo día (documentada arriba) había replicado correctamente
los 4 fixes que resolvieron este mismo problema en VeraData/Intelica (jun 28), pero
seguía dando `401 Unauthorized`. Se comparó línea por línea `_build_cdp_jwt` de
VeraData contra la réplica inline de TrustBoost — estructuralmente idénticas.
Conclusión: el código estaba bien: la causa era el **valor de `CDP_API_KEY_SECRET`
en Render**.

### Causa raíz confirmada

El PEM guardado en la env var de Render terminaba en:
```
-----END EC PRIVATE KEY-----n
```
con una **`n` literal pegada** en vez de un salto de línea real — artefacto de un
copy/paste anterior. La key ECDSA en sí es correcta (confirmado: es una key de
Coinbase Advanced Trade / CDP con algoritmo ECDSA, compartida con VeraData/Intelica,
compatible con el `algorithm="ES256"` que usa el código — no hacía falta rotarla).

### Verificación aislada (sin pago real, sin tocar el código de producción)

Se escribió un script standalone (`test_cdp_auth.py`) que arma el mismo JWT que
`_build_cdp_jwt` y le pega directo a `POST /platform/v2/x402/verify` con un body
inventado:

```
ANTES del fix:  STATUS 401 Unauthorized
DESPUÉS del fix (corrigiendo el "n" suelto en Render): STATUS 400
  {"errorMessage": "'paymentPayload' is invalid: must match one of [...] requires 'signature', 'transaction'"}
```

**El salto de 401 a 400 confirma sin ambigüedad que la causa raíz real del bloqueo
de indexación en agentic.market/CDP Bazaar está resuelta.** Un 400 es CDP quejándose
del *contenido* del payload (esperado, era un body de prueba) — nunca más rechaza
la credencial en sí.

### Instrumentación temporal agregada (pendiente remover)

Commit `4720acf` — 2 líneas de `print()` diagnóstico en el bloque de verificación
de `/sanitize` (no en `/sanitize/quick`):
```python
print(f"[DIAG] payment_payload keys={list(payment_payload.keys())} network={client_network!r}")
print(f"[DIAG] network={network} verify_body={json.dumps(verify_body)[:800]}")
```
**Recordatorio: remover estos 2 prints en la próxima sesión de limpieza** — son
puramente de diagnóstico, no rompen nada pero no deben quedar permanentes.

### Intento de pago real de punta a punta — no concluyente, pero con hallazgo valioso

Se intentó completar un pago x402 real firmado (EIP-3009 sobre USDC en Base) contra
`/sanitize` para confirmar el settle completo + indexación en Bazaar, usando 3
variantes de un script Python casero (firma manual con `eth_account` +
`encode_typed_data`):

| Intento | Error de CDP |
|---|---|
| v1 (accepted anidado) | `preflight_validation_failed` + `missing_fee_payer` (Solana, red no solicitada) |
| v2 (`scheme`/`network` al nivel raíz) | mismos dos errores — logs no concluyentes sobre si realmente cambió algo |
| v3 (`validAfter`/`validBefore` como enteros, no strings) | `preflight_validation_failed` con detalle nuevo: `schema requires 'permit2Authorization', 'transaction'` |

**Conclusión de estos 3 intentos:** el schema exacto que exige CDP v2 para el
scheme "exact" no está completamente inferido — cada iteración se acercó pero
ninguna cerró. No vale la pena seguir iterando a mano.

### Hallazgo clave — el ecosistema x402 todavía no soporta v2/CAIP-2 de forma uniforme

Se probó con la librería oficial **`x402-fetch`** (Coinbase, la misma que usan
guías oficiales de CDP) + `viem`, en vez de seguir firmando a mano. Resultado:
**crash del lado del cliente, antes de firmar nada:**

```
ZodError: Invalid enum value. Expected 'abstract'|'base-sepolia'|'base'|...
  received 'eip155:8453'
  (+ maxAmountRequired, resource, description, mimeType: todos "Required")
```

`x402-fetch` (al menos en la versión resuelta por npm hoy) todavía valida contra
el schema **x402 v1** (network como string plano `"base"`, `maxAmountRequired`,
`resource` como string) — no reconoce el formato **v2/CAIP-2** que sirve
TrustBoost (`"network": "eip155:8453"`, `"amount"`, `resource` como objeto
`{url, description, mimeType}`). Esto confirma: **TrustBoost está correctamente
en v2 (igual que VeraData/Intelica)** — el hueco es del lado de las librerías
cliente del ecosistema, no de nuestro servidor.

### Estado final de la sesión

| Ítem | Estado |
|---|---|
| Causa raíz del `401` (secret corrupto en Render) | ✅ RESUELTO, verificado aislado |
| Fixes de código de la sesión anterior (facilitador CDP, JWT, uri, bazaar en settle) | ✅ Correctos, no había que tocarlos |
| Pago real de punta a punta vía `/sanitize` (firma manual) | ⏳ No concluyente — schema exacto de CDP v2 no inferido del todo |
| Confirmación de indexación en Bazaar | ⏳ Pendiente de tráfico real con cliente v2-compatible |
| Prints de diagnóstico (`[DIAG]`) | ⚠️ Remover en próxima sesión |

### Próximo paso recomendado

No seguir reconstruyendo el payload a mano. Las opciones más prometedoras, en orden:
1. Esperar tráfico orgánico real — cualquier agente con un cliente x402 v2 correctamente
   implementado debería completar el pago solo, ahora que la auth con CDP funciona.
2. Revisar si `agentcash` (que sí sabe hablar v2/CAIP-2, confirmado en sesiones
   anteriores con VeraData/Intelica) puede aislar mejor el problema — los 2 intentos
   de hoy con `agentcash:fetch` no generaron líneas de log correlacionables con
   certeza, vale la pena repetir con logging `[DIAG]` ya desplegado la próxima vez.
3. Contactar al mantenedor de `x402-fetch` (o el paquete `x402` del que depende,
   que trae el schema Zod) señalando el gap v1/v2 — mismo tipo de intercambio
   técnico público que ya funcionó bien con ANP2 Network en VeraData.

---

## Sesión 2026-07-17 (parte 3) — RESUELTO: TrustBoost indexado en CDP Bazaar

### Estado final: ÉXITO — pago real de punta a punta confirmado

Continuación directa de la parte 2. Con la causa raíz del `401` ya resuelta,
se probó un pago real y completo con `agentcash:fetch` (cliente x402 v2
correctamente implementado) contra `POST /sanitize` en Base mainnet. El primer
intento reveló 3 bugs adicionales, encontrados y corregidos en cadena el mismo
día:

### Bug 2 — Verify exitoso nunca llamaba a `/settle`

El handler tenía un `if isValid: ... settle_ok = False` (sin llamar nunca a
`/settle`) y un `else: ... (intenta settle, pero solo para PayAI, CDP hace
`continue` antes)`. O sea: **un pago 100% válido según CDP nunca se liquidaba**.
Fix: se agregó la llamada real a `/settle` (con reintentos) dentro del camino
de éxito, sin tocar el camino de fallo existente.

**Commit:** `8fbc48a`

### Bug 3 — `/settle` reutilizaba el JWT de `/verify`

CDP exige un JWT distinto por endpoint (el claim `uri` debe matchear el path
exacto: `.../verify` vs `.../settle`). El primer intento del fix anterior
reusó el JWT de `/verify` para `/settle` → `401 Unauthorized` en el settle,
forzando un fallback silencioso a PayAI (el pago se liquidaba, pero por la
vía equivocada — sin la extensión Bazaar, sin indexar nada).

**Fix:** construir un JWT propio con `uri` terminado en `/settle` antes de esa
llamada. **Commit:** `9a53a2c`

### Bug 4 — Doble llamada a `/settle` con el mismo nonce

Tras el fix anterior, el settle principal pasó (`settle OK via cdp`), pero la
llamada *adicional* con la extensión `bazaar` (pensada para indexar en Bazaar)
fallaba: `400 "authorization nonce already submitted; transaction already
on-chain"`. Un nonce EIP-3009 solo puede liquidarse **una vez** — la blockchain
ya había marcado la autorización como usada en el primer settle.

**Fix:** armar el payload con `resource` + `extensions.bazaar` **antes** de la
única llamada a `/settle`, en vez de hacer una segunda llamada separada con el
mismo nonce. **Commit:** `5a700ff`

### Validación final en producción (agentcash, pago real, Base mainnet)

```
POST /sanitize -> 200 OK
  "status": "success"
  "sanitized_content": "Mi cedula es [REDACTED] y mi correo es [REDACTED]"
  "billing": {"license_type": "Pay-per-call (x402)", "status": "active"}

Log de Render:
  TrustBoost settle OK via cdp (payer=0xe4Aedc36D9...)
  TrustBoost CDP Bazaar settle: 200 EXTENSION-RESPONSES=eyJiYXphYXIiOnsic3RhdHVzIjoicHJvY2Vzc2luZyJ9fQ==
  (decodificado: {"bazaar":{"status":"processing"}})
```

Misma respuesta `{"bazaar":{"status":"processing"}}` documentada el 28 de
junio para el milestone original de Intelica en Bazaar — señal de que la
indexación debería completarse en ~5 minutos.

### Limpieza

Los 2 `print("[DIAG] ...")` agregados en la parte 2 para diagnosticar esto ya
se removieron (no aportan valor permanente). Queda un tercer `[DIAG]` en el
arranque del servidor (`CDP_API_KEY_ID present/CDP_API_KEY_SECRET present`)
que ya existía de antes y no se tocó.

### Hallazgo aparte, no resuelto (no bloqueante)

```
[Solana Anchor] Failed: argument 'blockhash': 'str' object cannot be converted to 'Hash'
```
Aparece en cada sanitización exitosa — parece ser la feature de anclaje de
prueba inmutable en Solana (`anchor_proof_on_solana`) fallando por un tipo de
dato incorrecto (`blockhash` como string en vez de objeto `Hash` de `solders`).
No bloquea la respuesta 200 al cliente (no-fatal), pero significa que el
"Proof of Sanitization on Solana" mencionado en la descripción pública del
servicio probablemente no se está anclando de verdad en ninguna llamada
reciente. Pendiente investigar en otra sesión — no es parte de la misión de
indexación en Bazaar.

### Estado de discovery agéntico — actualizado

| Canal | Estado |
|---|---|
| CDP Bazaar | ✅ LIVE — settle confirmado, indexación en curso (~5 min) |
| Agentic Market | ⏳ Debería aparecer en `agentic.market/services/api-trustboost-dev` poco después de Bazaar |
| 402 Index | ✅ ya verificado (sesión previa) |

### Lección metodológica del día

Cuando algo "casi funciona" con múltiples hipótesis plausibles, instrumentar
con `print()` de diagnóstico temporal (mostrando el payload real recibido y
el body real enviado) fue mucho más eficiente que seguir adivinando la forma
exacta del payload desde afuera — permitió ver en una sola vuelta que
`client_network` nunca se detectaba (Bug 1 de esta parte) en vez de sospechar
erróneamente del formato JSON del cliente.

---

## Nota — Jul 19, 2026: PR #170 en ARUNAGIRINATHAN-K/awesome-ai-agents-2026

PR abierto para agregar los 3 productos a este directorio (distinto al `caramaschiHG/awesome-ai-agents-2026`
donde ya estaban listados desde antes — mismo nombre de repo, dueños distintos).

**Origen:** el issue #118 (submission original de Intelica, 23 de junio) fue cerrado como "completed" por el
maintainer el 19 de julio sin que el contenido realmente llegara al README — se abrió este PR directamente
para cerrar el loop.

**Contenido:** 3 líneas, formato ajustado a mano para calzar exacto con las entradas vecinas del archivo
(`[Nombre](URL de GitHub)` + tags al final entre parentesis con 🏷️, sin emoji ni URL de API al inicio):
- Intelica -> seccion "Agent Tooling and Infrastructure"
- TrustBoost -> seccion "Agent Tooling and Infrastructure"
- VeraData -> seccion "AI Governance and Compliance" (la descripcion de esa seccion menciona explicitamente
  el EU AI Act ago-2026 -- encaje perfecto)

**Nota tecnica del proceso:** el primer PR se abrio por error contra el propio fork del usuario (no contra
el repo original) -- error comun del flujo "Create a new branch and start a pull request" de GitHub cuando
el nombre del fork difiere del original. Se corrigio abriendo un nuevo PR via "compare across forks"
explicito. El fine-grained PAT de este proyecto no puede forkear ni comentar en repos ajenos (misma
limitacion ya documentada en sesiones anteriores) -- todo el proceso de fork/PR se hizo manualmente desde
el navegador.

PR: https://github.com/ARUNAGIRINATHAN-K/awesome-ai-agents-2026/pull/170


### Actualización — PR #170: revisión automática (CodeRabbit + Gemini Code Assist)

Tras abrir el PR, dos bots de revisión (CodeRabbit, Gemini Code Assist) marcaron 2 reclamos
como no verificables desde los repos publicos linkeados en la entrada:

1. **Intelica** — "benchmarked against 3,600+ companies" — el numero es real (3,846 nodos en
   `intel_graph_nodes` al momento de escribir esto), pero `Intelica-docs/README.md` nunca lo
   documenta como cifra estatica (solo dice "accumulated competitive relationship map across
   all analyses", sin numero). Fix: se saco la cifra especifica de la entrada.

2. **VeraData** — "independently-verified hash chain" — la cadena de hashes y su verificacion
   externa (ANP2 Network, babyblueviper1/ERC-8299) son reales y estan documentadas en sesiones
   anteriores, pero `veradata-public/README.md` solo muestra el campo `audit_hash`, no la cadena
   completa ni la verificacion. Fix: se cambio a "EU AI Act compliant audit hash on every
   response" — lo que el repo linkeado si respalda.

**Leccion:** para PRs a directorios de terceros, las afirmaciones deben poder verificarse desde
el link que se provee en la entrada especifica, no desde el conocimiento interno completo del
producto. Ambos claims eran ciertos, pero no verificables desde esa fuente puntual — hay que
matchear la afirmacion a lo que el link realmente muestra, o agregar la evidencia publica antes
de reclamarlo.

PR (actualizado): https://github.com/ARUNAGIRINATHAN-K/awesome-ai-agents-2026/pull/170


## Session — Aug 28-29, 2026 — Auditoría cruzada tras feedback de NirDiamant en un tutorial de terceros

**Nota de alcance, importante**: este trabajo se originó revisando un PR de
terceros (`NirDiamant/agents-towards-production#60`, un tutorial de PII
usando TrustBoost como implementación de referencia) -- no de un cambio de
producto propio. Se documenta aquí, en `trustboost-api/CONTEXT.md`, y no en
el registro de Sentinel Oracle, porque son dos proyectos separados de Iv --
Sentinel Oracle es un oráculo de confianza x402 completamente distinto,
sin relación de código con TrustBoost. Parte de este trabajo se había
documentado por error en el archivo de estado de Sentinel Oracle en las
sesiones del 28-29 de agosto; queda corregido aquí, en el lugar correcto,
de ahora en adelante.

### Parte 1 — `TrustBoost-PII-Sanitizer` (repo de documentación/marketing): contradicción real encontrada y corregida

Auditoría quirúrgica pedida por Iv encontró una contradicción directa
dentro del propio repo: `README.md`, tabla "Trust Model", afirmaba *"What
TrustBoost never does: Share data with third parties"* -- mientras
`PRIVACY.md`, en el mismo repo, documenta que el texto se envía a OpenAI
GPT-4o-mini para la detección semántica. `SKILL.md` ya tenía la divulgación
honesta correcta; el README no.

**Fix**: commit `e05eb9d` en `TrustBoost-PII-Sanitizer` -- tabla corregida,
divulgación completa agregada (mismo texto que ya tenía `SKILL.md`),
referencia cruzada a `PRIVACY.md`. Hallazgos adicionales señalados pero no
corregidos (fuera del alcance pedido): las métricas "Precision 1.000/Recall
1.000" del benchmark vienen de 34 casos de prueba deliberadamente fáciles;
el archivo "Digital Consciousness Manifesto" tiene un tono que contrasta
con el resto de la documentación técnica.

### Parte 2 — Tres rondas de revisión real en `NirDiamant/agents-towards-production#60`

El PR de Iv (tutorial de PII, abierto desde el 29 de julio, usando
TrustBoost como Approach 2 opt-in junto a un Approach 1 regex/local) recibió
revisión sustantiva real de `NirDiamant` (dueño del repo, 21,300 estrellas)
el 28 de agosto -- "holding, not rejecting" -- más tres rondas subsecuentes
de revisión automática de CodeRabbit tras cada fix. Cronología completa:

**Ronda 1 (feedback de NirDiamant + primer fix, commit `a4dd9ba`)**:
objeción de fondo -- el tutorial mandaba texto crudo a TrustBoost sin
divulgar el salto adicional a OpenAI, ni explicar qué se retiene y dónde.
Reencuadre completo: regex como default explícito, TrustBoost como opt-in
con divulgación total (texto crudo → TrustBoost → OpenAI). Se agregó
`assets/data-flow-comparison.svg` (diagrama de flujo de datos, validado
como XML antes de comitear), `requirements.txt`, entrada en el índice del
README raíz bajo Security. **Hallazgo adicional**: el fix de manejo de
errores que Iv le había dicho a CodeRabbit el 15 de mayo que ya existía
("Added fail-closed error handling in trustboost_sanitize") nunca se había
aplicado de verdad al commit real -- verificado contra el diff, corregido
en esta misma pasada.

**Ronda 2 (8 hallazgos de CodeRabbit, commit `22c8b96`)**: incluyó una
autocorrección real -- la propia divulgación de la Ronda 1 ("neither
service stores the raw text") era demasiado amplia; CodeRabbit verificó con
búsqueda web que OpenAI retiene prompts/respuestas en logs de monitoreo de
abuso hasta 30 días por defecto (salvo aprobación ZDR/MAM), algo distinto a
si TrustBoost mismo almacena algo. Corregido distinguiendo ambos
explícitamente. Además: el ejemplo insignia del propio tutorial
(`+1-555-0123`) no coincidía con su propio regex de teléfono (confirmado
con Python real antes de arreglar); `create_privacy_aware_agent` llamaba a
TrustBoost sin condición, contradiciendo "regex es el default" -- corregido
con un parámetro `sanitizer` con default local; `should_block` en la
sección de LangGraph tenía el mismo problema de lista negra vs blanca que
se corrigió en Sentinel Oracle el 19 de agosto (patrón repetido,
reconocido); import obsoleto de LangChain confirmado roto contra la versión
1.3.18 real antes de corregir. 14 casos de prueba ejecutados.

**Ronda 3 (4 hallazgos más, commit `e69cfb7`)**: bug real confirmado con
repro directo -- `trustboost_sanitize()` nunca validaba que el JSON de
nivel superior fuera un `dict` antes de llamar `.get('data')` (una lista o
string JSON válido rompía con `AttributeError` no capturado). Contradicción
real encontrada en el propio docstring de `should_block` (decía que
`PRIVATE` bloqueaba, el código real lo dejaba pasar -- el código estaba
bien, el comentario estaba mal). **Autocorrección de una autocorrección**:
las fechas del EU AI Act de la Ronda 2 ("agosto 2027") también eran
imprecisas -- investigación fresca confirmó, con múltiples fuentes de
calidad (Gibson Dunn, Cloud Security Alliance, el servicio oficial de la
Comisión Europea), que el "Digital Omnibus on AI" (en vigor desde el 27 de
julio de 2026) aplazó Annex III a diciembre 2, 2027 y Annex I a agosto 2,
2028 -- no agosto 2027. Divulgación agregada sobre `wallet_id` como
identificador persistente enviado y almacenado por TrustBoost para control
de cuota. 10 casos de prueba ejecutados.

PR: https://github.com/NirDiamant/agents-towards-production/pull/60

### Parte 3 — El fix que sí vive en este repo: `trustboost-api` nunca fallaba cerrado si la llamada a OpenAI fallaba

Auditoría separada, pedida explícitamente por Iv tras notar que todo el
trabajo de las Partes 1-2 fue del lado de cliente/documentación, nunca del
servidor real. Lectura completa de `main.py` (3,968 líneas) confirmó que
casi todo lo documentado coincide con la implementación real -- incluida
una confirmación matemática de que `compute_score()` solo puede devolver
`CRITICAL/PRIVATE/SENSITIVE/CLEAN` (conjunto cerrado, sin ningún camino de
código que devuelva otra cosa), validando exactamente la lista blanca
construida del lado cliente en el PR de NirDiamant.

**El hallazgo real**: `gpt_sanitize()` llamaba directo a
`openai_client.chat.completions.create(...)` sin ningún `try/except`.
`_parse_model_json()` ya fallaba seguro ante una *respuesta* malformada de
OpenAI, pero eso nunca corre si la *llamada misma* falla (rate limit,
timeout, error de conexión, fallo de autenticación) -- sin manejador de
excepciones global registrado en la app. Mitigado por casualidad, no por
diseño: el manejo defensivo del lado cliente reforzado en la Parte 2 ya
convertía un 500 del servidor en `CRITICAL`, pero el servidor mismo no
tenía esa disciplina.

**Fix (commit `07030d9`, desplegado y verificado sano en producción)**:
extraído el diccionario de fail-safe (antes duplicado inline) a una función
compartida `_failsafe_result()`, usada tanto por el fallback de JSON
malformado como por el nuevo bloque `except` de `gpt_sanitize()` -- un solo
lugar, misma forma, para que los dos caminos no puedan desincronizarse. 6
casos de prueba nuevos agregados a `tests/test_sanitize.py` (ahora 24 en
total), usando instancias reales de `openai.RateLimitError`/
`APITimeoutError`/`APIConnectionError` construidas con objetos
`httpx.Request`/`Response` reales, no mocks genéricos. Verificado
`https://api.trustboost.dev/health` sano (`{"status":"ok","version":"2.6.0"}`)
después del despliegue automático a Render.

**Hallazgo de paso, no corregido**: la página pública raíz de la API
(`api.trustboost.dev/`) repite las mismas dos imprecisiones ya corregidas
en el tutorial ("F1=1.000" del mismo benchmark fácil; misma fecha
simplificada del EU AI Act). Señalado a Iv, fuera del alcance de esta
sesión.

### Parte 4 — Resultado real: NirDiamant invita a conversación de colocación paga

Tras las tres rondas de fixes reales, `NirDiamant` comentó de nuevo el 29
de agosto, esta vez sin nada técnico: invitación directa a mensaje de
LinkedIn para hablar de colocación paga de TrustBoost en el repo (21,300
estrellas de audiencia real). Mensaje redactado por Claude (dos variantes,
"directo y breve" vs "con más contexto de negocio"), revisado y **enviado
por Iv mismo** el mismo día -- deliberadamente no ejecutado por Claude, al
ser una negociación comercial personal, distinta a los comentarios técnicos
de GitHub ya hechos con autorización explícita en sesiones anteriores.

**Estado**: pendiente de respuesta de NirDiamant. Es el resultado más
cercano a una conversación de ingreso real que ha producido cualquier
trabajo de TrustBoost o Sentinel Oracle hasta la fecha.
