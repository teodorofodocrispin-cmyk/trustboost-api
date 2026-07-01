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
