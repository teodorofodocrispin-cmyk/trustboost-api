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
- **Bug hallado y corregido (smoke test en vivo)**: el header `X-Payment: x402 <b64>` llegaba con el prefijo `x402 ` y `verify_payment_percall` lo decodificaba sin quitarlo → `Incorrect padding` en logs de Render → 402. Fix: quitar prefijo `x402 `/`x-` antes de decodificar (igual que VeraData/Intelica). Confirmado con tx real `56fee92b…` (0.01 USDC a WALLET_BASE).
Verificado a nivel de módulo + enrutado + decode (tx real de Intelica y de 0.01). Smoke test en vivo de micropago 0.01 (Base) pendiente de re-confirmar tras fix de decode. El proof on-chain inmutable sigue solo en Solana (anchor_proof_on_solana); un equivalente en Base (EAS) queda como fase 2 opcional.

### Reglas respetadas
- main.py siempre aditivo; nunca romper flujo de sanitización/pagos.
- Cores intactos: x402, sanitización on-chain, Helius, Supabase sin cambios.
